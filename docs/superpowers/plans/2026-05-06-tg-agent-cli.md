# Telegram Agent CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `tg`, a Python Telegram CLI driven by Telethon (MTProto) that supports full read/write/delete CRUD, emits both human and JSON output, ships an MCP-server companion, and is safe for autonomous-agent use against a real user account.

**Architecture:** Refactor the existing single-file `telegram_test/tg_scrape.py` into a `tgcli/` package (commands, output framework, safety gates, chat resolver) reusing the already-working SQLite schema and Telethon session. Add a sibling `tgcli_mcp/` package that wraps each subcommand as an MCP tool. Every write operation passes through a single safety gate (write-allowed → confirm-required → rate-limit → audit-log) before reaching Telethon.

**Tech Stack:** Python 3.12, Telethon 1.43+, stdlib `sqlite3`/`argparse`/`asyncio`, the official `mcp` Python package (added in phase 10), pytest for tests. No new runtime dependencies in phases 1–9.

---

## Why we're building it

Existing tools each cover one slice; nothing is purpose-built for autonomous-agent operation against a *user* account.

| Existing tool        | What it does           | Why it's not enough             |
|----------------------|------------------------|---------------------------------|
| nchat                | Interactive TUI reader | No automation, no DB, no JSON   |
| iyear/tdl            | Bulk Go downloader     | No event-listener, no LLM hooks |
| paul-nameless/tg     | Python TUI             | Same as nchat                   |
| vysheng/tg           | Historical CLI         | Unmaintained since 2019         |
| telegram-send        | Bot-API stdout pipe    | Outbound only, bot-API only     |

This CLI must be drivable by Claude Code (via MCP), Codex (via shell + JSON), standalone Python agents (via shell + JSON), and the human (via human output) — all four through one binary.

## File Structure

```
telegram_test/
├── tg                          # bash wrapper (exists, no change)
├── tg_scrape.py                # legacy entry — becomes a 5-line shim re-exporting tgcli.__main__
├── tgcli/
│   ├── __init__.py
│   ├── __main__.py             # argparse dispatcher
│   ├── client.py               # Telethon client factory + auth-required guard
│   ├── db.py                   # SQLite connection + schema (current schema preserved)
│   ├── output.py               # JSON envelope, human formatter, exit codes
│   ├── safety.py               # write-gate, confirm-gate, rate-limit, audit-log writer
│   ├── resolve.py              # resolve <chat>: int_id → @username → fuzzy title
│   ├── env.py                  # .env loader (moved out of tg_scrape.py)
│   └── commands/
│       ├── __init__.py
│       ├── _common.py          # shared argument parsers, decorators
│       ├── auth.py             # login
│       ├── chats.py            # list, info, join, leave, mute, archive, title, discover
│       ├── messages.py         # list, get, search, send, edit, delete, forward, pin, react, mark-read, show, backfill
│       ├── contacts.py         # list, sync, add, remove, block
│       ├── media.py            # upload, download
│       ├── account.py          # me, sessions, export-data
│       ├── events.py           # listen, tail
│       ├── stats.py            # stats
│       └── api.py              # raw method escape hatch
├── tgcli_mcp/
│   ├── __init__.py
│   ├── server.py               # MCP server, exposes commands as tools
│   ├── run.sh                  # wrapper script for `claude mcp add`
│   └── tools.py                # tool registry: name → schema → handler
├── telegram.sqlite             # already exists, schema preserved
├── tg.session                  # already exists
├── audit.log                   # NDJSON audit log of write operations (created on first write)
└── media/                      # already exists

tests/
└── tgcli/
    ├── __init__.py
    ├── test_output.py          # pure-function tests for output.py
    ├── test_safety.py          # pure-function tests for safety.py
    ├── test_resolve.py         # tests for chat resolver against an in-memory DB
    └── test_cli_smoke.py       # subprocess invocations of `tg --help`, `tg <subcmd> --help`

docs/superpowers/plans/
└── 2026-05-06-tg-agent-cli.md  # this file
```

**Responsibility per file:**
- `tgcli/output.py` — pure functions: `success(cmd, data)`, `fail(cmd, code, message, **kw)`, `format_human(envelope, command)`, `is_tty_stdout()`. No I/O except final `print`.
- `tgcli/safety.py` — pure helpers: `require_write_allowed(args)`, `require_confirm(args, action)`, `RateLimiter` class (in-memory token bucket), `audit_write(cmd, args, result)`.
- `tgcli/resolve.py` — `async resolve_chat(client, db, raw)` returns `(chat_id, title)` or raises `NotFound`/`Ambiguous`.
- `tgcli/commands/<area>.py` — one module per subcommand area. Each exports `register(subparsers)` and `async def cmd_*(args)`.
- `tgcli_mcp/tools.py` — registers each MCP tool. Tool handler imports the underlying `cmd_*` and shapes its output to the MCP response format.

## Subcommand surface (final, full CRUD)

### Read (no gate)
- `tg chats list [--archived] [--type user|group|channel|bot] [--min-msgs N]`
- `tg chats info <chat>`
- `tg chats discover` (existing — full dialog scan)
- `tg messages list <chat> [--limit N] [--before DATE] [--after DATE] [--from USER] [--has-media]`
- `tg messages get <chat> <msg-id>`
- `tg messages search "<query>" [--chat C] [--from F] [--date-from D] [--date-to D]`
- `tg messages show <chat>` (existing alias for list)
- `tg contacts list [--chatted] [--with-phone] [--min-msgs N]`
- `tg contacts sync` (existing — pulls phone-book)
- `tg me`
- `tg unread`
- `tg stats [--min-msgs N]`
- `tg account info`
- `tg account sessions list`

### Write — text (write-gated)
- `tg messages send <chat> "<text>" [--reply-to ID] [--silent] [--schedule TIME] [--dry-run]`
- `tg messages edit <chat> <msg-id> "<new>" [--dry-run]`
- `tg messages forward <from-chat> <msg-id> --to <chat> [--silent] [--dry-run]`
- `tg messages pin <chat> <msg-id>` / `tg messages unpin <chat> <msg-id>`
- `tg messages react <chat> <msg-id> --emoji 👍`
- `tg messages mark-read <chat> [--up-to ID]`
- `tg media upload <chat> <file> [--caption T] [--reply-to ID] [--as voice|video|document|photo] [--dry-run]`

### Write — destructive (write-gated + confirm-gated)
- `tg messages delete <chat> <msg-id>... [--for-everyone] --confirm`
- `tg chats leave <chat> --confirm`
- `tg chats archive <chat>` / `tg chats unarchive <chat>`
- `tg contacts remove <user> --confirm`
- `tg contacts block <user> --confirm` / `tg contacts unblock <user>`
- `tg account sessions terminate <hash> --confirm`

### Chat lifecycle (write-gated, non-destructive)
- `tg chats join <invite-link|@username>`
- `tg chats mute <chat> [--for SECS]` / `tg chats unmute <chat>`
- `tg chats title <chat> "<new>"` (admin-only)
- `tg contacts add <phone> --first-name X [--last-name Y]`

### Files & background
- `tg media download <chat> <msg-id> [--out PATH]`
- `tg account export-data --out DIR`

### Listening
- `tg listen [--notify] [--download-media]` (existing — preserved)
- `tg events tail [--chat C] [--type incoming|outgoing|edit|delete] [--json]` (NDJSON live stream)

### Pre-existing (preserved)
- `tg login`, `tg backfill`, `tg discover`, `tg show`, `tg sync-contacts`

## Output spec

Auto-detect: TTY → human, pipe → JSON. Override via `--json` / `--human`.

**Success:**
```json
{ "ok": true, "command": "messages.send", "data": {...}, "warnings": [] }
```

**Error:**
```json
{ "ok": false, "command": "messages.send",
  "error": { "code": "FLOOD_WAIT", "message": "...", "retry_after_seconds": 30 } }
```

**Streaming (`events tail`):** NDJSON, one event per line, no envelope, schema:
```json
{ "event_type": "incoming", "chat_id": 12345, "message_id": 99, "date": "...", "data": {...} }
```

**Exit codes:**
| Code | Meaning |
|------|---------|
| 0    | success |
| 1    | generic error |
| 2    | invalid arguments |
| 3    | not authenticated |
| 4    | chat/message not found |
| 5    | FloodWait (Telegram-side rate limit) |
| 6    | write disallowed (no `--allow-write`) |
| 7    | destructive op missing `--confirm` |
| 8    | local rate limit hit |

## Safety model

Single safety pipeline; every write command passes through it in order:

1. **Write gate** — `args.allow_write` flag required *per invocation*. The previously-considered `TG_ALLOW_WRITE=1` env var is rejected: a leaked env makes every future agent call mutating. Flag-only is verbose but visible.
2. **Destructive gate (typed confirm)** — destructive commands take `--confirm <expected-target>` where `<expected-target>` must equal the resolved `chat_id` or `message_id`. Bare `--confirm` (with no value) does not satisfy the gate. Example:
   ```bash
   tg messages delete 12345 99 100 --allow-write --confirm 12345
   ```
3. **Dry-run short-circuit** — `--dry-run` emits a `would-do` envelope including: `request_id`, `resolved_chat_id`, `resolved_chat_title`, `telethon_method`, `normalized_args`. No API call.
4. **Local rate limiter** — token bucket. Default: 20 outbound msgs / 60s; 100 reads / 60s. On hit → log to `audit.log`, sleep, retry once, exit 8 if still blocked.
5. **Pre-call audit entry** — write an NDJSON line to `audit.log` *before* the Telethon call:
   ```json
   {"ts": "...", "request_id": "01HXYZ...", "phase": "before",
    "cmd": "messages.send", "actor": "agent|human",
    "resolved_chat_id": 12345, "resolved_chat_title": "Hamïd Ijadi",
    "telethon_method": "SendMessageRequest", "args": {...},
    "dry_run": false}
   ```
6. **Telethon call** — wrap in try/except. `FloodWaitError` → log retry-window to audit, exit 5; permission errors → exit 1 with body; other exceptions → exit 1.
7. **Post-call audit entry** — write the resulting `phase: "after"` line including `result: "ok|error"`, `message_id`, `error_code` if any, and the *same* `request_id` so retries are visible as a chain.

**Request IDs** — every write command generates a ULID `request_id` at parse time. Used in: pre/post audit entries, dry-run output, error envelopes, MCP tool responses. An agent that retries can include the previous `request_id` in `--idempotency-key` to detect duplicate-send attempts (server-side check: did we already commit this id? if yes, return prior result without re-sending).

**Batch operations** — for commands that take multiple targets (`messages delete <id1> <id2> ...`), the response envelope contains `data.results: [{ok, target_id, result|error}, ...]` with one entry per target, plus `data.summary: {total, succeeded, failed}`.

## Resolving the `<chat>` arg

Three-step fallback in `resolve.py`:
1. Numeric int → use as chat_id.
2. `@username` → `client.get_entity(username)` (Telethon API call) + DB cache.
3. Otherwise → accent-insensitive substring match against `tg_chats.title`. **Requires `--fuzzy` for any write or destructive command.** Without `--fuzzy`, fuzzy matches on a write command exit 2 with the message: `"'<raw>' looks like a fuzzy title match; pass --fuzzy to allow it for write operations, or use the chat_id directly."`
   - 0 matches → exit 4.
   - 1 match → use it.
   - >1 matches → exit 2 + disambiguation list to stderr.

For *read* commands, fuzzy match is allowed by default (read mistakes are recoverable; write mistakes are not).

For numeric IDs on write commands, the resolver loads the chat title and includes it in the dry-run / pre-call audit so the agent can verify the target *before* the typed `--confirm` is required.

Same logic for the `<user>` arg in contacts commands.

## MCP topology — three servers, not one

A single MCP server with `TG_MCP_WRITE`/`TG_MCP_DESTRUCTIVE` env toggles is rejected: env-toggled permissions are invisible in Claude Code's tool-permission UI and trivially misconfigured. Instead ship three distinct entry points, each a separate `claude mcp add` registration:

- **`tgcli_mcp.read_server`** — exposes ~12 read-only tools (`tg_chats_list`, `tg_messages_search`, `tg_me`, `tg_unread`, etc.). Always safe to wire.
- **`tgcli_mcp.write_server`** — exposes the read tools *plus* ~8 write tools (`tg_messages_send`, `tg_messages_react`, `tg_media_upload`, etc.). User opts in by registering this server instead of the read one.
- **`tgcli_mcp.destructive_server`** — exposes write *plus* ~5 destructive tools (`tg_destructive_messages_delete`, `tg_destructive_chats_leave`, `tg_destructive_contacts_block`, etc.). Tools in this server carry the `tg_destructive_*` prefix so Claude Code's permission prompt makes the risk visible at the tool name level.

Each server is one Python module under `tgcli_mcp/`, sharing the underlying `tgcli/commands/<area>.py` handlers. The wrapper script `tgcli_mcp/run.sh` takes the server name as `$1`:

```bash
claude mcp add tg-read   /path/to/tgcli_mcp/run.sh read
claude mcp add tg-write  /path/to/tgcli_mcp/run.sh write
claude mcp add tg-destr  /path/to/tgcli_mcp/run.sh destructive
```

User picks which one(s) to register based on trust. Default recommendation: read-only.

## Implementation phases

| Phase | Scope                                                                                  | Detailed in this plan |
|-------|----------------------------------------------------------------------------------------|-----------------------|
| 1     | Package refactor: tg_scrape.py → tgcli/ ; preserve current commands                    | YES (Phase 1 below)   |
| 2     | Output framework (json/human/exit codes) ; safety framework (gates/limiter/audit)      | YES (Phase 2 below)   |
| 3     | Chat resolver + `--min-msgs` filters everywhere                                        | YES (Phase 3 below)   |
| 4     | Read-API completion: `messages search/list/get`, `me`, `unread`, `chats info`          | summary — plan in detail when phase 3 lands |
| 5     | Write-text API: `send/edit/forward/pin/unpin/react/mark-read`                          | summary               |
| 6     | Destructive: `messages delete`, `chats leave`, `contacts remove/block`, `sessions terminate` | summary       |
| 7     | Media: `media upload/download`                                                         | summary               |
| 8     | Chat lifecycle: `join/mute/archive/title`, `contacts add`                              | summary               |
| 9     | Account: `account info/sessions/export-data` ; `events tail` ; `api` escape hatch      | summary               |
| 10    | MCP server wrapper                                                                     | summary               |
| 11    | Tests, README, error-code catalog, audit-log mirroring (optional Saved-Messages)       | summary               |

Phases 4–11 will get their own detailed plans (one per phase) once the foundation lands. Codex review focuses on the foundation (1–3) plus the overall design.

---

## Phase 1 — Package refactor

Goal: move every working command from `tg_scrape.py` into `tgcli/`. Behavior identical, file layout per spec above. After Phase 1, `./tg <subcmd>` runs unchanged for the user.

### Task 1.1: Scaffold the package skeleton

**Files:**
- Create: `telegram_test/tgcli/__init__.py`
- Create: `telegram_test/tgcli/__main__.py`
- Create: `telegram_test/tgcli/commands/__init__.py`

- [ ] **Step 1: Write the failing smoke test**

```python
# tests/tgcli/test_cli_smoke.py
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent / "telegram_test"
PYTHON = ROOT.parent / ".venv/bin/python"

def test_module_help_exits_zero():
    r = subprocess.run(
        [str(PYTHON), "-m", "tgcli", "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode == 0
    assert "usage:" in r.stdout.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/christiannikolov/Projects/scrapling-test
.venv/bin/pytest tests/tgcli/test_cli_smoke.py::test_module_help_exits_zero -v
```
Expected: FAIL — `No module named tgcli`.

- [ ] **Step 3: Create the empty package**

```python
# telegram_test/tgcli/__init__.py
"""Telegram agent CLI."""
```

```python
# telegram_test/tgcli/__main__.py
import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="tg", description="Telegram agent CLI")
    parser.add_subparsers(dest="cmd", required=True)
    args = parser.parse_args()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

```python
# telegram_test/tgcli/commands/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/tgcli/test_cli_smoke.py::test_module_help_exits_zero -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git init  # this repo is not yet a git repo per CLAUDE.md
git add telegram_test/tgcli tests/tgcli
git commit -m "feat(tgcli): scaffold package skeleton with smoke test"
```
*(If user prefers no-git, skip the git commands — but recommend init for tracking the refactor.)*

---

### Task 1.2: Move env loader and DB schema into tgcli (additive — no deletions)

**Reordering note (per codex review):** to keep every Phase-1 commit shippable, this task only *adds* the new modules. The corresponding deletions from `tg_scrape.py` happen in Task 1.6, *after* every command has been ported and the wrapper has switched over.

**Files:**
- Create: `telegram_test/tgcli/env.py`
- Create: `telegram_test/tgcli/db.py`
- (No modifications to `tg_scrape.py` in this task — it keeps working in parallel until Task 1.6.)

- [ ] **Step 1: Write a failing test for env loader**

```python
# tests/tgcli/test_env.py
import os
from tgcli.env import load_env_file

def test_load_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("TG_API_ID", raising=False)
    p = tmp_path / ".env"
    p.write_text('# comment\nTG_API_ID=99999\nTG_API_HASH="abc"\nEMPTY=\n')
    load_env_file(p)
    assert os.environ["TG_API_ID"] == "99999"
    assert os.environ["TG_API_HASH"] == "abc"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/tgcli/test_env.py -v
```
Expected: FAIL — `No module named tgcli.env`.

- [ ] **Step 3: Implement tgcli/env.py**

```python
# telegram_test/tgcli/env.py
import os
from pathlib import Path


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
```

- [ ] **Step 4: Implement tgcli/db.py with the existing schema**

```python
# telegram_test/tgcli/db.py
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tg_chats (
    chat_id INTEGER PRIMARY KEY, type TEXT, title TEXT, username TEXT,
    phone TEXT, first_name TEXT, last_name TEXT, is_bot INTEGER,
    last_seen_at TEXT, raw_json TEXT
);
CREATE TABLE IF NOT EXISTS tg_messages (
    chat_id INTEGER, message_id INTEGER, sender_id INTEGER, date TEXT,
    text TEXT, is_outgoing INTEGER, reply_to_msg_id INTEGER,
    has_media INTEGER, media_type TEXT, media_path TEXT, raw_json TEXT,
    PRIMARY KEY (chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_chat_date ON tg_messages(chat_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_messages_date ON tg_messages(date DESC);
CREATE TABLE IF NOT EXISTS tg_contacts (
    user_id INTEGER PRIMARY KEY, phone TEXT, first_name TEXT, last_name TEXT,
    username TEXT, is_mutual INTEGER, synced_at TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    try:
        con.execute("ALTER TABLE tg_messages ADD COLUMN media_path TEXT")
    except sqlite3.OperationalError:
        pass
    return con
```

- [ ] **Step 5: Verify env test passes**

```bash
.venv/bin/pytest tests/tgcli/test_env.py -v
```
Expected: PASS.

- [ ] **Step 6: Smoke-test that the existing tg_scrape.py still works**

```bash
cd telegram_test && ./tg stats
```
Expected: same output as before (db row counts, top chats, media breakdown). No errors.

- [ ] **Step 7: Commit**

```bash
git add telegram_test/tgcli tests/tgcli
git commit -m "feat(tgcli): extract env loader and db connection from tg_scrape"
```

---

### Task 1.3: Move client factory + auth check into tgcli

**Files:**
- Create: `telegram_test/tgcli/client.py`

- [ ] **Step 1: Write a failing test for the credential guard**

```python
# tests/tgcli/test_client.py
import pytest
from tgcli.client import ensure_credentials, MissingCredentials

def test_missing_credentials_raises(monkeypatch):
    monkeypatch.delenv("TG_API_ID", raising=False)
    monkeypatch.delenv("TG_API_HASH", raising=False)
    with pytest.raises(MissingCredentials):
        ensure_credentials()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/tgcli/test_client.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement tgcli/client.py**

```python
# telegram_test/tgcli/client.py
import os
from pathlib import Path
from telethon import TelegramClient


class MissingCredentials(RuntimeError):
    pass


def ensure_credentials() -> tuple[int, str]:
    api_id = int(os.environ.get("TG_API_ID", "0") or 0)
    api_hash = os.environ.get("TG_API_HASH", "")
    if not api_id or not api_hash:
        raise MissingCredentials(
            "TG_API_ID and TG_API_HASH must be set. "
            "Register an app at https://my.telegram.org/apps"
        )
    return api_id, api_hash


def make_client(session_path: Path) -> TelegramClient:
    api_id, api_hash = ensure_credentials()
    return TelegramClient(str(session_path), api_id, api_hash)
```

- [ ] **Step 4: Verify test passes**

```bash
.venv/bin/pytest tests/tgcli/test_client.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add telegram_test/tgcli/client.py tests/tgcli/test_client.py
git commit -m "feat(tgcli): client factory with credential guard"
```

---

### Task 1.4: Port the existing read commands

**Per codex review:** Task 1.4 is split into one sub-task per command, each with its own smoke test and commit. Order:

- **1.4a** — port `stats` to `tgcli/commands/stats.py`; smoke-test `./tg stats` against existing DB; commit.
- **1.4b** — port `contacts` (list + sync) to `tgcli/commands/contacts.py`; smoke-test against the 119-contact DB; commit.
- **1.4c** — port `show` to `tgcli/commands/messages.py`; smoke-test `./tg show Hamid`; commit.
- **1.4d** — port `discover` to `tgcli/commands/chats.py`; smoke-test (no Telegram call needed since DB already has 112 dialogs); commit.
- **1.4e** — port `backfill` to `tgcli/commands/messages.py`; verify `--dry-run` path; commit.
- **1.4f** — port `listen` to `tgcli/commands/events.py`; verify it still echoes to Saved Messages with `--notify`; commit.

(For brevity in this plan, the detailed step-by-step is shown only for 1.4a below; subsequent sub-tasks follow the same template — failing test, port, smoke-test, commit.)

### Task 1.4a: Port stats command

**Files:**
- Create: `telegram_test/tgcli/commands/stats.py`
- Create: `telegram_test/tgcli/commands/contacts.py`
- Create: `telegram_test/tgcli/commands/messages.py` *(initially only `show` and `backfill` ports)*
- Create: `telegram_test/tgcli/commands/chats.py` *(initially only `discover`)*
- Create: `telegram_test/tgcli/commands/_common.py`
- Modify: `telegram_test/tgcli/__main__.py` — register subparsers from each command module

- [ ] **Step 1: Define _common.py for shared registration helpers**

```python
# telegram_test/tgcli/commands/_common.py
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "telegram.sqlite"
SESSION_PATH = ROOT / "tg.session"
ENV_PATH = ROOT / ".env"
MEDIA_DIR = ROOT / "media"
```

- [ ] **Step 2: Port stats command**

```python
# telegram_test/tgcli/commands/stats.py
import argparse
from tgcli.commands._common import DB_PATH
from tgcli.db import connect


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("stats", help="DB summary")
    p.set_defaults(func=run)


def run(args) -> int:
    if not DB_PATH.exists():
        print(f"DB not yet created at {DB_PATH}.")
        return 1
    con = connect(DB_PATH)
    chats = con.execute("SELECT COUNT(*) FROM tg_chats").fetchone()[0]
    msgs = con.execute("SELECT COUNT(*) FROM tg_messages").fetchone()[0]
    contacts = con.execute("SELECT COUNT(*) FROM tg_contacts").fetchone()[0]
    print(f"DB: {DB_PATH} ({DB_PATH.stat().st_size // 1024} KB)")
    print(f"Chats: {chats}")
    print(f"Messages: {msgs}")
    print(f"Contacts: {contacts}")
    # full body comes verbatim from tg_scrape.py:cmd_stats
    return 0
```

*(Repeat the verbatim port for `contacts`, `messages.show`, `messages.backfill`, `chats.discover`, `contacts.sync` — copying body from `tg_scrape.py` with sync/async preserved. Each one in its own step + commit.)*

- [ ] **Step 3: Wire dispatcher**

```python
# telegram_test/tgcli/__main__.py
import argparse
import asyncio
import inspect
import sys
from pathlib import Path

from tgcli.env import load_env_file
from tgcli.commands import stats, contacts, messages, chats

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_env_file(ENV_PATH)


def main() -> int:
    parser = argparse.ArgumentParser(prog="tg", description="Telegram agent CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for mod in (stats, contacts, messages, chats):
        mod.register(sub)
    args = parser.parse_args()
    result = args.func(args)
    if inspect.iscoroutine(result):
        return asyncio.run(result) or 0
    return int(result or 0)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Smoke test each ported command**

```bash
cd telegram_test
.venv/bin/python -m tgcli stats
.venv/bin/python -m tgcli contacts list
.venv/bin/python -m tgcli messages show Hamid
.venv/bin/python -m tgcli chats discover
```
Expected: same output as `./tg stats`, `./tg contacts`, etc.

- [ ] **Step 5: Commit per command port**

```bash
git add telegram_test/tgcli/commands/<name>.py
git commit -m "feat(tgcli): port <name> command from tg_scrape.py"
```

---

### Task 1.5: Update the `tg` shell wrapper to use the package

**Files:**
- Modify: `telegram_test/tg` (single line change)

- [ ] **Step 1: Update wrapper**

```bash
# telegram_test/tg
#!/usr/bin/env bash
HERE="$(cd "$(dirname "$0")" && pwd)"
exec "$HERE/../.venv/bin/python" -m tgcli "$@"
```

- [ ] **Step 2: Verify all subcommands run via wrapper**

```bash
cd telegram_test
./tg stats
./tg contacts --chatted --limit 5
./tg messages show Polymarket --limit 3
```
Expected: same output as before refactor.

- [ ] **Step 3: Commit**

```bash
git add telegram_test/tg
git commit -m "refactor(tg): wrapper now invokes tgcli package"
```

---

### Task 1.6: Reduce tg_scrape.py to a deprecation shim

**Files:**
- Modify: `telegram_test/tg_scrape.py` (replace full content)

- [ ] **Step 1: Write deprecation shim**

```python
# telegram_test/tg_scrape.py
"""Deprecated: use `python -m tgcli ...` or `./tg ...`."""
import sys

print(
    "tg_scrape.py is deprecated; run via `./tg <subcmd>` or `python -m tgcli <subcmd>`.",
    file=sys.stderr,
)
from tgcli.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify backwards compatibility**

```bash
cd telegram_test
../.venv/bin/python tg_scrape.py stats
```
Expected: deprecation warning to stderr + same stats output as `./tg stats`.

- [ ] **Step 3: Commit**

```bash
git add telegram_test/tg_scrape.py
git commit -m "refactor(tg): tg_scrape.py becomes a deprecation shim"
```

---

## Phase 2 — Output framework + safety framework

### Task 2.1: Build the JSON envelope formatter (TDD)

**Files:**
- Create: `telegram_test/tgcli/output.py`
- Create: `tests/tgcli/test_output.py`

- [ ] **Step 1: Write failing test for success envelope**

```python
# tests/tgcli/test_output.py
import json
from tgcli.output import success, fail, ExitCode

def test_success_envelope_shape():
    env = success("messages.send", {"chat_id": 1, "message_id": 2})
    assert env == {
        "ok": True,
        "command": "messages.send",
        "data": {"chat_id": 1, "message_id": 2},
        "warnings": [],
    }
    json.dumps(env)  # must serialise

def test_fail_envelope_shape():
    env = fail("messages.send", ExitCode.FLOOD_WAIT, "wait", retry_after_seconds=30)
    assert env["ok"] is False
    assert env["error"]["code"] == "FLOOD_WAIT"
    assert env["error"]["retry_after_seconds"] == 30
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/tgcli/test_output.py -v
```
Expected: FAIL — `tgcli.output` not found.

- [ ] **Step 3: Implement output.py**

```python
# telegram_test/tgcli/output.py
import enum
import json
import sys
from typing import Any


class ExitCode(enum.IntEnum):
    OK = 0
    GENERIC = 1
    BAD_ARGS = 2
    NOT_AUTHED = 3
    NOT_FOUND = 4
    FLOOD_WAIT = 5
    WRITE_DISALLOWED = 6
    NEEDS_CONFIRM = 7
    LOCAL_RATE_LIMIT = 8


def success(command: str, data: Any, warnings: list[str] | None = None) -> dict:
    return {
        "ok": True,
        "command": command,
        "data": data,
        "warnings": warnings or [],
    }


def fail(command: str, code: ExitCode, message: str, **extra) -> dict:
    return {
        "ok": False,
        "command": command,
        "error": {"code": code.name, "message": message, **extra},
    }


def emit(envelope: dict, *, json_mode: bool, human_formatter=None) -> int:
    if json_mode:
        print(json.dumps(envelope, ensure_ascii=False, default=str))
    elif envelope["ok"] and human_formatter:
        human_formatter(envelope["data"])
    elif envelope["ok"]:
        print(json.dumps(envelope["data"], ensure_ascii=False, indent=2, default=str))
    else:
        print(f"ERROR [{envelope['error']['code']}]: {envelope['error']['message']}",
              file=sys.stderr)
    return ExitCode.OK if envelope["ok"] else ExitCode[envelope["error"]["code"]]


def is_tty_stdout() -> bool:
    return sys.stdout.isatty()
```

- [ ] **Step 4: Verify test passes**

```bash
.venv/bin/pytest tests/tgcli/test_output.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add telegram_test/tgcli/output.py tests/tgcli/test_output.py
git commit -m "feat(tgcli): JSON success/fail envelope and exit codes"
```

---

### Task 2.2: Build safety gates (TDD)

**Files:**
- Create: `telegram_test/tgcli/safety.py`
- Create: `tests/tgcli/test_safety.py`

- [ ] **Step 1: Write failing tests for write gate + confirm gate**

```python
# tests/tgcli/test_safety.py
import argparse
import os
import pytest
from tgcli.safety import (
    require_write_allowed, require_confirm,
    WriteDisallowed, NeedsConfirm,
)


def make_args(**kw):
    ns = argparse.Namespace()
    ns.allow_write = kw.get("allow_write", False)
    ns.confirm = kw.get("confirm", False)
    ns.dry_run = kw.get("dry_run", False)
    return ns


def test_write_gate_disallows_by_default(monkeypatch):
    monkeypatch.delenv("TG_ALLOW_WRITE", raising=False)
    with pytest.raises(WriteDisallowed):
        require_write_allowed(make_args())


def test_write_gate_via_flag():
    require_write_allowed(make_args(allow_write=True))  # no raise


def test_write_gate_via_env(monkeypatch):
    monkeypatch.setenv("TG_ALLOW_WRITE", "1")
    require_write_allowed(make_args())  # no raise


def test_confirm_gate_requires_flag():
    with pytest.raises(NeedsConfirm):
        require_confirm(make_args(allow_write=True), action="messages.delete")


def test_confirm_gate_via_flag():
    require_confirm(make_args(allow_write=True, confirm=True), action="x")  # no raise
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/tgcli/test_safety.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement safety.py**

```python
# telegram_test/tgcli/safety.py
import json
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


class WriteDisallowed(Exception): ...
class NeedsConfirm(Exception): ...
class LocalRateLimited(Exception): ...


def require_write_allowed(args) -> None:
    if getattr(args, "allow_write", False):
        return
    if os.environ.get("TG_ALLOW_WRITE") == "1":
        return
    raise WriteDisallowed(
        "Write operations require --allow-write or TG_ALLOW_WRITE=1"
    )


def require_confirm(args, action: str) -> None:
    if getattr(args, "confirm", False):
        return
    raise NeedsConfirm(
        f"Destructive op '{action}' requires --confirm"
    )


class RateLimiter:
    """Token-bucket-ish: max N events per window seconds."""

    def __init__(self, max_per_window: int, window_seconds: float):
        self.max = max_per_window
        self.window = window_seconds
        self.events: deque[float] = deque()

    def check(self) -> float:
        now = time.monotonic()
        while self.events and now - self.events[0] > self.window:
            self.events.popleft()
        if len(self.events) >= self.max:
            return self.window - (now - self.events[0])  # seconds to wait
        self.events.append(now)
        return 0.0


def audit_write(audit_path: Path, cmd: str, args_repr: dict, result: str, **extra) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cmd": cmd,
        "args": args_repr,
        "result": result,
        **extra,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
```

- [ ] **Step 4: Verify tests pass**

```bash
.venv/bin/pytest tests/tgcli/test_safety.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Add a rate-limiter test**

```python
# tests/tgcli/test_safety.py — append
import time
from tgcli.safety import RateLimiter

def test_rate_limiter_blocks_after_max():
    rl = RateLimiter(max_per_window=2, window_seconds=10)
    assert rl.check() == 0.0
    assert rl.check() == 0.0
    wait = rl.check()
    assert wait > 0
```

- [ ] **Step 6: Run, verify pass**

```bash
.venv/bin/pytest tests/tgcli/test_safety.py -v
```
Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add telegram_test/tgcli/safety.py tests/tgcli/test_safety.py
git commit -m "feat(tgcli): write gate, confirm gate, rate limiter, audit log"
```

---

### Task 2.3: Add `--json`/`--human` and `--allow-write`/`--confirm`/`--dry-run` flags to common parser

**Files:**
- Modify: `telegram_test/tgcli/commands/_common.py`
- Modify: each `tgcli/commands/<area>.py` to use shared parser

- [ ] **Step 1: Define the shared parser additions**

```python
# telegram_test/tgcli/commands/_common.py — append
import argparse


def add_output_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Force JSON output")
    parser.add_argument("--human", action="store_true", help="Force human output")


def add_write_flags(parser: argparse.ArgumentParser, *, destructive: bool = False) -> None:
    parser.add_argument("--allow-write", action="store_true",
                        help="Required for any write operation")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would happen, then exit without calling Telegram")
    if destructive:
        parser.add_argument("--confirm", action="store_true",
                            help="Required for destructive operation (delete/leave/block)")
```

- [ ] **Step 2: Update each `register()` to add output flags**

```python
# example: tgcli/commands/stats.py
def register(sub):
    p = sub.add_parser("stats", help="DB summary")
    add_output_flags(p)
    p.set_defaults(func=run)
```

- [ ] **Step 3: Smoke test**

```bash
./tg stats --json
./tg stats --human
./tg stats           # auto: human on TTY
./tg stats | cat     # auto: still currently human; will become json after task 2.4
```

- [ ] **Step 4: Commit**

```bash
git add telegram_test/tgcli
git commit -m "feat(tgcli): output and write flags on every parser"
```

---

### Task 2.4: Wire stats to the new envelope

**Files:**
- Modify: `telegram_test/tgcli/commands/stats.py`

- [ ] **Step 1: Add envelope and human formatter**

```python
# telegram_test/tgcli/commands/stats.py
import argparse
from tgcli.commands._common import DB_PATH, add_output_flags
from tgcli.db import connect
from tgcli.output import success, fail, ExitCode, emit, is_tty_stdout


def register(sub):
    p = sub.add_parser("stats", help="DB summary")
    add_output_flags(p)
    p.set_defaults(func=run)


def _human(data):
    print(f"DB:       {data['db_path']} ({data['db_kb']} KB)")
    print(f"Chats:    {data['chats']}")
    print(f"Messages: {data['messages']}")
    print(f"Contacts: {data['contacts']}")


def run(args) -> int:
    if not DB_PATH.exists():
        env = fail("stats", ExitCode.NOT_FOUND, f"DB not yet at {DB_PATH}")
        return emit(env, json_mode=args.json or not is_tty_stdout())
    con = connect(DB_PATH)
    data = {
        "db_path": str(DB_PATH),
        "db_kb": DB_PATH.stat().st_size // 1024,
        "chats": con.execute("SELECT COUNT(*) FROM tg_chats").fetchone()[0],
        "messages": con.execute("SELECT COUNT(*) FROM tg_messages").fetchone()[0],
        "contacts": con.execute("SELECT COUNT(*) FROM tg_contacts").fetchone()[0],
    }
    json_mode = args.json or (not args.human and not is_tty_stdout())
    return emit(success("stats", data), json_mode=json_mode, human_formatter=_human)
```

- [ ] **Step 2: Smoke-test json output**

```bash
./tg stats --json
./tg stats --json | python -c "import sys,json; print(json.load(sys.stdin)['ok'])"
```
Expected: prints JSON envelope with `ok=True`; second command prints `True`.

- [ ] **Step 3: Add a snapshot test**

```python
# tests/tgcli/test_cli_smoke.py — append
import json
def test_stats_json_envelope_shape():
    r = subprocess.run(
        [str(PYTHON), "-m", "tgcli", "stats", "--json"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0
    env = json.loads(r.stdout)
    assert env["ok"] is True
    assert env["command"] == "stats"
    assert "chats" in env["data"]
```

- [ ] **Step 4: Run all tests**

```bash
.venv/bin/pytest tests/tgcli -v
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add telegram_test/tgcli/commands/stats.py tests/tgcli/test_cli_smoke.py
git commit -m "feat(tgcli): stats emits envelope with --json/--human"
```

*(Task 2.5–2.7: repeat the same envelope wiring for `contacts`, `chats discover`, `messages show`. Each in its own task + commit.)*

---

## Phase 3 — Resolver + `--min-msgs` filter

### Task 3.1: Implement chat resolver (TDD)

**Files:**
- Create: `telegram_test/tgcli/resolve.py`
- Create: `tests/tgcli/test_resolve.py`

- [ ] **Step 1: Failing tests for the three-step fallback**

```python
# tests/tgcli/test_resolve.py
import pytest
import sqlite3
from tgcli.resolve import resolve_chat_db, NotFound, Ambiguous


def setup_db():
    con = sqlite3.connect(":memory:")
    con.execute("""
        CREATE TABLE tg_chats (
            chat_id INTEGER PRIMARY KEY, type TEXT, title TEXT,
            username TEXT, phone TEXT, first_name TEXT, last_name TEXT,
            is_bot INTEGER, last_seen_at TEXT, raw_json TEXT
        )
    """)
    con.executemany(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES(?,?,?,?)",
        [(1, "user", "Hamïd Ijadi", "HRALEyn"),
         (2, "user", "Hamburger Verein", None),
         (3, "user", "Joel", None)],
    )
    return con


def test_resolve_by_int():
    con = setup_db()
    assert resolve_chat_db(con, "3") == (3, "Joel")


def test_resolve_by_username():
    con = setup_db()
    assert resolve_chat_db(con, "@HRALEyn") == (1, "Hamïd Ijadi")


def test_resolve_by_fuzzy():
    con = setup_db()
    assert resolve_chat_db(con, "ijadi") == (1, "Hamïd Ijadi")


def test_resolve_ambiguous_raises():
    con = setup_db()
    with pytest.raises(Ambiguous) as e:
        resolve_chat_db(con, "Ham")
    assert len(e.value.candidates) == 2


def test_resolve_not_found_raises():
    con = setup_db()
    with pytest.raises(NotFound):
        resolve_chat_db(con, "nonexistent")
```

- [ ] **Step 2: Run, verify FAIL**

```bash
.venv/bin/pytest tests/tgcli/test_resolve.py -v
```

- [ ] **Step 3: Implement resolve.py**

```python
# telegram_test/tgcli/resolve.py
import sqlite3
import unicodedata


class NotFound(Exception): ...
class Ambiguous(Exception):
    def __init__(self, raw, candidates):
        super().__init__(f"'{raw}' is ambiguous: {len(candidates)} matches")
        self.candidates = candidates


def _strip_accents(s: str | None) -> str:
    if not s:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    ).lower()


def resolve_chat_db(con: sqlite3.Connection, raw: str) -> tuple[int, str]:
    """DB-only resolution. For username lookups beyond DB, async resolve_chat() also hits Telethon."""
    raw = raw.strip()
    if raw.lstrip("-").isdigit():
        row = con.execute("SELECT chat_id, title FROM tg_chats WHERE chat_id=?", (int(raw),)).fetchone()
        if row:
            return row
        raise NotFound(f"chat_id {raw} not in DB")
    if raw.startswith("@"):
        row = con.execute("SELECT chat_id, title FROM tg_chats WHERE LOWER(username)=LOWER(?)", (raw[1:],)).fetchone()
        if row:
            return row
        raise NotFound(f"username {raw} not in DB; use Telethon resolve_chat()")
    needle = _strip_accents(raw)
    rows = con.execute("SELECT chat_id, title FROM tg_chats").fetchall()
    matches = [r for r in rows if needle in _strip_accents(r[1])]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise NotFound(f"no chat title contains '{raw}'")
    raise Ambiguous(raw, matches)
```

- [ ] **Step 4: Run, verify PASS**

```bash
.venv/bin/pytest tests/tgcli/test_resolve.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add telegram_test/tgcli/resolve.py tests/tgcli/test_resolve.py
git commit -m "feat(tgcli): chat resolver — int/username/fuzzy"
```

---

### Task 3.2: Add `--min-msgs N` to stats and contacts

**Files:**
- Modify: `telegram_test/tgcli/commands/stats.py`
- Modify: `telegram_test/tgcli/commands/contacts.py`

- [ ] **Step 1: Failing test (smoke)**

```python
# tests/tgcli/test_cli_smoke.py — append
def test_stats_min_msgs_flag_accepted():
    r = subprocess.run(
        [str(PYTHON), "-m", "tgcli", "stats", "--min-msgs", "5", "--json"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0
```

- [ ] **Step 2: Run, expect FAIL** (`unrecognized arguments: --min-msgs`)

- [ ] **Step 3: Add the flag in `stats.register` + filter SQL**

Code in stats.py: add `p.add_argument("--min-msgs", type=int, default=0)` and apply to "Top 10 chats" subquery.

- [ ] **Step 4: Same change in contacts.py for the chatted filter**

- [ ] **Step 5: Run, expect PASS**

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(tgcli): --min-msgs filter on stats and contacts"
```

---

## Phases 4–11 (planned per phase)

After phase 3 lands and codex review confirms the foundation is sound, each subsequent phase will get its own dedicated plan file:

- `2026-MM-DD-tg-phase-4-read-api.md` — `messages search/list/get`, `me`, `unread`, `chats info`
- `2026-MM-DD-tg-phase-5-write-text.md` — `messages send/edit/forward/pin/react/mark-read`
- `2026-MM-DD-tg-phase-6-destructive.md` — `messages delete`, `chats leave`, `contacts remove/block`, `sessions terminate`
- `2026-MM-DD-tg-phase-7-media.md`
- `2026-MM-DD-tg-phase-8-lifecycle.md`
- `2026-MM-DD-tg-phase-9-account-events-api.md`
- `2026-MM-DD-tg-phase-10-mcp.md`
- `2026-MM-DD-tg-phase-11-polish.md`

Each follows the same TDD structure: failing test → minimal impl → verify → commit. Per-phase plan size ~150–250 lines.

## Resolved design decisions (post-codex review)

1. **Multiline send via stdin** → **YES**. `tg messages send <chat> -` reads from stdin.
2. **Fuzzy resolve safety** → **`--fuzzy` REQUIRED** for write/destructive ops (see Resolver section).
3. **`api` escape hatch** → **DROPPED FROM v1**. Skip until normal CRUD coverage is complete; revisit in phase 12+.
4. **MCP topology** → **THREE SEPARATE SERVERS** (see MCP topology section).
5. **MCP destructive tool naming** → **`tg_destructive_*` prefix** on every destructive tool.
6. **Audit log** → **NDJSON local file**, with pre-call + post-call entries sharing a `request_id`.
7. **Idempotency** → **`--idempotency-key <key>`** on every write op; if a prior `request_id` matches, return the cached prior result instead of re-sending.
8. **Listener vs `events tail`** → **keep both**. `listen --notify` is human-mode, `events tail --json` is agent-mode.
9. **Multi-account** → **defer**. Single session for v1.
10. **Test strategy** → **pure-function unit tests + command-level payload tests + smoke tests + manual real-account dry-run.** Command-level tests stop *before* the Telethon call and assert the constructed Telethon method + arg payload.

## Open design questions (still genuinely open)

1. **`--schedule` for send:** gate behind `--allow-schedule`? Add a `tg messages scheduled list/cancel` first so an agent that schedules can also see and cancel its own queue.
2. **Reactions on free accounts:** surface Premium-only constraint at parse time, or fail at API? *Decision pending.*
3. **Backfill incrementality:** add `tg_chats.last_backfilled_msg_id` watermark so re-runs only pull new messages? Big UX win for daily cron, slightly more state to maintain.
4. **`tg send <chat> "..."` shortcut alias** for `tg messages send`? Agents will use the short form constantly.
5. **Resolver — entity-type checks:** should `messages send` reject a `channel` chat (broadcast) where you can't actually send unless admin? Cheap pre-flight.
6. **Audit-log Telegram mirror:** mirror to your own Saved Messages so the audit is on-phone? Convenient, but doubles outbound traffic and pollutes Saved Messages.

## Out of scope (v1)

- Voice/video calls
- Stories
- Polls (parsed yes, created no)
- Bot account ownership (BotFather flows)
- Premium-only features (custom emoji, paid reactions)
- Secret (encrypted) chats
- Interactive TUI (use nchat for that)

## Success criteria

- [ ] Phases 1–3 complete: package refactor, output framework, safety framework, chat resolver, `--min-msgs`.
- [ ] All current commands (`stats`, `backfill`, `discover`, `show`, `contacts`, `sync-contacts`, `listen`) still work after refactor.
- [ ] Every command supports `--json` / `--human` with the consistent envelope.
- [ ] All write commands route through `safety.py` gates and emit audit-log entries.
- [ ] An agent (Claude Code) can: list unread chats → read messages from one → search archive → send a draft reply (with `--allow-write`) without tripping FloodWait or hitting a destructive operation by accident.
- [ ] MCP server (phase 10) exposes ≥10 read tools and ≥6 write tools.
- [ ] Total: ~2000 lines of Python, ≤4 dependencies (`telethon`, `mcp`, stdlib).

## Self-review notes

- Spec coverage: phases 4–11 are intentionally summarised, not detailed. Each gets its own plan file when its turn comes. Codex will review this design + Phase 1–3 detail.
- Placeholders: phase 4–11 task lists not present by design (per-phase planning), explicitly called out above. No `TODO`/`fill-in` strings inside phase 1–3 tasks.
- Type consistency: `chat_id` is always `int`, `message_id` always `int`, `command` always dot-notation string, exit codes always `ExitCode` enum members, audit entries always NDJSON.
- Git note: project is not currently a git repo (per CLAUDE.md). Recommend `git init` before phase 1 commit step. If user declines, drop the `git add/commit` steps and rely on file-state alone for review.
