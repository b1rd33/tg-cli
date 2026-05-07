# Phase 2 — Output Framework + Safety Framework

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every `tg` subcommand a uniform JSON/human output envelope, structured exit codes, request-id correlation, an audit log, and the safety gates (`--allow-write` / `--confirm` / `--dry-run`) — wired into a single `dispatch()` orchestrator so Phase 5 can add Telegram-side writes without re-plumbing each command.

**Architecture:**
- Two new pure modules: `tgcli/output.py` (envelope, exit codes, emit, request-id, tty detection) and `tgcli/safety.py` (write/confirm gates, rate limiter, audit-log writer). Both stdlib-only, no Telethon imports → trivially unit-testable.
- One new orchestration module: `tgcli/dispatch.py` exposing `run_command()` — **synchronous, returns an int exit code**. Its `runner` argument may be sync or async; dispatch resolves a coroutine internally via `asyncio.run()`. Every command's `run()` becomes a synchronous one-liner that returns `run_command(...)`, so `__main__` never sees a coroutine and there is no nested `asyncio.run()` risk. Dispatch generates a request ID, runs the command, catches `BadArgs` / `WriteDisallowed` / `NeedsConfirm` / `LocalRateLimited` / `MissingCredentials` / `SessionLocked` / `DatabaseMissing` / `FloodWaitError` and converts them to fail envelopes, then routes through `output.emit()` for JSON-vs-human selection.
- Each existing command refactored to: (1) add `add_output_flags(p)` to its parser; (2) split logic into a pure function returning `data` (or raising a typed exception); (3) call `run_command(...)` from its `run()` entry point. No business logic changes — just wrapping.
- Parser helpers `add_output_flags()` and `add_write_flags()` live in `tgcli/commands/_common.py`. Phase 2 adds output flags to every command and ships `add_write_flags()` ready for Phase 5; no command uses `--allow-write` yet because no TG-write subcommands exist yet (sync-contacts/discover/backfill only write the *local* SQLite DB, which is not gated).
- Audit log: append-only JSONL at `audit.log` in repo root (gitignored). Every command invocation gets an entry once envelopes route through dispatch — even read-only commands. Phase 5 will tag entries with `allow_write=true` for TG-side writes.

**Tech Stack:** Python 3.12 stdlib (`enum`, `json`, `sys`, `os`, `uuid`, `time`, `argparse`, `pathlib`, `datetime`, `collections.deque`, `contextlib`); existing pytest + Telethon. **No new third-party deps.**

**Backwards compatibility:** Stats currently prints rich human output (top-10 chats, media-by-type). Phase 2 preserves that human output via a per-command formatter passed to `emit()`; JSON output is the *new* shape. No flags removed; default mode auto-detects from TTY.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `tgcli/output.py` | **create** | `ExitCode` enum, `success()`, `fail()`, `emit()`, `new_request_id()`, `is_tty_stdout()` |
| `tgcli/safety.py` | **create** | `BadArgs`/`WriteDisallowed`/`NeedsConfirm`/`LocalRateLimited` exceptions, `require_write_allowed()`, `require_confirm()`, `RateLimiter`, `audit_write()` |
| `tgcli/dispatch.py` | **create** | `run_command(name, args, runner, *, human_formatter=None, audit=False)` orchestrator |
| `tgcli/commands/_common.py` | **modify** | Add `AUDIT_PATH`, `add_output_flags()`, `add_write_flags()` |
| `tgcli/commands/stats.py` | **modify** | Route through dispatch; keep rich human formatter |
| `tgcli/commands/contacts.py` | **modify** | Route both `contacts` (read) and `sync-contacts` (write-local-DB) through dispatch |
| `tgcli/commands/chats.py` | **modify** | Route `discover` through dispatch |
| `tgcli/commands/messages.py` | **modify** | Route `show` and `backfill` through dispatch |
| `tgcli/commands/events.py` | **modify** | Route `listen` through dispatch (long-running; emits envelope on shutdown only) |
| `tgcli/commands/auth.py` | **modify** | Route `login` through dispatch |
| `tgcli/__main__.py` | **modify** | Top-level catch-all so uncaught exceptions become a `GENERIC` fail envelope rather than a Python traceback |
| `.gitignore` | **modify** | Add `audit.log` |
| `tests/tgcli/test_output.py` | **create** | Envelope shape, exit code mapping, JSON serialization, request-id format, TTY detection |
| `tests/tgcli/test_safety.py` | **create** | Write gate (flag + env), confirm gate, rate limiter, audit-log JSONL append |
| `tests/tgcli/test_dispatch.py` | **create** | Happy path, exception → fail envelope, JSON/human routing, request-id propagation, audit-log entry |
| `tests/tgcli/test_cli_smoke.py` | **modify** | Add `stats --json` envelope assertion + exit-code assertion for unknown command |

---

## Task 1: `tgcli/output.py` — envelope, exit codes, emit, request-id

**Files:**
- Create: `tgcli/output.py`
- Create: `tests/tgcli/test_output.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/tgcli/test_output.py
import io
import json
import re
import pytest

from tgcli.output import (
    ExitCode,
    emit,
    fail,
    is_tty_stdout,
    new_request_id,
    success,
)


def test_success_envelope_shape():
    env = success("stats", {"chats": 5}, request_id="req-abc")
    assert env == {
        "ok": True,
        "command": "stats",
        "request_id": "req-abc",
        "data": {"chats": 5},
        "warnings": [],
    }
    json.dumps(env)  # must serialise


def test_success_envelope_with_warnings():
    env = success("stats", {}, request_id="r", warnings=["truncated"])
    assert env["warnings"] == ["truncated"]


def test_fail_envelope_shape():
    env = fail(
        "messages.send",
        ExitCode.FLOOD_WAIT,
        "wait 30s",
        request_id="req-xyz",
        retry_after_seconds=30,
    )
    assert env["ok"] is False
    assert env["command"] == "messages.send"
    assert env["request_id"] == "req-xyz"
    assert env["error"] == {
        "code": "FLOOD_WAIT",
        "message": "wait 30s",
        "retry_after_seconds": 30,
    }
    json.dumps(env)


def test_exit_code_values_are_stable():
    # These integer values are part of the public CLI contract.
    assert ExitCode.OK == 0
    assert ExitCode.GENERIC == 1
    assert ExitCode.BAD_ARGS == 2
    assert ExitCode.NOT_AUTHED == 3
    assert ExitCode.NOT_FOUND == 4
    assert ExitCode.FLOOD_WAIT == 5
    assert ExitCode.WRITE_DISALLOWED == 6
    assert ExitCode.NEEDS_CONFIRM == 7
    assert ExitCode.LOCAL_RATE_LIMIT == 8


def test_emit_json_success_returns_zero(capsys):
    code = emit(success("stats", {"x": 1}, request_id="r"), json_mode=True)
    assert code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["ok"] is True
    assert parsed["data"] == {"x": 1}


def test_emit_json_failure_returns_mapped_exit_code(capsys):
    env = fail("x", ExitCode.NOT_FOUND, "missing", request_id="r")
    code = emit(env, json_mode=True)
    assert code == ExitCode.NOT_FOUND
    err_line = capsys.readouterr().err
    # In JSON mode, the envelope still goes to stdout, not stderr.
    assert err_line == ""


def test_emit_human_uses_formatter(capsys):
    captured = []
    def fmt(data):
        captured.append(data)
    env = success("stats", {"chats": 9}, request_id="r")
    emit(env, json_mode=False, human_formatter=fmt)
    assert captured == [{"chats": 9}]


def test_emit_human_failure_writes_stderr(capsys):
    env = fail("stats", ExitCode.NOT_FOUND, "no DB", request_id="r")
    code = emit(env, json_mode=False)
    assert code == ExitCode.NOT_FOUND
    cap = capsys.readouterr()
    assert cap.out == ""
    assert "NOT_FOUND" in cap.err
    assert "no DB" in cap.err


def test_request_id_format():
    rid = new_request_id()
    # Format: req-<8 hex chars>
    assert re.fullmatch(r"req-[0-9a-f]{8}", rid)
    # Different each call
    assert new_request_id() != rid


def test_is_tty_stdout_returns_bool():
    # Just exercise the call — capsys redirects stdout so it is non-TTY here.
    assert is_tty_stdout() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/tgcli/test_output.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tgcli.output'`.

- [ ] **Step 3: Implement `tgcli/output.py`**

```python
"""JSON/human output envelope, exit codes, and request-id generation.

Pure stdlib. No Telethon, no DB. Safe to import from anywhere.

Envelope shape (success):
    {"ok": True, "command": str, "request_id": str, "data": Any, "warnings": [str]}

Envelope shape (failure):
    {"ok": False, "command": str, "request_id": str,
     "error": {"code": str, "message": str, **extra}}
"""
from __future__ import annotations

import enum
import json
import sys
import uuid
from typing import Any, Callable


class ExitCode(enum.IntEnum):
    """Process exit codes. Integer values are part of the public CLI contract."""

    OK = 0
    GENERIC = 1
    BAD_ARGS = 2
    NOT_AUTHED = 3
    NOT_FOUND = 4
    FLOOD_WAIT = 5
    WRITE_DISALLOWED = 6
    NEEDS_CONFIRM = 7
    LOCAL_RATE_LIMIT = 8


def new_request_id() -> str:
    """Short request ID for log/envelope correlation."""
    return f"req-{uuid.uuid4().hex[:8]}"


def is_tty_stdout() -> bool:
    return sys.stdout.isatty()


def success(
    command: str,
    data: Any,
    *,
    request_id: str,
    warnings: list[str] | None = None,
) -> dict:
    return {
        "ok": True,
        "command": command,
        "request_id": request_id,
        "data": data,
        "warnings": list(warnings) if warnings else [],
    }


def fail(
    command: str,
    code: ExitCode,
    message: str,
    *,
    request_id: str,
    **extra: Any,
) -> dict:
    return {
        "ok": False,
        "command": command,
        "request_id": request_id,
        "error": {"code": code.name, "message": message, **extra},
    }


def emit(
    envelope: dict,
    *,
    json_mode: bool,
    human_formatter: Callable[[Any], None] | None = None,
) -> int:
    """Print envelope and return process exit code."""
    if json_mode:
        print(json.dumps(envelope, ensure_ascii=False, default=str))
    elif envelope["ok"]:
        if human_formatter is not None:
            human_formatter(envelope["data"])
        else:
            # Default human formatter: pretty-print the data dict.
            print(json.dumps(envelope["data"], ensure_ascii=False, indent=2, default=str))
    else:
        err = envelope["error"]
        print(f"ERROR [{err['code']}]: {err['message']}", file=sys.stderr)

    if envelope["ok"]:
        return ExitCode.OK
    return ExitCode[envelope["error"]["code"]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/tgcli/test_output.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add tgcli/output.py tests/tgcli/test_output.py
git commit -m "feat(tgcli): output envelope, exit codes, request-id (Phase 2.1)"
```

---

## Task 2: `tgcli/safety.py` — gates, rate limiter, audit log

**Files:**
- Create: `tgcli/safety.py`
- Create: `tests/tgcli/test_safety.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/tgcli/test_safety.py
import argparse
import json
import time
from pathlib import Path

import pytest

from tgcli.safety import (
    BadArgs,
    LocalRateLimited,
    NeedsConfirm,
    RateLimiter,
    WriteDisallowed,
    audit_write,
    require_confirm,
    require_write_allowed,
)


def test_bad_args_is_an_exception():
    with pytest.raises(BadArgs):
        raise BadArgs("missing --pattern or --chat-id")


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


def test_write_gate_passes_with_flag(monkeypatch):
    monkeypatch.delenv("TG_ALLOW_WRITE", raising=False)
    require_write_allowed(make_args(allow_write=True))


def test_write_gate_passes_with_env(monkeypatch):
    monkeypatch.setenv("TG_ALLOW_WRITE", "1")
    require_write_allowed(make_args())


def test_write_gate_ignores_other_env_values(monkeypatch):
    monkeypatch.setenv("TG_ALLOW_WRITE", "yes")
    with pytest.raises(WriteDisallowed):
        require_write_allowed(make_args())


def test_confirm_gate_requires_flag():
    with pytest.raises(NeedsConfirm):
        require_confirm(make_args(allow_write=True), action="messages.delete")


def test_confirm_gate_passes_with_flag():
    require_confirm(
        make_args(allow_write=True, confirm=True),
        action="messages.delete",
    )


def test_rate_limiter_allows_under_max():
    rl = RateLimiter(max_per_window=3, window_seconds=10)
    assert rl.check() == 0.0
    assert rl.check() == 0.0
    assert rl.check() == 0.0


def test_rate_limiter_blocks_when_full():
    rl = RateLimiter(max_per_window=2, window_seconds=10)
    rl.check()
    rl.check()
    wait = rl.check()
    assert wait > 0
    assert wait <= 10


def test_rate_limiter_recovers_after_window():
    rl = RateLimiter(max_per_window=1, window_seconds=0.05)
    assert rl.check() == 0.0
    assert rl.check() > 0
    time.sleep(0.06)
    assert rl.check() == 0.0


def test_audit_write_appends_jsonl(tmp_path: Path):
    log = tmp_path / "subdir" / "audit.log"
    audit_write(log, cmd="stats", request_id="r1", args_repr={"--json": True}, result="ok")
    audit_write(log, cmd="stats", request_id="r2", args_repr={}, result="fail",
                error_code="NOT_FOUND")

    lines = log.read_text().splitlines()
    assert len(lines) == 2
    e1 = json.loads(lines[0])
    e2 = json.loads(lines[1])
    assert e1["cmd"] == "stats"
    assert e1["request_id"] == "r1"
    assert e1["result"] == "ok"
    assert "ts" in e1
    assert e2["error_code"] == "NOT_FOUND"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/tgcli/test_safety.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tgcli.safety'`.

- [ ] **Step 3: Implement `tgcli/safety.py`**

```python
"""Safety gates, rate limiter, audit log.

Stdlib only. No Telethon, no DB. Pure functions plus one tiny stateful class.
"""
from __future__ import annotations

import json
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BadArgs(Exception):
    """Raised when caller passed contradictory or insufficient args (maps to BAD_ARGS=2)."""


class WriteDisallowed(Exception):
    """Raised when a write op is invoked without --allow-write / TG_ALLOW_WRITE=1."""


class NeedsConfirm(Exception):
    """Raised when a destructive op is invoked without --confirm."""


class LocalRateLimited(Exception):
    """Raised when an in-process rate limiter blocks an op (vs. server FloodWait)."""

    def __init__(self, message: str, retry_after_seconds: float):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def require_write_allowed(args) -> None:
    """Raise WriteDisallowed unless --allow-write or TG_ALLOW_WRITE=1."""
    if getattr(args, "allow_write", False):
        return
    if os.environ.get("TG_ALLOW_WRITE") == "1":
        return
    raise WriteDisallowed(
        "Write operations require --allow-write or TG_ALLOW_WRITE=1"
    )


def require_confirm(args, action: str) -> None:
    """Raise NeedsConfirm unless --confirm was passed."""
    if getattr(args, "confirm", False):
        return
    raise NeedsConfirm(
        f"Destructive op '{action}' requires --confirm"
    )


class RateLimiter:
    """Sliding-window in-process rate limiter.

    `check()` returns 0.0 if the call is allowed (and records it),
    or seconds-to-wait if blocked (and does NOT record it).
    """

    def __init__(self, max_per_window: int, window_seconds: float):
        self.max = max_per_window
        self.window = window_seconds
        self.events: deque[float] = deque()

    def check(self) -> float:
        now = time.monotonic()
        while self.events and now - self.events[0] > self.window:
            self.events.popleft()
        if len(self.events) >= self.max:
            return self.window - (now - self.events[0])
        self.events.append(now)
        return 0.0


def audit_write(
    audit_path: Path,
    *,
    cmd: str,
    request_id: str,
    args_repr: dict[str, Any],
    result: str,
    **extra: Any,
) -> None:
    """Append one JSONL entry to the audit log. Creates parent dirs as needed."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cmd": cmd,
        "request_id": request_id,
        "args": args_repr,
        "result": result,
        **extra,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/tgcli/test_safety.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add tgcli/safety.py tests/tgcli/test_safety.py
git commit -m "feat(tgcli): safety gates, rate limiter, audit log (Phase 2.2)"
```

---

## Task 3: Common parser flags + audit path

**Files:**
- Modify: `tgcli/commands/_common.py`

- [ ] **Step 1: Add the audit path, env-overridable paths, and parser-helper functions**

Open `tgcli/commands/_common.py`. Replace the entire file contents with:

```python
"""Paths and shared argparse helpers for command modules.

All paths are env-overridable so tests (and multi-account agents) can isolate state.
The defaults preserve Phase 1 behaviour: <repo>/telegram.sqlite, <repo>/tg.session, etc.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def _override(env_var: str, default: Path) -> Path:
    val = os.environ.get(env_var)
    return Path(val) if val else default


ROOT: Path = Path(__file__).resolve().parent.parent.parent
DB_PATH: Path = _override("TG_DB_PATH", ROOT / "telegram.sqlite")
SESSION_PATH: Path = _override("TG_SESSION_PATH", ROOT / "tg.session")
ENV_PATH: Path = ROOT / ".env"
MEDIA_DIR: Path = _override("TG_MEDIA_DIR", ROOT / "media")
AUDIT_PATH: Path = _override("TG_AUDIT_PATH", ROOT / "audit.log")


def add_output_flags(parser: argparse.ArgumentParser) -> None:
    """`--json` / `--human` for any subcommand. Auto-detects from TTY when neither is set."""
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true",
                   help="Force JSON envelope output (default when stdout is not a TTY)")
    g.add_argument("--human", action="store_true",
                   help="Force human-readable output (default on a TTY)")


def add_write_flags(parser: argparse.ArgumentParser, *, destructive: bool = False) -> None:
    """Write-side gates. Phase 5+ commands attach these; Phase 2 ships them ready.

    `--allow-write` is required for any TG-side write.
    `--confirm` is additionally required for destructive ops (delete/leave/block).
    `--dry-run` prints what would happen and exits before calling Telegram.
    """
    parser.add_argument("--allow-write", action="store_true",
                        help="Required for any Telegram write (TG_ALLOW_WRITE=1 also works)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print intent and exit before calling Telegram")
    if destructive:
        parser.add_argument("--confirm", action="store_true",
                            help="Required in addition to --allow-write for destructive ops")
```

- [ ] **Step 2: Verify nothing imports `_common` in a way the rename breaks**

Run: `grep -rn "from tgcli.commands._common" tgcli/ tests/`
Expected: every import lists symbols that still exist (`ROOT`, `DB_PATH`, `SESSION_PATH`, `ENV_PATH`, `MEDIA_DIR`). The new symbols (`AUDIT_PATH`, `add_output_flags`, `add_write_flags`) are unused so far — that's fine.

- [ ] **Step 3: Run the existing test suite**

Run: `.venv/bin/pytest tests/tgcli -q`
Expected: 17 + 9 + 10 = 36 passed.

- [ ] **Step 4: Add `audit.log` to `.gitignore`**

Open `.gitignore` and append:

```
audit.log
```

- [ ] **Step 5: Commit**

```bash
git add tgcli/commands/_common.py .gitignore
git commit -m "feat(tgcli): parser helpers + audit path in _common (Phase 2.3)"
```

---

## Task 4: `tgcli/dispatch.py` — orchestrator

**Files:**
- Create: `tgcli/dispatch.py`
- Create: `tests/tgcli/test_dispatch.py`

The dispatcher is the single chokepoint where request IDs, exception → fail-envelope mapping, JSON-vs-human routing, and audit-logging happen. Each command's `run()` becomes a thin shim that builds args, defines a runner, and calls `run_command()`.

- [ ] **Step 1: Write the failing tests**

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
from tgcli.safety import BadArgs, LocalRateLimited, NeedsConfirm, WriteDisallowed


def make_args(**kw):
    ns = argparse.Namespace()
    ns.json = kw.get("json", True)  # tests default to JSON for easy parsing
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
    # Verified against Telethon 1.43.2: FloodWaitError(request, capture=0) sets `.seconds = int(capture)`.
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

Run: `.venv/bin/pytest tests/tgcli/test_dispatch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tgcli.dispatch'`.

- [ ] **Step 3: Confirm Telethon's FloodWaitError signature**

Run: `.venv/bin/python -c "from telethon.errors import FloodWaitError; import inspect; print(inspect.signature(FloodWaitError.__init__))"`

Expected output is along the lines of `(self, request, capture=0)` where `capture` is the seconds value, exposed as `.seconds` on the instance. The test above uses `capture=30` — verify the test still raises and exposes `.seconds == 30` before continuing. If the signature differs, adjust the test to construct the error so `e.seconds` is set, then proceed.

- [ ] **Step 4: Implement `tgcli/dispatch.py`**

```python
"""Single chokepoint that wraps every command's logic.

Responsibilities:
- Generate a request ID for log/envelope correlation.
- Run the runner (sync function OR coroutine function); resolve coroutines via asyncio.run.
- Map known exceptions to fail envelopes with stable exit codes.
- Route output through `output.emit()` honouring --json / --human / TTY auto.
- Append one entry to the audit log per invocation.

CONTRACT: `run_command(...)` is SYNCHRONOUS and returns an int exit code.
Each command's `run(args)` MUST be sync and `return run_command(...)`.
The async version of the work belongs in the runner, not the entry point.
This avoids nested asyncio.run() (which raises) when __main__ also tries
to await a coroutine returned from `args.func`.
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
from tgcli.safety import (
    BadArgs,
    LocalRateLimited,
    NeedsConfirm,
    WriteDisallowed,
    audit_write,
)

Runner = Callable[[], Any] | Callable[[], Awaitable[Any]]


def _resolve_json_mode(args) -> bool:
    """Honour --json / --human, else auto-detect from TTY."""
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
    except BaseException as exc:  # noqa: BLE001 — top-level catch by design
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

- [ ] **Step 5: Run all dispatch tests**

Run: `.venv/bin/pytest tests/tgcli/test_dispatch.py -v`
Expected: all passed (11 tests after BadArgs param entry was added).

- [ ] **Step 6: Run full suite to ensure nothing else broke**

Run: `.venv/bin/pytest tests/tgcli -q`
Expected: 17 + 9 + 11 + 11 = 48 passed.

- [ ] **Step 7: Commit**

```bash
git add tgcli/dispatch.py tests/tgcli/test_dispatch.py
git commit -m "feat(tgcli): dispatch orchestrator with envelope + audit (Phase 2.4)"
```

---

## Task 5: Wire `stats` through dispatch

**Files:**
- Modify: `tgcli/commands/stats.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

`stats` is the simplest read-only command and exercises the full envelope path including a non-trivial human formatter (top-10 chats, media-by-type).

- [ ] **Step 1: Replace `tgcli/commands/stats.py`**

```python
"""`tg stats` — DB summary.

Read-only: queries telegram.sqlite, returns counts + top-10 chats + media-by-type.
"""
from __future__ import annotations

import argparse
from typing import Any

from tgcli.commands._common import AUDIT_PATH, DB_PATH, add_output_flags
from tgcli.db import connect_readonly
from tgcli.dispatch import run_command


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("stats", help="DB summary")
    add_output_flags(p)
    p.set_defaults(func=run)


def _gather() -> dict[str, Any]:
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
        ORDER BY n DESC
        LIMIT 10
        """
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
        "chats": chats,
        "chats_by_kind": by_kind,
        "messages": messages,
        "contacts": contacts,
        "latest_message": (
            {"date": last[0], "chat_id": last[1]} if last else None
        ),
        "top_chats": [{"title": t, "messages": n} for t, n in top_chats],
        "media_by_type": [
            {"type": mtype or "?", "seen": total, "downloaded": dled or 0}
            for mtype, total, dled in media_rows
        ],
    }


def _human(data: dict) -> None:
    print(f"DB:       {data['db_path']} ({data['db_kb']} KB)")
    print(f"Chats:    {data['chats']}  ({data['chats_by_kind']})")
    print(f"Messages: {data['messages']}")
    print(f"Contacts: {data['contacts']}")
    if data["latest_message"]:
        lm = data["latest_message"]
        print(f"Latest:   {lm['date']}  (chat_id {lm['chat_id']})")
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
        runner=_gather,
        human_formatter=_human,
        audit_path=AUDIT_PATH,
    )
```

- [ ] **Step 2: Smoke-test manually**

```bash
./tg stats --human
./tg stats --json | python -m json.tool
./tg stats --json | python -c "import sys,json; e=json.load(sys.stdin); assert e['ok'] and e['command']=='stats'; print('ok')"
```

Expected: human output matches the previous format (top-10 chats, media-by-type); JSON envelope parses with `ok=True`.

- [ ] **Step 3: Add JSON-envelope assertion to `test_cli_smoke.py`**

Open `tests/tgcli/test_cli_smoke.py` and append:

```python
import json as _json
import os as _os
import subprocess as _subprocess
import sys as _sys
from pathlib import Path as _Path


def _run_stats_subprocess(tmp_path: _Path, *, db: _Path | None) -> _subprocess.CompletedProcess:
    """Invoke `python -m tgcli stats --json` with TG_DB_PATH/TG_AUDIT_PATH redirected to tmp_path."""
    project = _Path(__file__).resolve().parents[2]
    py = project / ".venv" / "bin" / "python"
    env = {
        **_os.environ,
        # Bypass credential guard (stats is read-only and doesn't connect to TG):
        "TG_API_ID": "1",
        "TG_API_HASH": "x",
        "TG_AUDIT_PATH": str(tmp_path / "audit.log"),
    }
    if db is not None:
        env["TG_DB_PATH"] = str(db)
    else:
        # Force a non-existent DB path so we don't accidentally hit the dev DB.
        env["TG_DB_PATH"] = str(tmp_path / "does-not-exist.sqlite")
    return _subprocess.run(
        [str(py), "-m", "tgcli", "stats", "--json"],
        cwd=str(project), capture_output=True, text=True, env=env,
    )


def test_stats_json_envelope_with_seeded_db(tmp_path):
    """With a freshly seeded DB, `tg stats --json` MUST return exit 0 + success envelope."""
    from tgcli.db import connect
    seed_db = tmp_path / "seeded.sqlite"
    con = connect(seed_db)  # creates schema
    con.execute("INSERT INTO tg_chats(chat_id, type, title) VALUES (1, 'user', 'Alice')")
    con.commit()
    con.close()

    r = _run_stats_subprocess(tmp_path, db=seed_db)
    assert r.returncode == 0, f"stderr: {r.stderr}"
    payload = _json.loads(r.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "stats"
    assert payload["request_id"].startswith("req-")
    assert payload["data"]["chats"] == 1


def test_stats_json_envelope_no_db_returns_not_found(tmp_path):
    """Without a DB, the envelope MUST be a structured failure with exit code 4."""
    r = _run_stats_subprocess(tmp_path, db=None)
    assert r.returncode == 4
    payload = _json.loads(r.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "NOT_FOUND"
```

(If `test_cli_smoke.py` already has imports / fixtures, reuse them rather than redeclaring.)

- [ ] **Step 4: Run full test suite**

Run: `.venv/bin/pytest tests/tgcli -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tgcli/commands/stats.py tests/tgcli/test_cli_smoke.py
git commit -m "feat(tgcli): stats emits envelope via dispatch (Phase 2.5)"
```

---

## Task 6: Wire `contacts` and `sync-contacts` through dispatch

**Files:**
- Modify: `tgcli/commands/contacts.py`

`sync-contacts` writes to the *local* SQLite DB but does not write to Telegram, so it does **not** require `--allow-write`. Phase 5 will gate Telegram-side writes only.

- [ ] **Step 1: Replace `tgcli/commands/contacts.py`**

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
    add_output_flags(co)
    co.set_defaults(func=run_list)

    sy = sub.add_parser("sync-contacts", help="Pull phone-book contacts from Telegram")
    add_output_flags(sy)
    sy.set_defaults(func=run_sync)


# ---------- contacts (read) ----------

def _list_data(args) -> dict[str, Any]:
    con = connect_readonly(DB_PATH)
    join = ("INNER JOIN tg_chats ch ON ch.chat_id = c.user_id"
            if args.chatted else
            "LEFT  JOIN tg_chats ch ON ch.chat_id = c.user_id")
    wheres = []
    if args.with_phone_only:
        wheres.append("(c.phone IS NOT NULL AND c.phone != '')")
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
    rows = con.execute(sql, (args.limit,)).fetchall()
    return {
        "filters": {"chatted": args.chatted, "with_phone_only": args.with_phone_only,
                    "limit": args.limit},
        "contacts": [
            {
                "first_name": fn,
                "last_name": ln,
                "phone": phone,
                "username": un,
                "is_mutual": bool(mut),
                "has_dialog": bool(has_dialog),
                "messages": n_msgs,
                "last_message": last_msg,
            }
            for fn, ln, phone, un, mut, has_dialog, n_msgs, last_msg in rows
        ],
    }


def _list_human(data: dict) -> None:
    contacts = data["contacts"]
    flags = []
    if data["filters"]["chatted"]:
        flags.append("chatted only")
    if data["filters"]["with_phone_only"]:
        flags.append("with phone")
    flag_str = f" [{', '.join(flags)}]" if flags else ""
    print(f"=== Contacts ({len(contacts)} shown){flag_str} ===\n")
    if not contacts:
        print("No contacts match. If using --chatted, run 'discover' first.")
        return
    for c in contacts:
        name = " ".join(p for p in [c["first_name"], c["last_name"]] if p) or "?"
        un_str = f"@{c['username']}" if c["username"] else ""
        phone_str = f"+{c['phone']}" if c["phone"] else "(no phone)"
        mut_str = " ✓" if c["is_mutual"] else "  "
        if c["messages"]:
            last_short = (c["last_message"] or "")[:10]
            tail = f"  · {c['messages']:>4} msgs · last {last_short}"
        elif c["has_dialog"]:
            tail = "  · dialog exists, 0 msgs cached"
        else:
            tail = "  · no chat"
        print(f"  {name:<28}  {phone_str:<18}  {un_str:<18}{mut_str}{tail}")


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

- [ ] **Step 2: Smoke-test (live)**

```bash
./tg contacts --json --limit 3 | python -m json.tool
./tg contacts --human --limit 3
```

Expected: JSON envelope with `data.contacts` of length ≤3; human output unchanged from Phase 1.

- [ ] **Step 3: Run tests**

Run: `.venv/bin/pytest tests/tgcli -q`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tgcli/commands/contacts.py
git commit -m "feat(tgcli): contacts + sync-contacts via dispatch (Phase 2.6)"
```

---

## Task 7: Wire `discover` through dispatch

**Files:**
- Modify: `tgcli/commands/chats.py`

- [ ] **Step 1: Replace `tgcli/commands/chats.py`**

```python
"""Chat-related subcommands. Phase 1 port: discover."""
from __future__ import annotations

import argparse
from typing import Any

from tgcli.client import make_client
from tgcli.commands._common import AUDIT_PATH, DB_PATH, SESSION_PATH, add_output_flags
from tgcli.commands.messages import _upsert_chat
from tgcli.db import connect
from tgcli.dispatch import run_command


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("discover", help="Fast scan of every dialog (no messages)")
    add_output_flags(p)
    p.set_defaults(func=run_discover)


async def _discover_runner(args) -> dict[str, Any]:
    import sys
    client = make_client(SESSION_PATH)
    await client.start()
    quiet = bool(getattr(args, "json", False))
    try:
        con = connect(DB_PATH)
        n = 0
        async for dialog in client.iter_dialogs():
            _upsert_chat(con, dialog.entity)
            n += 1
            if n % 50 == 0:
                con.commit()
                if not quiet:
                    print(f"  ...{n} dialogs", file=sys.stderr)
        con.commit()
        con.close()
    finally:
        await client.disconnect()
    return {"discovered": n, "db_path": str(DB_PATH)}


def _human(data: dict) -> None:
    print(f"Discovered {data['discovered']} dialogs in tg_chats")


def run_discover(args) -> int:
    return run_command(
        "discover", args,
        runner=lambda: _discover_runner(args),
        human_formatter=_human,
        audit_path=AUDIT_PATH,
    )
```

Note: progress prints now go to **stderr** in human mode and are suppressed entirely in JSON mode. Stdout is reserved for the final envelope so JSON consumers can `python -c 'json.load(sys.stdin)'` without filtering.

- [ ] **Step 2: Run tests**

Run: `.venv/bin/pytest tests/tgcli -q`
Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add tgcli/commands/chats.py
git commit -m "feat(tgcli): discover via dispatch (Phase 2.7)"
```

---

## Task 8: Wire `show` and `backfill` through dispatch

**Files:**
- Modify: `tgcli/commands/messages.py`

`messages.py` is the largest module — it owns the helpers (`_upsert_chat`, `_upsert_message`, `_download_media`, `_display_title`, `_strip_accents`, `_chat_kind`, `_media_type_of`) reused by `chats.py`, `events.py`, and `auth.py`. **Leave every helper alone.** Only `register()`, `run_show`, and `run_backfill` change.

### Exit-code mapping for `show`

The current `run_show` (`tgcli/commands/messages.py:186-247`) returns six different codes. Each must map to a typed exception or a success envelope. Audit:

| Current branch (line) | Old exit | New behavior |
|---|---|---|
| no pattern AND no --chat-id (188) | 2 | `raise BadArgs("Need a pattern or --chat-id")` |
| `connect_readonly` raises `DatabaseMissing` (192) | 1 | bubble up — dispatch maps to NOT_FOUND |
| no chats match pattern (202) | 4 | `raise DatabaseMissing(f"No chat title contains {args.pattern!r}")` |
| multiple chats match (205) | 2 | `raise BadArgs(...)` with the candidate list embedded in the message |
| `--chat-id` not in DB (214) | 4 | `raise DatabaseMissing(f"chat_id {args.chat_id} not in DB")` |
| zero messages cached (231) | 0 | success envelope; data has empty `messages` list and `cached_count: 0` |
| messages found (236) | 0 | success envelope |

### Exit-code mapping for `backfill`

The current `run_backfill` (`tgcli/commands/messages.py:252-294`) only returns 0. It catches per-chat exceptions internally and continues. Mapping is trivial: success only. Per-chat skip events go into `data.skipped` (list of `{title, error}`) so callers see them.

- [ ] **Step 1: Refactor `register()` to attach output flags**

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

    bf = sub.add_parser("backfill", help="Pull historical messages")
    bf.add_argument("--per-chat", type=int, default=200)
    bf.add_argument("--max-chats", type=int, default=100)
    bf.add_argument("--throttle", type=float, default=1.0)
    bf.add_argument("--download-media", action="store_true",
                    help="Also download photos / voice / video / documents to media/<chat_id>/")
    add_output_flags(bf)
    bf.set_defaults(func=run_backfill)
```

Update the file's imports: add
```python
from tgcli.commands._common import (
    AUDIT_PATH, DB_PATH, MEDIA_DIR, ROOT, SESSION_PATH, add_output_flags,
)
from tgcli.dispatch import run_command
from tgcli.safety import BadArgs
```
(Drop the existing `add_output_flags` import line if not present, and the `from tgcli.db import DatabaseMissing, connect, connect_readonly` line stays as-is — `DatabaseMissing` is what `_show_runner` raises explicitly.)

- [ ] **Step 2: Replace `run_show` with `_show_runner` + `_show_human` + thin sync `run_show`**

```python
def _show_runner(args) -> dict[str, Any]:
    if args.pattern is None and args.chat_id is None:
        raise BadArgs("Need a pattern or --chat-id. Example: tg show Ijadi")

    con = connect_readonly(DB_PATH)  # raises DatabaseMissing → NOT_FOUND

    chat_id = args.chat_id
    chat_title: str | None = None
    if chat_id is None:
        rows = con.execute("SELECT chat_id, title, type FROM tg_chats").fetchall()
        needle = _strip_accents(args.pattern)
        matches = [r for r in rows if needle in _strip_accents(r[1])]
        if not matches:
            raise DatabaseMissing(f"No chat title contains {args.pattern!r}")
        if len(matches) > 1:
            preview = "; ".join(f"{cid} [{kind}] {title}" for cid, title, kind in matches[:8])
            more = f"; +{len(matches) - 8} more" if len(matches) > 8 else ""
            raise BadArgs(
                f"Multiple chats match {args.pattern!r}: {preview}{more}. "
                f"Disambiguate with --chat-id <id>"
            )
        chat_id, chat_title, _ = matches[0]
    else:
        row = con.execute("SELECT title FROM tg_chats WHERE chat_id=?", (chat_id,)).fetchone()
        if not row:
            raise DatabaseMissing(f"chat_id {chat_id} not in DB")
        chat_title = row[0]

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


def _show_human(data: dict) -> None:
    chat = data["chat"]
    msgs = data["messages"]
    if not msgs:
        print(f"No messages stored for '{chat['title']}' (chat_id {chat['chat_id']}).")
        return
    direction = "oldest first" if data["order"] == "oldest_first" else "newest first"
    print(f"=== {chat['title']}  ·  chat_id {chat['chat_id']}  ·  {len(msgs)} messages, {direction} ===\n")
    for m in msgs:
        arrow = "→ you " if m["is_outgoing"] else "← them"
        ts = (m["date"] or "")[:19].replace("T", " ")
        if m["text"]:
            body = m["text"]
        elif m["media_type"]:
            body = f"[{m['media_type']}]"
        else:
            body = "[empty]"
        print(f"  {ts}  {arrow}  {body}")


def run_show(args) -> int:
    return run_command(
        "show", args,
        runner=lambda: _show_runner(args),
        human_formatter=_show_human,
        audit_path=AUDIT_PATH,
    )
```

- [ ] **Step 3: Replace `run_backfill` (was `async def`) with sync wrapper + async runner**

**Critical:** the new `run_backfill` is **sync**. Dispatch resolves the coroutine inside `_backfill_runner`. Do NOT keep `async def run_backfill(args) -> int` — that would make `__main__` try to await an int once dispatch already ran the loop, raising `RuntimeError: asyncio.run() cannot be called from a running event loop`.

```python
async def _backfill_runner(args) -> dict[str, Any]:
    client = make_client(SESSION_PATH)
    await client.start()
    con = connect(DB_PATH)
    quiet = bool(getattr(args, "json", False))

    chat_count = 0
    msg_total = 0
    media_total = 0
    skipped: list[dict] = []
    per_chat: list[dict] = []

    try:
        async for dialog in client.iter_dialogs():
            if chat_count >= args.max_chats:
                break
            chat_count += 1
            _upsert_chat(con, dialog.entity)
            con.commit()

            added = 0
            media_added = 0
            try:
                async for msg in client.iter_messages(dialog.entity, limit=args.per_chat):
                    media_path = None
                    if args.download_media and getattr(msg, "media", None):
                        media_path = await _download_media(client, msg, dialog.id)
                        if media_path:
                            media_added += 1
                    _upsert_message(con, msg, dialog.id, media_path=media_path)
                    added += 1
                con.commit()
            except Exception as e:
                title = _display_title(dialog.entity)
                skipped.append({"chat_id": dialog.id, "title": title, "error": str(e)})
                if not quiet:
                    print(f"  [{chat_count:>3}/{args.max_chats}] {title[:40]:40s}  SKIP ({e})", file=sys.stderr)
                continue

            msg_total += added
            media_total += media_added
            per_chat.append({
                "chat_id": dialog.id,
                "title": _display_title(dialog.entity),
                "messages_added": added,
                "media_added": media_added,
            })
            if not quiet:
                media_note = f", {media_added} media" if args.download_media else ""
                print(
                    f"  [{chat_count:>3}/{args.max_chats}] "
                    f"{_display_title(dialog.entity)[:40]:40s}  +{added:>4} msgs{media_note}  "
                    f"(running {msg_total})",
                    file=sys.stderr,
                )
            await asyncio.sleep(args.throttle)
    finally:
        con.close()
        await client.disconnect()

    return {
        "chats_processed": chat_count,
        "messages_inserted": msg_total,
        "media_downloaded": media_total,
        "skipped": skipped,
        "per_chat": per_chat,
    }


def _backfill_human(data: dict) -> None:
    media_note = f", {data['media_downloaded']} media files" if data["media_downloaded"] else ""
    print(
        f"\nBackfill done: {data['chats_processed']} chats, "
        f"{data['messages_inserted']} messages{media_note}"
    )
    if data["skipped"]:
        print(f"  ({len(data['skipped'])} chats skipped due to errors)")


def run_backfill(args) -> int:
    return run_command(
        "backfill", args,
        runner=lambda: _backfill_runner(args),
        human_formatter=_backfill_human,
        audit_path=AUDIT_PATH,
    )
```

Add `import sys` at the top of the file if not present (used by the stderr progress lines).

- [ ] **Step 4: Smoke-test live**

```bash
./tg show "Saved Messages" --limit 3 --json | python -m json.tool
./tg show "Saved Messages" --limit 3 --human
./tg show --json; echo "exit=$?"  # expect exit=2 (BadArgs: missing pattern)
./tg show --chat-id 999999999999 --json; echo "exit=$?"  # expect exit=4 (NOT_FOUND)
```

Expected: JSON envelope with `data.chat` and `data.messages`; human output reproduces Phase 1 layout; bad-arg path returns exit 2; not-found returns exit 4. Backfill is expensive — defer its smoke test to Task 11.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests/tgcli -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add tgcli/commands/messages.py
git commit -m "feat(tgcli): show + backfill via dispatch (Phase 2.8)"
```

---

## Task 9: Wire `login` and `listen` through dispatch

**Files:**
- Modify: `tgcli/commands/auth.py`
- Modify: `tgcli/commands/events.py`

- [ ] **Step 1: Refactor `auth.py`**

```python
"""Auth subcommands. Phase 1: login."""
from __future__ import annotations

import argparse
from typing import Any

from tgcli.client import make_client
from tgcli.commands._common import AUDIT_PATH, SESSION_PATH, add_output_flags
from tgcli.commands.messages import _display_title
from tgcli.dispatch import run_command


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("login", help="One-time interactive auth")
    add_output_flags(p)
    p.set_defaults(func=run_login)


async def _runner() -> dict[str, Any]:
    client = make_client(SESSION_PATH)
    await client.start()
    try:
        me = await client.get_me()
        return {
            "user_id": me.id,
            "username": getattr(me, "username", None),
            "display_name": _display_title(me),
            "session_path": str(SESSION_PATH),
        }
    finally:
        await client.disconnect()


def _human(data: dict) -> None:
    un = f"@{data['username']}" if data["username"] else "(no username)"
    print(f"Logged in as {data['display_name']} ({un}) — id {data['user_id']}")
    print(f"Session saved to {data['session_path']}")


def run_login(args) -> int:
    return run_command(
        "login", args,
        runner=_runner,
        human_formatter=_human,
        audit_path=AUDIT_PATH,
    )
```

- [ ] **Step 2: Refactor `events.py`**

`listen` is long-running. The envelope only emits when the listener exits (Ctrl+C → KeyboardInterrupt re-raises through dispatch, so wrap the runner so KeyboardInterrupt is caught locally and turned into a clean return).

```python
"""Live event subcommands. Phase 1 port: listen."""
from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any

from telethon import events

from tgcli.client import make_client
from tgcli.commands._common import AUDIT_PATH, DB_PATH, SESSION_PATH, add_output_flags
from tgcli.commands.messages import (
    _display_title,
    _download_media,
    _upsert_chat,
    _upsert_message,
)
from tgcli.db import connect
from tgcli.dispatch import run_command


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("listen", help="Capture new incoming messages forever")
    p.add_argument("--notify", action="store_true",
                   help="Echo each incoming message to your own Saved Messages")
    p.add_argument("--download-media", action="store_true",
                   help="Also download photos / voice / video / documents to media/<chat_id>/")
    add_output_flags(p)
    p.set_defaults(func=run_listen)


async def _runner(args) -> dict[str, Any]:
    client = make_client(SESSION_PATH)
    await client.start()
    con = connect(DB_PATH)
    me = await client.get_me()
    counters = {"messages_seen": 0, "media_downloaded": 0, "errors": 0}
    print(f"Listening as {_display_title(me)} (id {me.id})")
    print(f"  notify={'ON (echo to Saved Messages)' if args.notify else 'OFF'}")
    print(f"  download_media={'ON' if args.download_media else 'OFF'}")
    print("  Ctrl+C to stop\n")

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        try:
            chat = await event.get_chat()
            sender = await event.get_sender()
            _upsert_chat(con, chat)
            if sender is not None and getattr(sender, "id", None) != getattr(chat, "id", None):
                _upsert_chat(con, sender)
            media_path = None
            if args.download_media and getattr(event.message, "media", None):
                media_path = await _download_media(client, event.message, event.chat_id)
                if media_path:
                    counters["media_downloaded"] += 1
            _upsert_message(con, event.message, event.chat_id, media_path=media_path)
            con.commit()
            counters["messages_seen"] += 1
            sender_name = _display_title(sender) if sender else "?"
            chat_name = _display_title(chat) if chat else "DM"
            preview = (event.text or "[media]").replace("\n", " ")[:200]
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"  [{ts}] {sender_name} in {chat_name}: {preview}")
            if args.notify:
                line = f"📨 {sender_name} ({chat_name}): {preview}"
                await client.send_message("me", line[:4000])
        except Exception as e:
            counters["errors"] += 1
            print(f"  ERROR: {e}")

    try:
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        pass
    finally:
        con.close()
        await client.disconnect()
    return counters


def _human(data: dict) -> None:
    print(f"\nListener stopped. Seen {data['messages_seen']} messages, "
          f"{data['media_downloaded']} media downloaded, {data['errors']} errors.")


def run_listen(args) -> int:
    return run_command(
        "listen", args,
        runner=lambda: _runner(args),
        human_formatter=_human,
        audit_path=AUDIT_PATH,
    )
```

Note: in JSON mode the listener still streams human progress lines to stdout — that breaks JSON parseability. Resolution: when `--json` is set, suppress the per-message prints. Add this guard inside `_runner`:

```python
quiet = bool(getattr(args, "json", False))
...
if not quiet:
    print(f"Listening as ...")
...
if not quiet:
    print(f"  [{ts}] {sender_name} in {chat_name}: {preview}")
```

- [ ] **Step 3: Smoke-test login**

```bash
./tg login --json | python -m json.tool
```

Expected: envelope with `data.user_id`, `data.display_name`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/tgcli -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tgcli/commands/auth.py tgcli/commands/events.py
git commit -m "feat(tgcli): login + listen via dispatch (Phase 2.9)"
```

---

## Task 10: Top-level catch-all in `__main__`

**Files:**
- Modify: `tgcli/__main__.py`

If a command's `run()` somehow returns without going through dispatch (shouldn't happen post-Phase 2, but hard guarantee against future regressions), or if argparse itself fails, we still want a uniform JSON envelope when stdout is not a TTY.

- [ ] **Step 1: Replace `tgcli/__main__.py`**

```python
"""Argparse dispatcher for the `tg` CLI."""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from importlib import import_module

from tgcli.commands._common import AUDIT_PATH, ENV_PATH
from tgcli.env import load_env_file
from tgcli.output import ExitCode, fail, is_tty_stdout, new_request_id
from tgcli.safety import audit_write

load_env_file(ENV_PATH)

COMMAND_MODULES: tuple[str, ...] = (
    "tgcli.commands.auth",
    "tgcli.commands.stats",
    "tgcli.commands.contacts",
    "tgcli.commands.messages",
    "tgcli.commands.chats",
    "tgcli.commands.events",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tg",
        description="Telegram agent CLI — read/write/listen against your own Telegram account.",
    )
    sub = parser.add_subparsers(dest="cmd")
    for mod_name in COMMAND_MODULES:
        import_module(mod_name).register(sub)
    return parser


def _emit_top_level_failure(msg: str, code: ExitCode) -> int:
    """Used only when something fails before any command's run() is reached."""
    request_id = new_request_id()
    env = fail("(top-level)", code, msg, request_id=request_id)
    if is_tty_stdout():
        print(f"ERROR [{code.name}]: {msg}", file=sys.stderr)
    else:
        print(json.dumps(env, ensure_ascii=False, default=str))
    try:
        audit_write(AUDIT_PATH, cmd="(top-level)", request_id=request_id,
                    args_repr={}, result="fail", error_code=code.name)
    except OSError:
        pass
    return code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        # argparse exits 2 for usage errors; preserve that contract.
        return int(e.code or 0)
    if not args.cmd:
        parser.print_help(sys.stderr)
        return 0
    try:
        result = args.func(args)
        if inspect.iscoroutine(result):
            return int(asyncio.run(result) or 0)
        return int(result or 0)
    except KeyboardInterrupt:
        return _emit_top_level_failure("Interrupted by user", ExitCode.GENERIC)
    except SystemExit:
        raise


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run tests**

Run: `.venv/bin/pytest tests/tgcli -q`
Expected: all green.

- [ ] **Step 3: Smoke-test bad usage**

```bash
./tg nonexistent-cmd; echo "exit=$?"
./tg --help
```

Expected: argparse usage error → exit 2; `--help` → exit 0.

- [ ] **Step 4: Commit**

```bash
git add tgcli/__main__.py
git commit -m "feat(tgcli): top-level fail-envelope guard in __main__ (Phase 2.10)"
```

---

## Task 11: Verification & polish

**Files:** none (verification only)

- [ ] **Step 1: Confirm full suite passes**

Run: `.venv/bin/pytest tests/tgcli -v`
Expected: all green; counts: 17 (Phase 1) + 9 (output) + 11 (safety, with BadArgs) + 11 (dispatch, with BadArgs param) + 2 (new smoke tests) = 50 tests.

- [ ] **Step 2: Live JSON smoke test**

```bash
./tg stats --json | python -c "import sys,json; e=json.load(sys.stdin); assert e['ok']; assert e['command']=='stats'; assert e['request_id'].startswith('req-'); print('stats ok')"
./tg contacts --json --limit 3 | python -c "import sys,json; e=json.load(sys.stdin); assert e['ok']; assert isinstance(e['data']['contacts'], list); print('contacts ok')"
```

Expected: prints `stats ok` and `contacts ok`.

- [ ] **Step 3: Verify audit log**

```bash
tail -5 audit.log | python -c "import sys,json; [print(json.loads(l)['cmd'], json.loads(l)['request_id'], json.loads(l)['result']) for l in sys.stdin]"
```

Expected: recent entries with command, request_id, and result columns.

- [ ] **Step 4: Verify exit-code contract**

```bash
TG_API_ID="" TG_API_HASH="" ./tg login --json; echo "exit=$?"   # expect exit=3, NOT_AUTHED
./tg stats --json; echo "exit=$?"                                # expect exit=0 (DB exists)
```

- [ ] **Step 5: Confirm `audit.log` is gitignored**

Run: `git status --short | grep -c audit.log`
Expected: `0` (no untracked audit.log appears).

- [ ] **Step 6: Final commit (only if any cleanup edits made above)**

Skip if there's nothing to commit. Otherwise:

```bash
git add -p
git commit -m "chore(tgcli): Phase 2 verification cleanup"
```

---

## Self-Review Checklist

Before declaring Phase 2 complete:

1. **Spec coverage** — every item in user's brief has a task:
   - JSON envelope → Task 1
   - Human envelope / formatter → Task 1 + every per-command task (5–9)
   - Exit codes → Task 1
   - Write/destructive gates → Task 2 + Task 3 (parser helpers; commands wired in Phase 5)
   - Audit log → Task 2 + Task 4 (dispatch writes per-invocation)
   - Request IDs → Task 1 + Task 4
   - `connect()` refactor (commands route through envelope) → Tasks 4–9
2. **No new third-party deps** — confirmed: only stdlib + Telethon (already present).
3. **TDD discipline** — Tasks 1, 2, 4 all start with failing tests before implementation.
4. **Backwards compatibility** — every command keeps its existing flags; human output for `stats` reproduces top-10 chats and media-by-type; no command's exit-code semantics regress.

---

## Out of Scope (deferred)

- **Streaming progress events** for long-running commands (`backfill`, `discover`, `listen`) — Phase 4 candidate; either stderr-JSONL or `--progress` flag.
- **Telegram-side write commands** (`send`, `mark-read`, `delete`, `edit`, `leave`, `block`) — Phase 5. The gates and parser helpers are ready; no command uses them yet.
- **Resolver / `--min-msgs` filter** — Phase 3.
- **Top-level `--request-id`** override (so callers can supply their own correlation ID) — easy to add when needed; not in scope for Phase 2.
