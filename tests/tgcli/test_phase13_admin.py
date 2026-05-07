"""Phase 13 — channel/group admin commands."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime

import pytest

from tgcli.commands import admin
from tgcli.db import connect
from tgcli.safety import BadArgs, WriteDisallowed


def _seed(path):
    con = connect(path)
    con.executemany(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        [
            (-1001234, "supergroup", "Test SG", "test_sg"),
            (-1002222, "channel", "News", "news"),
            (-333, "group", "Small Group", None),
            (42, "user", "Alice Admin", "alice"),
            (43, "user", "Bob Member", "bob"),
        ],
    )
    con.commit()
    con.close()


def _args(**kw):
    defaults = {
        "allow_write": True,
        "dry_run": False,
        "idempotency_key": "phase13-key",
        "fuzzy": False,
        "json": True,
        "human": False,
        "read_only": False,
        "confirm": None,
        "rank": None,
        "until": None,
        "review": False,
        "revoke": False,
        "link": None,
        "title": None,
        "expire": None,
        "usage_limit": None,
        "request_needed": False,
        "limit": 50,
        "offset": 0,
        "max_size_mb": 10,
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _patch_db(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed(db)
    monkeypatch.setattr(admin, "DB_PATH", db)
    return db


class _FakeEntity:
    def __init__(self, entity_id: int, *, broadcast: bool = False):
        self.id = abs(entity_id)
        self.broadcast = broadcast
        self.title = f"entity-{entity_id}"


class _FakeUser:
    def __init__(self, user_id: int, name: str = "Target User"):
        self.id = user_id
        self.first_name = name
        self.last_name = None
        self.username = f"user{user_id}"


class _FakeMessage:
    def __init__(self, message_id: int, text: str):
        self.id = message_id
        self.sender_id = 42
        self.date = datetime(2026, 5, 8, tzinfo=UTC)
        self.text = text

    def to_dict(self):
        return {"id": self.id, "message": self.text}


class _FakeParticipant:
    def __init__(self, user_id: int, first_name: str):
        self.id = user_id
        self.first_name = first_name
        self.last_name = None
        self.username = first_name.lower()
        self.bot = False


class _FakeInvite:
    link = "https://t.me/+abc"


class _FakeClient:
    def __init__(self):
        self.calls = []
        self.uploaded = object()

    async def start(self):
        self.calls.append(("start",))

    async def get_entity(self, selector):
        self.calls.append(("get_entity", selector))
        if int(selector) in (42, 43):
            return _FakeUser(int(selector), "Alice" if int(selector) == 42 else "Bob")
        return _FakeEntity(int(selector), broadcast=int(selector) == -1002222)

    async def get_input_entity(self, selector):
        self.calls.append(("get_input_entity", selector))
        return f"input-{selector}"

    async def upload_file(self, path):
        self.calls.append(("upload_file", path))
        return self.uploaded

    async def __call__(self, request):
        self.calls.append(request)
        if request.__class__.__name__ == "ExportChatInviteRequest":
            return _FakeInvite()
        if request.__class__.__name__ == "SearchRequest":
            return argparse.Namespace(messages=[_FakeMessage(10, "pin")])
        if request.__class__.__name__ == "GetParticipantsRequest":
            return argparse.Namespace(count=1, users=[_FakeParticipant(42, "Alice")])
        return True

    async def iter_participants(self, entity, *, limit, offset):
        self.calls.append(("iter_participants", entity, limit, offset))
        for user in [_FakeParticipant(42, "Alice"), _FakeParticipant(43, "Bob")][
            offset : offset + limit
        ]:
            yield user

    async def disconnect(self):
        self.calls.append(("disconnect",))


@pytest.mark.parametrize(
    ("runner", "kwargs", "request_name"),
    [
        (admin._chat_title_runner, {"chat": "-1001234", "title": "Renamed"}, "EditTitleRequest"),
        (
            admin._chat_description_runner,
            {"chat": "-1001234", "description": "About"},
            "EditChatAboutRequest",
        ),
        (
            admin._promote_runner,
            {"chat": "-1001234", "user": "42", "confirm": "-1001234"},
            "EditAdminRequest",
        ),
        (
            admin._demote_runner,
            {"chat": "-1001234", "user": "42", "confirm": "-1001234"},
            "EditAdminRequest",
        ),
        (
            admin._ban_from_chat_runner,
            {"chat": "-1001234", "user": "42", "confirm": "-1001234"},
            "EditBannedRequest",
        ),
        (
            admin._kick_runner,
            {"chat": "-1001234", "user": "42", "confirm": "-1001234"},
            "EditBannedRequest",
        ),
        (admin._unban_from_chat_runner, {"chat": "-1001234", "user": "42"}, "EditBannedRequest"),
        (
            admin._set_permissions_runner,
            {"chat": "-1001234", "send_messages": False, "send_media": True},
            "EditChatDefaultBannedRightsRequest",
        ),
        (
            admin._chat_invite_link_runner,
            {"chat": "-1001234", "title": "ops", "usage_limit": 5},
            "ExportChatInviteRequest",
        ),
    ],
)
def test_admin_write_happy_paths(monkeypatch, tmp_path, runner, kwargs, request_name):
    _patch_db(monkeypatch, tmp_path)
    fake = _FakeClient()
    monkeypatch.setattr(admin, "make_client", lambda session_path: fake)

    data = asyncio.run(runner(_args(**kwargs)))

    assert data["chat"]["chat_id"] == -1001234
    assert data["idempotent_replay"] is False
    assert any(call.__class__.__name__ == request_name for call in fake.calls)


def test_chat_photo_uploads_file_and_uses_edit_photo(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0data")
    fake = _FakeClient()
    monkeypatch.setattr(admin, "make_client", lambda session_path: fake)

    data = asyncio.run(admin._chat_photo_runner(_args(chat="-1001234", file=str(path))))

    assert data["photo_set"] is True
    assert ("upload_file", str(path.resolve())) in fake.calls
    assert any(call.__class__.__name__ == "EditPhotoRequest" for call in fake.calls)


def test_chat_invite_link_revoke_uses_edit_exported_invite(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    fake = _FakeClient()
    monkeypatch.setattr(admin, "make_client", lambda session_path: fake)

    data = asyncio.run(
        admin._chat_invite_link_runner(
            _args(chat="-1001234", revoke=True, link="https://t.me/+old")
        )
    )

    assert data["revoked"] is True
    assert any(call.__class__.__name__ == "EditExportedChatInviteRequest" for call in fake.calls)


def test_chat_pinned_list_reads_pinned_messages(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    fake = _FakeClient()
    monkeypatch.setattr(admin, "make_client", lambda session_path: fake)

    data = asyncio.run(admin._chat_pinned_list_runner(_args(chat="-1001234", limit=5)))

    assert data["chat"]["chat_id"] == -1001234
    assert data["messages"][0]["message_id"] == 10
    assert any(call.__class__.__name__ == "SearchRequest" for call in fake.calls)


def test_chat_members_lists_paged_participants(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    fake = _FakeClient()
    monkeypatch.setattr(admin, "make_client", lambda session_path: fake)

    data = asyncio.run(admin._chat_members_runner(_args(chat="-1001234", limit=1, offset=1)))

    assert data["members"] == [
        {"user_id": 42, "display_name": "Alice", "username": "alice", "is_bot": False}
    ]
    assert data["paging"] == {"limit": 1, "offset": 1, "returned": 1}


def test_destructive_admin_requires_typed_chat_confirm(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)

    with pytest.raises(BadArgs, match="must equal"):
        asyncio.run(admin._ban_from_chat_runner(_args(chat="-1001234", user="42", confirm="42")))


def test_write_gate_runs_before_dry_run(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)

    with pytest.raises(WriteDisallowed):
        asyncio.run(
            admin._chat_title_runner(
                _args(chat="-1001234", title="Nope", allow_write=False, dry_run=True)
            )
        )


def test_set_permissions_review_returns_payload_without_telethon(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)

    def fail_make_client(session_path):
        raise AssertionError("review must not create a Telethon client")

    monkeypatch.setattr(admin, "make_client", fail_make_client)

    data = asyncio.run(
        admin._set_permissions_runner(
            _args(chat="-1001234", send_messages=False, pin_messages=True, review=True)
        )
    )

    assert data["review"] is True
    assert data["payload"]["permissions"]["send_messages"] is False
    assert data["payload"]["permissions"]["pin_messages"] is True


def test_dry_run_resolves_payload_and_skips_telethon(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)

    def fail_make_client(session_path):
        raise AssertionError("dry-run must not create a Telethon client")

    monkeypatch.setattr(admin, "make_client", fail_make_client)

    data = asyncio.run(
        admin._promote_runner(
            _args(
                chat="-1001234",
                user="42",
                confirm="-1001234",
                add_admins=True,
                dry_run=True,
            )
        )
    )

    assert data["dry_run"] is True
    assert data["payload"]["user"] == {"user_id": 42, "display_name": "Alice Admin"}
    assert data["payload"]["admin_rights"]["add_admins"] is True


def test_admin_pre_audit_includes_affected_user(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    audit = tmp_path / "audit.log"
    monkeypatch.setattr(admin, "AUDIT_PATH", audit)
    fake = _FakeClient()
    monkeypatch.setattr(admin, "make_client", lambda session_path: fake)

    asyncio.run(admin._ban_from_chat_runner(_args(chat="-1001234", user="42", confirm="-1001234")))

    entry = json.loads(audit.read_text().splitlines()[0])
    assert entry["phase"] == "before"
    assert entry["payload_preview"]["user"] == {"user_id": 42, "display_name": "Alice Admin"}
