# Phase 6 - Text Write Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-05-07

**Author:** Codex

**Status:** Draft

**Prerequisite:** Phase 4 complete with `80 passed`; current flat read commands (`search`, `list-msgs`, `get-msg`, `me`, `unread`, `chats-info`) remain green before starting.

**Goal:** Add Phase 6 text-write commands: `send`, `edit-msg`, `forward`, `pin-msg`, `unpin-msg`, `react`, and `mark-read`.

**Architecture:**
- Keep the flat argparse surface and register all seven write commands in `tgcli/commands/messages.py`.
- Every command uses `add_write_flags(parser, destructive=False)`, `require_write_allowed(args)`, `require_explicit_or_fuzzy(args, raw_selector)`, dry-run short-circuiting, idempotency lookup/recording, a process-global outbound write limiter, explicit pre-call audit, and post-call audit with the same `request_id`.
- Telethon-calling behavior is covered with monkeypatched async fake clients in unit tests; subprocess smoke tests cover only paths that do not need a live Telegram connection.

**Tech Stack:** Python 3.12 stdlib (`argparse`, `asyncio`, `json`, `sqlite3`, `sys`, `datetime`, `pathlib`), Telethon already present in the project, existing pytest. **No new third-party deps.**

**Backwards compatibility:** Current Phase 4 suite is `80 passed`. Phase 6 adds about 20-25 unit tests plus about 5 smoke tests, and should finish around `105-110 passed`.

---

## Existing Code Map

| Area | Current line references | Phase 6 use |
|---|---:|---|
| Master write-text scope | `docs/superpowers/plans/2026-05-06-tg-agent-cli.md:101-107`, `1300-1306` | Source scope for send, edit, forward, pin, unpin, react, and mark-read text-write commands |
| Master safety model | `docs/superpowers/plans/2026-05-06-tg-agent-cli.md:168-190` | Required write gate, dry-run, local rate limit, pre-call audit, Telethon call, post-call audit, and shared request id order |
| Master resolver rule | `docs/superpowers/plans/2026-05-06-tg-agent-cli.md:194-206` | Fuzzy title selectors require explicit `--fuzzy` for writes; integer ids and `@username` selectors remain explicit |
| Resolved design decisions | `docs/superpowers/plans/2026-05-06-tg-agent-cli.md:1315-1326` | Must honor stdin send, fuzzy safety, pre/post audit, idempotency, and test strategy |
| Phase 4 plan structure | `docs/superpowers/plans/2026-05-07-tg-agent-cli-phase-4.md:1-24`, `26-73`, `75-1473`, `1477-1554` | Match header, code map, file table, design decisions, task format, verification, commit sequence, checklist, and out-of-scope sections |
| Flat message command registration | `tgcli/commands/messages.py:36-85` | Add the seven flat write parsers beside `show`, `search`, `list-msgs`, `get-msg`, and `backfill` |
| Existing live Telethon lifecycle | `tgcli/commands/messages.py:539-624` | Reuse `make_client(SESSION_PATH)`, `await client.start()`, and `finally: await client.disconnect()` patterns for write runners |
| Existing cached chat resolver calls | `tgcli/commands/messages.py:359-534` | Write runners also resolve chat selectors against SQLite before calling Telethon |
| Common parser helpers | `tgcli/commands/_common.py:26-49` | Extend `add_write_flags()` with `--idempotency-key` and `--fuzzy`, then call it with `destructive=False` for every Phase 6 parser |
| Safety exceptions and gates | `tgcli/safety.py:16-33`, `36-53` | Reuse `BadArgs`, `WriteDisallowed`, `LocalRateLimited`, `require_write_allowed()`, and keep destructive confirm unused in Phase 6 |
| Rate limiter | `tgcli/safety.py:56-75` | Add a process-global outbound write limiter using the existing `RateLimiter` class |
| Audit writer | `tgcli/safety.py:78-98` | Add `audit_pre()` and keep `audit_write()` as the post-call audit writer |
| Dispatch request id and exception mapping | `tgcli/dispatch.py:48-78`, `89-126` | Expose the generated `request_id` on `args._request_id` before the runner is invoked so explicit runner-level `audit_pre()` shares the post-audit id |
| DB schema entrypoint | `tgcli/db.py:14-68`, `75-96` | Add `tg_idempotency` to `SCHEMA`; `connect()` applies it before helpers read/write keys |
| DB resolver implementation | `tgcli/resolve.py:33-82` | `require_explicit_or_fuzzy()` checks selector shape before `resolve_chat_db()` performs fuzzy matching |
| Text normalization helper | `tgcli/text.py:7-15` | No code change; note that fuzzy matching remains resolver-owned and accent-insensitive there |
| CLI module loading | `tgcli/__main__.py:18-36` | No new command module is needed because `tgcli.commands.messages` is already imported |
| Current safety tests | `tests/tgcli/test_safety.py:1-105` | Append tests for `require_explicit_or_fuzzy()` and `audit_pre()` |
| Current smoke tests | `tests/tgcli/test_cli_smoke.py:1-282` | Append subprocess smoke tests for write gate, fuzzy gate, dry-run, and parser surfaces |

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| tgcli/safety.py | modify | Add require_explicit_or_fuzzy(), audit_pre(), write-rate-limiter singleton |
| tgcli/db.py | modify | Add tg_idempotency table to SCHEMA |
| tgcli/idempotency.py | create | lookup(con, key, command) -> dict \| None and record(con, key, command, request_id, result_envelope) helpers |
| tgcli/commands/messages.py | modify | Add 7 write subcommands and their runners |
| tests/tgcli/test_phase6_writes.py | create | Unit tests for all 7 commands + idempotency + fuzzy-gate + dry-run |
| tests/tgcli/test_idempotency.py | create | Unit tests for idempotency helpers |
| tests/tgcli/test_safety.py | modify | Add tests for require_explicit_or_fuzzy and audit_pre |
| tests/tgcli/test_cli_smoke.py | modify | Add subprocess smoke tests for write-gate / idempotency / dry-run paths |

---

## Design Decisions

1. **Naming: flat vs grouped.** Stay flat for consistency with Phase 4: `send`, `edit-msg`, `forward`, `pin-msg`, `unpin-msg`, `react`, and `mark-read`. Phase 4 deliberately registered flat top-level commands in `tgcli/commands/messages.py:36-85`; using grouped `tg messages ...` only for Phase 6 would split the CLI style without improving safety.

2. **`--idempotency-key` storage.** Add `tg_idempotency(key TEXT PRIMARY KEY, command TEXT, request_id TEXT, result_json TEXT, created_at TEXT)` to `telegram.sqlite`. TTL is keep-forever in v1 because outbound writes are rare enough that correctness and replay visibility matter more than automatic cleanup.

3. **Pre-audit hook placement.** Use option (b): each write runner calls `audit_pre()` explicitly after building the resolved payload and before the Telethon call. This keeps dispatch clean and lets each command choose its own safe payload preview.

4. **Stdin reading.** When the text positional argument is literal `-`, read via `sys.stdin.read()`, strip trailing newlines, and reject an empty result after stripping with `BadArgs`. Direct positional text uses the same trailing-newline strip so stdin and argv text normalize consistently.

5. **Fuzzy-write gate location.** Add `require_explicit_or_fuzzy()` to `tgcli/safety.py` alongside `require_write_allowed()` and `require_confirm()`. The safety module already owns write-side caller intent checks, and placing the fuzzy gate there prevents each command runner from duplicating selector-shape rules.

6. **Rate-limiter scope is in-process only.** `OUTBOUND_WRITE_LIMITER` lives on the `RateLimiter` instance's in-memory deque, so it resets on every CLI invocation. This only throttles long-running consumers (the listener, a batch SDK script, future MCP server). One-shot `./tg send …` calls in a tight shell loop are NOT protected. A file-backed cross-invocation cooldown is deferred to Phase 8 polish.

7. **Idempotency replay returns a fresh request_id.** When `lookup_idempotency()` hits, the runner returns the cached `data` dict (with `idempotent_replay: True` injected), and `dispatch.run_command()` wraps it in a NEW envelope with a NEW `request_id`. The original-call's `request_id` is preserved in the `tg_idempotency.request_id` column for forensic traceability. This means callers see two distinct request_ids for the same logical write — by design, so audit-log analysis can count replays.

8. **Idempotency replay does NOT re-validate the chat selector.** Replay short-circuits before `_resolve_write_chat()`, so reusing the same `--idempotency-key` with a different `--chat` returns the cached result for the *original* chat. This is correct: the idempotency key is a caller-asserted "I already validated this is the right op." Mismatched keys are caller error, not platform error.

9. **Audit log records full message bodies.** `audit_pre` writes the full resolved `payload` (including `text`) to `audit.log`. Phase 8 polish will set owner-only file perms (0600) on `audit.log` to bound the disclosure surface; until then, `audit.log` is gitignored but world-readable on the local filesystem. No content truncation in v1 — full fidelity matters more than partial privacy at this stage.

---

## Task 1: Safety, idempotency schema, and idempotency helpers

**Goal:** Add pure safety/idempotency foundations before any Telethon write command exists.

**Files:**
- Modify: `tgcli/safety.py`
- Modify: `tgcli/db.py`
- Create: `tgcli/idempotency.py`
- Modify: `tests/tgcli/test_safety.py`
- Create: `tests/tgcli/test_idempotency.py`

- [ ] **Step 1: Write failing tests for fuzzy gate and pre-audit**

Append these tests to `tests/tgcli/test_safety.py`:

```python
def test_require_explicit_or_fuzzy_allows_integer_selector():
    require_explicit_or_fuzzy(make_args(), "12345")


def test_require_explicit_or_fuzzy_allows_username_selector():
    require_explicit_or_fuzzy(make_args(), "@alpha")


def test_require_explicit_or_fuzzy_rejects_title_without_flag():
    with pytest.raises(BadArgs, match="pass --fuzzy"):
        require_explicit_or_fuzzy(make_args(), "Alpha Chat")


def test_require_explicit_or_fuzzy_allows_title_with_flag():
    args = make_args()
    args.fuzzy = True
    require_explicit_or_fuzzy(args, "Alpha Chat")


def test_audit_pre_appends_before_entry(tmp_path: Path):
    log = tmp_path / "audit.log"
    audit_pre(
        log,
        cmd="send",
        request_id="req-pre",
        resolved_chat_id=123,
        resolved_chat_title="Alpha",
        payload_preview={"text": "hello"},
        telethon_method="client.send_message",
        dry_run=False,
    )

    entry = json.loads(log.read_text().splitlines()[0])
    assert entry["phase"] == "before"
    assert entry["cmd"] == "send"
    assert entry["request_id"] == "req-pre"
    assert entry["resolved_chat_id"] == 123
    assert entry["payload_preview"] == {"text": "hello"}
    assert entry["telethon_method"] == "client.send_message"
    assert entry["dry_run"] is False
```

Update the import block in `tests/tgcli/test_safety.py`:

```python
from tgcli.safety import (
    BadArgs,
    LocalRateLimited,
    NeedsConfirm,
    RateLimiter,
    WriteDisallowed,
    audit_pre,
    audit_write,
    require_confirm,
    require_explicit_or_fuzzy,
    require_write_allowed,
)
```

- [ ] **Step 2: Write failing tests for idempotency helpers**

Create `tests/tgcli/test_idempotency.py`:

```python
import pytest

from tgcli.db import connect
from tgcli.idempotency import lookup, record
from tgcli.safety import BadArgs


def test_lookup_returns_none_without_key(tmp_path):
    con = connect(tmp_path / "telegram.sqlite")
    try:
        assert lookup(con, None, "send") is None
        assert lookup(con, "", "send") is None
    finally:
        con.close()


def test_record_and_lookup_round_trip_envelope(tmp_path):
    con = connect(tmp_path / "telegram.sqlite")
    try:
        envelope = {
            "ok": True,
            "command": "send",
            "request_id": "req-1",
            "data": {"message_id": 77},
            "warnings": [],
        }
        record(con, "key-1", "send", "req-1", envelope)
        assert lookup(con, "key-1", "send") == envelope
    finally:
        con.close()


def test_lookup_rejects_key_reused_for_different_command(tmp_path):
    con = connect(tmp_path / "telegram.sqlite")
    try:
        record(
            con,
            "key-1",
            "send",
            "req-1",
            {
                "ok": True,
                "command": "send",
                "request_id": "req-1",
                "data": {"message_id": 77},
                "warnings": [],
            },
        )
        with pytest.raises(BadArgs, match="already used"):
            lookup(con, "key-1", "edit-msg")
    finally:
        con.close()
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_safety.py tests/tgcli/test_idempotency.py -q
```

Expected: FAIL because `require_explicit_or_fuzzy`, `audit_pre`, `tgcli.idempotency`, and `tg_idempotency` do not exist.

- [ ] **Step 4: Add safety helpers**

Add these imports near the top of `tgcli/safety.py`:

```python
import re
```

Add this code after `require_confirm()`:

```python
_EXPLICIT_INT_RE = re.compile(r"^[+-]?\d+$")


def _is_explicit_chat_selector(raw_selector: str) -> bool:
    value = str(raw_selector).strip()
    return bool(_EXPLICIT_INT_RE.fullmatch(value) or (value.startswith("@") and len(value) > 1))


def require_explicit_or_fuzzy(args, raw_selector: str) -> None:
    """Require --fuzzy before a write command may use title-based chat resolution."""
    if _is_explicit_chat_selector(raw_selector):
        return
    if getattr(args, "fuzzy", False):
        return
    raise BadArgs(
        f"{raw_selector!r} looks like a fuzzy title match; pass --fuzzy to allow it "
        "for write operations, or use the chat_id directly."
    )
```

Add this singleton after the `RateLimiter` class:

```python
OUTBOUND_WRITE_LIMITER = RateLimiter(max_per_window=20, window_seconds=60.0)
```

Add this helper before `audit_write()`:

```python
def audit_pre(
    audit_path: Path,
    *,
    cmd: str,
    request_id: str,
    resolved_chat_id: int,
    resolved_chat_title: str,
    payload_preview: dict[str, Any],
    telethon_method: str,
    dry_run: bool,
) -> None:
    """Append the pre-call write audit entry."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "phase": "before",
        "cmd": cmd,
        "request_id": request_id,
        "resolved_chat_id": resolved_chat_id,
        "resolved_chat_title": resolved_chat_title,
        "telethon_method": telethon_method,
        "payload_preview": payload_preview,
        "dry_run": dry_run,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
```

- [ ] **Step 5: Add idempotency schema**

Add this table inside `tgcli/db.py` `SCHEMA`, after the `tg_me` table:

```python
CREATE TABLE IF NOT EXISTS tg_idempotency (
    key         TEXT PRIMARY KEY,
    command     TEXT NOT NULL,
    request_id  TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
```

- [ ] **Step 6: Add idempotency helper module**

Create `tgcli/idempotency.py`:

```python
"""Idempotency helpers for Telegram-side write commands."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from tgcli.safety import BadArgs


def lookup(con: sqlite3.Connection, key: str | None, command: str) -> dict[str, Any] | None:
    """Return a cached result envelope for key+command, if one exists."""
    if not key:
        return None
    row = con.execute(
        """
        SELECT command, result_json
        FROM tg_idempotency
        WHERE key = ?
        """,
        (key,),
    ).fetchone()
    if row is None:
        return None
    recorded_command, result_json = row
    if recorded_command != command:
        raise BadArgs(
            f"Idempotency key {key!r} was already used for command {recorded_command!r}"
        )
    return json.loads(result_json)


def record(
    con: sqlite3.Connection,
    key: str | None,
    command: str,
    request_id: str,
    result_envelope: dict[str, Any],
) -> None:
    """Persist a successful write result envelope for later replay."""
    if not key:
        return
    con.execute(
        """
        INSERT INTO tg_idempotency(key, command, request_id, result_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            key,
            command,
            request_id,
            json.dumps(result_envelope, ensure_ascii=False, default=str),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    con.commit()
```

- [ ] **Step 7: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_safety.py tests/tgcli/test_idempotency.py -q
```

Expected: `18 passed` in these two files.

- [ ] **Step 8: Run full suite**

Run:

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: about `88 passed` (80 baseline + 5 safety tests + 3 idempotency tests).

- [ ] **Step 9: Commit**

```bash
git add tgcli/safety.py tgcli/db.py tgcli/idempotency.py tests/tgcli/test_safety.py tests/tgcli/test_idempotency.py
git commit -m "feat(tgcli): add write safety and idempotency foundations"
```

---

## Task 2: Parser flags and write runner plumbing

**Goal:** Add the Phase 6 parser surface and shared write-runner helpers without making Telethon calls yet.

**Files:**
- Modify: `tgcli/commands/_common.py`
- Modify: `tgcli/dispatch.py`
- Modify: `tgcli/commands/messages.py`
- Create: `tests/tgcli/test_phase6_writes.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Write failing parser smoke tests**

Append these tests to `tests/tgcli/test_cli_smoke.py`:

```python
def test_phase6_write_commands_have_help():
    commands = ["send", "edit-msg", "forward", "pin-msg", "unpin-msg", "react", "mark-read"]
    for command in commands:
        result = _subprocess.run(
            [str(PYTHON), "-m", "tgcli", command, "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"command: {command} stderr: {result.stderr}"
        assert "--allow-write" in result.stdout
        assert "--dry-run" in result.stdout
        assert "--idempotency-key" in result.stdout
        assert "--fuzzy" in result.stdout


def test_phase6_write_gate_smoke_blocks_without_allow_write(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "user", "Alpha Chat", "alpha"),
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
        [str(PYTHON), "-m", "tgcli", "send", "@alpha", "hello", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 6
    payload = _json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "WRITE_DISALLOWED"
```

- [ ] **Step 2: Write failing unit tests for helper behavior**

Create `tests/tgcli/test_phase6_writes.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase6_writes.py tests/tgcli/test_cli_smoke.py::test_phase6_write_commands_have_help tests/tgcli/test_cli_smoke.py::test_phase6_write_gate_smoke_blocks_without_allow_write -q
```

Expected: FAIL because write parsers and `_read_text_arg()` do not exist.

- [ ] **Step 4: Extend write parser flags**

Replace `add_write_flags()` in `tgcli/commands/_common.py` with:

```python
def add_write_flags(parser: argparse.ArgumentParser, *, destructive: bool = False) -> None:
    """Write-side gates for Telegram-side mutations."""
    parser.add_argument("--allow-write", action="store_true",
                        help="Required for any Telegram write")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print resolved payload and exit before calling Telegram")
    parser.add_argument("--idempotency-key", default=None,
                        help="Return a cached result when this write key was already completed")
    parser.add_argument("--fuzzy", action="store_true",
                        help="Allow title-based fuzzy chat resolution for this write")
    if destructive:
        parser.add_argument("--confirm", action="store_true",
                            help="Required in addition to --allow-write for destructive ops")
```

- [ ] **Step 5: Expose dispatch request id to runners**

In `tgcli/dispatch.py`, add this line immediately after `request_id = new_request_id()` in `run_command()`:

```python
    setattr(args, "_request_id", request_id)
```

The pre-audit call remains explicit in each runner. This line only makes the existing dispatch request id available so pre- and post-audit entries can share it.

- [ ] **Step 6: Update `tgcli/commands/messages.py` imports**

Change the `_common` import to include `add_write_flags`:

```python
from tgcli.commands._common import (
    AUDIT_PATH, DB_PATH, MEDIA_DIR, ROOT, SESSION_PATH, add_output_flags,
    add_write_flags, decode_raw_json,
)
```

Add these Telethon imports after the existing `telethon.tl.types` imports:

```python
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
```

Change the safety import to:

```python
from tgcli.safety import (
    BadArgs,
    LocalRateLimited,
    OUTBOUND_WRITE_LIMITER,
    audit_pre,
    require_explicit_or_fuzzy,
    require_write_allowed,
)
```

Add this idempotency import:

```python
from tgcli.idempotency import lookup as lookup_idempotency
from tgcli.idempotency import record as record_idempotency
```

- [ ] **Step 7: Add write parser registrations**

Insert these parser blocks in `register()` after `get-msg` and before `backfill`:

```python
    snd = sub.add_parser("send", help="Send a text message")
    snd.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    snd.add_argument("text", help="Message text, or '-' to read from stdin")
    snd.add_argument("--reply-to", type=int, default=None,
                     help="Reply to this Telegram message id")
    snd.add_argument("--silent", action="store_true",
                     help="Send without notification")
    snd.add_argument("--no-webpage", action="store_true",
                     help="Disable link preview")
    add_write_flags(snd, destructive=False)
    add_output_flags(snd)
    snd.set_defaults(func=run_send)

    edit = sub.add_parser("edit-msg", help="Edit one of your own text messages")
    edit.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    edit.add_argument("message_id", type=int, help="Telegram message id to edit")
    edit.add_argument("text", help="Replacement text, or '-' to read from stdin")
    add_write_flags(edit, destructive=False)
    add_output_flags(edit)
    edit.set_defaults(func=run_edit_msg)

    fwd = sub.add_parser("forward", help="Forward one cached message")
    fwd.add_argument("from_chat", help="Source chat id, @username, or fuzzy title with --fuzzy")
    fwd.add_argument("message_id", type=int, help="Telegram message id to forward")
    fwd.add_argument("to_chat", help="Destination chat id, @username, or fuzzy title with --fuzzy")
    add_write_flags(fwd, destructive=False)
    add_output_flags(fwd)
    fwd.set_defaults(func=run_forward)

    pin = sub.add_parser("pin-msg", help="Pin a message")
    pin.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    pin.add_argument("message_id", type=int, help="Telegram message id to pin")
    add_write_flags(pin, destructive=False)
    add_output_flags(pin)
    pin.set_defaults(func=run_pin_msg)

    unpin = sub.add_parser("unpin-msg", help="Unpin a message")
    unpin.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    unpin.add_argument("message_id", type=int, help="Telegram message id to unpin")
    add_write_flags(unpin, destructive=False)
    add_output_flags(unpin)
    unpin.set_defaults(func=run_unpin_msg)

    react = sub.add_parser("react", help="Add a reaction to a message")
    react.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    react.add_argument("message_id", type=int, help="Telegram message id to react to")
    react.add_argument("emoji", help="Reaction emoji")
    add_write_flags(react, destructive=False)
    add_output_flags(react)
    react.set_defaults(func=run_react)

    mark = sub.add_parser("mark-read", help="Mark all messages in a chat as read")
    mark.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    add_write_flags(mark, destructive=False)
    add_output_flags(mark)
    mark.set_defaults(func=run_mark_read)
```

- [ ] **Step 8: Add shared write helpers**

Add this code before the `# ---------- backfill ----------` section in `tgcli/commands/messages.py`:

```python
# ---------- text writes ----------

def _read_text_arg(value: str) -> str:
    text = sys.stdin.read() if value == "-" else value
    text = text.rstrip("\n")
    if text.strip() == "":
        raise BadArgs("Text cannot be empty")
    return text


def _request_id(args) -> str:
    return getattr(args, "_request_id", "req-direct")


def _check_write_rate_limit() -> None:
    wait = OUTBOUND_WRITE_LIMITER.check()
    if wait > 0:
        raise LocalRateLimited("Local outbound write rate limit hit", wait)


def _dry_run_envelope(command: str, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "dry_run": True,
        "request_id": request_id,
        "command": command,
        "payload": payload,
    }


def _write_result(command: str, request_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "command": command,
        "request_id": request_id,
        "data": data,
        "warnings": [],
    }


def _resolve_write_chat(con, args, raw_selector: str) -> dict[str, Any]:
    require_explicit_or_fuzzy(args, raw_selector)
    chat_id, chat_title = resolve_chat_db(con, raw_selector)
    return {"chat_id": chat_id, "title": chat_title}


def _write_human(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _run_write_command(name: str, args, runner) -> int:
    return run_command(
        name,
        args,
        runner=lambda: runner(args),
        human_formatter=_write_human,
        audit_path=AUDIT_PATH,
    )
```

- [ ] **Step 9: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase6_writes.py tests/tgcli/test_cli_smoke.py::test_phase6_write_commands_have_help tests/tgcli/test_cli_smoke.py::test_phase6_write_gate_smoke_blocks_without_allow_write -q
```

Expected: `5 passed`.

- [ ] **Step 10: Run full suite**

Run:

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: about `91 passed`.

- [ ] **Step 11: Commit**

```bash
git add tgcli/commands/_common.py tgcli/dispatch.py tgcli/commands/messages.py tests/tgcli/test_phase6_writes.py tests/tgcli/test_cli_smoke.py
git commit -m "feat(tgcli): add text write command plumbing"
```

---

## Task 3: `tg send`

**Goal:** Implement `tg send <chat> <text-or-stdin>` with reply, silent, no-webpage, dry-run, idempotency, audit, and rate-limit behavior.

**Files:**
- Modify: `tgcli/commands/messages.py`
- Modify: `tests/tgcli/test_phase6_writes.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Add failing unit tests for send**

Append these tests to `tests/tgcli/test_phase6_writes.py`:

```python
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

        async def send_message(self, entity, text, *, reply_to=None, silent=False, link_preview=True):
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
```

- [ ] **Step 2: Add failing send dry-run smoke test**

Append this test to `tests/tgcli/test_cli_smoke.py`:

```python
def test_phase6_send_dry_run_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "user", "Alpha Chat", "alpha"),
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
        [
            str(PYTHON),
            "-m",
            "tgcli",
            "send",
            "@alpha",
            "hello",
            "--allow-write",
            "--dry-run",
            "--json",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    payload = _json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["payload"]["chat"]["chat_id"] == 123
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase6_writes.py::test_send_dry_run_resolves_payload_and_skips_telethon tests/tgcli/test_phase6_writes.py::test_send_calls_telethon_and_returns_new_message_id tests/tgcli/test_cli_smoke.py::test_phase6_send_dry_run_smoke -q
```

Expected: FAIL because `_send_runner()` is not implemented.

- [ ] **Step 4: Add send implementation**

Add this code under the shared write helpers in `tgcli/commands/messages.py`:

```python
async def _send_runner(args) -> dict[str, Any]:
    command = "send"
    request_id = _request_id(args)
    require_write_allowed(args)
    text = _read_text_arg(args.text)

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
            "text": text,
            "reply_to": args.reply_to,
            "silent": bool(args.silent),
            "link_preview": not bool(args.no_webpage),
            "telethon_method": "client.send_message",
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
            telethon_method="client.send_message",
            dry_run=False,
        )

        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            sent = await client.send_message(
                entity,
                text,
                reply_to=args.reply_to,
                silent=bool(args.silent),
                link_preview=not bool(args.no_webpage),
            )
            data = {
                "chat": chat,
                "message_id": int(sent.id),
                "text": text,
                "idempotent_replay": False,
            }
            record_idempotency(
                con,
                args.idempotency_key,
                command,
                request_id,
                _write_result(command, request_id, data),
            )
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_send(args) -> int:
    return _run_write_command("send", args, _send_runner)
```

- [ ] **Step 5: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase6_writes.py::test_send_dry_run_resolves_payload_and_skips_telethon tests/tgcli/test_phase6_writes.py::test_send_calls_telethon_and_returns_new_message_id tests/tgcli/test_cli_smoke.py::test_phase6_send_dry_run_smoke -q
```

Expected: `3 passed`.

- [ ] **Step 6: Run full suite**

Run:

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: about `94 passed`.

- [ ] **Step 7: Commit**

```bash
git add tgcli/commands/messages.py tests/tgcli/test_phase6_writes.py tests/tgcli/test_cli_smoke.py
git commit -m "feat(tgcli): add text send command"
```

---

## Task 4: `tg edit-msg` and `tg forward`

**Goal:** Implement editing one of the user's own messages and forwarding one cached message.

**Files:**
- Modify: `tgcli/commands/messages.py`
- Modify: `tests/tgcli/test_phase6_writes.py`

- [ ] **Step 1: Add failing unit tests for edit and forward**

Append these tests to `tests/tgcli/test_phase6_writes.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase6_writes.py::test_edit_msg_calls_telethon tests/tgcli/test_phase6_writes.py::test_forward_calls_telethon -q
```

Expected: FAIL because `_edit_msg_runner()` and `_forward_runner()` do not exist.

- [ ] **Step 3: Add edit and forward implementation**

Add this code after `run_send()`:

```python
async def _edit_msg_runner(args) -> dict[str, Any]:
    command = "edit-msg"
    request_id = _request_id(args)
    require_write_allowed(args)
    text = _read_text_arg(args.text)

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
            "message_id": int(args.message_id),
            "text": text,
            "telethon_method": "client.edit_message",
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
            telethon_method="client.edit_message",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            edited = await client.edit_message(entity, int(args.message_id), text)
            data = {
                "chat": chat,
                "message_id": int(getattr(edited, "id", args.message_id)),
                "text": text,
                "idempotent_replay": False,
            }
            record_idempotency(con, args.idempotency_key, command, request_id, _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_edit_msg(args) -> int:
    return _run_write_command("edit-msg", args, _edit_msg_runner)


async def _forward_runner(args) -> dict[str, Any]:
    command = "forward"
    request_id = _request_id(args)
    require_write_allowed(args)

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        from_chat = _resolve_write_chat(con, args, args.from_chat)
        to_chat = _resolve_write_chat(con, args, args.to_chat)
        payload = {
            "from_chat": from_chat,
            "to_chat": to_chat,
            "message_id": int(args.message_id),
            "telethon_method": "client.forward_messages",
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)
        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=to_chat["chat_id"],
            resolved_chat_title=to_chat["title"],
            payload_preview=payload,
            telethon_method="client.forward_messages",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            from_entity = await client.get_entity(from_chat["chat_id"])
            to_entity = await client.get_entity(to_chat["chat_id"])
            forwarded = await client.forward_messages(
                to_entity,
                messages=int(args.message_id),
                from_peer=from_entity,
            )
            data = {
                "from_chat": from_chat,
                "to_chat": to_chat,
                "source_message_id": int(args.message_id),
                "message_id": int(forwarded.id),
                "idempotent_replay": False,
            }
            record_idempotency(con, args.idempotency_key, command, request_id, _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_forward(args) -> int:
    return _run_write_command("forward", args, _forward_runner)
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase6_writes.py::test_edit_msg_calls_telethon tests/tgcli/test_phase6_writes.py::test_forward_calls_telethon -q
```

Expected: `2 passed`.

- [ ] **Step 5: Run full suite**

Run:

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: about `96 passed`.

- [ ] **Step 6: Commit**

```bash
git add tgcli/commands/messages.py tests/tgcli/test_phase6_writes.py
git commit -m "feat(tgcli): add edit and forward write commands"
```

---

## Task 5: `tg pin-msg` and `tg unpin-msg`

**Goal:** Implement pinning and unpinning one message in a chat.

**Files:**
- Modify: `tgcli/commands/messages.py`
- Modify: `tests/tgcli/test_phase6_writes.py`

- [ ] **Step 1: Add failing unit tests for pin and unpin**

Append these tests to `tests/tgcli/test_phase6_writes.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase6_writes.py::test_pin_msg_calls_telethon tests/tgcli/test_phase6_writes.py::test_unpin_msg_calls_telethon -q
```

Expected: FAIL because `_pin_msg_runner()` and `_unpin_msg_runner()` do not exist.

- [ ] **Step 3: Add pin/unpin implementation**

Add this helper and runners after `run_forward()`:

```python
async def _pin_state_runner(args, *, command: str, pinned: bool) -> dict[str, Any]:
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
        method = "client.pin_message" if pinned else "client.unpin_message"
        payload = {
            "chat": chat,
            "message_id": int(args.message_id),
            "pinned": pinned,
            "telethon_method": method,
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
            telethon_method=method,
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            if pinned:
                await client.pin_message(entity, int(args.message_id))
            else:
                await client.unpin_message(entity, int(args.message_id))
            data = {
                "chat": chat,
                "message_id": int(args.message_id),
                "pinned": pinned,
                "idempotent_replay": False,
            }
            record_idempotency(con, args.idempotency_key, command, request_id, _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


async def _pin_msg_runner(args) -> dict[str, Any]:
    return await _pin_state_runner(args, command="pin-msg", pinned=True)


def run_pin_msg(args) -> int:
    return _run_write_command("pin-msg", args, _pin_msg_runner)


async def _unpin_msg_runner(args) -> dict[str, Any]:
    return await _pin_state_runner(args, command="unpin-msg", pinned=False)


def run_unpin_msg(args) -> int:
    return _run_write_command("unpin-msg", args, _unpin_msg_runner)
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase6_writes.py::test_pin_msg_calls_telethon tests/tgcli/test_phase6_writes.py::test_unpin_msg_calls_telethon -q
```

Expected: `2 passed`.

- [ ] **Step 5: Run full suite**

Run:

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: about `98 passed`.

- [ ] **Step 6: Commit**

```bash
git add tgcli/commands/messages.py tests/tgcli/test_phase6_writes.py
git commit -m "feat(tgcli): add pin and unpin write commands"
```

---

## Task 6: `tg react` and `tg mark-read`

**Goal:** Implement reactions through `client(SendReactionRequest(...))` and marking all messages in one chat as read.

**Files:**
- Modify: `tgcli/commands/messages.py`
- Modify: `tests/tgcli/test_phase6_writes.py`

- [ ] **Step 1: Add failing unit tests for react and mark-read**

Append these tests to `tests/tgcli/test_phase6_writes.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase6_writes.py::test_react_uses_send_reaction_request tests/tgcli/test_phase6_writes.py::test_mark_read_calls_send_read_acknowledge -q
```

Expected: FAIL because `_react_runner()` and `_mark_read_runner()` do not exist.

- [ ] **Step 3: Add react and mark-read implementation**

Add this code after `run_unpin_msg()`:

```python
async def _react_runner(args) -> dict[str, Any]:
    command = "react"
    request_id = _request_id(args)
    require_write_allowed(args)
    if str(args.emoji).strip() == "":
        raise BadArgs("Emoji cannot be empty")
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
            "message_id": int(args.message_id),
            "emoji": args.emoji,
            "telethon_method": "SendReactionRequest",
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
            telethon_method="SendReactionRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            await client(
                SendReactionRequest(
                    peer=entity,
                    msg_id=int(args.message_id),
                    reaction=[ReactionEmoji(emoticon=args.emoji)],
                )
            )
            data = {
                "chat": chat,
                "message_id": int(args.message_id),
                "emoji": args.emoji,
                "idempotent_replay": False,
            }
            record_idempotency(con, args.idempotency_key, command, request_id, _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_react(args) -> int:
    return _run_write_command("react", args, _react_runner)


async def _mark_read_runner(args) -> dict[str, Any]:
    command = "mark-read"
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
            "telethon_method": "client.send_read_acknowledge",
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
            telethon_method="client.send_read_acknowledge",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            await client.send_read_acknowledge(entity)
            data = {
                "chat": chat,
                "marked_read": True,
                "idempotent_replay": False,
            }
            record_idempotency(con, args.idempotency_key, command, request_id, _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_mark_read(args) -> int:
    return _run_write_command("mark-read", args, _mark_read_runner)
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase6_writes.py::test_react_uses_send_reaction_request tests/tgcli/test_phase6_writes.py::test_mark_read_calls_send_read_acknowledge -q
```

Expected: `2 passed`.

- [ ] **Step 5: Run full suite**

Run:

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: about `100 passed`.

- [ ] **Step 6: Commit**

```bash
git add tgcli/commands/messages.py tests/tgcli/test_phase6_writes.py
git commit -m "feat(tgcli): add react and mark-read commands"
```

---

## Task 7: Idempotency, fuzzy-gate, audit, and rate-limit integration tests

**Goal:** Prove the shared safety behavior applies to write commands, not just helper functions.

**Files:**
- Modify: `tests/tgcli/test_phase6_writes.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Add failing integration unit tests**

Append these tests to `tests/tgcli/test_phase6_writes.py`:

```python
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

        async def send_message(self, entity, text, *, reply_to=None, silent=False, link_preview=True):
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
    """Coverage gap fix per codex review: a write-disabled caller must NOT receive a cache replay.

    First call records an idempotency entry under --allow-write; second call drops the flag and
    presents the same key. Expected: WriteDisallowed, NOT a silent cached success.
    """
    from tgcli.safety import WriteDisallowed

    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    class FakeMessage:
        id = 999

    class FakeClient:
        async def start(self): pass
        async def get_entity(self, chat_id): return f"entity-{chat_id}"
        async def send_message(self, entity, text, **kw): return FakeMessage()
        async def disconnect(self): pass

    monkeypatch.setattr(messages, "make_client", lambda session_path: FakeClient())

    # First call: writes are allowed, cache populated.
    allowed = _args(chat="@alpha", text="hello", reply_to=None, silent=False,
                    no_webpage=False, idempotency_key="shared-key")
    allowed.allow_write = True
    asyncio.run(messages._send_runner(allowed))

    # Second call: same key, but allow_write=False. Must reject before cache lookup.
    blocked = _args(chat="@alpha", text="hello", reply_to=None, silent=False,
                    no_webpage=False, idempotency_key="shared-key")
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

        async def send_message(self, entity, text, *, reply_to=None, silent=False, link_preview=True):
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
```

- [ ] **Step 2: Add fuzzy-gate smoke test**

Append this test to `tests/tgcli/test_cli_smoke.py`:

```python
def test_phase6_fuzzy_write_gate_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute("INSERT INTO tg_chats(chat_id, type, title) VALUES (?, ?, ?)", (123, "user", "Alpha Chat"))
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
        [
            str(PYTHON),
            "-m",
            "tgcli",
            "send",
            "Alpha",
            "hello",
            "--allow-write",
            "--dry-run",
            "--json",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 2
    payload = _json.loads(result.stdout)
    assert payload["error"]["code"] == "BAD_ARGS"
    assert "pass --fuzzy" in payload["error"]["message"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase6_writes.py::test_fuzzy_write_selector_requires_fuzzy tests/tgcli/test_phase6_writes.py::test_idempotency_key_skips_second_telethon_call tests/tgcli/test_phase6_writes.py::test_rate_limit_blocks_before_telethon tests/tgcli/test_phase6_writes.py::test_pre_audit_and_post_audit_share_request_id tests/tgcli/test_cli_smoke.py::test_phase6_fuzzy_write_gate_smoke -q
```

Expected: FAIL if any write runner bypasses fuzzy gate, idempotency lookup, rate limiter, or shared request-id audit.

- [ ] **Step 4: Fix any integration gaps with these exact rules**

Every write runner must follow the concrete order already shown in the command implementations from Tasks 3-6:

1. Set `command` to the exact CLI command name and `request_id = _request_id(args)`.
2. Call `require_write_allowed(args)`.
3. For `send` and `edit-msg`, call `_read_text_arg(args.text)` before opening Telethon.
4. Open `con = connect(DB_PATH)` and close it in `finally`.
5. Call `lookup_idempotency(con, args.idempotency_key, command)` and return `dict(replay["data"])` with `idempotent_replay = True` when a replay exists.
6. Resolve every chat selector with `_resolve_write_chat(con, args, raw_selector)`.
7. Build the same concrete payload fields used by the command:
   `send` uses `chat`, `text`, `reply_to`, `silent`, `link_preview`, `telethon_method`;
   `edit-msg` uses `chat`, `message_id`, `text`, `telethon_method`;
   `forward` uses `from_chat`, `to_chat`, `message_id`, `telethon_method`;
   `pin-msg` and `unpin-msg` use `chat`, `message_id`, `pinned`, `telethon_method`;
   `react` uses `chat`, `message_id`, `emoji`, `telethon_method`;
   `mark-read` uses `chat`, `telethon_method`.
8. Return `_dry_run_envelope(command, request_id, payload)` when `args.dry_run` is true.
9. Call `_check_write_rate_limit()` before `audit_pre()`.
10. Call `audit_pre(AUDIT_PATH, cmd=command, request_id=request_id, resolved_chat_id=..., resolved_chat_title=..., payload_preview=payload, telethon_method=..., dry_run=False)`.
11. Create `client = make_client(SESSION_PATH)`, `await client.start()`, run the command-specific Telethon call, and `await client.disconnect()` in `finally`.
12. Build the command result with `idempotent_replay = False` and persist it with `record_idempotency(con, args.idempotency_key, command, request_id, _write_result(command, request_id, data))`.

- [ ] **Step 5: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase6_writes.py::test_fuzzy_write_selector_requires_fuzzy tests/tgcli/test_phase6_writes.py::test_idempotency_key_skips_second_telethon_call tests/tgcli/test_phase6_writes.py::test_rate_limit_blocks_before_telethon tests/tgcli/test_phase6_writes.py::test_pre_audit_and_post_audit_share_request_id tests/tgcli/test_cli_smoke.py::test_phase6_fuzzy_write_gate_smoke -q
```

Expected: `5 passed`.

- [ ] **Step 6: Run full suite**

Run:

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: about `106 passed` (one extra for the new write-gate-blocks-cache-hit test added during codex review).

- [ ] **Step 7: Commit**

```bash
git add tgcli/commands/messages.py tests/tgcli/test_phase6_writes.py tests/tgcli/test_cli_smoke.py
git commit -m "test(tgcli): cover write safety integration"
```

---

## Task 8: Final smoke coverage and command count stabilization

**Goal:** Add subprocess coverage for dry-run paths that can run without Telegram and lock in final test count expectations.

**Files:**
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Add remaining dry-run smoke tests**

Append this test to `tests/tgcli/test_cli_smoke.py`:

```python
def test_phase6_other_write_dry_run_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "user", "Alpha Chat", "alpha"),
    )
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (456, "user", "Beta Chat", "beta"),
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
        [str(PYTHON), "-m", "tgcli", "edit-msg", "@alpha", "1", "updated", "--allow-write", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "forward", "@alpha", "1", "@beta", "--allow-write", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "pin-msg", "@alpha", "1", "--allow-write", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "unpin-msg", "@alpha", "1", "--allow-write", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "react", "@alpha", "1", "👍", "--allow-write", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "mark-read", "@alpha", "--allow-write", "--dry-run", "--json"],
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

- [ ] **Step 2: Run targeted smoke tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_cli_smoke.py::test_phase6_write_commands_have_help tests/tgcli/test_cli_smoke.py::test_phase6_write_gate_smoke_blocks_without_allow_write tests/tgcli/test_cli_smoke.py::test_phase6_send_dry_run_smoke tests/tgcli/test_cli_smoke.py::test_phase6_fuzzy_write_gate_smoke tests/tgcli/test_cli_smoke.py::test_phase6_other_write_dry_run_smoke -q
```

Expected: `5 passed`.

- [ ] **Step 3: Run full suite**

Run:

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: about `106 passed` if the lower end of the Phase 6 unit test target was implemented, and no less than `105 passed`.

- [ ] **Step 4: Commit**

```bash
git add tests/tgcli/test_cli_smoke.py
git commit -m "test(tgcli): add write command smoke coverage"
```

---

## Final Verification

Run:

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: about `105-110 passed`.

Run these local DB smoke commands with a seeded `TG_DB_PATH`:

```bash
TG_DB_PATH=/path/to/seeded.sqlite TG_AUDIT_PATH=/tmp/tg-audit.log ./tg send "@alpha" "hello" --allow-write --dry-run --json | python -m json.tool
TG_DB_PATH=/path/to/seeded.sqlite TG_AUDIT_PATH=/tmp/tg-audit.log ./tg edit-msg "@alpha" 1 "updated" --allow-write --dry-run --json | python -m json.tool
TG_DB_PATH=/path/to/seeded.sqlite TG_AUDIT_PATH=/tmp/tg-audit.log ./tg forward "@alpha" 1 "@beta" --allow-write --dry-run --json | python -m json.tool
TG_DB_PATH=/path/to/seeded.sqlite TG_AUDIT_PATH=/tmp/tg-audit.log ./tg pin-msg "@alpha" 1 --allow-write --dry-run --json | python -m json.tool
TG_DB_PATH=/path/to/seeded.sqlite TG_AUDIT_PATH=/tmp/tg-audit.log ./tg unpin-msg "@alpha" 1 --allow-write --dry-run --json | python -m json.tool
TG_DB_PATH=/path/to/seeded.sqlite TG_AUDIT_PATH=/tmp/tg-audit.log ./tg react "@alpha" 1 "👍" --allow-write --dry-run --json | python -m json.tool
TG_DB_PATH=/path/to/seeded.sqlite TG_AUDIT_PATH=/tmp/tg-audit.log ./tg mark-read "@alpha" --allow-write --dry-run --json | python -m json.tool
```

Expected:
- Every dry-run command exits 0, returns `data.dry_run == true`, includes the resolved chat payload, and does not construct a Telethon client.
- Fuzzy title selectors without `--fuzzy` exit 2 with `BAD_ARGS`.
- Missing `--allow-write` exits 6 with `WRITE_DISALLOWED`.
- Unit tests, not subprocess tests, verify Telethon call shapes.

Manual live verification, skipped in automated tests because the sandbox cannot reach Telegram:

```bash
./tg send "@alpha" "manual phase 6 smoke" --allow-write --idempotency-key manual-send-1 --json | python -m json.tool
./tg send "@alpha" "manual phase 6 smoke" --allow-write --idempotency-key manual-send-1 --json | python -m json.tool
./tg edit-msg "@alpha" <own-message-id> "manual phase 6 edited" --allow-write --json | python -m json.tool
./tg react "@alpha" <message-id> "👍" --allow-write --json | python -m json.tool
./tg mark-read "@alpha" --allow-write --json | python -m json.tool
```

Expected:
- First `send` returns a real `data.message_id`.
- Second `send` with the same idempotency key returns the cached result and does not send another Telegram message.
- `edit-msg` works only for a message owned by the authenticated user; Telegram-side permission failures are surfaced through the existing dispatch exception envelope.
- `react` builds `SendReactionRequest(peer=..., msg_id=..., reaction=[ReactionEmoji(...)])`.
- `mark-read` calls `client.send_read_acknowledge(entity)`.

---

## Exact Commit Sequence

```bash
git commit -m "feat(tgcli): add write safety and idempotency foundations"
git commit -m "feat(tgcli): add text write command plumbing"
git commit -m "feat(tgcli): add text send command"
git commit -m "feat(tgcli): add edit and forward write commands"
git commit -m "feat(tgcli): add pin and unpin write commands"
git commit -m "feat(tgcli): add react and mark-read commands"
git commit -m "test(tgcli): cover write safety integration"
git commit -m "test(tgcli): add write command smoke coverage"
```

---

## Self-Review Checklist

Before declaring Phase 6 complete:

1. **Scope** - CLI exposes exactly these write commands: `send`, `edit-msg`, `forward`, `pin-msg`, `unpin-msg`, `react`, `mark-read`.
2. **Naming** - Commands are flat top-level commands; no grouped `messages` subparser is introduced.
3. **Write flags** - Every Phase 6 parser calls `add_write_flags(parser, destructive=False)`.
4. **Non-destructive** - No Phase 6 parser adds or requires `--confirm`.
5. **Write gate** - Every runner calls `require_write_allowed(args)` before dry-run and before Telethon.
6. **Stdin** - `send` and `edit-msg` support literal `-`, read `sys.stdin.read()`, strip trailing newlines, and reject empty text after stripping.
7. **Fuzzy gate** - Every chat selector in every write runner passes through `require_explicit_or_fuzzy(args, raw_selector)` before `resolve_chat_db()`.
8. **Dry-run** - Every runner builds a resolved payload, returns it with `dry_run: true`, and does not call Telethon.
9. **Idempotency** - Every runner accepts `--idempotency-key`, checks `tg_idempotency` before Telethon, and records successful non-dry-run results.
10. **Pre-audit** - Every non-dry-run Telethon write calls `audit_pre()` explicitly before the Telethon call.
11. **Post-audit** - Existing post-audit through `audit_write()` still records success/failure.
12. **Request id** - Pre-audit and post-audit entries share the same `request_id`.
13. **Rate limit** - Every non-dry-run Telethon write checks the process-global outbound limiter and maps blocks to exit 8 through `LocalRateLimited`.
14. **Telethon calls** - `send` uses `client.send_message`, `edit-msg` uses `client.edit_message`, `forward` uses `client.forward_messages`, pin/unpin use `client.pin_message`/`client.unpin_message`, `react` uses `client(SendReactionRequest(...))`, and `mark-read` uses `client.send_read_acknowledge`.
15. **Tests** - Telethon-calling paths are unit tests with fake async clients; subprocess tests cover only parser, bad-args, write-gate, fuzzy-gate, and dry-run paths.
16. **Test count** - Full suite finishes around `105-110 passed`, equal to Phase 4 `80 passed` plus Phase 6 unit and smoke coverage.

---

## Out of Scope

- Destructive Telegram commands: message delete, chat leave, contact remove/block, and session termination.
- Media upload or download changes.
- Chat lifecycle commands such as join, mute, archive, title changes, or contact add.
- External tool-server wrappers.
- Business integrations or automated response behavior.
