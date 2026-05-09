import argparse
import asyncio

import pytest

from tgcli.commands import chats, messages
from tgcli.db import connect
from tgcli.safety import BadArgs, WriteDisallowed


def _seed_chat(path):
    con = connect(path)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "supergroup", "Alpha Forum", "alpha_forum"),
    )
    con.commit()
    con.close()


def _args(**kw):
    defaults = {
        "allow_write": True,
        "dry_run": False,
        "idempotency_key": None,
        "fuzzy": False,
        "json": True,
        "human": False,
        "parse_mode": "plain",
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def test_topic_edit_requires_at_least_one_mutating_flag():
    args = _args(
        chat="@alpha_forum",
        topic_id=55,
        title=None,
        icon_emoji_id=None,
        closed=False,
        reopen=False,
        hidden=False,
        unhidden=False,
    )
    with pytest.raises(BadArgs, match="nothing to edit"):
        chats._topic_edit_mutations(args)


def test_topic_edit_rejects_conflicting_closed_flags():
    args = _args(
        chat="@alpha_forum",
        topic_id=55,
        title=None,
        icon_emoji_id=None,
        closed=True,
        reopen=True,
        hidden=False,
        unhidden=False,
    )
    with pytest.raises(BadArgs, match="mutually exclusive"):
        chats._topic_edit_mutations(args)


def test_topic_reply_precedence_and_topic_fallback():
    reply_to, warnings = messages._topic_reply_to(reply_to=44, topic=55)
    assert reply_to == 44
    assert warnings == ["--topic ignored because --reply-to was provided"]

    reply_to, warnings = messages._topic_reply_to(reply_to=None, topic=55)
    assert reply_to == 55
    assert warnings == []


def test_topics_list_uses_get_forum_topics_request(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeTopic:
        def __init__(self, topic_id, title):
            self.id = topic_id
            self.title = title
            self.icon_emoji_id = 987
            self.closed = False
            self.hidden = False
            self.top_message = topic_id
            self.unread_count = 3

    class FakeResult:
        topics = [FakeTopic(10, "General"), FakeTopic(20, "Ops")]

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def start(self):
            self.calls.append(("start",))

        async def get_entity(self, chat_id):
            self.calls.append(("get_entity", chat_id))
            return f"entity-{chat_id}"

        async def __call__(self, request):
            self.calls.append(("request", request))
            return FakeResult()

        async def disconnect(self):
            self.calls.append(("disconnect",))

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    data = asyncio.run(chats._topics_list_runner(_args(chat="@alpha_forum", limit=5, query="gen")))

    assert data["chat"] == {"chat_id": 123, "title": "Alpha Forum"}
    assert data["topics"][0] == {
        "topic_id": 10,
        "title": "General",
        "icon_emoji_id": 987,
        "closed": False,
        "hidden": False,
        "top_message_id": 10,
        "unread_count": 3,
    }
    request = [call[1] for call in fake.calls if call[0] == "request"][0]
    assert request.limit == 5
    assert request.q == "gen"


def test_topics_list_non_forum_error_becomes_bad_args(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        async def start(self):
            pass

        async def get_entity(self, chat_id):
            return f"entity-{chat_id}"

        async def __call__(self, request):
            # Simulate the real Telethon error class. Verified against
            # .venv/lib/python3.12/site-packages/telethon/errors/rpcerrorlist.py:446.
            from telethon.errors.rpcerrorlist import ChannelForumMissingError

            raise ChannelForumMissingError(request=request)

        async def disconnect(self):
            pass

    monkeypatch.setattr(chats, "make_client", lambda session_path: FakeClient())
    with pytest.raises(BadArgs, match="not a forum supergroup"):
        asyncio.run(chats._topics_list_runner(_args(chat="@alpha_forum", limit=5, query=None)))


def test_topic_create_calls_create_forum_topic_request_and_replays_idempotency(
    monkeypatch, tmp_path
):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeUpdates:
        updates = [argparse.Namespace(id=77, title="Launch")]

    class FakeClient:
        def __init__(self):
            self.calls = []
            self.create_count = 0

        async def start(self):
            self.calls.append(("start",))

        async def get_entity(self, chat_id):
            return f"entity-{chat_id}"

        async def __call__(self, request):
            self.calls.append(("request", request))
            self.create_count += 1
            return FakeUpdates()

        async def disconnect(self):
            self.calls.append(("disconnect",))

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    args = _args(
        chat="@alpha_forum",
        title="Launch",
        icon_emoji_id=123456,
        idempotency_key="topic-create-1",
    )

    first = asyncio.run(chats._topic_create_runner(args))
    second = asyncio.run(chats._topic_create_runner(args))

    assert first["topic_id"] == 77
    assert first["title"] == "Launch"
    assert first["chat"] == {"chat_id": 123, "title": "Alpha Forum"}
    assert second["topic_id"] == 77
    assert second["idempotent_replay"] is True
    assert fake.create_count == 1
    request = [call[1] for call in fake.calls if call[0] == "request"][0]
    assert request.title == "Launch"
    assert request.icon_emoji_id == 123456


def test_topic_edit_uses_edit_forum_topic_request(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def start(self):
            pass

        async def get_entity(self, chat_id):
            return f"entity-{chat_id}"

        async def __call__(self, request):
            self.calls.append(("request", request))

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    args = _args(
        chat="@alpha_forum",
        topic_id=55,
        title="Renamed",
        icon_emoji_id=999,
        closed=True,
        reopen=False,
        hidden=False,
        unhidden=True,
    )

    data = asyncio.run(chats._topic_edit_runner(args))

    assert data["topic_id"] == 55
    assert data["edited"] is True
    # When title/icon and closed/hidden are both set, runner splits into two
    # EditForumTopicRequest calls to avoid Telegram's TOPIC_CLOSE_SEPARATELY.
    assert data["telethon_calls"] == 2
    requests = [call[1] for call in fake.calls if call[0] == "request"]
    assert len(requests) == 2
    # First call: content (title + icon).
    assert requests[0].topic_id == 55
    assert requests[0].title == "Renamed"
    assert requests[0].icon_emoji_id == 999
    assert requests[0].closed is None  # state not in this call
    # Second call: state (closed + hidden).
    assert requests[1].topic_id == 55
    assert requests[1].title is None  # content not in this call
    assert requests[1].closed is True
    assert requests[1].hidden is False


def test_topic_pin_and_unpin_use_update_pinned_forum_topic_request(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.requests = []

        async def start(self):
            pass

        async def get_entity(self, chat_id):
            return f"entity-{chat_id}"

        async def __call__(self, request):
            self.requests.append(request)

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)

    pinned = asyncio.run(chats._topic_pin_runner(_args(chat="@alpha_forum", topic_id=55)))
    unpinned = asyncio.run(chats._topic_unpin_runner(_args(chat="@alpha_forum", topic_id=55)))

    assert pinned["pinned"] is True
    assert unpinned["pinned"] is False
    assert [request.pinned for request in fake.requests] == [True, False]


def test_send_topic_sets_reply_to_when_reply_to_unset(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    class FakeMessage:
        id = 777

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def start(self):
            pass

        async def get_entity(self, chat_id):
            return f"entity-{chat_id}"

        async def send_message(
            self, entity, text, *, reply_to=None, silent=False, link_preview=True, parse_mode=None
        ):
            self.calls.append(("send_message", entity, text, reply_to, silent, link_preview))
            return FakeMessage()

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(messages, "make_client", lambda session_path: fake)
    args = _args(
        chat="@alpha_forum", text="hello", reply_to=None, topic=55, silent=False, no_webpage=False
    )

    data = asyncio.run(messages._send_runner(args))

    assert data["topic_id"] == 55
    assert data["warnings"] == []
    assert ("send_message", "entity-123", "hello", 55, False, True) in fake.calls


def test_send_reply_to_overrides_topic_with_warning(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    class FakeMessage:
        id = 777

    class FakeClient:
        async def start(self):
            pass

        async def get_entity(self, chat_id):
            return f"entity-{chat_id}"

        async def send_message(
            self, entity, text, *, reply_to=None, silent=False, link_preview=True, parse_mode=None
        ):
            self.reply_to = reply_to
            return FakeMessage()

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(messages, "make_client", lambda session_path: fake)
    args = _args(
        chat="@alpha_forum", text="hello", reply_to=44, topic=55, silent=False, no_webpage=False
    )

    data = asyncio.run(messages._send_runner(args))

    assert fake.reply_to == 44
    assert data["topic_id"] == 55
    assert data["reply_to"] == 44
    assert data["warnings"] == ["--topic ignored because --reply-to was provided"]
