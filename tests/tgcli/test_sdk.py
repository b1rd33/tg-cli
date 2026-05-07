"""Phase 11 SDK tests — `from tgcli import Client`."""

from __future__ import annotations

import pytest


def test_client_importable():
    from tgcli import Client


def test_client_default_account():
    from tgcli import Client

    c = Client()
    assert c.account == "default"


def test_client_repr_includes_account():
    from tgcli import Client

    c = Client()
    assert "default" in repr(c)


def test_client_has_namespaces():
    from tgcli import Client

    c = Client()
    for name in (
        "messages",
        "chats",
        "topics",
        "folders",
        "contacts",
        "media",
        "accounts",
        "admin",
    ):
        assert hasattr(c, name), f"Client missing namespace: {name}"


def test_client_account_mismatch_raises():
    """Asking for an account that doesn't match the one frozen at import
    must raise — silent wrong-account writes are unacceptable."""
    from tgcli import Client

    with pytest.raises(RuntimeError, match="TG_ACCOUNT"):
        Client(account="some-other-account")


def test_messages_send_dry_run_returns_envelope(tmp_path, monkeypatch):
    """Dry-run path must not call Telegram. Patches DB_PATH on the
    messages module directly because path globals are frozen at import time."""
    from tgcli.db import connect

    db = tmp_path / "db.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats (chat_id, type, title) VALUES (?, ?, ?)",
        (12345, "user", "Test"),
    )
    con.commit()
    con.close()

    from tgcli.commands import messages as msg_mod

    monkeypatch.setattr(msg_mod, "DB_PATH", db)
    monkeypatch.setattr(msg_mod, "AUDIT_PATH", tmp_path / "audit.log")

    from tgcli import Client

    c = Client()
    result = c.messages.send(chat=12345, text="hello", allow_write=True, dry_run=True)
    # _dry_run_envelope returns {"dry_run": True, "request_id": ..., "command": ..., "payload": {...}}
    assert result["dry_run"] is True
    assert result["command"] == "send"
    assert result["payload"]["chat"]["chat_id"] == 12345
    assert result["payload"]["text"] == "hello"


def test_messages_send_without_allow_write_raises():
    from tgcli import Client
    from tgcli.safety import WriteDisallowed

    c = Client()
    with pytest.raises(WriteDisallowed):
        c.messages.send(chat=12345, text="hello")


def test_stats_returns_db_summary(tmp_path, monkeypatch):
    from tgcli.db import connect

    db = tmp_path / "db.sqlite"
    con = connect(db)
    con.close()

    from tgcli.commands import stats as stats_mod

    monkeypatch.setattr(stats_mod, "DB_PATH", db)

    from tgcli import Client

    c = Client()
    result = c.stats()
    assert "chats" in result and "messages" in result and "top_chats" in result
    assert result["chats"] == 0


def test_messages_show_returns_history(tmp_path, monkeypatch):
    from tgcli.db import connect

    db = tmp_path / "db.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats (chat_id, type, title) VALUES (?, ?, ?)",
        (12345, "user", "Test"),
    )
    con.execute(
        "INSERT INTO tg_messages (chat_id, message_id, date, is_outgoing, text) "
        "VALUES (?, ?, ?, ?, ?)",
        (12345, 1, "2026-05-08T10:00:00Z", 0, "hello world"),
    )
    con.commit()
    con.close()

    from tgcli.commands import messages as msg_mod

    monkeypatch.setattr(msg_mod, "DB_PATH", db)

    from tgcli import Client

    c = Client()
    result = c.messages.show(chat_id=12345, limit=10)
    assert result["chat"]["chat_id"] == 12345
    assert len(result["messages"]) == 1
    assert result["messages"][0]["text"] == "hello world"


def test_admin_chat_title_dry_run(tmp_path, monkeypatch):
    from tgcli.db import connect

    db = tmp_path / "db.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats (chat_id, type, title) VALUES (?, ?, ?)",
        (-1001234567890, "channel", "Demo"),
    )
    con.commit()
    con.close()

    from tgcli.commands import admin as admin_mod

    monkeypatch.setattr(admin_mod, "DB_PATH", db)
    monkeypatch.setattr(admin_mod, "AUDIT_PATH", tmp_path / "audit.log")

    from tgcli import Client

    c = Client()
    result = c.admin.chat_title(
        chat=-1001234567890,
        title="New Title",
        allow_write=True,
        dry_run=True,
    )
    assert result["dry_run"] is True
    assert result["command"] == "chat-title"
    assert result["payload"]["title"] == "New Title"


def test_admin_chat_title_without_allow_write_raises():
    from tgcli import Client
    from tgcli.safety import WriteDisallowed

    c = Client()
    with pytest.raises(WriteDisallowed):
        c.admin.chat_title(chat=-1001234567890, title="X")
