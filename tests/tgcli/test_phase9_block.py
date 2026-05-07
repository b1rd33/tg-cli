"""Phase 9 — block-user / unblock-user."""
from __future__ import annotations

import argparse
import asyncio

import pytest

from tgcli.commands import contacts
from tgcli.db import connect
from tgcli.safety import BadArgs


def _seed(path):
    con = connect(path)
    con.executemany(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        [(200, "user", "Bob", "bob"),
         (300, "bot", "HelpBot", "helpbot"),
         (-1001, "channel", "ChanX", "chx")],
    )
    con.commit(); con.close()


def _args(**kw):
    defaults = {"allow_write": True, "dry_run": False, "idempotency_key": "k1",
                "fuzzy": False, "json": True, "human": False, "read_only": False,
                "confirm": None}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class _FakeClient:
    def __init__(self):
        self.calls = []

    async def start(self): pass

    async def get_input_entity(self, c):
        from telethon.tl.types import InputPeerUser
        return InputPeerUser(user_id=int(c), access_hash=0)

    async def __call__(self, request):
        self.calls.append(request)
        return True

    async def disconnect(self): pass


def test_block_user_rejects_non_user(monkeypatch, tmp_path):
    db = tmp_path / "x.sqlite"
    _seed(db)
    monkeypatch.setattr(contacts, "DB_PATH", db)
    args = _args(user="-1001", confirm="-1001")
    with pytest.raises(BadArgs, match="user or bot"):
        asyncio.run(contacts._block_user_runner(args))


def test_block_user_typed_confirm_mismatch(monkeypatch, tmp_path):
    db = tmp_path / "x.sqlite"
    _seed(db)
    monkeypatch.setattr(contacts, "DB_PATH", db)
    args = _args(user="200", confirm="999")
    with pytest.raises(BadArgs, match="must equal"):
        asyncio.run(contacts._block_user_runner(args))


def test_block_user_calls_block_request(monkeypatch, tmp_path):
    db = tmp_path / "x.sqlite"
    _seed(db)
    monkeypatch.setattr(contacts, "DB_PATH", db)
    fake = _FakeClient()
    monkeypatch.setattr(contacts, "make_client", lambda s: fake)
    args = _args(user="200", confirm="200")
    data = asyncio.run(contacts._block_user_runner(args))
    assert data["blocked"] is True
    assert fake.calls[0].__class__.__name__ == "BlockRequest"


def test_block_user_accepts_bot(monkeypatch, tmp_path):
    """Bots are users in Telegram's data model; block should accept them."""
    db = tmp_path / "x.sqlite"
    _seed(db)
    monkeypatch.setattr(contacts, "DB_PATH", db)
    fake = _FakeClient()
    monkeypatch.setattr(contacts, "make_client", lambda s: fake)
    args = _args(user="300", confirm="300")
    data = asyncio.run(contacts._block_user_runner(args))
    assert data["blocked"] is True


def test_unblock_user_no_confirm_required(monkeypatch, tmp_path):
    """Unblock is recoverable; no --confirm needed."""
    db = tmp_path / "x.sqlite"
    _seed(db)
    monkeypatch.setattr(contacts, "DB_PATH", db)
    fake = _FakeClient()
    monkeypatch.setattr(contacts, "make_client", lambda s: fake)
    args = _args(user="200")
    args.confirm = None
    data = asyncio.run(contacts._unblock_user_runner(args))
    assert data["unblocked"] is True
    assert fake.calls[0].__class__.__name__ == "UnblockRequest"
