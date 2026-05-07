import argparse
import asyncio
import json

import pytest
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo

from tgcli.commands import media
from tgcli.db import connect
from tgcli.safety import BadArgs, WriteDisallowed


def _seed_chat(path):
    con = connect(path)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "user", "Alpha Chat", "alpha"),
    )
    con.commit()
    con.close()


def _args(**kw):
    defaults = {
        "allow_write": True,
        "dry_run": False,
        "idempotency_key": None,
        "fuzzy": False,
        "json": True,
        "human": False,
        "caption": None,
        "reply_to": None,
        "silent": False,
        "ttl": None,
        "max_size_mb": 100,
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _write(path, data: bytes):
    path.write_bytes(data)
    return path


def _patch_db(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(media, "DB_PATH", db)
    return db


class FakeMessage:
    id = 777


class FakeClient:
    def __init__(self):
        self.calls = []
        self.send_count = 0

    async def start(self):
        self.calls.append(("start",))

    async def get_entity(self, chat_id):
        self.calls.append(("get_entity", chat_id))
        return f"entity-{chat_id}"

    async def send_file(self, entity, file, **kwargs):
        self.send_count += 1
        self.calls.append(("send_file", entity, file, kwargs))
        return FakeMessage()

    async def disconnect(self):
        self.calls.append(("disconnect",))


@pytest.mark.parametrize(
    ("runner", "filename", "content", "expected_type"),
    [
        (media._upload_photo_runner, "photo.jpg", b"\xff\xd8\xff\xe0data", "photo"),
        (media._upload_voice_runner, "voice.ogg", b"OggSxxxxOpusHead", "voice"),
        (media._upload_video_runner, "video.mp4", b"\x00\x00\x00\x18ftypmp42data", "video"),
        (media._upload_document_runner, "doc.bin", b"anything", "document"),
    ],
)
def test_media_upload_happy_paths(monkeypatch, tmp_path, runner, filename, content, expected_type):
    _patch_db(monkeypatch, tmp_path)
    path = _write(tmp_path / filename, content)
    fake = FakeClient()
    monkeypatch.setattr(media, "make_client", lambda session_path: fake)
    args = _args(chat="@alpha", file=str(path), caption="caption", reply_to=5, silent=True, ttl=7)

    data = asyncio.run(runner(args))

    assert data["message_id"] == 777
    assert data["media_type"] == expected_type
    assert data["chat"] == {"chat_id": 123, "title": "Alpha Chat"}
    call = fake.calls[2]
    assert call[0] == "send_file"
    assert call[1] == "entity-123"
    assert call[2] == str(path.resolve())
    assert call[3]["caption"] == "caption"
    assert call[3]["reply_to"] == 5
    assert call[3]["silent"] is True
    if expected_type in {"photo", "video"}:
        assert call[3]["ttl"] == 7


def test_voice_upload_sets_voice_attribute(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    path = _write(tmp_path / "voice.ogg", b"OggSxxxxOpusHead")
    fake = FakeClient()
    monkeypatch.setattr(media, "make_client", lambda session_path: fake)

    asyncio.run(media._upload_voice_runner(_args(chat="@alpha", file=str(path))))

    attrs = fake.calls[2][3]["attributes"]
    assert any(isinstance(attr, DocumentAttributeAudio) and attr.voice for attr in attrs)


def test_video_upload_sets_video_attribute(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    path = _write(tmp_path / "video.webm", b"\x1a\x45\xdf\xa3webm")
    fake = FakeClient()
    monkeypatch.setattr(media, "make_client", lambda session_path: fake)

    asyncio.run(media._upload_video_runner(_args(chat="@alpha", file=str(path))))

    attrs = fake.calls[2][3]["attributes"]
    assert any(isinstance(attr, DocumentAttributeVideo) for attr in attrs)


def test_media_upload_rejects_file_too_big(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    path = _write(tmp_path / "photo.png", b"\x89PNG\r\n\x1a\n" + b"x" * 10)

    with pytest.raises(BadArgs, match="exceeds --max-size-mb"):
        asyncio.run(media._upload_photo_runner(_args(chat="@alpha", file=str(path), max_size_mb=0)))


def test_media_upload_rejects_missing_file(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)

    with pytest.raises(BadArgs, match="does not exist"):
        asyncio.run(
            media._upload_document_runner(_args(chat="@alpha", file=str(tmp_path / "nope")))
        )


def test_photo_upload_rejects_wrong_magic_bytes(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    path = _write(tmp_path / "photo.jpg", b"not really a jpeg")

    with pytest.raises(BadArgs, match="unsupported photo MIME"):
        asyncio.run(media._upload_photo_runner(_args(chat="@alpha", file=str(path))))


def test_media_upload_dry_run_resolves_payload_and_skips_telethon(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    path = _write(tmp_path / "photo.webp", b"RIFFxxxxWEBPdata")
    made_client = False

    def fail_make_client(session_path):
        nonlocal made_client
        made_client = True
        raise AssertionError("dry-run must not make a Telethon client")

    monkeypatch.setattr(media, "make_client", fail_make_client)

    data = asyncio.run(
        media._upload_photo_runner(_args(chat="@alpha", file=str(path), dry_run=True))
    )

    assert made_client is False
    assert data["dry_run"] is True
    assert data["payload"]["chat"] == {"chat_id": 123, "title": "Alpha Chat"}
    assert data["payload"]["file_path"] == str(path.resolve())
    assert data["payload"]["telethon_method"] == "client.send_file"


def test_media_upload_replays_idempotency(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    path = _write(tmp_path / "doc.bin", b"document")
    fake = FakeClient()
    monkeypatch.setattr(media, "make_client", lambda session_path: fake)
    args = _args(chat="@alpha", file=str(path), idempotency_key="same-key")

    first = asyncio.run(media._upload_document_runner(args))
    second = asyncio.run(media._upload_document_runner(args))

    assert first["message_id"] == 777
    assert second["message_id"] == 777
    assert second["idempotent_replay"] is True
    assert fake.send_count == 1


def test_media_upload_rejects_path_traversal(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)

    with pytest.raises(BadArgs, match="path traversal"):
        asyncio.run(media._upload_document_runner(_args(chat="@alpha", file="../secret.txt")))


def test_media_upload_rejects_forbidden_path_character(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)

    with pytest.raises(BadArgs, match="forbidden character"):
        asyncio.run(media._upload_document_runner(_args(chat="@alpha", file="bad?name.txt")))


def test_media_write_gate_runs_before_dry_run(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    path = _write(tmp_path / "doc.bin", b"document")

    with pytest.raises(WriteDisallowed):
        asyncio.run(
            media._upload_document_runner(
                _args(chat="@alpha", file=str(path), allow_write=False, dry_run=True)
            )
        )


def test_upload_pre_audit_logs_absolute_path(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    audit = tmp_path / "audit.log"
    monkeypatch.setattr(media, "AUDIT_PATH", audit)
    path = _write(tmp_path / "doc.bin", b"document")
    fake = FakeClient()
    monkeypatch.setattr(media, "make_client", lambda session_path: fake)

    asyncio.run(media._upload_document_runner(_args(chat="@alpha", file=str(path))))

    first_entry = json.loads(audit.read_text().splitlines()[0])
    assert first_entry["phase"] == "before"
    assert first_entry["payload_preview"]["file_path"] == str(path.resolve())
