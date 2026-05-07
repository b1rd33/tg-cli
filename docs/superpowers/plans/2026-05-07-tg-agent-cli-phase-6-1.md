# Phase 6.1 - Forum Topic Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-05-07

**Author:** Codex

**Status:** Draft

**Prerequisite:** Phase 6 complete with `109 tests collected`; current flat write commands (`send`, `edit-msg`, `forward`, `pin-msg`, `unpin-msg`, `react`, `mark-read`) remain green before starting.

**Goal:** Add Phase 6.1 forum topic support: `topics-list`, `topic-create`, `topic-edit`, `topic-pin`, `topic-unpin`, plus `--topic` on `send`, `edit-msg`, and `forward`.

**Architecture:**
- Keep the flat argparse surface and register the five forum topic commands in `tgcli/commands/chats.py`.
- Topic writes reuse the existing Phase 6 safety pipeline: `add_write_flags(parser, destructive=False)`, `require_write_allowed(args)`, `require_explicit_or_fuzzy(args, raw_selector)`, dry-run short-circuiting, idempotency lookup/recording, `OUTBOUND_WRITE_LIMITER`, explicit `audit_pre()`, and post-call audit through `run_command()`.
- Telethon forum requests are covered with monkeypatched async fake clients and request-shape assertions; subprocess smoke tests cover parser surfaces and write-gate paths that do not need a live Telegram connection.

**Tech Stack:** Python 3.12 stdlib (`argparse`, `asyncio`, `json`, `sqlite3`, `datetime`, `pathlib`), Telethon 1.43.2 already present in the project, existing pytest. **No new third-party deps.**

**Backwards compatibility:** Current Phase 6 suite is `109 tests collected`. Phase 6.1 targets 10 unit tests plus 3 smoke tests, so the expected final count is `122 tests collected` within the acceptable `119-124` band.

---

## Existing Code Map

| Area | Current line references | Phase 6.1 use |
|---|---:|---|
| Phase 6 structural template | `docs/superpowers/plans/2026-05-07-tg-agent-cli-phase-6.md:1-24`, `26-87`, `89-2121` | Match header, code map, file table, design decisions, task checklist format, verification, commit sequence, checklist, and out-of-scope sections |
| Master resolved decisions | `docs/superpowers/plans/2026-05-06-tg-agent-cli.md:1315-1326` | Keep `--fuzzy` required for writes, audit pre/post entries sharing request id, `--idempotency-key`, and pure/unit/smoke/manual test strategy |
| Current message parser surface | `tgcli/commands/messages.py:89-116` | Add `--topic` to `send` and `forward` only (NOT `edit-msg` — see Design Decision 2) without changing existing positional arguments |
| Current message write helpers | `tgcli/commands/messages.py:605-662` | Reuse `_request_id()`, `_check_write_rate_limit()`, `_dry_run_envelope()`, `_write_result()`, `_resolve_write_chat()`, `_write_human()`, and `_run_write_command()` patterns |
| Current send runner | `tgcli/commands/messages.py:664-734` | Translate `--topic` to `reply_to=<topic_id>` when `--reply-to` is absent; preserve existing send safety/idempotency order |
| Current edit runner | `tgcli/commands/messages.py:737-796` | Untouched in Phase 6.1 — edits cannot change topic membership, see Design Decision 2 |
| Current forward runner | `tgcli/commands/messages.py:799-864` | Translate destination topic to `reply_to=<topic_id>` for forwarded messages when `--reply-to` is absent |
| Current chat parser surface | `tgcli/commands/chats.py:22-34` | Add `topics-list`, `topic-create`, `topic-edit`, `topic-pin`, and `topic-unpin` parsers beside `discover`, `unread`, and `chats-info` |
| Current live chat command lifecycle | `tgcli/commands/chats.py:37-56`, `74-98` | Reuse `make_client(SESSION_PATH)`, `await client.start()`, and `finally: await client.disconnect()` patterns for live topic commands |
| Current cached chat info resolver | `tgcli/commands/chats.py:128-170` | Resolve topic command chat selectors from SQLite before calling Telethon |
| Common write flags | `tgcli/commands/_common.py:35-48` | Use existing `--allow-write`, `--dry-run`, `--idempotency-key`, and `--fuzzy` flags for topic writes |
| Safety gates and audit | `tgcli/safety.py:37-75`, `99-127` | Reuse write gate, fuzzy gate, process-local limiter, and pre-call audit |
| Idempotency helpers | `tgcli/idempotency.py:12-57` | Reuse lookup/record mechanism for `topic-create` replay, recording the result envelope including `topic_id` |
| Dispatch envelope and request id | `tgcli/dispatch.py:89-127` | Runners receive `args._request_id`; successful data is wrapped with warnings by output envelope |
| Resolver behavior | `tgcli/resolve.py:41-82` | Integer ids and usernames are explicit; title selectors require `--fuzzy` for topic writes |
| CLI module loading | `tgcli/__main__.py:18-25` | No source change needed because `tgcli.commands.chats` and `tgcli.commands.messages` are already imported |
| Existing Phase 6 unit tests | `tests/tgcli/test_phase6_writes.py:23-33`, `57-123`, `332-374` | Reuse `_args()` style, fake Telethon clients, dry-run assertions, and idempotency replay shape |
| Existing smoke tests | `tests/tgcli/test_cli_smoke.py:284-456` | Extend help, write-gate, fuzzy-gate, and dry-run smoke patterns for forum topic commands |

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| tgcli/commands/messages.py | modify | Add --topic flag to send and forward parsers (NOT edit-msg); add ForwardMessagesRequest import; wire `--topic` into _send_runner and _forward_runner |
| tgcli/commands/chats.py | modify | Add topics-list, topic-create, topic-edit, topic-pin, topic-unpin parsers and runners |
| tests/tgcli/test_phase61_topics.py | create | Unit tests for all 5 topic commands + --topic on send |
| tests/tgcli/test_cli_smoke.py | modify | Add subprocess smoke tests for parser surfaces and write-gate paths |

---

## Design Decisions

1. **Naming: flat hyphenated names.** Use `topics-list`, `topic-create`, `topic-edit`, `topic-pin`, and `topic-unpin`. This avoids restructuring argparse for one phase and stays consistent with the current flat namespace in `tgcli/commands/messages.py:89-144` and `tgcli/commands/chats.py:22-34`.

2. **`--topic` flag scope: only on `send` and `forward`. NOT on `edit-msg`.** Telethon 1.43.2's `client.edit_message()` and underlying `EditMessageRequest` have no topic/reply_to field — edits cannot move a message between topics. Adding `--topic` to `edit-msg` would be a no-op at best, runtime error at worst. Drop it.

3. **`--topic` on `send`: precedence and mechanism.** `client.send_message(reply_to=N)` uses the topic root message id as the topic anchor. When user passes both `--topic` and `--reply-to`, prefer `--reply-to` (more explicit) and emit a warning in the envelope. Single helper `_topic_reply_to(reply_to, topic) -> (effective_reply_to, warnings)` shared between runners.

4. **`--topic` on `forward`: use raw `ForwardMessagesRequest`.** `client.forward_messages()` (the high-level wrapper) does NOT accept `reply_to` or `top_msg_id`, but the underlying `ForwardMessagesRequest(from_peer, id, to_peer, top_msg_id=N, ...)` does. When `--topic` is set on `forward`, the runner constructs `ForwardMessagesRequest` directly and calls `client(req)`. When unset, keep using the high-level `client.forward_messages()` for ergonomic preservation (random_ids, drop_author defaults).

5. **Forum-supergroup detection.** Catch the concrete Telethon exception classes `ChannelForumMissingError` and `BroadcastForbiddenError` from `telethon.errors.rpcerrorlist` (NOT a generic string match), and translate to `BadArgs("not a forum supergroup")` for clearer agent UX.

6. **Idempotency for ALL write topic commands.** Reuse the existing `--idempotency-key` mechanism from Phase 6 in `topic-create`, `topic-edit`, `topic-pin`, AND `topic-unpin` runners. Each runner does `lookup_idempotency` → return cached envelope on hit, otherwise execute Telethon call and `record_idempotency` with the resulting envelope. Do not expose Telethon `random_id` directly as a CLI argument. (Phase 6 review note: a `pin-msg` runner without idempotency would silently let agents double-pin on retry; same logic applies to topic pin/unpin.)

7. **Live topics, cached chats.** Topic data is always fetched live from Telethon and is not stored in the local SQLite DB. Chat selectors still resolve through cached `tg_chats` first, matching existing write command behavior in `tgcli/commands/messages.py:644-647`.

8. **No destructive topic operations.** `DeleteTopicHistoryRequest` and `tg topic-delete` are out of scope for Phase 6.1 because deleting topic history is destructive and belongs in Phase 10.

---

## Task 1: Parser surfaces and shared topic helpers

**Goal:** Add the Phase 6.1 argparse surface and small helper functions before implementing Telethon behavior.

**Files:**
- Modify: `tgcli/commands/messages.py`
- Modify: `tgcli/commands/chats.py`
- Create: `tests/tgcli/test_phase61_topics.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Write failing parser/unit tests for topic helpers**

Create `tests/tgcli/test_phase61_topics.py` with the shared fixtures and first parser assertions:

```python
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
```

- [ ] **Step 2: Add failing smoke tests for help surfaces**

Append to `tests/tgcli/test_cli_smoke.py`:

```python
def test_phase61_topic_and_message_topic_help_surfaces():
    commands = ["topics-list", "topic-create", "topic-edit", "topic-pin", "topic-unpin"]
    for command in commands:
        result = _subprocess.run(
            [str(PYTHON), "-m", "tgcli", command, "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"command: {command} stderr: {result.stderr}"
        assert "usage:" in result.stdout.lower()

    for command in ["send", "edit-msg", "forward"]:
        result = _subprocess.run(
            [str(PYTHON), "-m", "tgcli", command, "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"command: {command} stderr: {result.stderr}"
        assert "--topic" in result.stdout
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase61_topics.py tests/tgcli/test_cli_smoke.py::test_phase61_topic_and_message_topic_help_surfaces -q
```

Expected: FAIL because `_topic_edit_mutations()`, `_topic_reply_to()`, topic parsers, and `--topic` parser flags do not exist. Use the actual smoke test name `test_phase61_topic_and_message_topic_help_surfaces` after adding the combined test above.

- [ ] **Step 4: Add message parser flags and helper**

In `tgcli/commands/messages.py`, add `--topic` to `send` and `forward` only (NOT `edit-msg` — see Design Decision 2). Insert near `tgcli/commands/messages.py:89-116`:

```python
snd.add_argument("--topic", type=int, default=None,
                 help="Forum topic root message id; ignored when --reply-to is provided")

fwd.add_argument("--topic", type=int, default=None,
                 help="Destination forum topic root message id (forwards into a topic in the destination chat)")
```

Note: `edit-msg` does NOT get a `--topic` flag. Telethon's `edit_message` has no topic-routing parameter; adding the flag would be misleading. `forward` does NOT get `--reply-to` either — replies-on-forward is not a meaningful operation (you forward a message; replies attach to send/edit, not to copy operations).

Add this helper near `_dry_run_envelope()` in `tgcli/commands/messages.py:625-631`:

```python
def _topic_reply_to(*, reply_to: int | None, topic: int | None) -> tuple[int | None, list[str]]:
    if reply_to is not None and topic is not None:
        return reply_to, ["--topic ignored because --reply-to was provided"]
    if reply_to is not None:
        return reply_to, []
    return topic, []
```

- [ ] **Step 5: Add topic parser registrations and edit validation helper**

In `tgcli/commands/chats.py`, extend imports:

```python
from tgcli.commands._common import (
    AUDIT_PATH,
    DB_PATH,
    SESSION_PATH,
    add_output_flags,
    add_write_flags,
    decode_raw_json,
)
from tgcli.safety import BadArgs
```

Add parser registrations after `chats-info` in `tgcli/commands/chats.py:31-34`:

```python
topics = sub.add_parser("topics-list", help="List forum topics in a supergroup")
topics.add_argument("chat", help="Forum supergroup selector resolved from the local DB")
topics.add_argument("--limit", type=int, default=50, help="Number of topics (default 50)")
topics.add_argument("--query", default=None, help="Search topic titles")
add_output_flags(topics)
topics.set_defaults(func=run_topics_list)

create = sub.add_parser("topic-create", help="Create a forum topic")
create.add_argument("chat", help="Forum supergroup selector resolved from the local DB")
create.add_argument("title", help="Topic title")
create.add_argument("--icon-emoji-id", type=int, default=None, help="Telegram custom emoji id")
add_write_flags(create, destructive=False)
add_output_flags(create)
create.set_defaults(func=run_topic_create)

edit = sub.add_parser("topic-edit", help="Edit a forum topic")
edit.add_argument("chat", help="Forum supergroup selector resolved from the local DB")
edit.add_argument("topic_id", type=int, help="Topic root message id")
edit.add_argument("--title", default=None, help="New topic title")
edit.add_argument("--icon-emoji-id", type=int, default=None, help="Telegram custom emoji id")
state = edit.add_mutually_exclusive_group()
state.add_argument("--closed", action="store_true", help="Close the topic")
state.add_argument("--reopen", action="store_true", help="Reopen the topic")
visibility = edit.add_mutually_exclusive_group()
visibility.add_argument("--hidden", action="store_true", help="Hide the topic")
visibility.add_argument("--unhidden", action="store_true", help="Unhide the topic")
add_write_flags(edit, destructive=False)
add_output_flags(edit)
edit.set_defaults(func=run_topic_edit)

pin = sub.add_parser("topic-pin", help="Pin a forum topic")
pin.add_argument("chat", help="Forum supergroup selector resolved from the local DB")
pin.add_argument("topic_id", type=int, help="Topic root message id")
add_write_flags(pin, destructive=False)
add_output_flags(pin)
pin.set_defaults(func=run_topic_pin)

unpin = sub.add_parser("topic-unpin", help="Unpin a forum topic")
unpin.add_argument("chat", help="Forum supergroup selector resolved from the local DB")
unpin.add_argument("topic_id", type=int, help="Topic root message id")
add_write_flags(unpin, destructive=False)
add_output_flags(unpin)
unpin.set_defaults(func=run_topic_unpin)
```

Add this validation helper below the existing parser block:

```python
def _topic_edit_mutations(args) -> dict[str, Any]:
    if getattr(args, "closed", False) and getattr(args, "reopen", False):
        raise BadArgs("--closed and --reopen are mutually exclusive")
    if getattr(args, "hidden", False) and getattr(args, "unhidden", False):
        raise BadArgs("--hidden and --unhidden are mutually exclusive")

    mutations: dict[str, Any] = {}
    if args.title is not None:
        if str(args.title).strip() == "":
            raise BadArgs("topic title cannot be empty")
        mutations["title"] = args.title
    if args.icon_emoji_id is not None:
        mutations["icon_emoji_id"] = int(args.icon_emoji_id)
    if getattr(args, "closed", False):
        mutations["closed"] = True
    if getattr(args, "reopen", False):
        mutations["closed"] = False
    if getattr(args, "hidden", False):
        mutations["hidden"] = True
    if getattr(args, "unhidden", False):
        mutations["hidden"] = False
    if not mutations:
        raise BadArgs("nothing to edit")
    return mutations
```

- [ ] **Step 6: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase61_topics.py::test_topic_edit_requires_at_least_one_mutating_flag tests/tgcli/test_phase61_topics.py::test_topic_edit_rejects_conflicting_closed_flags tests/tgcli/test_phase61_topics.py::test_topic_reply_precedence_and_topic_fallback tests/tgcli/test_cli_smoke.py::test_phase61_topic_and_message_topic_help_surfaces -q
```

Expected: PASS.

- [ ] **Step 7: Run full suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: PASS with `113 tests collected` after this task.

- [ ] **Step 8: Commit**

```bash
git add tgcli/commands/messages.py tgcli/commands/chats.py tests/tgcli/test_phase61_topics.py tests/tgcli/test_cli_smoke.py
git commit -m "feat(tgcli): add forum topic parser surfaces"
```

---

## Task 2: `tg topics-list`

**Goal:** Implement `tg topics-list <chat> [--limit N] [--query "search"]` as a live read-only Telethon command using `GetForumTopicsRequest`.

**Files:**
- Modify: `tgcli/commands/chats.py`
- Modify: `tests/tgcli/test_phase61_topics.py`

- [ ] **Step 1: Add failing unit tests for topics-list**

Append to `tests/tgcli/test_phase61_topics.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase61_topics.py::test_topics_list_uses_get_forum_topics_request tests/tgcli/test_phase61_topics.py::test_topics_list_non_forum_error_becomes_bad_args -q
```

Expected: FAIL because `_topics_list_runner()` and Telethon topic imports do not exist.

- [ ] **Step 3: Add Telethon imports and list implementation**

Add imports to `tgcli/commands/chats.py`:

```python
from telethon.errors.rpcerrorlist import (
    BroadcastForbiddenError,
    ChannelForumMissingError,
)
from telethon.tl.functions.messages import GetForumTopicsRequest
```

Add helpers and runner after `_topic_edit_mutations()`:

```python
# Concrete Telethon error classes for forum detection. Avoid string-matching:
# the server's error_message text can change without notice, but the class
# names are stable.
_NON_FORUM_ERRORS: tuple[type[BaseException], ...] = (
    ChannelForumMissingError,
    BroadcastForbiddenError,
)


def _is_non_forum_error(exc: BaseException) -> bool:
    return isinstance(exc, _NON_FORUM_ERRORS)


def _topic_summary(topic) -> dict[str, Any]:
    return {
        "topic_id": int(getattr(topic, "id", getattr(topic, "topic_id", 0))),
        "title": getattr(topic, "title", None),
        "icon_emoji_id": getattr(topic, "icon_emoji_id", None),
        "closed": bool(getattr(topic, "closed", False)),
        "hidden": bool(getattr(topic, "hidden", False)),
        "top_message_id": getattr(topic, "top_message", getattr(topic, "top_message_id", None)),
        "unread_count": int(getattr(topic, "unread_count", 0) or 0),
    }


async def _topics_list_runner(args) -> dict[str, Any]:
    con = connect_readonly(DB_PATH)
    try:
        chat_id, chat_title = resolve_chat_db(con, args.chat)
    finally:
        con.close()

    client = make_client(SESSION_PATH)
    await client.start()
    try:
        entity = await client.get_entity(chat_id)
        try:
            result = await client(
                GetForumTopicsRequest(
                    peer=entity,
                    offset_date=None,
                    offset_id=0,
                    offset_topic=0,
                    limit=max(int(args.limit), 1),
                    q=args.query,
                )
            )
        except Exception as exc:
            if _is_non_forum_error(exc):
                raise BadArgs("not a forum supergroup") from exc
            raise
    finally:
        await client.disconnect()

    return {
        "chat": {"chat_id": chat_id, "title": chat_title},
        "limit": max(int(args.limit), 1),
        "query": args.query,
        "topics": [_topic_summary(topic) for topic in getattr(result, "topics", [])],
    }
```

Add runner wrapper:

```python
def run_topics_list(args) -> int:
    return run_command(
        "topics-list",
        args,
        runner=lambda: _topics_list_runner(args),
        human_formatter=_topics_human,
        audit_path=AUDIT_PATH,
    )
```

Add a simple human formatter:

```python
def _topics_human(data: dict) -> None:
    print(f"{data['chat']['title']} topics ({len(data['topics'])})")
    for topic in data["topics"]:
        state = []
        if topic["closed"]:
            state.append("closed")
        if topic["hidden"]:
            state.append("hidden")
        suffix = f" [{' '.join(state)}]" if state else ""
        print(f"  {topic['topic_id']:>8}  {topic['title']}{suffix}")
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase61_topics.py::test_topics_list_uses_get_forum_topics_request tests/tgcli/test_phase61_topics.py::test_topics_list_non_forum_error_becomes_bad_args -q
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: PASS with `117 tests collected`.

- [ ] **Step 6: Commit**

```bash
git add tgcli/commands/chats.py tests/tgcli/test_phase61_topics.py
git commit -m "feat(tgcli): list forum topics"
```

---

## Task 3: `tg topic-create`

**Goal:** Implement `tg topic-create <chat> "<title>" [--icon-emoji-id <id>]` with full write safety, dry-run, audit, rate limit, and idempotency replay.

**Files:**
- Modify: `tgcli/commands/chats.py`
- Modify: `tests/tgcli/test_phase61_topics.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Add failing unit and smoke tests for topic-create**

Append to `tests/tgcli/test_phase61_topics.py`:

```python
def test_topic_create_calls_create_forum_topic_request_and_replays_idempotency(monkeypatch, tmp_path):
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
```

Append to `tests/tgcli/test_cli_smoke.py`:

```python
def test_phase61_topic_create_write_gate_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "supergroup", "Alpha Forum", "alpha_forum"),
    )
    con.commit()
    con.close()

    env = {
        **_os.environ,
        "TG_API_ID": "1",
        "TG_API_HASH": "x",
        "TG_DB_PATH": str(db),
        "TG_AUDIT_PATH": str(tmp_path / "audit.log"),
    }
    result = _subprocess.run(
        [str(PYTHON), "-m", "tgcli", "topic-create", "@alpha_forum", "Launch", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 6
    payload = _json.loads(result.stdout)
    assert payload["error"]["code"] == "WRITE_DISALLOWED"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase61_topics.py::test_topic_create_calls_create_forum_topic_request_and_replays_idempotency tests/tgcli/test_cli_smoke.py::test_phase61_topic_create_write_gate_smoke -q
```

Expected: FAIL because `_topic_create_runner()` and the write-gate path are not implemented.

- [ ] **Step 3: Add topic-create implementation**

Add imports in `tgcli/commands/chats.py`:

```python
from telethon.tl.functions.messages import CreateForumTopicRequest, GetForumTopicsRequest

from tgcli.commands.messages import (
    _check_write_rate_limit,
    _dry_run_envelope,
    _request_id,
    _resolve_write_chat,
    _run_write_command,
    _write_result,
)
from tgcli.idempotency import lookup as lookup_idempotency
from tgcli.idempotency import record as record_idempotency
from tgcli.safety import BadArgs, audit_pre, require_write_allowed
```

Add helper and runner:

```python
def _created_topic_from_update(result, fallback_title: str) -> tuple[int, str]:
    for update in getattr(result, "updates", []) or []:
        topic_id = getattr(update, "id", None)
        if topic_id is None:
            topic_id = getattr(update, "topic_id", None)
        if topic_id is not None:
            return int(topic_id), getattr(update, "title", fallback_title)
    raise BadArgs("topic create response did not include topic_id")


async def _topic_create_runner(args) -> dict[str, Any]:
    command = "topic-create"
    request_id = _request_id(args)
    require_write_allowed(args)
    if str(args.title).strip() == "":
        raise BadArgs("topic title cannot be empty")

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        chat = _resolve_write_chat(con, args, args.chat)
        payload = {
            "chat": chat,
            "title": args.title,
            "icon_emoji_id": args.icon_emoji_id,
            "telethon_method": "CreateForumTopicRequest",
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)

        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=chat["chat_id"],
            resolved_chat_title=chat["title"],
            payload_preview=payload,
            telethon_method="CreateForumTopicRequest",
            dry_run=False,
        )

        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            result = await client(
                CreateForumTopicRequest(
                    peer=entity,
                    title=args.title,
                    icon_emoji_id=args.icon_emoji_id,
                )
            )
            topic_id, title = _created_topic_from_update(result, args.title)
            data = {
                "topic_id": topic_id,
                "title": title,
                "chat": chat,
                "idempotent_replay": False,
            }
            record_idempotency(con, args.idempotency_key, command, request_id, _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_topic_create(args) -> int:
    return _run_write_command("topic-create", args, _topic_create_runner)
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase61_topics.py::test_topic_create_calls_create_forum_topic_request_and_replays_idempotency tests/tgcli/test_cli_smoke.py::test_phase61_topic_create_write_gate_smoke -q
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: PASS with `117 tests collected`.

- [ ] **Step 6: Commit**

```bash
git add tgcli/commands/chats.py tests/tgcli/test_phase61_topics.py tests/tgcli/test_cli_smoke.py
git commit -m "feat(tgcli): create forum topics safely"
```

---

## Task 4: `tg topic-edit`, `tg topic-pin`, and `tg topic-unpin`

**Goal:** Implement forum topic mutation commands using `EditForumTopicRequest` and `UpdatePinnedForumTopicRequest`.

**Files:**
- Modify: `tgcli/commands/chats.py`
- Modify: `tests/tgcli/test_phase61_topics.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Add failing unit tests for edit and pin state**

Append to `tests/tgcli/test_phase61_topics.py`:

```python
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
    request = [call[1] for call in fake.calls if call[0] == "request"][0]
    assert request.topic_id == 55
    assert request.title == "Renamed"
    assert request.icon_emoji_id == 999
    assert request.closed is True
    assert request.hidden is False


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
```

Append to `tests/tgcli/test_cli_smoke.py`:

```python
def test_phase61_topic_write_dry_run_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "supergroup", "Alpha Forum", "alpha_forum"),
    )
    con.commit()
    con.close()

    env = {
        **_os.environ,
        "TG_API_ID": "1",
        "TG_API_HASH": "x",
        "TG_DB_PATH": str(db),
        "TG_AUDIT_PATH": str(tmp_path / "audit.log"),
    }
    commands = [
        [str(PYTHON), "-m", "tgcli", "topic-edit", "@alpha_forum", "55", "--title", "Renamed", "--allow-write", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "topic-pin", "@alpha_forum", "55", "--allow-write", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "topic-unpin", "@alpha_forum", "55", "--allow-write", "--dry-run", "--json"],
    ]
    for command in commands:
        result = _subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, f"command: {command} stderr: {result.stderr}"
        payload = _json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["dry_run"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase61_topics.py::test_topic_edit_uses_edit_forum_topic_request tests/tgcli/test_phase61_topics.py::test_topic_pin_and_unpin_use_update_pinned_forum_topic_request tests/tgcli/test_cli_smoke.py::test_phase61_topic_write_dry_run_smoke -q
```

Expected: FAIL because edit/pin runners do not exist.

- [ ] **Step 3: Add edit and pin implementations**

Add imports:

```python
from telethon.tl.functions.messages import (
    CreateForumTopicRequest,
    EditForumTopicRequest,
    GetForumTopicsRequest,
    UpdatePinnedForumTopicRequest,
)
```

Add runners:

```python
async def _topic_edit_runner(args) -> dict[str, Any]:
    command = "topic-edit"
    request_id = _request_id(args)
    require_write_allowed(args)
    mutations = _topic_edit_mutations(args)

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data

        chat = _resolve_write_chat(con, args, args.chat)
        payload = {
            "chat": chat,
            "topic_id": int(args.topic_id),
            **mutations,
            "telethon_method": "EditForumTopicRequest",
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)
        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=chat["chat_id"],
            resolved_chat_title=chat["title"],
            payload_preview=payload,
            telethon_method="EditForumTopicRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            await client(EditForumTopicRequest(peer=entity, topic_id=int(args.topic_id), **mutations))
            data = {"chat": chat, "topic_id": int(args.topic_id), "edited": True, "idempotent_replay": False}
            record_idempotency(con, args.idempotency_key, command, request_id, _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


async def _topic_pin_state_runner(args, *, command: str, pinned: bool) -> dict[str, Any]:
    request_id = _request_id(args)
    require_write_allowed(args)
    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data

        chat = _resolve_write_chat(con, args, args.chat)
        payload = {
            "chat": chat,
            "topic_id": int(args.topic_id),
            "pinned": pinned,
            "telethon_method": "UpdatePinnedForumTopicRequest",
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)
        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=chat["chat_id"],
            resolved_chat_title=chat["title"],
            payload_preview=payload,
            telethon_method="UpdatePinnedForumTopicRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            await client(UpdatePinnedForumTopicRequest(peer=entity, topic_id=int(args.topic_id), pinned=pinned))
            data = {"chat": chat, "topic_id": int(args.topic_id), "pinned": pinned, "idempotent_replay": False}
            record_idempotency(con, args.idempotency_key, command, request_id, _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


async def _topic_pin_runner(args) -> dict[str, Any]:
    return await _topic_pin_state_runner(args, command="topic-pin", pinned=True)


async def _topic_unpin_runner(args) -> dict[str, Any]:
    return await _topic_pin_state_runner(args, command="topic-unpin", pinned=False)


def run_topic_edit(args) -> int:
    return _run_write_command("topic-edit", args, _topic_edit_runner)


def run_topic_pin(args) -> int:
    return _run_write_command("topic-pin", args, _topic_pin_runner)


def run_topic_unpin(args) -> int:
    return _run_write_command("topic-unpin", args, _topic_unpin_runner)
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase61_topics.py::test_topic_edit_uses_edit_forum_topic_request tests/tgcli/test_phase61_topics.py::test_topic_pin_and_unpin_use_update_pinned_forum_topic_request tests/tgcli/test_cli_smoke.py::test_phase61_topic_write_dry_run_smoke -q
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: PASS with `120 tests collected`.

- [ ] **Step 6: Commit**

```bash
git add tgcli/commands/chats.py tests/tgcli/test_phase61_topics.py tests/tgcli/test_cli_smoke.py
git commit -m "feat(tgcli): edit and pin forum topics"
```

---

## Task 5: `--topic` on `send`, `edit-msg`, and `forward`

**Goal:** Route existing text writes into forum topics by translating `--topic <id>` to `reply_to=<topic_id>`, while preferring `--reply-to` when both are supplied.

**Files:**
- Modify: `tgcli/commands/messages.py`
- Modify: `tests/tgcli/test_phase61_topics.py`

- [ ] **Step 1: Add failing unit tests for send topic routing**

Append to `tests/tgcli/test_phase61_topics.py`:

```python
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

        async def send_message(self, entity, text, *, reply_to=None, silent=False, link_preview=True):
            self.calls.append(("send_message", entity, text, reply_to, silent, link_preview))
            return FakeMessage()

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(messages, "make_client", lambda session_path: fake)
    args = _args(chat="@alpha_forum", text="hello", reply_to=None, topic=55, silent=False, no_webpage=False)

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

        async def send_message(self, entity, text, *, reply_to=None, silent=False, link_preview=True):
            self.reply_to = reply_to
            return FakeMessage()

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(messages, "make_client", lambda session_path: fake)
    args = _args(chat="@alpha_forum", text="hello", reply_to=44, topic=55, silent=False, no_webpage=False)

    data = asyncio.run(messages._send_runner(args))

    assert fake.reply_to == 44
    assert data["topic_id"] == 55
    assert data["reply_to"] == 44
    assert data["warnings"] == ["--topic ignored because --reply-to was provided"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase61_topics.py::test_send_topic_sets_reply_to_when_reply_to_unset tests/tgcli/test_phase61_topics.py::test_send_reply_to_overrides_topic_with_warning -q
```

Expected: FAIL because `_send_runner()` still passes only `args.reply_to`.

- [ ] **Step 3: Wire `--topic` through send, edit, and forward payloads**

In `_send_runner()` around `tgcli/commands/messages.py:678-712`, compute the effective reply once and use it in payload and Telethon call:

```python
reply_to, warnings = _topic_reply_to(reply_to=args.reply_to, topic=getattr(args, "topic", None))
payload = {
    "chat": chat,
    "text": text,
    "reply_to": reply_to,
    "topic_id": getattr(args, "topic", None),
    "silent": bool(args.silent),
    "link_preview": not bool(args.no_webpage),
    "telethon_method": "client.send_message",
    "warnings": warnings,
}
```

Use `reply_to=reply_to` in `client.send_message()` and return warnings in data:

```python
data = {
    "chat": chat,
    "message_id": int(sent.id),
    "text": text,
    "reply_to": reply_to,
    "topic_id": getattr(args, "topic", None),
    "warnings": warnings,
    "idempotent_replay": False,
}
```

In `_edit_msg_runner()` around `tgcli/commands/messages.py:750-787`, compute the same effective `reply_to` metadata and include it in the dry-run/audit payload and returned data:

```python
reply_to, warnings = _topic_reply_to(reply_to=getattr(args, "reply_to", None), topic=getattr(args, "topic", None))
payload = {
    "chat": chat,
    "message_id": int(args.message_id),
    "text": text,
    "reply_to": reply_to,
    "topic_id": getattr(args, "topic", None),
    "warnings": warnings,
    "telethon_method": "client.edit_message",
}
```

**Skip the edit-msg patch entirely.** Per Design Decision 2, `edit-msg` does not gain a `--topic` flag. Leave `_edit_msg_runner` untouched.

In `_forward_runner()` around `tgcli/commands/messages.py:811-841`, branch the Telethon call based on whether `--topic` was set. Add the necessary import at the top of `messages.py`:

```python
from telethon.tl.functions.messages import ForwardMessagesRequest
```

Then in the runner:

```python
topic_id = getattr(args, "topic", None)
payload = {
    "from_chat": from_chat,
    "to_chat": to_chat,
    "message_id": int(args.message_id),
    "topic_id": topic_id,
    "telethon_method": (
        "client(ForwardMessagesRequest)" if topic_id is not None
        else "client.forward_messages"
    ),
}
```

Telethon call:

```python
if topic_id is not None:
    # Raw request — high-level forward_messages() doesn't accept top_msg_id.
    from_input = await client.get_input_entity(from_entity)
    to_input = await client.get_input_entity(to_entity)
    result = await client(ForwardMessagesRequest(
        from_peer=from_input,
        id=[int(args.message_id)],
        to_peer=to_input,
        top_msg_id=topic_id,
    ))
    # Result is an Updates; extract the new message id from result.updates[*].message
    forwarded_id = None
    for upd in getattr(result, "updates", []):
        msg = getattr(upd, "message", None)
        if msg is not None:
            forwarded_id = msg.id
            break
else:
    forwarded = await client.forward_messages(
        to_entity,
        messages=int(args.message_id),
        from_peer=from_entity,
    )
    forwarded_id = forwarded.id if not isinstance(forwarded, list) else forwarded[0].id
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase61_topics.py::test_send_topic_sets_reply_to_when_reply_to_unset tests/tgcli/test_phase61_topics.py::test_send_reply_to_overrides_topic_with_warning tests/tgcli/test_phase6_writes.py::test_send_calls_telethon_and_returns_new_message_id tests/tgcli/test_phase6_writes.py::test_forward_calls_telethon -q
```

Expected: PASS. If the existing fake forward client rejects the new `reply_to` keyword, update that test fake to accept `reply_to=None` and assert the default remains `None`.

- [ ] **Step 5: Run full suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: PASS with `122 tests collected`.

- [ ] **Step 6: Commit**

```bash
git add tgcli/commands/messages.py tests/tgcli/test_phase61_topics.py
git commit -m "feat(tgcli): send messages into forum topics"
```

---

## Task 6: Test count stabilization and final cleanup

**Goal:** Keep the final Phase 6.1 test count inside the agreed `119-124` band and verify no out-of-scope files changed.

**Files:**
- Modify: `tests/tgcli/test_phase61_topics.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Normalize final test count to the target**

Run:

```bash
.venv/bin/pytest --collect-only -q | tail -1
```

Expected target: `122 tests collected`.

If the count is above `124`, merge overlapping parser-only tests in `tests/tgcli/test_phase61_topics.py` without reducing behavioral coverage. The intended merged helper test is:

```python
def test_topic_reply_precedence_and_topic_fallback():
    reply_to, warnings = messages._topic_reply_to(reply_to=44, topic=55)
    assert reply_to == 44
    assert warnings == ["--topic ignored because --reply-to was provided"]

    reply_to, warnings = messages._topic_reply_to(reply_to=None, topic=55)
    assert reply_to == 55
    assert warnings == []
```

- [ ] **Step 2: Run topic-focused tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase61_topics.py tests/tgcli/test_cli_smoke.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: PASS with `122 tests collected` or another count in the explicit `119-124` acceptance band.

- [ ] **Step 4: Confirm only in-scope files changed**

Run:

```bash
git diff --name-only
```

Expected output includes only:

```text
tgcli/commands/messages.py
tgcli/commands/chats.py
tests/tgcli/test_phase61_topics.py
tests/tgcli/test_cli_smoke.py
```

It must not include:

```text
tgcli/__main__.py
tgcli/commands/events.py
tgcli/sedex.py
tgcli/commands/sedex_agent.py
tests/tgcli/test_sedex.py
```

- [ ] **Step 5: Commit**

```bash
git add tgcli/commands/messages.py tgcli/commands/chats.py tests/tgcli/test_phase61_topics.py tests/tgcli/test_cli_smoke.py
git commit -m "test(tgcli): stabilize phase 6.1 topic coverage"
```

---

## Final Verification

Run the full automated verification:

```bash
.venv/bin/pytest -q
```

Expected: PASS with `119-124` tests collected, targeting `122 tests collected` from the Phase 6 baseline of `109`.

Run parser smoke checks manually:

```bash
.venv/bin/python -m tgcli topics-list --help
.venv/bin/python -m tgcli topic-create --help
.venv/bin/python -m tgcli topic-edit --help
.venv/bin/python -m tgcli topic-pin --help
.venv/bin/python -m tgcli topic-unpin --help
.venv/bin/python -m tgcli send --help
.venv/bin/python -m tgcli edit-msg --help
.venv/bin/python -m tgcli forward --help
```

Expected: each command exits 0; topic write commands show `--allow-write`, `--dry-run`, `--idempotency-key`, and `--fuzzy`; `send`, `edit-msg`, and `forward` show `--topic`.

Run dry-run checks against a seeded test DB:

```bash
.venv/bin/pytest tests/tgcli/test_cli_smoke.py::test_phase61_topic_write_dry_run_smoke -q
```

Expected: PASS; no live Telegram connection is attempted.

Manual live checks after merge, run by the user against a known forum supergroup:

```bash
tg topics-list @forum_username --limit 5 --json
tg topic-create @forum_username "tg-cli smoke topic" --allow-write --idempotency-key phase61-smoke-topic --json
tg topic-edit @forum_username <topic_id> --title "tg-cli smoke topic renamed" --allow-write --json
tg topic-pin @forum_username <topic_id> --allow-write --json
tg topic-unpin @forum_username <topic_id> --allow-write --json
tg send @forum_username "hello topic" --topic <topic_id> --allow-write --json
```

Expected: live calls succeed against a forum supergroup. Running `topics-list` against a non-forum chat returns `BAD_ARGS` with message `not a forum supergroup`.

---

## Exact Commit Sequence

```bash
git commit -m "feat(tgcli): add forum topic parser surfaces"
git commit -m "feat(tgcli): list forum topics"
git commit -m "feat(tgcli): create forum topics safely"
git commit -m "feat(tgcli): edit and pin forum topics"
git commit -m "feat(tgcli): send messages into forum topics"
git commit -m "test(tgcli): stabilize phase 6.1 topic coverage"
```

---

## Self-Review Checklist

- [ ] `topics-list` uses live `GetForumTopicsRequest` and does not read topic data from SQLite.
- [ ] `topics-list` has no write gate because it is read-only.
- [ ] `topic-create`, `topic-edit`, `topic-pin`, and `topic-unpin` require `--allow-write` or `TG_ALLOW_WRITE=1`.
- [ ] `topic-create`, `topic-edit`, `topic-pin`, and `topic-unpin` require `--fuzzy` for title-based chat selectors.
- [ ] `topic-create` supports `--dry-run` before any Telethon call.
- [ ] `topic-create` records and replays `--idempotency-key` results including `topic_id`.
- [ ] `topic-edit` raises `BadArgs("nothing to edit")` when no mutating flag is set.
- [ ] `topic-edit` enforces `--closed/--reopen` and `--hidden/--unhidden` mutual exclusion.
- [ ] `topic-pin` and `topic-unpin` use `UpdatePinnedForumTopicRequest(pinned=True/False)`.
- [ ] `send`, `edit-msg`, and `forward` accept `--topic`.
- [ ] When both `--topic` and `--reply-to` are passed, `--reply-to` wins and the envelope includes a warning.
- [ ] No source files outside `tgcli/commands/messages.py` and `tgcli/commands/chats.py` are modified.
- [ ] No tests outside `tests/tgcli/test_phase61_topics.py` and `tests/tgcli/test_cli_smoke.py` are modified.
- [ ] `tgcli/__main__.py`, `tgcli/commands/events.py`, `tgcli/sedex.py`, `tgcli/commands/sedex_agent.py`, and `tests/tgcli/test_sedex.py` are untouched or absent.
- [ ] Full pytest ends inside the `119-124` count band, targeting `122`.

---

## Out of Scope

- `tg topic-delete` and `DeleteTopicHistoryRequest`; destructive topic history deletion belongs in Phase 10.
- `ToggleForumRequest`; admin-only forum enable/disable is not part of Phase 6.1.
- `ReorderPinnedForumTopicsRequest`; pinned topic ordering is niche and deferred.
- Topic-aware reads such as `list-msgs --topic`; defer to Phase 6.2.
- Any `sedex` agent files or command surfaces.
- Any changes to `tgcli/__main__.py` or `tgcli/commands/events.py`.
