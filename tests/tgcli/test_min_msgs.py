import argparse

from tgcli.commands import contacts, stats
from tgcli.db import connect


def _seed_db(path):
    con = connect(path)
    con.executemany(
        "INSERT INTO tg_chats(chat_id, type, title) VALUES (?, ?, ?)",
        [
            (1, "user", "Busy"),
            (2, "user", "Quiet"),
        ],
    )
    con.executemany(
        "INSERT INTO tg_contacts(user_id, first_name, is_mutual) VALUES (?, ?, ?)",
        [
            (1, "Busy", 1),
            (2, "Quiet", 1),
        ],
    )
    con.executemany(
        """
        INSERT INTO tg_messages(chat_id, message_id, date, text, is_outgoing, has_media)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (1, 1, "2026-05-01T10:00:00", "a", 0, 0),
            (1, 2, "2026-05-01T10:01:00", "b", 0, 0),
            (1, 3, "2026-05-01T10:02:00", "c", 0, 0),
            (2, 1, "2026-05-01T11:00:00", "d", 0, 0),
        ],
    )
    con.commit()
    con.close()


def test_min_msgs_filters_stats_and_chatted_contacts(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_db(db)
    monkeypatch.setattr(stats, "DB_PATH", db)
    monkeypatch.setattr(contacts, "DB_PATH", db)

    stats_data = stats._gather(argparse.Namespace(min_msgs=2))
    assert stats_data["top_chats"] == [{"title": "Busy", "messages": 3}]
    assert stats_data["filters"] == {"min_msgs": 2}

    chatted_data = contacts._list_data(
        argparse.Namespace(
            chatted=True,
            with_phone_only=False,
            limit=10,
            min_msgs=2,
        )
    )
    assert [row["first_name"] for row in chatted_data["contacts"]] == ["Busy"]
    assert chatted_data["filters"]["min_msgs"] == 2

    unchatted_data = contacts._list_data(
        argparse.Namespace(
            chatted=False,
            with_phone_only=False,
            limit=10,
            min_msgs=2,
        )
    )
    assert [row["first_name"] for row in unchatted_data["contacts"]] == ["Busy", "Quiet"]


def test_min_msgs_zero_is_a_no_op(monkeypatch, tmp_path):
    """Default `--min-msgs 0` must not filter anything."""
    db = tmp_path / "telegram.sqlite"
    _seed_db(db)
    monkeypatch.setattr(stats, "DB_PATH", db)

    data = stats._gather(argparse.Namespace(min_msgs=0))
    titles = [row["title"] for row in data["top_chats"]]
    assert titles == ["Busy", "Quiet"]  # both chats present


def test_min_msgs_above_max_returns_empty(monkeypatch, tmp_path):
    """Threshold above the busiest chat yields an empty top_chats list."""
    db = tmp_path / "telegram.sqlite"
    _seed_db(db)
    monkeypatch.setattr(stats, "DB_PATH", db)

    data = stats._gather(argparse.Namespace(min_msgs=99))
    assert data["top_chats"] == []
    assert data["filters"] == {"min_msgs": 99}
