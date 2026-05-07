# Phase 3 - Resolver + `--min-msgs` Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable DB-only chat resolver, route `tg show` through it, classify resolver errors in the dispatch envelope, and add `--min-msgs` filters to `stats` and `contacts`.

**Architecture:**
- Add two pure stdlib modules: `tgcli/text.py` for accent-insensitive text normalization and `tgcli/resolve.py` for DB-only chat lookup. `resolve_chat_db(con, raw)` returns only `(chat_id, title)` because `_show_runner` only needs those values before querying `tg_messages`.
- Keep exception-to-envelope behavior centralized in `tgcli/dispatch.py`. Resolver `NotFound` maps to `NOT_FOUND` exit 4, and resolver `Ambiguous` maps to `BAD_ARGS` exit 2 with `candidates` in the JSON error object.
- Add `--min-msgs` at the command SQL boundary: `stats` applies it as a `HAVING` clause on the top-chat message count, and `contacts` applies it only when `--chatted` is set.

**Tech Stack:** Python 3.12 stdlib (`sqlite3`, `unicodedata`, `argparse`, `json`, `subprocess`, `pathlib`), existing pytest. **No new third-party deps.**

**Backwards compatibility:** Current full suite is `55 passed`. Phase 3 adds 9 tests and should finish at `64 passed`. Existing outcomes must remain: `./tg show Polymarket --json` succeeds, `./tg show --json` exits 2, and `./tg show --chat-id 999999999999 --json` exits 4.

---

## Existing Code Map

| Area | Current line references | Phase 3 use |
|---|---:|---|
| Master Phase 3 sketch | `docs/superpowers/plans/2026-05-06-tg-agent-cli.md:1132-1296` | Source scope for resolver and `--min-msgs`, with corrected paths from `telegram_test/tgcli/...` to `tgcli/...` |
| Phase 2 plan style | `docs/superpowers/plans/2026-05-06-tg-agent-cli-phase-2.md:1-18`, `20-40`, `2012-2035` | Header, file table, task format, checklist, out-of-scope format |
| Accent stripping | `tgcli/commands/messages.py:60-64` | Move to `tgcli/text.py` |
| Inline `show` resolution | `tgcli/commands/messages.py:194-247`, especially `203-221` | Replace inline lookup with `resolve_chat_db` |
| Stats top-chat SQL | `tgcli/commands/stats.py:15-18`, `21-40` | Add parser flag and `HAVING COUNT(*) >= ?` |
| Contacts chatted SQL | `tgcli/commands/contacts.py:16-24`, `33-53` | Add parser flag and filter only when `--chatted` is set |
| Dispatch classifier | `tgcli/dispatch.py:53-79`, failure envelope at `102-117` | Add resolver exceptions |
| `BadArgs` definition | `tgcli/safety.py:16-18` | Keep missing-argument errors mapped to exit 2 |
| Exit-code values | `tgcli/output.py:21-32` | Preserve `BAD_ARGS=2` and `NOT_FOUND=4` |
| Dispatch test style | `tests/tgcli/test_dispatch.py:17-29`, `66-83` | Reuse `make_args()` and `_read_stdout()` style |
| CLI smoke style | `tests/tgcli/test_cli_smoke.py:30-49`, `52-76` | Reuse subprocess + temp DB style |

Note: `tests/tgcli/test_messages.py` and `tests/tgcli/test_stats.py` were requested as source files, but they do not exist in the current tree. This plan creates `tests/tgcli/test_messages.py` and uses `tests/tgcli/test_min_msgs.py` plus `tests/tgcli/test_cli_smoke.py` for stats and contacts coverage.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `tgcli/text.py` | **create** | Shared `strip_accents()` helper for case- and accent-insensitive matching |
| `tgcli/resolve.py` | **create** | DB-only `resolve_chat_db(con, raw) -> tuple[int, str]`, plus `NotFound` and `Ambiguous` |
| `tgcli/dispatch.py` | **modify** | Map `NotFound` to `NOT_FOUND`; map `Ambiguous` to `BAD_ARGS` with `candidates` extra field |
| `tgcli/commands/messages.py` | **modify** | Import resolver, remove local `_strip_accents`, and delegate `_show_runner` chat lookup |
| `tgcli/commands/stats.py` | **modify** | Add `--min-msgs`; apply to top-chat SQL as `HAVING COUNT(*) >= ?` |
| `tgcli/commands/contacts.py` | **modify** | Add `--min-msgs`; apply only when `--chatted` is set |
| `tests/tgcli/test_resolve.py` | **create** | Five resolver tests from master plan: int, username, fuzzy, ambiguous, not found |
| `tests/tgcli/test_dispatch.py` | **modify** | Verify resolver exceptions produce correct envelopes and serialized candidates |
| `tests/tgcli/test_messages.py` | **create** | Unit test proving `_show_runner` delegates pattern resolution to `resolve_chat_db` |
| `tests/tgcli/test_min_msgs.py` | **create** | Pure unit coverage for stats and contacts `--min-msgs` filtering |
| `tests/tgcli/test_cli_smoke.py` | **modify** | Subprocess smoke test proving both `--min-msgs` flags are accepted and exit 0 |

---

## Design Decisions

1. `_strip_accents` moves to `tgcli/text.py` as public `strip_accents()`. Duplicating it in `tgcli/resolve.py` would create two normalization rules that can drift; extracting it keeps title matching consistent across `messages` and the resolver without coupling resolver code to Telethon-heavy command helpers.
2. `resolve_chat_db()` returns `tuple[int, str]`. `_show_runner` only uses `chat_id` to query `tg_messages` and `title` to build the output envelope, so widening the return type or doing a second DB lookup is unnecessary.
3. `Ambiguous.candidates` is `list[tuple[int, str]]`. `json.dumps()` serializes tuples as JSON arrays, so the dispatch envelope will expose `candidates` as `[[chat_id, title], ...]`, which is clean for callers and explicitly tested.
4. Async `resolve_chat()` that hits Telethon is deferred. Phase 3 resolver is SQLite-only and safe to import in unit tests.

---

## Task 1: Shared text normalization and DB chat resolver

**Goal:** Create a pure DB resolver with the required three lookup strategies: integer `chat_id`, `@username`, and fuzzy title substring match.

**Files:**
- Create: `tgcli/text.py`
- Create: `tgcli/resolve.py`
- Create: `tests/tgcli/test_resolve.py`

- [ ] **Step 1: Write the failing resolver tests**

```python
# tests/tgcli/test_resolve.py
import sqlite3

import pytest

from tgcli.resolve import Ambiguous, NotFound, resolve_chat_db


def setup_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute(
        """
        CREATE TABLE tg_chats (
            chat_id INTEGER PRIMARY KEY,
            type TEXT,
            title TEXT,
            username TEXT,
            phone TEXT,
            first_name TEXT,
            last_name TEXT,
            is_bot INTEGER,
            last_seen_at TEXT,
            raw_json TEXT
        )
        """
    )
    con.executemany(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        [
            (1, "user", "Hamïd Ijadi", "HRALEyn"),  # diacritic exercises strip_accents
            (2, "user", "Hamburger Verein", None),
            (3, "user", "Joel", None),
        ],
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
    # 'ijadi' must match 'Hamïd Ijadi' through accent stripping AND case folding.
    assert resolve_chat_db(con, "ijadi") == (1, "Hamïd Ijadi")


def test_resolve_ambiguous_raises():
    con = setup_db()
    with pytest.raises(Ambiguous) as exc:
        resolve_chat_db(con, "Ham")
    assert exc.value.raw == "Ham"
    assert exc.value.candidates == [(1, "Hamïd Ijadi"), (2, "Hamburger Verein")]


def test_resolve_not_found_raises():
    con = setup_db()
    with pytest.raises(NotFound):
        resolve_chat_db(con, "nonexistent")


def test_resolve_malformed_int_falls_through_to_fuzzy():
    """'--123' must not be mistaken for an integer chat_id (would crash with ValueError)."""
    con = setup_db()
    # No title contains '--123', so we expect NotFound from the fuzzy path,
    # NOT a leaked ValueError.
    with pytest.raises(NotFound):
        resolve_chat_db(con, "--123")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/tgcli/test_resolve.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'tgcli.resolve'`.

- [ ] **Step 3: Implement `tgcli/text.py`**

```python
"""Shared text-normalization helpers."""
from __future__ import annotations

import unicodedata


def strip_accents(value: str | None) -> str:
    """Return lowercase text with combining accent marks removed."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(
        char for char in decomposed
        if unicodedata.category(char) != "Mn"
    ).lower()
```

- [ ] **Step 4: Implement `tgcli/resolve.py`**

```python
"""DB-only chat resolution helpers.

Resolution order:
1. Integer chat_id.
2. @username against cached tg_chats.username.
3. Case- and accent-insensitive title substring match.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from tgcli.text import strip_accents


class NotFound(Exception):
    """Raised when a chat selector has no match in the local DB."""


class Ambiguous(Exception):
    """Raised when fuzzy title resolution matches more than one chat."""

    def __init__(self, raw: str, candidates: Sequence[tuple[int, str]]):
        self.raw = raw
        self.candidates = list(candidates)
        super().__init__(f"{raw!r} is ambiguous: {len(self.candidates)} matches")


def _title_or_id(chat_id: int, title: str | None) -> str:
    return title or f"chat_{chat_id}"


def _try_int(value: str) -> int | None:
    """Return int if value parses as a single signed integer, else None.

    Uses int() directly so that malformed inputs like "--123" or "12-3" return
    None rather than passing the looser `lstrip("-").isdigit()` check and then
    raising ValueError.
    """
    try:
        return int(value)
    except ValueError:
        return None


def resolve_chat_db(con: sqlite3.Connection, raw: str) -> tuple[int, str]:
    """Resolve a user-supplied chat selector using only the local SQLite DB."""
    value = str(raw).strip()
    if not value:
        raise NotFound("empty chat selector")

    chat_id_int = _try_int(value)
    if chat_id_int is not None:
        row = con.execute(
            "SELECT chat_id, title FROM tg_chats WHERE chat_id = ?",
            (chat_id_int,),
        ).fetchone()
        if row:
            return int(row[0]), _title_or_id(int(row[0]), row[1])
        raise NotFound(f"chat_id {value} not in DB")

    if value.startswith("@"):
        username = value[1:]
        if not username:
            raise NotFound("empty username")
        row = con.execute(
            "SELECT chat_id, title FROM tg_chats WHERE LOWER(username) = LOWER(?)",
            (username,),
        ).fetchone()
        if row:
            return int(row[0]), _title_or_id(int(row[0]), row[1])
        raise NotFound(f"username {value} not in DB")

    needle = strip_accents(value)
    rows = con.execute(
        "SELECT chat_id, title FROM tg_chats ORDER BY chat_id"
    ).fetchall()
    matches = [
        (int(chat_id), _title_or_id(int(chat_id), title))
        for chat_id, title in rows
        if needle in strip_accents(title)
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise NotFound(f"no chat title contains {value!r}")
    raise Ambiguous(value, matches)
```

- [ ] **Step 5: Run resolver tests**

Expected: `6 passed` (5 master-plan cases + the malformed-int regression test).

Run: `.venv/bin/pytest tests/tgcli/test_resolve.py -q`

Expected: `6 passed`.

- [ ] **Step 6: Run full suite**

Run: `.venv/bin/pytest tests/tgcli -q`

Expected: `61 passed` (55 baseline + 6 resolver).

- [ ] **Step 7: Commit**

```bash
git add tgcli/text.py tgcli/resolve.py tests/tgcli/test_resolve.py
git commit -m "feat(tgcli): add DB chat resolver"
```

---

## Task 2: Dispatch classifier for resolver exceptions

**Goal:** Ensure resolver errors leave the CLI through the existing JSON/human envelope path with stable exit codes and machine-readable candidate data.

**Files:**
- Modify: `tgcli/dispatch.py`
- Modify: `tests/tgcli/test_dispatch.py`

- [ ] **Step 1: Add a failing dispatch test for resolver exceptions**

Replace `tests/tgcli/test_dispatch.py` with:

```python
# tests/tgcli/test_dispatch.py
import argparse
import asyncio
import json
import re
from pathlib import Path

import pytest

from tgcli.client import MissingCredentials, SessionLocked
from tgcli.db import DatabaseMissing
from tgcli.dispatch import run_command
from tgcli.output import ExitCode
from tgcli.resolve import Ambiguous, NotFound
from tgcli.safety import BadArgs, LocalRateLimited, NeedsConfirm, WriteDisallowed


def make_args(**kw):
    ns = argparse.Namespace()
    ns.json = kw.get("json", True)
    ns.human = kw.get("human", False)
    ns.allow_write = kw.get("allow_write", False)
    ns.confirm = kw.get("confirm", False)
    ns.dry_run = kw.get("dry_run", False)
    return ns


def _read_stdout(capsys) -> dict:
    out = capsys.readouterr().out.strip()
    return json.loads(out)


def test_run_command_success_emits_envelope(capsys, tmp_path):
    args = make_args()
    code = run_command(
        "stats", args,
        runner=lambda: {"chats": 4},
        audit_path=tmp_path / "audit.log",
    )
    assert code == 0
    env = _read_stdout(capsys)
    assert env["ok"] is True
    assert env["command"] == "stats"
    assert env["data"] == {"chats": 4}
    assert re.fullmatch(r"req-[0-9a-f]{8}", env["request_id"])


def test_run_command_writes_audit_entry(tmp_path, capsys):
    log = tmp_path / "audit.log"
    run_command("stats", make_args(), runner=lambda: {"chats": 1}, audit_path=log)
    line = log.read_text().splitlines()[0]
    entry = json.loads(line)
    assert entry["cmd"] == "stats"
    assert entry["result"] == "ok"
    assert entry["request_id"].startswith("req-")


def test_run_command_async_runner(capsys, tmp_path):
    async def runner():
        await asyncio.sleep(0)
        return {"value": 42}

    code = run_command("x", make_args(), runner=runner, audit_path=tmp_path / "audit.log")
    assert code == 0
    assert _read_stdout(capsys)["data"] == {"value": 42}


@pytest.mark.parametrize("exc, expected_code", [
    (BadArgs("missing pattern"), ExitCode.BAD_ARGS),
    (DatabaseMissing("no DB"), ExitCode.NOT_FOUND),
    (MissingCredentials("no creds"), ExitCode.NOT_AUTHED),
    (SessionLocked("locked"), ExitCode.GENERIC),
    (WriteDisallowed("nope"), ExitCode.WRITE_DISALLOWED),
    (NeedsConfirm("confirm"), ExitCode.NEEDS_CONFIRM),
    (LocalRateLimited("slow", 1.5), ExitCode.LOCAL_RATE_LIMIT),
])
def test_run_command_maps_known_exceptions(exc, expected_code, capsys, tmp_path):
    def boom():
        raise exc

    code = run_command("x", make_args(), runner=boom, audit_path=tmp_path / "audit.log")
    assert code == expected_code
    env = _read_stdout(capsys)
    assert env["ok"] is False
    assert env["error"]["code"] == expected_code.name


def test_run_command_maps_resolver_exceptions(capsys, tmp_path):
    def missing():
        raise NotFound("no chat title contains 'zzz'")

    code = run_command("show", make_args(), runner=missing, audit_path=tmp_path / "audit.log")
    env = _read_stdout(capsys)
    assert code == ExitCode.NOT_FOUND
    assert env["ok"] is False
    assert env["error"]["code"] == "NOT_FOUND"
    assert env["error"]["message"] == "no chat title contains 'zzz'"

    def ambiguous():
        raise Ambiguous("Al", [(1, "Alpha"), (2, "Alpine")])

    code = run_command("show", make_args(), runner=ambiguous, audit_path=tmp_path / "audit.log")
    env = _read_stdout(capsys)
    assert code == ExitCode.BAD_ARGS
    assert env["ok"] is False
    assert env["error"]["code"] == "BAD_ARGS"
    assert env["error"]["candidates"] == [[1, "Alpha"], [2, "Alpine"]]


def test_run_command_unknown_exception_becomes_generic(capsys, tmp_path):
    def boom():
        raise RuntimeError("kaboom")

    code = run_command("x", make_args(), runner=boom, audit_path=tmp_path / "audit.log")
    assert code == ExitCode.GENERIC
    env = _read_stdout(capsys)
    assert env["error"]["code"] == "GENERIC"
    assert "kaboom" in env["error"]["message"]


def test_run_command_failure_writes_audit_entry(tmp_path, capsys):
    log = tmp_path / "audit.log"

    def boom():
        raise DatabaseMissing("no DB")

    run_command("stats", make_args(), runner=lambda: boom(), audit_path=log)
    entry = json.loads(log.read_text().splitlines()[0])
    assert entry["result"] == "fail"
    assert entry["error_code"] == "NOT_FOUND"


def test_run_command_local_rate_limited_includes_retry_after(capsys, tmp_path):
    def boom():
        raise LocalRateLimited("slow down", 2.5)

    run_command("x", make_args(), runner=boom, audit_path=tmp_path / "audit.log")
    env = _read_stdout(capsys)
    assert env["error"]["retry_after_seconds"] == 2.5


def test_run_command_human_mode_uses_formatter(capsys, tmp_path):
    captured: list = []

    def fmt(data):
        captured.append(data)

    run_command(
        "stats",
        make_args(json=False, human=True),
        runner=lambda: {"chats": 7},
        human_formatter=fmt,
        audit_path=tmp_path / "audit.log",
    )
    assert captured == [{"chats": 7}]


def test_run_command_telethon_floodwait_maps_to_flood_wait(capsys, tmp_path):
    from telethon.errors import FloodWaitError

    def boom():
        raise FloodWaitError(request=None, capture=30)

    code = run_command("x", make_args(), runner=boom, audit_path=tmp_path / "audit.log")
    assert code == ExitCode.FLOOD_WAIT
    env = _read_stdout(capsys)
    assert env["error"]["code"] == "FLOOD_WAIT"
    assert env["error"]["retry_after_seconds"] == 30
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/tgcli/test_dispatch.py::test_run_command_maps_resolver_exceptions -q`

Expected: FAIL because `NotFound` is classified as `GENERIC` and `Ambiguous` has no `candidates` extra field.

- [ ] **Step 3: Implement dispatch classifier changes**

Replace `tgcli/dispatch.py` with:

```python
"""Single chokepoint that wraps every command's logic.

Responsibilities:
- Generate a request ID for log/envelope correlation.
- Run the runner, which may be sync or async.
- Map known exceptions to fail envelopes with stable exit codes.
- Route output through `output.emit()` honoring --json, --human, and TTY auto.
- Append one entry to the audit log per invocation.
"""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any, Awaitable, Callable

from telethon.errors import FloodWaitError

from tgcli.client import MissingCredentials, SessionLocked
from tgcli.db import DatabaseMissing
from tgcli.output import ExitCode, emit, fail, is_tty_stdout, new_request_id, success
from tgcli.resolve import Ambiguous, NotFound
from tgcli.safety import (
    BadArgs,
    LocalRateLimited,
    NeedsConfirm,
    WriteDisallowed,
    audit_write,
)

Runner = Callable[[], Any] | Callable[[], Awaitable[Any]]


def _resolve_json_mode(args) -> bool:
    """Honor --json / --human, else auto-detect from TTY."""
    if getattr(args, "json", False):
        return True
    if getattr(args, "human", False):
        return False
    return not is_tty_stdout()


def _args_repr(args) -> dict[str, Any]:
    """Best-effort dict copy of argparse Namespace for the audit log."""
    return {k: v for k, v in vars(args).items() if not k.startswith("_") and k != "func"}


def _classify_exception(exc: BaseException) -> tuple[ExitCode, str, dict[str, Any]]:
    """Map a known exception to (exit_code, message, extra-fields-for-envelope)."""
    if isinstance(exc, Ambiguous):
        return ExitCode.BAD_ARGS, str(exc), {"candidates": exc.candidates}
    if isinstance(exc, NotFound):
        return ExitCode.NOT_FOUND, str(exc), {}
    if isinstance(exc, BadArgs):
        return ExitCode.BAD_ARGS, str(exc), {}
    if isinstance(exc, DatabaseMissing):
        return ExitCode.NOT_FOUND, str(exc), {}
    if isinstance(exc, MissingCredentials):
        return ExitCode.NOT_AUTHED, str(exc), {}
    if isinstance(exc, SessionLocked):
        return ExitCode.GENERIC, str(exc), {}
    if isinstance(exc, WriteDisallowed):
        return ExitCode.WRITE_DISALLOWED, str(exc), {}
    if isinstance(exc, NeedsConfirm):
        return ExitCode.NEEDS_CONFIRM, str(exc), {}
    if isinstance(exc, LocalRateLimited):
        return (
            ExitCode.LOCAL_RATE_LIMIT,
            str(exc),
            {"retry_after_seconds": exc.retry_after_seconds},
        )
    if isinstance(exc, FloodWaitError):
        return (
            ExitCode.FLOOD_WAIT,
            f"Telegram FloodWait: wait {exc.seconds}s",
            {"retry_after_seconds": exc.seconds},
        )
    return ExitCode.GENERIC, f"{type(exc).__name__}: {exc}", {}


def _invoke(runner: Runner) -> Any:
    """Call sync or async runner, returning its data."""
    result = runner()
    if inspect.iscoroutine(result):
        return asyncio.run(result)
    return result


def run_command(
    name: str,
    args,
    runner: Runner,
    *,
    human_formatter: Callable[[Any], None] | None = None,
    audit_path: Path,
) -> int:
    """Run a command and return its process exit code."""
    request_id = new_request_id()
    json_mode = _resolve_json_mode(args)

    try:
        data = _invoke(runner)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        code, message, extra = _classify_exception(exc)
        envelope = fail(name, code, message, request_id=request_id, **extra)
        audit_write(
            audit_path,
            cmd=name,
            request_id=request_id,
            args_repr=_args_repr(args),
            result="fail",
            error_code=code.name,
        )
        return emit(envelope, json_mode=json_mode)

    envelope = success(name, data, request_id=request_id)
    audit_write(
        audit_path,
        cmd=name,
        request_id=request_id,
        args_repr=_args_repr(args),
        result="ok",
    )
    return emit(envelope, json_mode=json_mode, human_formatter=human_formatter)
```

- [ ] **Step 4: Run dispatch tests**

Run: `.venv/bin/pytest tests/tgcli/test_dispatch.py -q`

Expected: `12 passed`.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/pytest tests/tgcli -q`

Expected: `62 passed`.

- [ ] **Step 6: Commit**

```bash
git add tgcli/dispatch.py tests/tgcli/test_dispatch.py
git commit -m "feat(tgcli): classify resolver errors"
```

---

## Task 3: Refactor `tg show` to use the resolver

**Goal:** Remove inline title matching from `_show_runner` and delegate all chat lookup to `resolve_chat_db()` while preserving current exit-code behavior.

**Files:**
- Modify: `tgcli/commands/messages.py`
- Create: `tests/tgcli/test_messages.py`

- [ ] **Step 1: Write a failing `_show_runner` delegation test**

```python
# tests/tgcli/test_messages.py
import argparse

from tgcli.commands import messages
from tgcli.db import connect


def test_show_runner_delegates_pattern_to_resolver(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title) VALUES (?, ?, ?)",
        (123, "channel", "Polymarket"),
    )
    con.execute(
        """
        INSERT INTO tg_messages(chat_id, message_id, date, text, is_outgoing, has_media)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (123, 1, "2026-05-01T12:00:00", "hello", 0, 0),
    )
    con.commit()
    con.close()

    calls: list[str] = []

    def fake_resolve(con_arg, raw):
        calls.append(raw)
        return 123, "Polymarket"

    monkeypatch.setattr(messages, "DB_PATH", db)
    monkeypatch.setattr(messages, "resolve_chat_db", fake_resolve)

    args = argparse.Namespace(
        pattern="Polymarket",
        chat_id=None,
        limit=10,
        reverse=False,
    )
    data = messages._show_runner(args)

    assert calls == ["Polymarket"]
    assert data["chat"] == {"chat_id": 123, "title": "Polymarket"}
    assert data["messages"] == [
        {
            "date": "2026-05-01T12:00:00",
            "is_outgoing": False,
            "text": "hello",
            "media_type": None,
        }
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/tgcli/test_messages.py -q`

Expected: FAIL with `AttributeError` because `tgcli.commands.messages` has no `resolve_chat_db` import yet.

- [ ] **Step 3: Update `tgcli/commands/messages.py` imports and `_show_runner`**

In `tgcli/commands/messages.py`, remove `import unicodedata`, remove the `_strip_accents()` helper at lines 60-64, add `from tgcli.resolve import resolve_chat_db`, and replace `_show_runner()` with this complete function:

```python
def _show_runner(args) -> dict[str, Any]:
    if args.pattern is None and args.chat_id is None:
        raise BadArgs("Need a pattern or --chat-id. Example: tg show Ijadi")

    con = connect_readonly(DB_PATH)
    raw_selector = str(args.chat_id) if args.chat_id is not None else args.pattern
    chat_id, chat_title = resolve_chat_db(con, raw_selector)

    order = "ASC" if args.reverse else "DESC"
    rows = con.execute(
        f"""
        SELECT date, is_outgoing, text, media_type
        FROM tg_messages
        WHERE chat_id = ?
        ORDER BY date {order}
        LIMIT ?
        """,
        (chat_id, args.limit),
    ).fetchall()

    return {
        "chat": {"chat_id": chat_id, "title": chat_title},
        "order": "oldest_first" if args.reverse else "newest_first",
        "messages": [
            {
                "date": date,
                "is_outgoing": bool(is_out),
                "text": text or None,
                "media_type": media,
            }
            for date, is_out, text, media in rows
        ],
    }
```

The import block at the top of `tgcli/commands/messages.py` should become:

```python
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Any

from telethon.tl.types import (
    Channel,
    Chat,
    DocumentAttributeAudio,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
    MessageMediaWebPage,
    User,
)

from tgcli.client import make_client
from tgcli.commands._common import (
    AUDIT_PATH, DB_PATH, MEDIA_DIR, ROOT, SESSION_PATH, add_output_flags,
)
from tgcli.db import connect, connect_readonly
from tgcli.dispatch import run_command
from tgcli.resolve import resolve_chat_db
from tgcli.safety import BadArgs
```

- [ ] **Step 4: Run message tests**

Run: `.venv/bin/pytest tests/tgcli/test_messages.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Run preserved behavior smoke commands**

Run:

```bash
./tg show Polymarket --json | python -m json.tool
./tg show --json; echo "exit=$?"
./tg show --chat-id 999999999999 --json; echo "exit=$?"
```

Expected:
- First command exits 0 and prints a success envelope with `data.chat`.
- Second command prints a `BAD_ARGS` envelope and `exit=2`.
- Third command prints a `NOT_FOUND` envelope and `exit=4`.

- [ ] **Step 6: Run full suite**

Run: `.venv/bin/pytest tests/tgcli -q`

Expected: `63 passed`.

- [ ] **Step 7: Commit**

```bash
git add tgcli/commands/messages.py tests/tgcli/test_messages.py
git commit -m "refactor(tgcli): use resolver in show"
```

---

## Task 4: Add `--min-msgs` to `stats` and `contacts`

**Goal:** Add a default-off message-count threshold to `stats` top chats and to `contacts --chatted`.

**Files:**
- Modify: `tgcli/commands/stats.py`
- Modify: `tgcli/commands/contacts.py`
- Create: `tests/tgcli/test_min_msgs.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Write failing pure unit tests**

```python
# tests/tgcli/test_min_msgs.py
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
```

- [ ] **Step 2: Add failing subprocess smoke test**

Append this complete test to `tests/tgcli/test_cli_smoke.py`:

```python
def test_min_msgs_flags_are_accepted(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "seeded.sqlite"
    con = connect(db)
    con.execute("INSERT INTO tg_chats(chat_id, type, title) VALUES (1, 'user', 'Busy')")
    con.execute("INSERT INTO tg_contacts(user_id, first_name, is_mutual) VALUES (1, 'Busy', 1)")
    con.execute(
        """
        INSERT INTO tg_messages(chat_id, message_id, date, text, is_outgoing, has_media)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (1, 1, "2026-05-01T10:00:00", "hello", 0, 0),
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

    stats_result = _subprocess.run(
        [str(PYTHON), "-m", "tgcli", "stats", "--min-msgs", "1", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert stats_result.returncode == 0, f"stderr: {stats_result.stderr}"
    assert _json.loads(stats_result.stdout)["ok"] is True

    contacts_result = _subprocess.run(
        [
            str(PYTHON),
            "-m",
            "tgcli",
            "contacts",
            "--chatted",
            "--min-msgs",
            "1",
            "--json",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert contacts_result.returncode == 0, f"stderr: {contacts_result.stderr}"
    assert _json.loads(contacts_result.stdout)["ok"] is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/tgcli/test_min_msgs.py tests/tgcli/test_cli_smoke.py::test_min_msgs_flags_are_accepted -q`

Expected: FAIL because `_gather()` does not accept args yet and argparse does not recognize `--min-msgs`.

- [ ] **Step 4: Replace `tgcli/commands/stats.py`**

```python
"""`tg stats` - DB summary.

Read-only: queries telegram.sqlite, returns counts + top chats + media-by-type.
"""
from __future__ import annotations

import argparse
from typing import Any

from tgcli.commands._common import AUDIT_PATH, DB_PATH, add_output_flags
from tgcli.db import connect_readonly
from tgcli.dispatch import run_command


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("stats", help="DB summary")
    p.add_argument(
        "--min-msgs",
        type=int,
        default=0,
        help="Only include top chats with at least N cached messages",
    )
    add_output_flags(p)
    p.set_defaults(func=run)


def _min_msgs(args) -> int:
    return max(int(getattr(args, "min_msgs", 0) or 0), 0)


def _gather(args) -> dict[str, Any]:
    min_msgs = _min_msgs(args)
    con = connect_readonly(DB_PATH)
    chats = con.execute("SELECT COUNT(*) FROM tg_chats").fetchone()[0]
    messages = con.execute("SELECT COUNT(*) FROM tg_messages").fetchone()[0]
    contacts = con.execute("SELECT COUNT(*) FROM tg_contacts").fetchone()[0]
    by_kind = dict(con.execute("SELECT type, COUNT(*) FROM tg_chats GROUP BY type").fetchall())
    last = con.execute(
        "SELECT date, chat_id FROM tg_messages WHERE date IS NOT NULL "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    top_chats = con.execute(
        """
        SELECT c.title, COUNT(*) AS n
        FROM tg_messages m
        JOIN tg_chats c ON c.chat_id = m.chat_id
        GROUP BY m.chat_id
        HAVING COUNT(*) >= ?
        ORDER BY n DESC
        LIMIT 10
        """,
        (min_msgs,),
    ).fetchall()
    media_rows = con.execute(
        """
        SELECT media_type,
               COUNT(*) AS total,
               SUM(CASE WHEN media_path IS NOT NULL THEN 1 ELSE 0 END) AS dled
        FROM tg_messages
        WHERE has_media = 1
        GROUP BY media_type
        ORDER BY total DESC
        """
    ).fetchall()
    return {
        "db_path": str(DB_PATH),
        "db_kb": DB_PATH.stat().st_size // 1024,
        "filters": {"min_msgs": min_msgs},
        "chats": chats,
        "chats_by_kind": by_kind,
        "messages": messages,
        "contacts": contacts,
        "latest_message": (
            {"date": last[0], "chat_id": last[1]} if last else None
        ),
        "top_chats": [{"title": title, "messages": n} for title, n in top_chats],
        "media_by_type": [
            {"type": media_type or "?", "seen": total, "downloaded": downloaded or 0}
            for media_type, total, downloaded in media_rows
        ],
    }


def _human(data: dict) -> None:
    print(f"DB:       {data['db_path']} ({data['db_kb']} KB)")
    print(f"Chats:    {data['chats']}  ({data['chats_by_kind']})")
    print(f"Messages: {data['messages']}")
    print(f"Contacts: {data['contacts']}")
    if data["latest_message"]:
        latest = data["latest_message"]
        print(f"Latest:   {latest['date']}  (chat_id {latest['chat_id']})")
    if data["top_chats"]:
        print("\nTop 10 chats by message count:")
        for row in data["top_chats"]:
            print(f"  {row['messages']:>6}  {row['title']}")
    if data["media_by_type"]:
        print("\nMedia by type:")
        for row in data["media_by_type"]:
            print(f"  {row['type']:>12}  {row['seen']:>5} seen, {row['downloaded']:>5} downloaded")


def run(args) -> int:
    return run_command(
        "stats", args,
        runner=lambda: _gather(args),
        human_formatter=_human,
        audit_path=AUDIT_PATH,
    )
```

- [ ] **Step 5: Replace `tgcli/commands/contacts.py`**

```python
"""`tg contacts` (list) and `tg sync-contacts` (pull phone-book)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any

from telethon.tl.functions.contacts import GetContactsRequest

from tgcli.client import make_client
from tgcli.commands._common import AUDIT_PATH, DB_PATH, SESSION_PATH, add_output_flags
from tgcli.db import connect, connect_readonly
from tgcli.dispatch import run_command


def register(sub: argparse._SubParsersAction) -> None:
    co = sub.add_parser("contacts", help="List synced contacts with phone numbers")
    co.add_argument("--limit", type=int, default=200)
    co.add_argument("--with-phone-only", action="store_true",
                    help="Hide contacts with no phone number")
    co.add_argument("--chatted", action="store_true",
                    help="Only contacts with whom you have a dialog (run 'discover' first)")
    co.add_argument(
        "--min-msgs",
        type=int,
        default=0,
        help="With --chatted, require at least N cached messages",
    )
    add_output_flags(co)
    co.set_defaults(func=run_list)

    sy = sub.add_parser("sync-contacts", help="Pull phone-book contacts from Telegram")
    add_output_flags(sy)
    sy.set_defaults(func=run_sync)


def _min_msgs(args) -> int:
    return max(int(getattr(args, "min_msgs", 0) or 0), 0)


# ---------- contacts (read) ----------

def _list_data(args) -> dict[str, Any]:
    min_msgs = _min_msgs(args)
    con = connect_readonly(DB_PATH)
    join = ("INNER JOIN tg_chats ch ON ch.chat_id = c.user_id"
            if args.chatted else
            "LEFT  JOIN tg_chats ch ON ch.chat_id = c.user_id")
    wheres = []
    params: list[Any] = []
    if args.with_phone_only:
        wheres.append("(c.phone IS NOT NULL AND c.phone != '')")
    if args.chatted and min_msgs > 0:
        wheres.append("(SELECT COUNT(*) FROM tg_messages WHERE chat_id = c.user_id) >= ?")
        params.append(min_msgs)
    where_sql = (" WHERE " + " AND ".join(wheres)) if wheres else ""
    sql = f"""
        SELECT c.first_name, c.last_name, c.phone, c.username, c.is_mutual,
               (ch.chat_id IS NOT NULL) AS has_dialog,
               (SELECT COUNT(*) FROM tg_messages WHERE chat_id = c.user_id) AS n_msgs,
               (SELECT MAX(date)  FROM tg_messages WHERE chat_id = c.user_id) AS last_msg
        FROM tg_contacts c
        {join}
        {where_sql}
        ORDER BY n_msgs DESC, COALESCE(c.first_name, ''), COALESCE(c.last_name, '')
        LIMIT ?
    """
    rows = con.execute(sql, (*params, args.limit)).fetchall()
    return {
        "filters": {
            "chatted": args.chatted,
            "with_phone_only": args.with_phone_only,
            "limit": args.limit,
            "min_msgs": min_msgs,
        },
        "contacts": [
            {
                "first_name": first_name,
                "last_name": last_name,
                "phone": phone,
                "username": username,
                "is_mutual": bool(is_mutual),
                "has_dialog": bool(has_dialog),
                "messages": n_msgs,
                "last_message": last_msg,
            }
            for first_name, last_name, phone, username, is_mutual, has_dialog, n_msgs, last_msg in rows
        ],
    }


def _list_human(data: dict) -> None:
    contacts = data["contacts"]
    flags = []
    if data["filters"]["chatted"]:
        flags.append("chatted only")
    if data["filters"]["with_phone_only"]:
        flags.append("with phone")
    if data["filters"]["min_msgs"]:
        flags.append(f"min {data['filters']['min_msgs']} msgs")
    flag_str = f" [{', '.join(flags)}]" if flags else ""
    print(f"=== Contacts ({len(contacts)} shown){flag_str} ===\n")
    if not contacts:
        print("No contacts match. If using --chatted, run 'discover' first.")
        return
    for contact in contacts:
        name = " ".join(
            part for part in [contact["first_name"], contact["last_name"]]
            if part
        ) or "?"
        username_str = f"@{contact['username']}" if contact["username"] else ""
        phone_str = f"+{contact['phone']}" if contact["phone"] else "(no phone)"
        mutual_str = " ✓" if contact["is_mutual"] else "  "
        if contact["messages"]:
            last_short = (contact["last_message"] or "")[:10]
            tail = f"  · {contact['messages']:>4} msgs · last {last_short}"
        elif contact["has_dialog"]:
            tail = "  · dialog exists, 0 msgs cached"
        else:
            tail = "  · no chat"
        print(f"  {name:<28}  {phone_str:<18}  {username_str:<18}{mutual_str}{tail}")


def run_list(args) -> int:
    return run_command(
        "contacts", args,
        runner=lambda: _list_data(args),
        human_formatter=_list_human,
        audit_path=AUDIT_PATH,
    )


# ---------- sync-contacts (writes local DB) ----------

async def _sync_runner() -> dict[str, Any]:
    client = make_client(SESSION_PATH)
    await client.start()
    try:
        con = connect(DB_PATH)
        result = await client(GetContactsRequest(hash=0))
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        n = 0
        for user in result.users:
            con.execute(
                """
                INSERT INTO tg_contacts (
                    user_id, phone, first_name, last_name, username, is_mutual, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    phone      = excluded.phone,
                    first_name = excluded.first_name,
                    last_name  = excluded.last_name,
                    username   = excluded.username,
                    is_mutual  = excluded.is_mutual,
                    synced_at  = excluded.synced_at
                """,
                (
                    user.id,
                    getattr(user, "phone", None),
                    getattr(user, "first_name", None),
                    getattr(user, "last_name", None),
                    getattr(user, "username", None),
                    int(bool(getattr(user, "mutual_contact", False))),
                    now,
                ),
            )
            n += 1
        con.commit()
        con.close()
    finally:
        await client.disconnect()
    return {"synced": n, "db_path": str(DB_PATH)}


def _sync_human(data: dict) -> None:
    print(f"Synced {data['synced']} contacts to {data['db_path']}")


def run_sync(args) -> int:
    return run_command(
        "sync-contacts", args,
        runner=_sync_runner,
        human_formatter=_sync_human,
        audit_path=AUDIT_PATH,
    )
```

- [ ] **Step 6: Run targeted tests**

Run: `.venv/bin/pytest tests/tgcli/test_min_msgs.py tests/tgcli/test_cli_smoke.py -q`

Expected: 7 passed (3 min_msgs unit + 4 cli_smoke including the new one).

- [ ] **Step 7: Run full suite**

Run: `.venv/bin/pytest tests/tgcli -q`

Expected: `67 passed` (55 baseline + 6 resolver + 1 dispatch + 1 messages + 4 min_msgs/smoke).

- [ ] **Step 8: Commit**

```bash
git add tgcli/commands/stats.py tgcli/commands/contacts.py tests/tgcli/test_min_msgs.py tests/tgcli/test_cli_smoke.py
git commit -m "feat(tgcli): add --min-msgs filters"
```

---

## Final Verification

Run:

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: `67 passed`.

Run:

```bash
./tg show Polymarket --json | python -m json.tool
./tg show --json; echo "exit=$?"
./tg show --chat-id 999999999999 --json; echo "exit=$?"
./tg stats --min-msgs 5 --json | python -m json.tool
./tg contacts --chatted --min-msgs 5 --json | python -m json.tool
```

Expected:
- `show Polymarket` exits 0 and prints a success envelope.
- `show --json` exits 2 with `BAD_ARGS`.
- `show --chat-id 999999999999 --json` exits 4 with `NOT_FOUND`.
- `stats --min-msgs 5 --json` exits 0.
- `contacts --chatted --min-msgs 5 --json` exits 0.

---

## Exact Commit Sequence

```bash
git commit -m "feat(tgcli): add DB chat resolver"
git commit -m "feat(tgcli): classify resolver errors"
git commit -m "refactor(tgcli): use resolver in show"
git commit -m "feat(tgcli): add --min-msgs filters"
```

---

## Self-Review Checklist

Before declaring Phase 3 complete:

1. **Resolver module** - `tgcli/resolve.py` exposes `resolve_chat_db(con, raw) -> tuple[int, str]`, uses integer, `@username`, and fuzzy title strategies in that order, and imports only stdlib plus `tgcli.text`.
2. **Resolver tests** - `tests/tgcli/test_resolve.py` contains exactly the five master-plan cases: `by_int`, `by_username`, `by_fuzzy`, `ambiguous_raises`, and `not_found_raises`.
3. **Dispatch mapping** - `Ambiguous` maps to `BAD_ARGS` exit 2 and includes `candidates`; `NotFound` maps to `NOT_FOUND` exit 4.
4. **Show refactor** - `_show_runner` delegates lookup to `resolve_chat_db`; missing selector still raises `BadArgs`; missing `--chat-id` still exits 4 through resolver `NotFound`.
5. **`--min-msgs` stats** - `stats` parser accepts `--min-msgs`; default `0` leaves top-chat output unchanged; nonzero values apply through a `HAVING` clause.
6. **`--min-msgs` contacts** - `contacts` parser accepts `--min-msgs`; the filter applies only with `--chatted`; default `0` leaves output unchanged.
7. **Path correction** - all implementation paths use `tgcli/...` at project root, not `telegram_test/tgcli/...`.
8. **No source changes outside scope** - only the files listed in the File Structure table are touched during implementation.
9. **Test count** - full suite finishes at `64 passed`, which is within the requested low-60s range.

---

## Out of Scope

- Async `resolve_chat()` that hits Telethon for uncached usernames or entities is deferred to Phase 4 or later.
- Telegram-side write commands remain deferred to Phase 5.
- Rich resolver ranking, exact title matching precedence, recent-chat preference, and interactive disambiguation are not part of Phase 3.
