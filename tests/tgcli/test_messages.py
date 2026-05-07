import argparse

from tgcli.commands import messages
from tgcli.db import connect


def test_show_runner_delegates_pattern_to_resolver(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title) VALUES (?, ?, ?)",
        (123, "channel", "Polymarket"),
    )
    con.execute(
        """
        INSERT INTO tg_messages(chat_id, message_id, date, text, is_outgoing, has_media)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (123, 1, "2026-05-01T12:00:00", "hello", 0, 0),
    )
    con.commit()
    con.close()

    calls: list[str] = []

    def fake_resolve(con_arg, raw):
        calls.append(raw)
        return 123, "Polymarket"

    monkeypatch.setattr(messages, "DB_PATH", db)
    monkeypatch.setattr(messages, "resolve_chat_db", fake_resolve)

    args = argparse.Namespace(
        pattern="Polymarket",
        chat_id=None,
        limit=10,
        reverse=False,
    )
    data = messages._show_runner(args)

    assert calls == ["Polymarket"]
    assert data["chat"] == {"chat_id": 123, "title": "Polymarket"}
    assert data["messages"] == [
        {
            "date": "2026-05-01T12:00:00",
            "is_outgoing": False,
            "text": "hello",
            "media_type": None,
        }
    ]
