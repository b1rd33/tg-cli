import argparse
import asyncio
import io
import json

import pytest

from tgcli.commands import messages
from tgcli.db import connect
from tgcli.safety import BadArgs, WriteDisallowed


def _seed_chat(path):
    con = connect(path)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "user", "Alpha Chat", "alpha"),
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
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def test_read_text_arg_reads_stdin_and_strips_trailing_newlines(monkeypatch):
    monkeypatch.setattr(messages.sys, "stdin", io.StringIO("hello\n\n"))
    assert messages._read_text_arg("-") == "hello"


def test_read_text_arg_rejects_empty_stdin(monkeypatch):
    monkeypatch.setattr(messages.sys, "stdin", io.StringIO("\n\n"))
    with pytest.raises(BadArgs, match="Text cannot be empty"):
        messages._read_text_arg("-")


def test_write_gate_runs_before_dry_run(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    args = _args(chat="@alpha", text="hello", allow_write=False, dry_run=True)
    with pytest.raises(WriteDisallowed):
        asyncio.run(messages._send_runner(args))


def test_send_dry_run_resolves_payload_and_skips_telethon(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    made_client = False

    def fail_make_client(session_path):
        nonlocal made_client
        made_client = True
        raise AssertionError("dry-run must not make a Telethon client")

    monkeypatch.setattr(messages, "make_client", fail_make_client)

    args = _args(
        chat="@alpha",
        text="hello",
        reply_to=5,
        silent=True,
        no_webpage=True,
        dry_run=True,
    )
    data = asyncio.run(messages._send_runner(args))

    assert made_client is False
    assert data["dry_run"] is True
    assert data["payload"]["chat"] == {"chat_id": 123, "title": "Alpha Chat"}
    assert data["payload"]["text"] == "hello"
    assert data["payload"]["telethon_method"] == "client.send_message"


def test_send_calls_telethon_and_returns_new_message_id(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    class FakeMessage:
        id = 777

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def start(self):
            self.calls.append(("start",))

        async def get_entity(self, chat_id):
            self.calls.append(("get_entity", chat_id))
            return f"entity-{chat_id}"

        async def send_message(
            self, entity, text, *, reply_to=None, silent=False, link_preview=True
        ):
            self.calls.append(("send_message", entity, text, reply_to, silent, link_preview))
            return FakeMessage()

        async def disconnect(self):
            self.calls.append(("disconnect",))

    fake = FakeClient()
    monkeypatch.setattr(messages, "make_client", lambda session_path: fake)
    args = _args(chat="@alpha", text="hello", reply_to=5, silent=True, no_webpage=True)

    data = asyncio.run(messages._send_runner(args))

    assert data["message_id"] == 777
    assert ("send_message", "entity-123", "hello", 5, True, False) in fake.calls
    assert fake.calls[-1] == ("disconnect",)


def test_edit_msg_calls_telethon(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    class FakeMessage:
        id = 55

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def start(self):
            self.calls.append(("start",))

        async def get_entity(self, chat_id):
            return f"entity-{chat_id}"

        async def edit_message(self, entity, message_id, text):
            self.calls.append(("edit_message", entity, message_id, text))
            return FakeMessage()

        async def disconnect(self):
            self.calls.append(("disconnect",))

    fake = FakeClient()
    monkeypatch.setattr(messages, "make_client", lambda session_path: fake)
    args = _args(chat="@alpha", message_id=55, text="updated")

    data = asyncio.run(messages._edit_msg_runner(args))

    assert data["message_id"] == 55
    assert ("edit_message", "entity-123", 55, "updated") in fake.calls
    assert fake.calls[-1] == ("disconnect",)


def test_forward_calls_telethon(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (456, "user", "Beta Chat", "beta"),
    )
    con.commit()
    con.close()
    monkeypatch.setattr(messages, "DB_PATH", db)

    class FakeMessage:
        id = 88

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def start(self):
            self.calls.append(("start",))

        async def get_entity(self, chat_id):
            self.calls.append(("get_entity", chat_id))
            return f"entity-{chat_id}"

        async def forward_messages(self, to_entity, messages, from_peer):
            self.calls.append(("forward_messages", to_entity, messages, from_peer))
            return FakeMessage()

        async def disconnect(self):
            self.calls.append(("disconnect",))

    fake = FakeClient()
    monkeypatch.setattr(messages, "make_client", lambda session_path: fake)
    args = _args(from_chat="@alpha", message_id=9, to_chat="@beta")

    data = asyncio.run(messages._forward_runner(args))

    assert data["message_id"] == 88
    assert ("forward_messages", "entity-456", 9, "entity-123") in fake.calls


def test_pin_msg_calls_telethon(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def start(self):
            self.calls.append(("start",))

        async def get_entity(self, chat_id):
            return f"entity-{chat_id}"

        async def pin_message(self, entity, message_id):
            self.calls.append(("pin_message", entity, message_id))

        async def disconnect(self):
            self.calls.append(("disconnect",))

    fake = FakeClient()
    monkeypatch.setattr(messages, "make_client", lambda session_path: fake)
    data = asyncio.run(messages._pin_msg_runner(_args(chat="@alpha", message_id=10)))

    assert data["message_id"] == 10
    assert ("pin_message", "entity-123", 10) in fake.calls


def test_unpin_msg_calls_telethon(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def start(self):
            self.calls.append(("start",))

        async def get_entity(self, chat_id):
            return f"entity-{chat_id}"

        async def unpin_message(self, entity, message_id):
            self.calls.append(("unpin_message", entity, message_id))

        async def disconnect(self):
            self.calls.append(("disconnect",))

    fake = FakeClient()
    monkeypatch.setattr(messages, "make_client", lambda session_path: fake)
    data = asyncio.run(messages._unpin_msg_runner(_args(chat="@alpha", message_id=10)))

    assert data["message_id"] == 10
    assert ("unpin_message", "entity-123", 10) in fake.calls


def test_react_uses_send_reaction_request(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def start(self):
            self.calls.append(("start",))

        async def get_entity(self, chat_id):
            return f"entity-{chat_id}"

        async def __call__(self, request):
            self.calls.append(("request", request))

        async def disconnect(self):
            self.calls.append(("disconnect",))

    fake = FakeClient()
    monkeypatch.setattr(messages, "make_client", lambda session_path: fake)
    data = asyncio.run(messages._react_runner(_args(chat="@alpha", message_id=10, emoji="👍")))

    assert data["message_id"] == 10
    assert data["emoji"] == "👍"
    request = [call[1] for call in fake.calls if call[0] == "request"][0]
    assert request.msg_id == 10


def test_mark_read_calls_send_read_acknowledge(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def start(self):
            self.calls.append(("start",))

        async def get_entity(self, chat_id):
            return f"entity-{chat_id}"

        async def send_read_acknowledge(self, entity):
            self.calls.append(("send_read_acknowledge", entity))

        async def disconnect(self):
            self.calls.append(("disconnect",))

    fake = FakeClient()
    monkeypatch.setattr(messages, "make_client", lambda session_path: fake)
    data = asyncio.run(messages._mark_read_runner(_args(chat="@alpha")))

    assert data["chat"] == {"chat_id": 123, "title": "Alpha Chat"}
    assert ("send_read_acknowledge", "entity-123") in fake.calls


def test_fuzzy_write_selector_requires_fuzzy(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    args = _args(chat="Alpha", text="hello")
    with pytest.raises(BadArgs, match="pass --fuzzy"):
        asyncio.run(messages._send_runner(args))


def test_idempotency_key_skips_second_telethon_call(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    class FakeMessage:
        id = 777

    class FakeClient:
        def __init__(self):
            self.send_count = 0

        async def start(self):
            pass

        async def get_entity(self, chat_id):
            return f"entity-{chat_id}"

        async def send_message(
            self, entity, text, *, reply_to=None, silent=False, link_preview=True
        ):
            self.send_count += 1
            return FakeMessage()

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(messages, "make_client", lambda session_path: fake)
    args = _args(
        chat="@alpha",
        text="hello",
        reply_to=None,
        silent=False,
        no_webpage=False,
        idempotency_key="same-key",
    )

    first = asyncio.run(messages._send_runner(args))
    second = asyncio.run(messages._send_runner(args))

    assert first["message_id"] == 777
    assert second["message_id"] == 777
    assert second["idempotent_replay"] is True
    assert fake.send_count == 1


def test_write_gate_blocks_even_with_valid_cache_hit(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    class FakeMessage:
        id = 999

    class FakeClient:
        async def start(self):
            pass

        async def get_entity(self, chat_id):
            return f"entity-{chat_id}"

        async def send_message(self, entity, text, **kw):
            return FakeMessage()

        async def disconnect(self):
            pass

    monkeypatch.setattr(messages, "make_client", lambda session_path: FakeClient())

    allowed = _args(
        chat="@alpha",
        text="hello",
        reply_to=None,
        silent=False,
        no_webpage=False,
        idempotency_key="shared-key",
    )
    allowed.allow_write = True
    asyncio.run(messages._send_runner(allowed))

    blocked = _args(
        chat="@alpha",
        text="hello",
        reply_to=None,
        silent=False,
        no_webpage=False,
        idempotency_key="shared-key",
    )
    blocked.allow_write = False
    with pytest.raises(WriteDisallowed):
        asyncio.run(messages._send_runner(blocked))


def test_rate_limit_blocks_before_telethon(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    class BlockingLimiter:
        def check(self):
            return 12.5

    monkeypatch.setattr(messages, "OUTBOUND_WRITE_LIMITER", BlockingLimiter())
    monkeypatch.setattr(
        messages,
        "make_client",
        lambda session_path: pytest.fail("rate-limited command must not call Telethon"),
    )

    args = _args(chat="@alpha", text="hello", reply_to=None, silent=False, no_webpage=False)
    with pytest.raises(messages.LocalRateLimited) as exc:
        asyncio.run(messages._send_runner(args))
    assert exc.value.retry_after_seconds == 12.5


def test_pre_audit_and_post_audit_share_request_id(monkeypatch, tmp_path, capsys):
    db = tmp_path / "telegram.sqlite"
    audit = tmp_path / "audit.log"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)
    monkeypatch.setattr(messages, "AUDIT_PATH", audit)

    class FakeMessage:
        id = 777

    class FakeClient:
        async def start(self):
            pass

        async def get_entity(self, chat_id):
            return f"entity-{chat_id}"

        async def send_message(
            self, entity, text, *, reply_to=None, silent=False, link_preview=True
        ):
            return FakeMessage()

        async def disconnect(self):
            pass

    monkeypatch.setattr(messages, "make_client", lambda session_path: FakeClient())
    args = _args(chat="@alpha", text="hello", reply_to=None, silent=False, no_webpage=False)

    code = messages.run_send(args)

    assert code == 0
    lines = [json.loads(line) for line in audit.read_text().splitlines()]
    before = [line for line in lines if line.get("phase") == "before"][0]
    after = [line for line in lines if line.get("result") == "ok"][0]
    assert before["request_id"] == after["request_id"]
