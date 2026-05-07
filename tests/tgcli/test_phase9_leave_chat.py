"""Phase 9 — leave-chat."""
from __future__ import annotations

import argparse
import asyncio

import pytest

from tgcli.commands import chats
from tgcli.db import connect
from tgcli.safety import BadArgs


def _seed(path, *, self_id=42):
    con = connect(path)
    con.execute("INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
                (self_id, "user", "Saved Messages (self)", "me"))
    con.execute("INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
                (-1001234, "supergroup", "Test SG", "test_sg"))
    con.execute(
        """INSERT INTO tg_me(key, user_id, username, display_name, cached_at)
           VALUES ('self', ?, ?, ?, ?)""",
        (self_id, "me", "Me", "2026-05-08T10:00:00+00:00"),
    )
    con.commit(); con.close()


def _args(**kw):
    defaults = {"allow_write": True, "dry_run": False, "idempotency_key": "leave-1",
                "fuzzy": False, "json": True, "human": False, "read_only": False,
                "confirm": None}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class _FakeClient:
    def __init__(self):
        self.calls = []

    async def start(self): pass

    async def get_input_entity(self, c):
        from telethon.tl.types import InputPeerChannel
        return InputPeerChannel(channel_id=abs(int(c)), access_hash=0)

    async def delete_dialog(self, entity):
        self.calls.append(("delete_dialog", entity))
        return True

    async def disconnect(self): pass


def test_leave_chat_rejects_self_dm(monkeypatch, tmp_path):
    db = tmp_path / "x.sqlite"
    _seed(db)
    monkeypatch.setattr(chats, "DB_PATH", db)
    args = _args(chat="42", confirm="42")
    with pytest.raises(BadArgs, match="cannot leave"):
        asyncio.run(chats._leave_chat_runner(args))


def test_leave_chat_marks_tg_chats_left(monkeypatch, tmp_path):
    db = tmp_path / "x.sqlite"
    _seed(db)
    monkeypatch.setattr(chats, "DB_PATH", db)
    monkeypatch.setattr(chats, "make_client", lambda s: _FakeClient())
    args = _args(chat="-1001234", confirm="-1001234")
    data = asyncio.run(chats._leave_chat_runner(args))
    assert data["left"] is True
    import sqlite3
    con = sqlite3.connect(db)
    left = con.execute("SELECT left FROM tg_chats WHERE chat_id=-1001234").fetchone()[0]
    con.close()
    assert left == 1


def test_leave_chat_typed_confirm_mismatch(monkeypatch, tmp_path):
    db = tmp_path / "x.sqlite"
    _seed(db)
    monkeypatch.setattr(chats, "DB_PATH", db)
    args = _args(chat="-1001234", confirm="999")
    with pytest.raises(BadArgs, match="must equal"):
        asyncio.run(chats._leave_chat_runner(args))


def test_leave_chat_rejects_user_chat(monkeypatch, tmp_path):
    """1-on-1 user chats can't be 'left' the same way."""
    db = tmp_path / "x.sqlite"
    _seed(db)
    import sqlite3
    con = sqlite3.connect(db)
    con.execute("INSERT INTO tg_chats(chat_id, type, title) VALUES (200, 'user', 'Bob')")
    con.commit(); con.close()
    monkeypatch.setattr(chats, "DB_PATH", db)
    args = _args(chat="200", confirm="200")
    with pytest.raises(BadArgs, match="user chat"):
        asyncio.run(chats._leave_chat_runner(args))
