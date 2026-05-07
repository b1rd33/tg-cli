"""Phase 9 — delete-msg with batch + tombstones."""

from __future__ import annotations

import argparse
import asyncio

import pytest

from tgcli.commands import messages
from tgcli.db import connect
from tgcli.safety import BadArgs


def _seed(path):
    con = connect(path)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "user", "Alpha", "alpha"),
    )
    con.executemany(
        """INSERT INTO tg_messages(chat_id, message_id, sender_id, date, text,
            is_outgoing, has_media) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (123, 100, 11, "2026-05-08T10:00:00", "first", 1, 0),
            (123, 101, 11, "2026-05-08T10:01:00", "second", 1, 0),
        ],
    )
    con.commit()
    con.close()


def _args(**kw):
    defaults = {
        "allow_write": True,
        "dry_run": False,
        "idempotency_key": "k1",
        "fuzzy": False,
        "json": True,
        "human": False,
        "read_only": False,
        "confirm": "123",
        "for_everyone": True,
        "include_deleted": False,
        "pattern": None,
        "chat_id": None,
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class _FakeClient:
    def __init__(self):
        self.calls = []

    async def start(self):
        pass

    async def get_input_entity(self, chat_id):
        from telethon.tl.types import InputPeerUser

        return InputPeerUser(user_id=int(chat_id), access_hash=0)

    async def delete_messages(self, entity, ids, *, revoke=False):
        self.calls.append(("delete_messages", entity, list(ids), revoke))
        return [type("AffectedMessages", (), {"pts": 1, "pts_count": 1})() for _ in ids]

    async def disconnect(self):
        pass


def test_delete_msg_rejects_wrong_confirm_value(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed(db)
    monkeypatch.setattr(messages, "DB_PATH", db)
    args = _args(chat="@alpha", message_ids=[100], confirm="999")
    with pytest.raises(BadArgs, match="must equal"):
        asyncio.run(messages._delete_msg_runner(args))


def test_delete_msg_batch_envelope_shape(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed(db)
    monkeypatch.setattr(messages, "DB_PATH", db)
    fake = _FakeClient()
    monkeypatch.setattr(messages, "make_client", lambda s: fake)
    args = _args(chat="@alpha", message_ids=[100, 101], confirm="123")
    data = asyncio.run(messages._delete_msg_runner(args))
    assert data["chat"]["chat_id"] == 123
    assert data["for_everyone"] is True
    assert data["summary"] == {"total": 2, "succeeded": 2, "failed": 0}
    assert len(data["results"]) == 2
    assert data["results"][0]["ok"] is True


def test_delete_msg_writes_tombstone_for_revoked(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed(db)
    monkeypatch.setattr(messages, "DB_PATH", db)
    monkeypatch.setattr(messages, "make_client", lambda s: _FakeClient())
    args = _args(chat="@alpha", message_ids=[100], confirm="123", for_everyone=True)
    asyncio.run(messages._delete_msg_runner(args))
    import sqlite3

    con = sqlite3.connect(db)
    deleted = con.execute(
        "SELECT deleted FROM tg_messages WHERE chat_id=123 AND message_id=100"
    ).fetchone()[0]
    con.close()
    assert deleted == 1


def test_delete_msg_for_everyone_auto_detect_outgoing(monkeypatch, tmp_path):
    """When --for-everyone is unset and all ids are outgoing, default to True."""
    db = tmp_path / "telegram.sqlite"
    _seed(db)
    monkeypatch.setattr(messages, "DB_PATH", db)
    fake = _FakeClient()
    monkeypatch.setattr(messages, "make_client", lambda s: fake)
    args = _args(chat="@alpha", message_ids=[100, 101], confirm="123", for_everyone=None)
    data = asyncio.run(messages._delete_msg_runner(args))
    assert data["for_everyone"] is True


def test_show_runner_filters_deleted_by_default(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed(db)
    import sqlite3

    con = sqlite3.connect(db)
    con.execute("UPDATE tg_messages SET deleted = 1 WHERE message_id = 100")
    con.commit()
    con.close()
    monkeypatch.setattr(messages, "DB_PATH", db)
    args = _args(
        chat=None, pattern="@alpha", chat_id=None, limit=10, reverse=False, include_deleted=False
    )
    data = messages._show_runner(args)
    texts = [m.get("text") for m in data["messages"]]
    assert "first" not in texts
    assert "second" in texts


def test_show_runner_include_deleted_returns_both(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed(db)
    import sqlite3

    con = sqlite3.connect(db)
    con.execute("UPDATE tg_messages SET deleted = 1 WHERE message_id = 100")
    con.commit()
    con.close()
    monkeypatch.setattr(messages, "DB_PATH", db)
    args = _args(
        chat=None, pattern="@alpha", chat_id=None, limit=10, reverse=False, include_deleted=True
    )
    data = messages._show_runner(args)
    texts = [m.get("text") for m in data["messages"]]
    assert "first" in texts and "second" in texts
