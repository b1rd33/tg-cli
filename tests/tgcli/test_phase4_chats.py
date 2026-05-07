import argparse
import asyncio
import json

from tgcli.commands import chats
from tgcli.db import connect


def test_chats_info_runner_returns_cached_metadata(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute(
        """
        INSERT INTO tg_chats(
            chat_id, type, title, username, phone, first_name,
            last_name, is_bot, last_seen_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            900,
            "supergroup",
            "Alpha Group",
            "alpha_group",
            None,
            None,
            None,
            0,
            "2026-05-07T09:00:00",
            json.dumps({"id": 900, "participants_count": 123}),
        ),
    )
    con.commit()
    con.close()
    monkeypatch.setattr(chats, "DB_PATH", db)

    data = chats._chat_info_runner(argparse.Namespace(chat="@alpha_group"))

    assert data["chat_id"] == 900
    assert data["title"] == "Alpha Group"
    assert data["username"] == "alpha_group"
    assert data["type"] == "supergroup"
    assert data["member_count"] == 123
    assert data["raw_json"] == {"id": 900, "participants_count": 123}


def test_unread_runner_lists_only_chats_with_unread(monkeypatch):
    class FakeEntity:
        def __init__(self, id_value, title):
            self.id = id_value
            self.title = title

    class FakeDialog:
        def __init__(self, id_value, title, unread_count):
            self.id = id_value
            self.entity = FakeEntity(id_value, title)
            self.unread_count = unread_count

    class FakeClient:
        def __init__(self):
            self.started = False
            self.disconnected = False

        async def start(self):
            self.started = True

        async def iter_dialogs(self):
            for dialog in [
                FakeDialog(1, "Quiet", 0),
                FakeDialog(2, "Busy", 5),
                FakeDialog(3, "Mentioned", 2),
            ]:
                yield dialog

        async def disconnect(self):
            self.disconnected = True

    fake_client = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake_client)

    data = asyncio.run(chats._unread_runner(argparse.Namespace()))

    assert fake_client.started is True
    assert fake_client.disconnected is True
    assert data["chats"] == [
        {"chat_id": 2, "title": "Busy", "type": "unknown", "unread_count": 5},
        {"chat_id": 3, "title": "Mentioned", "type": "unknown", "unread_count": 2},
    ]
    assert data["total_unread"] == 7
