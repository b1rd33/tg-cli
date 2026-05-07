import asyncio
import json

import pytest

from tgcli.commands import auth
from tgcli.db import connect
from tgcli.resolve import NotFound


def _seed_me(path):
    con = connect(path)
    con.execute(
        """
        INSERT INTO tg_me(
            key, user_id, username, phone, first_name, last_name,
            display_name, is_bot, cached_at, raw_json
        ) VALUES ('self', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            42,
            "alice",
            "15550001000",
            "Alice",
            "Example",
            "Alice Example",
            0,
            "2026-05-07T10:00:00+00:00",
            json.dumps({"id": 42, "username": "alice"}),
        ),
    )
    con.commit()
    con.close()


def test_me_offline_reads_cached_self(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_me(db)
    monkeypatch.setattr(auth, "DB_PATH", db)

    data = auth._me_offline_runner()

    assert data["source"] == "cache"
    assert data["user_id"] == 42
    assert data["username"] == "alice"
    assert data["display_name"] == "Alice Example"
    assert data["raw_json"] == {"id": 42, "username": "alice"}


def test_me_offline_without_cache_raises_not_found(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    connect(db).close()
    monkeypatch.setattr(auth, "DB_PATH", db)

    with pytest.raises(NotFound):
        auth._me_offline_runner()


def test_me_live_uses_client_and_caches_result(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    monkeypatch.setattr(auth, "DB_PATH", db)

    class FakeUser:
        id = 77
        username = "liveuser"
        phone = "15550002000"
        first_name = "Live"
        last_name = "User"
        bot = False

        def to_dict(self):
            return {"id": self.id, "username": self.username}

    class FakeClient:
        def __init__(self):
            self.started = False
            self.disconnected = False

        async def start(self):
            self.started = True

        async def get_me(self):
            return FakeUser()

        async def disconnect(self):
            self.disconnected = True

    fake_client = FakeClient()
    monkeypatch.setattr(auth, "make_client", lambda session_path: fake_client)

    data = asyncio.run(auth._me_live_runner())

    assert fake_client.started is True
    assert fake_client.disconnected is True
    assert data["source"] == "live"
    assert data["user_id"] == 77
    assert data["username"] == "liveuser"

    cached = auth._me_offline_runner()
    assert cached["source"] == "cache"
    assert cached["user_id"] == 77
    assert cached["raw_json"] == {"id": 77, "username": "liveuser"}
