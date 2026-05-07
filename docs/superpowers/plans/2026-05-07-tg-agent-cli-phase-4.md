# Phase 4 - Read API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-05-07

**Author:** Codex

**Status:** Draft

**Prerequisite:** Phase 3 complete with `67 passed`; `tgcli.resolve.resolve_chat_db()` exists and resolver exceptions are classified by `tgcli.dispatch.run_command()`.

**Goal:** Add Phase 4 read API commands for cached message search, cached message listing, cached message lookup, cached chat info, live self info, offline self cache, and live unread counts.

**Architecture:**
- Keep the current flat argparse surface and add `search`, `list-msgs`, `get-msg`, `me`, `unread`, and `chats-info` as top-level commands. This matches how `show`, `backfill`, `login`, and `discover` are registered today while keeping command implementations in the relevant domain modules.
- All cached DB readers open SQLite with `connect_readonly(DB_PATH)` and use `resolve_chat_db()` for chat selectors. The only local write in this phase is the explicit `tg me` live cache update, which uses `connect(DB_PATH)` after `client.get_me()` succeeds.
- Every command exits through `dispatch.run_command()` with a data-returning runner and, where useful, a human formatter.

**Tech Stack:** Python 3.12 stdlib (`argparse`, `asyncio`, `json`, `sqlite3`, `subprocess`, `datetime`, `pathlib`), Telethon client calls already wrapped by `tgcli.client.make_client`, existing pytest. **No new third-party deps.**

**Backwards compatibility:** Current full suite is `67 passed`. Phase 4 adds 10 unit tests and 3 smoke tests, and should finish at `80 passed`.

---

## Existing Code Map

| Area | Current line references | Phase 4 use |
|---|---:|---|
| Master Phase 4 sketch | `docs/superpowers/plans/2026-05-06-tg-agent-cli.md:1300-1305` | Source scope for `messages search/list/get`, `me`, `unread`, and `chats info` |
| Phase 3 plan structure | `docs/superpowers/plans/2026-05-07-tg-agent-cli-phase-3.md:1-16`, `18-63`, `65-1372` | Header, code map, file table, task format, verification, checklist, and out-of-scope structure |
| Flat message command registration | `tgcli/commands/messages.py:35-55` | Add `search`, `list-msgs`, and `get-msg` parsers beside `show` and `backfill` |
| Current cached message reader | `tgcli/commands/messages.py:185-246` | Reuse `_show_runner` and `_show_human` patterns for local DB-only reads and human formatting |
| Cached message schema and raw JSON writes | `tgcli/commands/messages.py:139-166`, `tgcli/db.py:28-44` | Return full cached message data for `get-msg`, including `raw_json` |
| Live Telethon lifecycle | `tgcli/commands/messages.py:251-309`, `tgcli/commands/chats.py:20-39`, `tgcli/commands/auth.py:19-31` | Use `make_client(SESSION_PATH)`, `await client.start()`, and `finally: await client.disconnect()` |
| Auth command registration | `tgcli/commands/auth.py:13-16` | Add flat `me` command beside `login` |
| Discover command registration | `tgcli/commands/chats.py:14-17` | Add flat `unread` and `chats-info` commands beside `discover` |
| DB resolver | `tgcli/resolve.py:41-82` | All chat-selector runners call `resolve_chat_db(con, args.chat)` |
| Dispatch chokepoint | `tgcli/dispatch.py:89-126` | Every new command routes through `run_command()` |
| Output contract | `tgcli/output.py:21-32`, `tgcli/output.py:76-97` | Preserve exit codes and JSON/human envelope behavior |
| Bad argument exception | `tgcli/safety.py:16-18` | Validate empty search query and malformed date filters as `BAD_ARGS` |
| Read-only DB connection | `tgcli/db.py:71-76` | Cached read commands use `connect_readonly(DB_PATH)` |
| DB schema entrypoint | `tgcli/db.py:14-55`, `tgcli/db.py:62-68` | Add `tg_me` cache table for `tg me --offline` |
| CLI module loading | `tgcli/__main__.py:18-36` | No new command module is needed because existing modules are already imported |
| Unit DB test style | `tests/tgcli/test_messages.py:7-50`, `tests/tgcli/test_min_msgs.py:39-90` | Seed temp DBs with `tgcli.db.connect()` and monkeypatch command module `DB_PATH` |
| Smoke test style | `tests/tgcli/test_cli_smoke.py:30-49`, `tests/tgcli/test_cli_smoke.py:79-131` | Append subprocess tests using `TG_DB_PATH` and `TG_AUDIT_PATH` env overrides |
| Current baseline | `tests/tgcli/test_cli_smoke.py:11-131`, `tests/tgcli/test_db.py:11-67`, `tests/tgcli/test_dispatch.py:31-166` | Existing 67 tests must remain green |

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `tgcli/commands/_common.py` | **modify** | Add `decode_raw_json()` for cached raw JSON returned by messages and chats |
| `tgcli/db.py` | **modify** | Add `tg_me` cache table for `tg me --offline` |
| `tgcli/commands/messages.py` | **modify** | Add flat cached `search`, `list-msgs`, and `get-msg` commands |
| `tgcli/commands/auth.py` | **modify** | Add flat `me` command with live default and `--offline` cache-only mode |
| `tgcli/commands/chats.py` | **modify** | Add flat `unread` live command and cached `chats-info` command |
| `tests/tgcli/test_phase4_messages_read.py` | **create** | Five unit tests for message search, list, and get runners |
| `tests/tgcli/test_auth_me.py` | **create** | Three unit tests for `me --offline` and live cache behavior |
| `tests/tgcli/test_phase4_chats.py` | **create** | Two unit tests for `chats-info` and `unread` |
| `tests/tgcli/test_cli_smoke.py` | **modify** | Add three subprocess smoke tests for flat read commands using `TG_DB_PATH` |

---

## Design Decisions

1. **Flat naming.** Use Option A: implement `tg search`, `tg list-msgs`, `tg get-msg`, `tg me`, `tg unread`, and `tg chats-info` as flat top-level parsers. `show` and `backfill` are registered flat at `tgcli/commands/messages.py:35-55`, and adding grouped subparsers now would reshape the CLI surface before Phase 5 write commands exist. **Future-collision risk:** if Phase 6+ adds e.g. `search-contacts` or `search-chats`, the bare `search` will need either a rename or a subparser group. Flag noted; rename pass deferred to Phase 11 polish.

2. **`raw_json` envelope contract.** `decode_raw_json()` returns one of: `dict` (parse success), `str` (cached text was not valid JSON), or `null` (cached column was empty). Downstream consumers must accept all three. Returning the raw string on parse failure preserves debug fidelity over silently emitting `null`.

---

## Task 1: Cached message search, list, and get commands

**Goal:** Add local DB-only message readers with flat command names and resolver-backed chat selectors.

**Files:**
- Modify: `tgcli/commands/_common.py`
- Modify: `tgcli/commands/messages.py`
- Create: `tests/tgcli/test_phase4_messages_read.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Write failing unit tests for cached message readers**

```python
# tests/tgcli/test_phase4_messages_read.py
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
```

- [ ] **Step 2: Add failing subprocess smoke coverage for flat message commands**

Append this complete test to `tests/tgcli/test_cli_smoke.py`:

```python
def test_phase4_message_read_commands_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "seeded.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "user", "Alpha Chat", "alpha"),
    )
    con.execute(
        """
        INSERT INTO tg_messages(
            chat_id, message_id, sender_id, date, text,
            is_outgoing, reply_to_msg_id, has_media, media_type, media_path, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            123,
            1,
            11,
            "2026-05-01T10:00:00",
            "Hello from cache",
            0,
            None,
            0,
            None,
            None,
            "{\"id\": 1}",
        ),
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
        [str(PYTHON), "-m", "tgcli", "search", "@alpha", "Hello", "--json"],
        [str(PYTHON), "-m", "tgcli", "list-msgs", "@alpha", "--since", "2026-05-01", "--json"],
        [str(PYTHON), "-m", "tgcli", "get-msg", "@alpha", "1", "--json"],
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase4_messages_read.py tests/tgcli/test_cli_smoke.py::test_phase4_message_read_commands_smoke -q
```

Expected: FAIL because `tgcli.commands.messages` has no `_search_runner`, `_list_runner`, `_get_runner`, and argparse does not recognize `search`, `list-msgs`, or `get-msg`.

- [ ] **Step 4: Add shared raw JSON decoding helper**

Add this function to the end of `tgcli/commands/_common.py`:

```python
def decode_raw_json(value: str | None):
    """Return parsed raw_json when possible, preserving invalid cached text."""
    if value is None or value == "":
        return None
    import json

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
```

- [ ] **Step 5: Update `tgcli/commands/messages.py` imports and registration**

Change the `_common` import to include `decode_raw_json`:

```python
from tgcli.commands._common import (
    AUDIT_PATH, DB_PATH, MEDIA_DIR, ROOT, SESSION_PATH, add_output_flags,
    decode_raw_json,
)
```

Change the resolver import to also pull in `NotFound` (used by `_get_runner` for missing-message-id):

```python
from tgcli.resolve import NotFound, resolve_chat_db
```

Replace the existing `from tgcli.resolve import resolve_chat_db` line in `tgcli/commands/messages.py:31` with the version above.

Replace `register()` in `tgcli/commands/messages.py` with:

```python
def register(sub: argparse._SubParsersAction) -> None:
    sh = sub.add_parser("show", help="Print messages from one chat")
    sh.add_argument("pattern", nargs="?", default=None,
                    help="Substring of chat title (case- and accent-insensitive)")
    sh.add_argument("--chat-id", type=int, default=None,
                    help="Use exact chat_id instead of pattern")
    sh.add_argument("--limit", type=int, default=50,
                    help="Number of messages (default 50)")
    sh.add_argument("--reverse", action="store_true",
                    help="Oldest first instead of newest first")
    add_output_flags(sh)
    sh.set_defaults(func=run_show)

    se = sub.add_parser("search", help="Search cached messages in one chat")
    se.add_argument("chat", help="Chat selector resolved from the local DB")
    se.add_argument("query", help="Text query to search in cached message text")
    se.add_argument("--limit", type=int, default=50,
                    help="Number of messages (default 50)")
    se.add_argument("--case-sensitive", action="store_true",
                    help="Require exact case match after the DB LIKE scan")
    add_output_flags(se)
    se.set_defaults(func=run_search)

    ls = sub.add_parser("list-msgs", help="List cached messages from one chat")
    ls.add_argument("chat", help="Chat selector resolved from the local DB")
    ls.add_argument("--limit", type=int, default=50,
                    help="Number of messages (default 50)")
    ls.add_argument("--since", default=None,
                    help="Only include messages on or after YYYY-MM-DD")
    ls.add_argument("--until", default=None,
                    help="Only include messages on or before YYYY-MM-DD")
    ls.add_argument("--reverse", action="store_true",
                    help="Oldest first instead of newest first")
    add_output_flags(ls)
    ls.set_defaults(func=run_list)

    gm = sub.add_parser("get-msg", help="Get one cached message by id")
    gm.add_argument("chat", help="Chat selector resolved from the local DB")
    gm.add_argument("message_id", type=int, help="Cached Telegram message id")
    add_output_flags(gm)
    gm.set_defaults(func=run_get)

    bf = sub.add_parser("backfill", help="Pull historical messages")
    bf.add_argument("--per-chat", type=int, default=200)
    bf.add_argument("--max-chats", type=int, default=100)
    bf.add_argument("--throttle", type=float, default=1.0)
    bf.add_argument("--download-media", action="store_true",
                    help="Also download photos / voice / video / documents to media/<chat_id>/")
    add_output_flags(bf)
    bf.set_defaults(func=run_backfill)
```

- [ ] **Step 6: Add message search/list/get implementation**

Add this code after `run_show()` and before the `# ---------- backfill ----------` section in `tgcli/commands/messages.py`:

```python
# ---------- search / list / get ----------

def _positive_limit(value: int, *, default: int = 50) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 1)


def _like_pattern(query: str) -> str:
    escaped = (
        query
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


def _date_start(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise BadArgs(f"Invalid --since date {value!r}; expected YYYY-MM-DD") from exc
    return f"{value}T00:00:00"


def _date_end(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise BadArgs(f"Invalid --until date {value!r}; expected YYYY-MM-DD") from exc
    return f"{value}T23:59:59"


def _message_summary(row) -> dict[str, Any]:
    message_id, date, is_outgoing, text, media_type = row
    return {
        "message_id": int(message_id),
        "date": date,
        "is_outgoing": bool(is_outgoing),
        "text": text or None,
        "media_type": media_type,
    }


def _full_message(row) -> dict[str, Any]:
    (
        chat_id,
        message_id,
        sender_id,
        date,
        text,
        is_outgoing,
        reply_to_msg_id,
        has_media,
        media_type,
        media_path,
        raw_json,
    ) = row
    return {
        "chat_id": int(chat_id),
        "message_id": int(message_id),
        "sender_id": sender_id,
        "date": date,
        "text": text or None,
        "is_outgoing": bool(is_outgoing),
        "reply_to_msg_id": reply_to_msg_id,
        "has_media": bool(has_media),
        "media_type": media_type,
        "media_path": media_path,
        "raw_json": decode_raw_json(raw_json),
    }


def _search_runner(args) -> dict[str, Any]:
    query = str(args.query)
    if query == "":
        raise BadArgs("Search query cannot be empty")

    con = connect_readonly(DB_PATH)
    try:
        chat_id, chat_title = resolve_chat_db(con, args.chat)
        params: list[Any] = [chat_id, _like_pattern(query)]
        case_clause = ""
        if args.case_sensitive:
            case_clause = " AND instr(text, ?) > 0"
            params.append(query)
        params.append(_positive_limit(args.limit))
        rows = con.execute(
            f"""
            SELECT message_id, date, is_outgoing, text, media_type
            FROM tg_messages
            WHERE chat_id = ?
              AND text IS NOT NULL
              AND text LIKE ? ESCAPE '\\'
              {case_clause}
            ORDER BY date DESC, message_id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    finally:
        con.close()

    return {
        "chat": {"chat_id": chat_id, "title": chat_title},
        "query": query,
        "case_sensitive": bool(args.case_sensitive),
        "limit": _positive_limit(args.limit),
        "messages": [_message_summary(row) for row in rows],
    }


def _search_human(data: dict) -> None:
    chat = data["chat"]
    print(f"=== Search {data['query']!r} in {chat['title']} (chat_id {chat['chat_id']}) ===\n")
    if not data["messages"]:
        print("No cached messages matched.")
        return
    for message in data["messages"]:
        ts = (message["date"] or "")[:19].replace("T", " ")
        if message["text"]:
            body = message["text"]
        elif message["media_type"]:
            body = f"[{message['media_type']}]"
        else:
            body = "[empty]"
        print(f"  #{message['message_id']:<6} {ts}  {body}")


def run_search(args) -> int:
    return run_command(
        "search", args,
        runner=lambda: _search_runner(args),
        human_formatter=_search_human,
        audit_path=AUDIT_PATH,
    )


def _list_runner(args) -> dict[str, Any]:
    since = _date_start(args.since)
    until = _date_end(args.until)
    order = "ASC" if args.reverse else "DESC"
    where = ["chat_id = ?"]
    params: list[Any] = []

    con = connect_readonly(DB_PATH)
    try:
        chat_id, chat_title = resolve_chat_db(con, args.chat)
        params.append(chat_id)
        if since is not None:
            where.append("date >= ?")
            params.append(since)
        if until is not None:
            where.append("date <= ?")
            params.append(until)
        params.append(_positive_limit(args.limit))
        rows = con.execute(
            f"""
            SELECT message_id, date, is_outgoing, text, media_type
            FROM tg_messages
            WHERE {" AND ".join(where)}
            ORDER BY date {order}, message_id {order}
            LIMIT ?
            """,
            params,
        ).fetchall()
    finally:
        con.close()

    return {
        "chat": {"chat_id": chat_id, "title": chat_title},
        "order": "oldest_first" if args.reverse else "newest_first",
        "filters": {
            "limit": _positive_limit(args.limit),
            "since": args.since,
            "until": args.until,
        },
        "messages": [_message_summary(row) for row in rows],
    }


def _list_human(data: dict) -> None:
    chat = data["chat"]
    msgs = data["messages"]
    if not msgs:
        print(f"No cached messages for '{chat['title']}' matched the filters.")
        return
    direction = "oldest first" if data["order"] == "oldest_first" else "newest first"
    print(f"=== {chat['title']}  chat_id {chat['chat_id']}  {len(msgs)} messages, {direction} ===\n")
    for message in msgs:
        arrow = "you" if message["is_outgoing"] else "them"
        ts = (message["date"] or "")[:19].replace("T", " ")
        if message["text"]:
            body = message["text"]
        elif message["media_type"]:
            body = f"[{message['media_type']}]"
        else:
            body = "[empty]"
        print(f"  #{message['message_id']:<6} {ts}  {arrow:<4}  {body}")


def run_list(args) -> int:
    return run_command(
        "list-msgs", args,
        runner=lambda: _list_runner(args),
        human_formatter=_list_human,
        audit_path=AUDIT_PATH,
    )


def _get_runner(args) -> dict[str, Any]:
    con = connect_readonly(DB_PATH)
    try:
        chat_id, chat_title = resolve_chat_db(con, args.chat)
        row = con.execute(
            """
            SELECT chat_id, message_id, sender_id, date, text,
                   is_outgoing, reply_to_msg_id, has_media, media_type,
                   media_path, raw_json
            FROM tg_messages
            WHERE chat_id = ? AND message_id = ?
            """,
            (chat_id, args.message_id),
        ).fetchone()
    finally:
        con.close()

    if row is None:
        raise NotFound(f"message {args.message_id} not cached in chat {chat_id}")
    return {
        "chat": {"chat_id": chat_id, "title": chat_title},
        "message": _full_message(row),
    }


def _get_human(data: dict) -> None:
    chat = data["chat"]
    message = data["message"]
    print(f"{chat['title']} (chat_id {chat['chat_id']}) message #{message['message_id']}")
    print(json.dumps(message, ensure_ascii=False, indent=2, default=str))


def run_get(args) -> int:
    return run_command(
        "get-msg", args,
        runner=lambda: _get_runner(args),
        human_formatter=_get_human,
        audit_path=AUDIT_PATH,
    )
```

- [ ] **Step 7: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase4_messages_read.py tests/tgcli/test_cli_smoke.py::test_phase4_message_read_commands_smoke -q
```

Expected: `6 passed`.

- [ ] **Step 8: Run full suite**

Run:

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: `73 passed` (67 baseline + 5 message unit + 1 message smoke).

- [ ] **Step 9: Commit**

```bash
git add tgcli/commands/_common.py tgcli/commands/messages.py tests/tgcli/test_phase4_messages_read.py tests/tgcli/test_cli_smoke.py
git commit -m "feat(tgcli): add cached message read commands"
```

---

## Task 2: `tg me` live and offline cache

**Goal:** Add `tg me` with live default behavior, persistent cache update, and `--offline` cache-only behavior.

**Files:**
- Modify: `tgcli/db.py`
- Modify: `tgcli/commands/auth.py`
- Create: `tests/tgcli/test_auth_me.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Write failing unit tests for `tg me`**

```python
# tests/tgcli/test_auth_me.py
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
```

- [ ] **Step 2: Add failing subprocess smoke coverage for `tg me --offline`**

Append this complete test to `tests/tgcli/test_cli_smoke.py`:

```python
def test_phase4_me_offline_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "seeded.sqlite"
    con = connect(db)
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
            "{\"id\": 42}",
        ),
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
        [str(PYTHON), "-m", "tgcli", "me", "--offline", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    payload = _json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["source"] == "cache"
    assert payload["data"]["user_id"] == 42
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_auth_me.py tests/tgcli/test_cli_smoke.py::test_phase4_me_offline_smoke -q
```

Expected: FAIL because `tg_me` does not exist and `tgcli.commands.auth` has no `me` runners.

- [ ] **Step 4: Add `tg_me` cache table to `tgcli/db.py`**

Add this table definition inside `SCHEMA` after the `tg_contacts` table:

```python
CREATE TABLE IF NOT EXISTS tg_me (
    key          TEXT PRIMARY KEY CHECK (key = 'self'),
    user_id      INTEGER,
    username     TEXT,
    phone        TEXT,
    first_name   TEXT,
    last_name    TEXT,
    display_name TEXT,
    is_bot       INTEGER,
    cached_at    TEXT,
    raw_json     TEXT
);
```

The full `SCHEMA` string should contain `tg_chats`, `tg_messages`, `tg_contacts`, and `tg_me`, and `connect()` must continue to call `con.executescript(SCHEMA)` before `_migrate(con)`.

- [ ] **Step 5: Update `tgcli/commands/auth.py` imports and registration**

Replace the imports at the top of `tgcli/commands/auth.py` with:

```python
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from tgcli.client import make_client
from tgcli.commands._common import (
    AUDIT_PATH,
    DB_PATH,
    SESSION_PATH,
    add_output_flags,
    decode_raw_json,
)
from tgcli.commands.messages import _display_title
from tgcli.db import connect, connect_readonly
from tgcli.dispatch import run_command
from tgcli.resolve import NotFound
```

Replace `register()` in `tgcli/commands/auth.py` with:

```python
def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("login", help="One-time interactive auth")
    add_output_flags(p)
    p.set_defaults(func=run_login)

    me = sub.add_parser("me", help="Print authenticated user info")
    me.add_argument("--offline", action="store_true",
                    help="Read cached self user info without connecting to Telegram")
    add_output_flags(me)
    me.set_defaults(func=run_me)
```

- [ ] **Step 6: Add `tg me` cache helpers and runner**

Add this code after `run_login()` in `tgcli/commands/auth.py`:

```python
# ---------- me ----------

def _cached_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _me_public(row: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "user_id": row["user_id"],
        "username": row["username"],
        "phone": row["phone"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "display_name": row["display_name"],
        "is_bot": bool(row["is_bot"]),
        "cached_at": row["cached_at"],
        "session_path": str(SESSION_PATH),
        "raw_json": decode_raw_json(row["raw_json"]),
    }


def _row_from_user(user) -> dict[str, Any]:
    raw_json = json.dumps(user.to_dict(), ensure_ascii=False, default=str)[:50000]
    return {
        "user_id": user.id,
        "username": getattr(user, "username", None),
        "phone": getattr(user, "phone", None),
        "first_name": getattr(user, "first_name", None),
        "last_name": getattr(user, "last_name", None),
        "display_name": _display_title(user),
        "is_bot": int(bool(getattr(user, "bot", False))),
        "cached_at": _cached_at(),
        "raw_json": raw_json,
    }


def _write_me_cache(row: dict[str, Any]) -> None:
    con = connect(DB_PATH)
    try:
        con.execute(
            """
            INSERT INTO tg_me(
                key, user_id, username, phone, first_name, last_name,
                display_name, is_bot, cached_at, raw_json
            ) VALUES ('self', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                user_id      = excluded.user_id,
                username     = excluded.username,
                phone        = excluded.phone,
                first_name   = excluded.first_name,
                last_name    = excluded.last_name,
                display_name = excluded.display_name,
                is_bot       = excluded.is_bot,
                cached_at    = excluded.cached_at,
                raw_json     = excluded.raw_json
            """,
            (
                row["user_id"],
                row["username"],
                row["phone"],
                row["first_name"],
                row["last_name"],
                row["display_name"],
                row["is_bot"],
                row["cached_at"],
                row["raw_json"],
            ),
        )
        con.commit()
    finally:
        con.close()


def _me_offline_runner() -> dict[str, Any]:
    con = connect_readonly(DB_PATH)
    try:
        row = con.execute(
            """
            SELECT user_id, username, phone, first_name, last_name,
                   display_name, is_bot, cached_at, raw_json
            FROM tg_me
            WHERE key = 'self'
            """
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise NotFound("No cached self user info. Run 'tg me' once before using --offline.")
    keys = [
        "user_id",
        "username",
        "phone",
        "first_name",
        "last_name",
        "display_name",
        "is_bot",
        "cached_at",
        "raw_json",
    ]
    return _me_public(dict(zip(keys, row)), source="cache")


async def _me_live_runner() -> dict[str, Any]:
    client = make_client(SESSION_PATH)
    await client.start()
    try:
        me = await client.get_me()
        row = _row_from_user(me)
        _write_me_cache(row)
        return _me_public(row, source="live")
    finally:
        await client.disconnect()


def _me_human(data: dict) -> None:
    username = f"@{data['username']}" if data["username"] else "(no username)"
    print(f"{data['display_name']} ({username}) id {data['user_id']}")
    print(f"Source: {data['source']}  Cached: {data['cached_at']}")


def run_me(args) -> int:
    runner = _me_offline_runner if args.offline else _me_live_runner
    return run_command(
        "me", args,
        runner=runner,
        human_formatter=_me_human,
        audit_path=AUDIT_PATH,
    )
```

- [ ] **Step 7: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_auth_me.py tests/tgcli/test_cli_smoke.py::test_phase4_me_offline_smoke -q
```

Expected: `4 passed`.

- [ ] **Step 8: Run full suite**

Run:

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: `77 passed` (73 after Task 1 + 3 `me` unit + 1 `me` smoke).

- [ ] **Step 9: Commit**

```bash
git add tgcli/db.py tgcli/commands/auth.py tests/tgcli/test_auth_me.py tests/tgcli/test_cli_smoke.py
git commit -m "feat(tgcli): add self user read command"
```

---

## Task 3: Live unread counts and cached chat info

**Goal:** Add `tg unread` for live unread counts and `tg chats-info` for detailed cached chat metadata.

**Files:**
- Modify: `tgcli/commands/chats.py`
- Create: `tests/tgcli/test_phase4_chats.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Write failing unit tests for chats read commands**

```python
# tests/tgcli/test_phase4_chats.py
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
```

- [ ] **Step 2: Add failing subprocess smoke coverage for `tg chats-info`**

Append this complete test to `tests/tgcli/test_cli_smoke.py`:

```python
def test_phase4_chats_info_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "seeded.sqlite"
    con = connect(db)
    con.execute(
        """
        INSERT INTO tg_chats(
            chat_id, type, title, username, raw_json
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            900,
            "supergroup",
            "Alpha Group",
            "alpha_group",
            "{\"id\": 900, \"participants_count\": 123}",
        ),
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
        [str(PYTHON), "-m", "tgcli", "chats-info", "@alpha_group", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    payload = _json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["chat_id"] == 900
    assert payload["data"]["member_count"] == 123
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase4_chats.py tests/tgcli/test_cli_smoke.py::test_phase4_chats_info_smoke -q
```

Expected: FAIL because `tgcli.commands.chats` has no `_chat_info_runner`, no `_unread_runner`, and argparse does not recognize `chats-info`.

- [ ] **Step 4: Update `tgcli/commands/chats.py` imports and registration**

Replace the imports at the top of `tgcli/commands/chats.py` with:

```python
from __future__ import annotations

import argparse
import json
from typing import Any

from tgcli.client import make_client
from tgcli.commands._common import (
    AUDIT_PATH,
    DB_PATH,
    SESSION_PATH,
    add_output_flags,
    decode_raw_json,
)
from tgcli.commands.messages import _chat_kind, _display_title, _upsert_chat
from tgcli.db import connect, connect_readonly
from tgcli.dispatch import run_command
from tgcli.resolve import NotFound, resolve_chat_db
```

Replace `register()` in `tgcli/commands/chats.py` with:

```python
def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("discover", help="Fast scan of every dialog (no messages)")
    add_output_flags(p)
    p.set_defaults(func=run_discover)

    unread = sub.add_parser("unread", help="List chats with unread messages")
    add_output_flags(unread)
    unread.set_defaults(func=run_unread)

    info = sub.add_parser("chats-info", help="Show cached chat metadata")
    info.add_argument("chat", help="Chat selector resolved from the local DB")
    add_output_flags(info)
    info.set_defaults(func=run_chats_info)
```

- [ ] **Step 5: Add unread and chats-info implementation**

Add this code after `run_discover()` in `tgcli/commands/chats.py`:

```python
# ---------- unread ----------

async def _unread_runner(args) -> dict[str, Any]:
    client = make_client(SESSION_PATH)
    await client.start()
    chats: list[dict[str, Any]] = []
    try:
        async for dialog in client.iter_dialogs():
            unread_count = int(getattr(dialog, "unread_count", 0) or 0)
            if unread_count <= 0:
                continue
            entity = getattr(dialog, "entity", None)
            chats.append(
                {
                    "chat_id": int(dialog.id),
                    "title": _display_title(entity) if entity is not None else f"chat_{dialog.id}",
                    "type": _chat_kind(entity) if entity is not None else "unknown",
                    "unread_count": unread_count,
                }
            )
    finally:
        await client.disconnect()
    return {
        "total_chats": len(chats),
        "total_unread": sum(row["unread_count"] for row in chats),
        "chats": chats,
    }


def _unread_human(data: dict) -> None:
    print(f"Unread: {data['total_unread']} messages across {data['total_chats']} chats")
    for row in data["chats"]:
        print(f"  {row['unread_count']:>4}  {row['title']}  (chat_id {row['chat_id']})")


def run_unread(args) -> int:
    return run_command(
        "unread", args,
        runner=lambda: _unread_runner(args),
        human_formatter=_unread_human,
        audit_path=AUDIT_PATH,
    )


# ---------- chats-info ----------

def _member_count(raw_json) -> int | None:
    if not isinstance(raw_json, dict):
        return None
    for key in ("participants_count", "members_count", "member_count"):
        value = raw_json.get(key)
        if isinstance(value, int):
            return value
    return None


def _chat_info_runner(args) -> dict[str, Any]:
    con = connect_readonly(DB_PATH)
    try:
        chat_id, resolved_title = resolve_chat_db(con, args.chat)
        row = con.execute(
            """
            SELECT chat_id, type, title, username, phone, first_name,
                   last_name, is_bot, last_seen_at, raw_json
            FROM tg_chats
            WHERE chat_id = ?
            """,
            (chat_id,),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise NotFound(f"chat {chat_id} not in DB")
    (
        chat_id,
        chat_type,
        title,
        username,
        phone,
        first_name,
        last_name,
        is_bot,
        last_seen_at,
        raw_json,
    ) = row
    decoded_raw = decode_raw_json(raw_json)
    return {
        "chat_id": int(chat_id),
        "title": title or resolved_title,
        "username": username,
        "type": chat_type,
        "phone": phone,
        "first_name": first_name,
        "last_name": last_name,
        "is_bot": bool(is_bot),
        "last_seen_at": last_seen_at,
        "member_count": _member_count(decoded_raw),
        "raw_json": decoded_raw,
    }


def _chats_info_human(data: dict) -> None:
    username = f"@{data['username']}" if data["username"] else "(no username)"
    member_count = data["member_count"] if data["member_count"] is not None else "unknown"
    print(f"{data['title']} ({username})")
    print(f"chat_id: {data['chat_id']}")
    print(f"type: {data['type']}")
    print(f"member_count: {member_count}")
    print(f"last_seen_at: {data['last_seen_at']}")
    print("raw_json:")
    print(json.dumps(data["raw_json"], ensure_ascii=False, indent=2, default=str))


def run_chats_info(args) -> int:
    return run_command(
        "chats-info", args,
        runner=lambda: _chat_info_runner(args),
        human_formatter=_chats_info_human,
        audit_path=AUDIT_PATH,
    )
```

- [ ] **Step 6: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase4_chats.py tests/tgcli/test_cli_smoke.py::test_phase4_chats_info_smoke -q
```

Expected: `3 passed`.

- [ ] **Step 7: Run full suite**

Run:

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: `80 passed` (77 after Task 2 + 2 chats unit + 1 chats-info smoke).

- [ ] **Step 8: Commit**

```bash
git add tgcli/commands/chats.py tests/tgcli/test_phase4_chats.py tests/tgcli/test_cli_smoke.py
git commit -m "feat(tgcli): add unread and cached chat info"
```

---

## Final Verification

Run:

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: `80 passed`.

Run these local DB smoke commands with a seeded `TG_DB_PATH`:

```bash
TG_DB_PATH=/path/to/seeded.sqlite TG_AUDIT_PATH=/tmp/tg-audit.log ./tg search "@alpha" "Hello" --json | python -m json.tool
TG_DB_PATH=/path/to/seeded.sqlite TG_AUDIT_PATH=/tmp/tg-audit.log ./tg list-msgs "@alpha" --since 2026-05-01 --until 2026-05-07 --json | python -m json.tool
TG_DB_PATH=/path/to/seeded.sqlite TG_AUDIT_PATH=/tmp/tg-audit.log ./tg get-msg "@alpha" 1 --json | python -m json.tool
TG_DB_PATH=/path/to/seeded.sqlite TG_AUDIT_PATH=/tmp/tg-audit.log ./tg me --offline --json | python -m json.tool
TG_DB_PATH=/path/to/seeded.sqlite TG_AUDIT_PATH=/tmp/tg-audit.log ./tg chats-info "@alpha_group" --json | python -m json.tool
```

Expected:
- `search` exits 0 and returns `data.messages` from cached `tg_messages`.
- `list-msgs` exits 0 and honors `--since`, `--until`, `--limit`, and `--reverse`.
- `get-msg` exits 0 and returns `data.message.raw_json`.
- `me --offline` exits 0 when `tg_me` has a cached row and exits 4 with `NOT_FOUND` when the cache is empty.
- `chats-info` exits 0 and returns cached `raw_json` plus `member_count` when present in cached metadata.

Manual live verification, skipped in automated tests because the sandbox cannot reach Telegram:

```bash
./tg me --json | python -m json.tool
./tg unread --json | python -m json.tool
```

Expected:
- `me` calls `client.get_me()`, disconnects in `finally`, prints authenticated user info, and refreshes the `tg_me` cache.
- `unread` calls `client.iter_dialogs()`, disconnects in `finally`, and returns only chats with `unread_count > 0`.

---

## Exact Commit Sequence

```bash
git commit -m "feat(tgcli): add cached message read commands"
git commit -m "feat(tgcli): add self user read command"
git commit -m "feat(tgcli): add unread and cached chat info"
```

---

## Self-Review Checklist

Before declaring Phase 4 complete:

1. **Naming** - CLI exposes flat `search`, `list-msgs`, `get-msg`, `me`, `unread`, and `chats-info`; no grouped subparser tree is introduced.
2. **DB read-only rule** - `search`, `list-msgs`, `get-msg`, `me --offline`, and `chats-info` use `connect_readonly(DB_PATH)` for cache reads.
3. **Resolver rule** - every command that accepts a chat selector calls `resolve_chat_db(con, args.chat)`.
4. **Dispatch rule** - each new command uses `run_command()` with a data-returning runner and an explicit command name.
5. **Message search** - `search` defaults to limit 50, scans one resolved chat with SQL `text LIKE ?`, and honors `--case-sensitive`.
6. **Message list** - `list-msgs` defaults to limit 50, supports `--since YYYY-MM-DD`, `--until YYYY-MM-DD`, and `--reverse`.
7. **Message get** - `get-msg` fetches by `(chat_id, message_id)` and returns sender, date, text, reply, media fields, and `raw_json`.
8. **Self info** - `me` defaults live, uses `make_client(SESSION_PATH)`, awaits `client.start()`, awaits `client.get_me()`, caches the result, and disconnects in `finally`.
9. **Offline self info** - `me --offline` never constructs a Telethon client and returns only the cached `tg_me` row.
10. **Unread** - `unread` is always live, has no offline flag, uses `client.iter_dialogs()`, and returns only positive unread counts.
11. **Chat info** - `chats-info` is local DB-only and has no `--live` flag in Phase 4.
12. **Live tests** - automated tests monkeypatch the Telethon client; no test requires network access.
13. **Test count** - full suite finishes at `80 passed`, equal to Phase 3 `67 passed` plus 13 new tests.

---

## Out of Scope

- Grouped commands such as `tg messages search` and `tg chats info` are deferred unless a later phase intentionally reshapes the CLI hierarchy.
- Telegram write commands remain deferred to Phase 5.
- Destructive commands remain deferred to Phase 6.
- Media retrieval or download improvements remain deferred to Phase 7.
- `tg chats-info --live` is deferred to Phase 9 or later.
- Multi-account cache separation is deferred.
