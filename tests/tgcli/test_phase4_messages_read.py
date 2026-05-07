import argparse
import json

import pytest

from tgcli.commands import messages
from tgcli.db import connect
from tgcli.resolve import NotFound


def _seed_messages_db(path):
    con = connect(path)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "user", "Alpha Chat", "alpha"),
    )
    con.executemany(
        """
        INSERT INTO tg_messages(
            chat_id, message_id, sender_id, date, text,
            is_outgoing, reply_to_msg_id, has_media, media_type, media_path, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                123,
                1,
                11,
                "2026-05-01T10:00:00",
                "Hello World",
                0,
                None,
                0,
                None,
                None,
                json.dumps({"id": 1, "message": "Hello World"}),
            ),
            (
                123,
                2,
                22,
                "2026-05-02T10:00:00",
                "hello lower",
                1,
                1,
                0,
                None,
                None,
                json.dumps({"id": 2, "message": "hello lower"}),
            ),
            (
                123,
                3,
                11,
                "2026-05-03T10:00:00",
                "Third item",
                0,
                None,
                1,
                "photo",
                "media/123/3.jpg",
                json.dumps({"id": 3, "message": "Third item"}),
            ),
        ],
    )
    con.commit()
    con.close()


def test_search_runner_finds_cached_messages_case_insensitive(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_messages_db(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    args = argparse.Namespace(
        chat="@alpha",
        query="hello",
        limit=50,
        case_sensitive=False,
    )
    data = messages._search_runner(args)

    assert data["chat"] == {"chat_id": 123, "title": "Alpha Chat"}
    assert data["query"] == "hello"
    assert data["case_sensitive"] is False
    assert [row["message_id"] for row in data["messages"]] == [2, 1]
    assert data["messages"][0]["is_outgoing"] is True


def test_search_runner_can_be_case_sensitive(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_messages_db(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    args = argparse.Namespace(
        chat="Alpha",
        query="Hello",
        limit=50,
        case_sensitive=True,
    )
    data = messages._search_runner(args)

    assert [row["message_id"] for row in data["messages"]] == [1]
    assert data["case_sensitive"] is True


def test_list_runner_applies_date_filters_and_reverse_order(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_messages_db(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    args = argparse.Namespace(
        chat="123",
        limit=50,
        since="2026-05-02",
        until="2026-05-03",
        reverse=True,
    )
    data = messages._list_runner(args)

    assert data["order"] == "oldest_first"
    assert data["filters"] == {
        "limit": 50,
        "since": "2026-05-02",
        "until": "2026-05-03",
    }
    assert [row["message_id"] for row in data["messages"]] == [2, 3]


def test_get_runner_returns_full_cached_message_with_raw_json(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_messages_db(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    args = argparse.Namespace(chat="@alpha", message_id=3)
    data = messages._get_runner(args)

    assert data["chat"] == {"chat_id": 123, "title": "Alpha Chat"}
    assert data["message"] == {
        "chat_id": 123,
        "message_id": 3,
        "sender_id": 11,
        "date": "2026-05-03T10:00:00",
        "text": "Third item",
        "is_outgoing": False,
        "reply_to_msg_id": None,
        "has_media": True,
        "media_type": "photo",
        "media_path": "media/123/3.jpg",
        "raw_json": {"id": 3, "message": "Third item"},
    }


def test_get_runner_missing_message_raises_not_found(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_messages_db(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    args = argparse.Namespace(chat="@alpha", message_id=999)
    with pytest.raises(NotFound):
        messages._get_runner(args)
