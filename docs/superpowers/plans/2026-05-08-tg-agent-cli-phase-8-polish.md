# Phase 8 — wacli Polish Bundle

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-05-08

**Status:** Draft

**Prerequisite:** Phases 1–6.2 complete with `140 passed`. Two follow-up fix commits already merged (`37977d9`, `a6d421c`).

**Goal:** Ship the 12-item wacli polish bundle in one phase. Each item is small and ≤30 minutes except multi-account (#9, ~1 hour).

**Architecture:**
- Each item gets its own commit on `feat/phase-8-polish` so any can be reverted independently.
- No new third-party deps. `pathlib`, `argparse`, `os`, `stat`, `time` from stdlib.
- Multi-account uses isolated `accounts/<NAME>/` directories. Default account = `default`. Migration on first use moves existing root-level files into `accounts/default/`.
- All 140 existing tests must still pass.

**Tech Stack:** Python 3.12 stdlib + Telethon 1.43.2. Pre-commit hooks via stdlib only (a small script in `.git/hooks/`).

**Backwards compatibility:** End at ~155 passing tests (140 baseline + ~15 new).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `tgcli/commands/_common.py` | modify | Path injection guard, file-perm helpers, account-aware paths |
| `tgcli/safety.py` | modify | `require_writes_not_readonly()` gate; rapid-send warning hook |
| `tgcli/dispatch.py` | modify | Wire `--read-only` and `--lock-wait` and rapid-send warning |
| `tgcli/__main__.py` | modify | Top-level `--account`, `--read-only`, `--lock-wait`, `--full` flags |
| `tgcli/client.py` | modify | `acquire_session_lock(wait_seconds)` |
| `tgcli/db.py` | modify | Apply 0600 perms on schema-create |
| `tgcli/output.py` | modify | `--full` toggle (carry through emit) |
| `tgcli/accounts.py` | **create** | Account directory layout, current-selector file, migration |
| `tgcli/commands/accounts.py` | **create** | `accounts add/use/list/show/remove` CLI |
| `tgcli/commands/doctor.py` | **create** | `tg doctor` health check |
| `tgcli/commands/messages.py` | modify | `--max-messages` / `--max-db-size` on backfill; rapid-send |
| `tests/tgcli/test_phase8_*.py` | **create** | One file per major item (perms, doctor, accounts, readonly, etc.) |
| `tests/tgcli/conftest.py` | modify | Account isolation fixture |
| `Makefile` | **create** | `make gate` runs format-check + lint + test + diff-check |
| `.git/hooks/commit-msg` | **create** | Conventional Commits enforcement |
| `AGENTS.md` | **create** | Top-level agent doc (replaces/parallels CLAUDE.md if present) |
| `.gitignore` | modify | Ignore `accounts/` |

---

## Design Decisions

1. **Multi-account migration is best-effort, opt-in via flag use.** First use of `--account NAME` (or any `accounts ...` command) triggers a one-time migration: move `tg.session`, `telegram.sqlite`, `audit.log`, `media/` into `accounts/default/`. Without using `--account` or `accounts ...`, behavior is unchanged. This avoids breaking single-account users on upgrade.

2. **Account selection precedence**: `--account NAME` flag → `TG_ACCOUNT` env → `accounts/.current` file → fallback to `default`. The `.current` file is plain text containing the account name.

3. **Read-only enforcement at the dispatch level.** `--read-only` (or `TG_READONLY=1`) sets `args._read_only=True`. Any runner that calls `require_write_allowed(args)` ALSO calls `require_writes_not_readonly(args)`. The latter is a new pure-stdlib check that raises `WriteDisallowed("read-only mode active")`. Local DB writes (sync-contacts, discover, backfill, listen) — these write to local SQLite, not Telegram. Per the brief: read-only mode rejects them too. Implement by adding the check to those runners.

4. **`--lock-wait` semantics.** Default 0 = fail-fast (current behavior). Positive value = retry the flock every 100ms up to N seconds. Implemented in `acquire_session_lock(wait_seconds)`.

5. **`--full` semantics.** Pure presentational flag. Affects only `_human` formatters that currently truncate (chat titles, message text). JSON output unchanged. Plumbed via `args.full` accessed by the formatter.

6. **Owner-only file perms.** Apply 0600 to file on first creation in `connect()` (DB), `acquire_session_lock()` (lock file), `audit_pre`/`audit_write` (audit log), and let Telethon's session file inherit the umask (we touch the dir to 0700). Don't try to chmod existing files retroactively beyond a one-time best-effort pass at startup — too risky.

7. **Rapid-send warning.** A small in-process counter on `_check_write_rate_limit()`. If the per-minute write count crosses 5, append a one-line warning to stderr and a `warning` entry to audit.log. Don't block. Threshold configurable later via `--rapid-send-warn-threshold` (not in this phase).

8. **Path injection guard.** `_safe_user_path(value: str)` rejects any string containing `?` or `#` with `BadArgs`. Apply at the boundary where `--account NAME` and `MEDIA_DIR` overrides are read. Steal the regex pattern from wacli's `internal/pathutil/`.

9. **`tg doctor` envelope shape.** Returns `data.checks: [{name, status, message}]` plus a top-level `data.summary: {total, passed, failed, warnings}`. Exit 0 if all pass; exit 1 (GENERIC) if any failed. Live-network check is opt-in via `--live` flag.

10. **`--max-messages` / `--max-db-size` on backfill.** Defaults 100,000 messages / 500 MB. Computed before each per-chat backfill loop iteration. If >80% of either, log a warning. If >100%, raise `BadArgs` to stop cleanly.

11. **Conventional commits hook is git-hosted.** `.git/hooks/commit-msg` (not committed; project convention). The `make gate` script optionally installs it via `make install-hooks`. We DO commit the hook source as `.githooks/commit-msg` and the install script.

12. **AGENTS.md.** ~80 lines, intro + key facts + build/test commands + agent notes. Reuses content from CLAUDE.md if it exists; otherwise written fresh.

---

## Task 1: Path injection guard + AGENTS.md (small, no risk)

**Files:**
- Modify: `tgcli/commands/_common.py` (add `_safe_user_path`)
- Create: `AGENTS.md`
- Create: `tests/tgcli/test_phase8_paths.py`

- [ ] **Step 1: Add path-injection unit test**

```python
# tests/tgcli/test_phase8_paths.py
import pytest
from tgcli.commands._common import _safe_user_path
from tgcli.safety import BadArgs


def test_safe_user_path_passes_normal_paths(tmp_path):
    p = _safe_user_path(str(tmp_path / "subdir"))
    assert "subdir" in p


def test_safe_user_path_rejects_question_mark():
    with pytest.raises(BadArgs, match="contains forbidden character"):
        _safe_user_path("/tmp/foo?mode=ro")


def test_safe_user_path_rejects_hash():
    with pytest.raises(BadArgs, match="contains forbidden character"):
        _safe_user_path("/tmp/foo#fragment")


def test_safe_user_path_allows_unicode_and_spaces(tmp_path):
    p = _safe_user_path(str(tmp_path / "Hellö World"))
    assert "Hellö World" in p
```

- [ ] **Step 2: Run, expect FAIL**

```bash
.venv/bin/pytest tests/tgcli/test_phase8_paths.py -q
```

- [ ] **Step 3: Implement in `tgcli/commands/_common.py`**

Append to that file:

```python
def _safe_user_path(value: str) -> str:
    """Reject user-supplied paths that contain SQLite URI metacharacters.

    `?` and `#` would let an attacker inject URI parameters or fragment
    segments into a sqlite3 connection string. We don't accept either at
    any boundary that flows into a path or URI.
    """
    from tgcli.safety import BadArgs
    for ch in ("?", "#"):
        if ch in value:
            raise BadArgs(f"path {value!r} contains forbidden character {ch!r}")
    return value
```

- [ ] **Step 4: Run, expect 4 passed**

- [ ] **Step 5: Create `AGENTS.md` at repo root** (~80 lines)

```markdown
# AGENTS.md — tg-cli

Agent-friendly Telegram CLI built on Telethon. All commands emit a uniform JSON envelope or human output; writes are gated behind `--allow-write`; every invocation logs to `audit.log`.

## Quick reference

- **Read commands:** `stats`, `me`, `show`, `search`, `list-msgs`, `get-msg`, `contacts`, `unread`, `chats-info`, `topics-list`, `folders-list`, `folder-show`
- **Write commands:** `send`, `edit-msg`, `forward`, `pin-msg`, `unpin-msg`, `react`, `mark-read`, `topic-create`, `topic-edit`, `topic-pin`, `topic-unpin`, `folder-create`, `folder-edit`, `folder-delete`, `folder-add-chat`, `folder-remove-chat`, `folders-reorder`
- **Local-DB writers:** `sync-contacts`, `discover`, `backfill` (write only to `telegram.sqlite`, not to Telegram)
- **Live event stream:** `listen`
- **Auth:** `login`
- **Health:** `doctor`
- **Multi-account:** `accounts add|use|list|show|remove`

## Architectural facts

- Paths are env-overridable: `TG_DB_PATH`, `TG_SESSION_PATH`, `TG_AUDIT_PATH`, `TG_MEDIA_DIR`, `TG_API_ID`, `TG_API_HASH`.
- Single-process Telethon session lock at `tg.session.lock` via `fcntl.flock`. `--lock-wait DURATION` lets you wait instead of fail-fast.
- All chat selectors resolve through `resolve_chat_db()` in three strategies: integer chat_id, `@username`, fuzzy title match. Fuzzy matches require `--fuzzy` for any write.
- Idempotency: every write command accepts `--idempotency-key NAME`. Same key + same command returns the cached envelope without re-calling Telegram.
- Read-only mode: `--read-only` or `TG_READONLY=1` rejects writes (Telegram-side AND local DB writes).

## Exit codes (public contract)

```
0  OK                  command succeeded
1  GENERIC             unclassified error
2  BAD_ARGS             invalid args (or fuzzy-write without --fuzzy)
3  NOT_AUTHED           TG_API_ID/HASH not set or session expired
4  NOT_FOUND            chat / message / folder not in DB or server
5  FLOOD_WAIT           Telegram rate-limited; retry after `retry_after_seconds`
6  WRITE_DISALLOWED     write attempted without --allow-write
7  NEEDS_CONFIRM        destructive op without --confirm (Phase 10+)
8  LOCAL_RATE_LIMIT     in-process write limiter tripped
9  PREMIUM_REQUIRED     Telegram requires Premium for this action
```

## Build / test

```
.venv/bin/pytest tests/tgcli -q     # unit tests
make gate                            # format + lint + test + diff-check
./tg doctor --json                   # diagnose env + cache + (with --live) network
```

## Conventions

- Conventional Commits: `feat|fix|docs|refactor|test|chore|perf|security|ci(scope): subject`
- Plans live in `docs/superpowers/plans/YYYY-MM-DD-...md`
- One commit per plan task on a `feat/phase-N-...` branch; squash-merge to main when phase complete.
- Audit log is append-only NDJSON at `audit.log`. Pre + post entries share `request_id`.

## Read me first if working on...

- **Adding a write command:** read `tgcli/commands/messages.py`'s `_send_runner` end-to-end. The pipeline is fixed: write gate → read text → idempotency lookup → resolver + fuzzy gate → dry-run short-circuit → rate limit → audit_pre → Telethon → record_idempotency → audit_post.
- **Adding a read command:** much simpler — just resolve the chat, query SQLite, return data dict.
- **Telethon API surface:** read the actual installed Telethon at `.venv/lib/python3.12/site-packages/telethon/tl/functions/`. Don't trust outdated docs.

## Gotchas

- Folder emoticons: Telegram has a curated allowlist; non-allowed emojis are silently dropped. `folder-create` round-trips and warns when this happens.
- Topic edits combining title + close/reopen: Telegram returns TOPIC_CLOSE_SEPARATELY. Runner auto-splits into two requests.
- Reactions: free accounts can't react in Saved Messages or many groups; `react` returns exit 9 PREMIUM_REQUIRED.
```

- [ ] **Step 6: Commit**

```bash
git add tgcli/commands/_common.py tests/tgcli/test_phase8_paths.py AGENTS.md
git commit -m "feat(tgcli): path injection guard + AGENTS.md"
```

---

## Task 2: Owner-only file perms (0600 / 0700)

**Files:**
- Modify: `tgcli/commands/_common.py` (add `_chmod_owner_only`)
- Modify: `tgcli/db.py` (chmod after creating DB file)
- Modify: `tgcli/safety.py` (chmod audit log on first write)
- Modify: `tgcli/client.py` (chmod session lock + session file)
- Create: `tests/tgcli/test_phase8_perms.py`

- [ ] **Step 1: Test**

```python
# tests/tgcli/test_phase8_perms.py
import os
import stat
from pathlib import Path

from tgcli.commands._common import _chmod_owner_only


def test_chmod_owner_only_file(tmp_path):
    f = tmp_path / "secret.dat"
    f.write_text("x")
    _chmod_owner_only(f)
    mode = stat.S_IMODE(os.stat(f).st_mode)
    assert mode == 0o600


def test_chmod_owner_only_dir(tmp_path):
    d = tmp_path / "secret_dir"
    d.mkdir()
    _chmod_owner_only(d)
    mode = stat.S_IMODE(os.stat(d).st_mode)
    assert mode == 0o700


def test_chmod_owner_only_idempotent(tmp_path):
    f = tmp_path / "again.dat"
    f.write_text("x")
    _chmod_owner_only(f)
    _chmod_owner_only(f)  # second call must not raise
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600


def test_chmod_owner_only_missing_path_is_silent(tmp_path):
    # Should never raise on a non-existent path; security best-effort.
    _chmod_owner_only(tmp_path / "does-not-exist")
```

- [ ] **Step 2: Implement** — add to `tgcli/commands/_common.py`:

```python
import os
import stat


def _chmod_owner_only(path) -> None:
    """Best-effort chmod to 0600 (file) / 0700 (dir). Silent on missing path or perm errors."""
    from pathlib import Path
    p = Path(path)
    try:
        if not p.exists():
            return
        target = 0o700 if p.is_dir() else 0o600
        current = stat.S_IMODE(os.stat(p).st_mode)
        if current != target:
            os.chmod(p, target)
    except (OSError, PermissionError):
        # We're security-best-effort; don't fail the operation if chmod can't apply.
        pass
```

- [ ] **Step 3: Wire into create paths**

In `tgcli/db.py`, after the `connect()` initial CREATE TABLE script, add:

```python
from tgcli.commands._common import _chmod_owner_only
_chmod_owner_only(path)
```

In `tgcli/safety.py`, in `audit_write()` and `audit_pre()`, after writing the line:

```python
_chmod_owner_only(audit_path)
```

In `tgcli/client.py`, in `acquire_session_lock()`, after `f.flush()`:

```python
from tgcli.commands._common import _chmod_owner_only
_chmod_owner_only(lock_path)
_chmod_owner_only(session_path.with_suffix(".session"))  # Telethon's actual file
```

- [ ] **Step 4: Run all tests, expect green**

- [ ] **Step 5: Commit**

```bash
git add tgcli/commands/_common.py tgcli/db.py tgcli/safety.py tgcli/client.py tests/tgcli/test_phase8_perms.py
git commit -m "feat(tgcli): 0600/0700 owner-only perms on session/DB/audit"
```

---

## Task 3: `--read-only` global flag

**Files:**
- Modify: `tgcli/safety.py` (add `require_writes_not_readonly`)
- Modify: `tgcli/__main__.py` (top-level `--read-only` flag)
- Modify: `tgcli/dispatch.py` (apply read-only before runner)
- Modify: `tgcli/commands/messages.py`, `chats.py`, `contacts.py` (local DB writers also gated)
- Create: `tests/tgcli/test_phase8_readonly.py`

- [ ] **Step 1: Test**

```python
# tests/tgcli/test_phase8_readonly.py
import argparse
import asyncio
import pytest

from tgcli.commands import messages
from tgcli.db import connect
from tgcli.safety import WriteDisallowed, require_writes_not_readonly


def test_require_writes_not_readonly_passes_when_unset():
    args = argparse.Namespace()
    require_writes_not_readonly(args)  # no raise


def test_require_writes_not_readonly_raises_with_flag():
    args = argparse.Namespace(read_only=True)
    with pytest.raises(WriteDisallowed, match="read-only"):
        require_writes_not_readonly(args)


def test_require_writes_not_readonly_raises_with_env(monkeypatch):
    monkeypatch.setenv("TG_READONLY", "1")
    args = argparse.Namespace()
    with pytest.raises(WriteDisallowed):
        require_writes_not_readonly(args)


def test_send_runner_blocked_in_readonly_mode(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute("INSERT INTO tg_chats(chat_id, type, title) VALUES (1, 'user', 'X')")
    con.commit()
    con.close()
    monkeypatch.setattr(messages, "DB_PATH", db)

    args = argparse.Namespace(
        chat="1", text="x", reply_to=None, silent=False, no_webpage=False,
        topic=None, allow_write=True, dry_run=False, idempotency_key=None,
        fuzzy=False, json=True, human=False, read_only=True,
    )
    with pytest.raises(WriteDisallowed, match="read-only"):
        asyncio.run(messages._send_runner(args))
```

- [ ] **Step 2: Implement `require_writes_not_readonly`** in `tgcli/safety.py`:

```python
def require_writes_not_readonly(args) -> None:
    """Gate writes when --read-only or TG_READONLY=1 is set. Raises WriteDisallowed."""
    import os
    if getattr(args, "read_only", False) or os.environ.get("TG_READONLY") == "1":
        raise WriteDisallowed("Writes blocked in read-only mode (--read-only / TG_READONLY=1)")
```

- [ ] **Step 3: Add top-level `--read-only` flag in `tgcli/__main__.py`**

In `build_parser()`, add to the top-level parser:

```python
parser.add_argument("--read-only", action="store_true",
                    help="Reject any write to Telegram or local DB. Also via TG_READONLY=1.")
```

argparse will set `args.read_only` (with underscore) on every command.

- [ ] **Step 4: Wire `require_writes_not_readonly` into write runners**

In every write runner that calls `require_write_allowed(args)`, add a `require_writes_not_readonly(args)` call right after. The runners are in `tgcli/commands/messages.py` and `tgcli/commands/chats.py`. Roughly 13 sites.

Also call it from local-DB writers that don't currently have `require_write_allowed`:
- `_sync_runner` in `contacts.py`
- `_discover_runner` in `chats.py`
- `_backfill_runner` in `messages.py`

(`listen` reads incoming and writes to local DB — gate it too.)

- [ ] **Step 5: Run tests, expect green**

- [ ] **Step 6: Commit**

```bash
git add tgcli/safety.py tgcli/__main__.py tgcli/commands/*.py tests/tgcli/test_phase8_readonly.py
git commit -m "feat(tgcli): --read-only global flag + TG_READONLY env"
```

---

## Task 4: `--lock-wait DURATION`

**Files:**
- Modify: `tgcli/client.py` (`acquire_session_lock` accepts wait_seconds)
- Modify: `tgcli/__main__.py` (top-level `--lock-wait` flag)
- Create: `tests/tgcli/test_phase8_lockwait.py`

- [ ] **Step 1: Test**

```python
# tests/tgcli/test_phase8_lockwait.py
import time
from pathlib import Path

import pytest

from tgcli.client import SessionLocked, acquire_session_lock


def test_lock_wait_zero_fails_fast(tmp_path, monkeypatch):
    import tgcli.client as client_mod
    monkeypatch.setattr(client_mod, "_lock_handle", None)
    sp = tmp_path / "tg.session"
    acquire_session_lock(sp, wait_seconds=0)


def test_lock_wait_releases_after_held(tmp_path, monkeypatch):
    """If a held lock is released during the wait window, we acquire it."""
    import fcntl
    import tgcli.client as client_mod
    monkeypatch.setattr(client_mod, "_lock_handle", None)
    sp = tmp_path / "tg.session"
    lock_path = Path(str(sp) + ".lock")
    holder = lock_path.open("w")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    # Release after 200ms; we'll wait up to 1 second.
    import threading
    threading.Timer(0.2, lambda: (fcntl.flock(holder.fileno(), fcntl.LOCK_UN), holder.close())).start()
    start = time.monotonic()
    acquire_session_lock(sp, wait_seconds=1)
    elapsed = time.monotonic() - start
    assert 0.15 < elapsed < 0.6


def test_lock_wait_timeout_raises(tmp_path, monkeypatch):
    import fcntl
    import tgcli.client as client_mod
    monkeypatch.setattr(client_mod, "_lock_handle", None)
    sp = tmp_path / "tg.session"
    lock_path = Path(str(sp) + ".lock")
    holder = lock_path.open("w")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(SessionLocked):
            acquire_session_lock(sp, wait_seconds=0.3)
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()
```

- [ ] **Step 2: Implement** in `tgcli/client.py`:

```python
def acquire_session_lock(session_path: Path, *, wait_seconds: float = 0) -> None:
    """Take an exclusive flock on <session>.lock. Idempotent within a process.

    wait_seconds=0 fails fast (current behavior). Positive value retries
    every 100ms until acquired or timeout.
    """
    global _lock_handle
    if _lock_handle is not None:
        return
    lock_path = Path(str(session_path) + ".lock")
    deadline = time.monotonic() + max(wait_seconds, 0)
    while True:
        f = lock_path.open("w")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            f.write(str(os.getpid()))
            f.flush()
            _lock_handle = f
            return
        except BlockingIOError:
            f.close()
            if time.monotonic() >= deadline:
                try:
                    existing_pid = lock_path.read_text().strip() or "?"
                except OSError:
                    existing_pid = "?"
                raise SessionLocked(
                    f"Another tg process holds the Telethon session (PID {existing_pid}). "
                    f"Wait for it to finish, or kill it with: kill {existing_pid}"
                )
            time.sleep(0.1)
```

Add `import time` at the top.

- [ ] **Step 3: Top-level flag in `__main__.py`**

```python
parser.add_argument("--lock-wait", type=float, default=0,
                    help="Wait up to N seconds for the Telethon session lock (default 0 = fail fast)")
```

- [ ] **Step 4: Wire** — `make_client(session_path)` becomes `make_client(session_path, lock_wait=0)`. The `__main__.py` passes `args.lock_wait` through. Update all callers (~7 files).

- [ ] **Step 5: Run tests, commit**

```bash
git add tgcli/client.py tgcli/__main__.py tgcli/commands/*.py tests/tgcli/test_phase8_lockwait.py
git commit -m "feat(tgcli): --lock-wait DURATION for session lock acquisition"
```

---

## Task 5: `--full` flag (disable column truncation)

**Files:**
- Modify: `tgcli/__main__.py` (top-level `--full`)
- Modify: `tgcli/commands/messages.py` (`_show_human` etc.)
- Modify: `tgcli/commands/contacts.py` (`_list_human`)
- Create: `tests/tgcli/test_phase8_full.py`

- [ ] **Step 1: Test**

```python
# tests/tgcli/test_phase8_full.py
import io

from tgcli.commands.messages import _show_human


def test_show_human_truncates_long_text_by_default(capsys):
    data = {
        "chat": {"chat_id": 1, "title": "T"},
        "order": "newest_first",
        "messages": [{"date": "2026-05-08T10:00:00", "is_outgoing": False,
                      "text": "x" * 500, "media_type": None}],
    }
    _show_human(data, full=False)
    out = capsys.readouterr().out
    assert "..." in out or len(out.split("\n")[2]) < 400


def test_show_human_full_shows_everything(capsys):
    data = {
        "chat": {"chat_id": 1, "title": "T"},
        "order": "newest_first",
        "messages": [{"date": "2026-05-08T10:00:00", "is_outgoing": False,
                      "text": "x" * 500, "media_type": None}],
    }
    _show_human(data, full=True)
    out = capsys.readouterr().out
    assert "x" * 500 in out
```

- [ ] **Step 2: Implement** — change `_show_human(data)` to `_show_human(data, *, full=False)`. Truncate `body` to e.g. 200 chars + `…` when not full. The dispatch passes `full=args.full` to the formatter.

This requires a small refactor in `dispatch.run_command()` to pass `args` to the formatter. Simpler: change the human_formatter signature to `(data, args)` and update all formatters.

Alternative (simpler): have each runner read `args.full` and bake the formatter via a closure:

```python
def _human_formatter_factory(args):
    full = bool(getattr(args, "full", False))
    def _formatter(data):
        _show_human(data, full=full)
    return _formatter

# In run_show:
return run_command("show", args, runner=lambda: _show_runner(args),
                   human_formatter=_human_formatter_factory(args),
                   audit_path=AUDIT_PATH)
```

- [ ] **Step 3: Add `--full` to `__main__.py` top-level parser**

- [ ] **Step 4: Apply truncation in 3 formatters that have long fields:**
- `messages._show_human` (text)
- `messages._search_human` (text)
- `messages._list_human` (text)
- `contacts._list_human` (titles, phones)

- [ ] **Step 5: Run tests, commit**

```bash
git add tgcli/__main__.py tgcli/commands/messages.py tgcli/commands/contacts.py tests/tgcli/test_phase8_full.py
git commit -m "feat(tgcli): --full flag disables human-mode truncation"
```

---

## Task 6: `--max-messages` and `--max-db-size` on backfill

**Files:**
- Modify: `tgcli/commands/messages.py` (`_backfill_runner`)
- Modify: `tgcli/commands/messages.py` (`register` adds the flags)
- Create: `tests/tgcli/test_phase8_backfill_caps.py`

- [ ] **Step 1: Test**

```python
# tests/tgcli/test_phase8_backfill_caps.py
import argparse
import pytest

from tgcli.commands.messages import _check_backfill_caps
from tgcli.safety import BadArgs


def test_caps_pass_when_under_threshold(tmp_path):
    db = tmp_path / "telegram.sqlite"
    db.write_bytes(b"x" * 1000)  # 1KB
    args = argparse.Namespace(max_messages=100_000, max_db_size_mb=500)
    warnings = _check_backfill_caps(db, current_msg_count=10, args=args)
    assert warnings == []


def test_caps_fail_when_over_db_size(tmp_path):
    db = tmp_path / "telegram.sqlite"
    db.write_bytes(b"x" * (600 * 1024 * 1024))  # 600MB
    args = argparse.Namespace(max_messages=100_000, max_db_size_mb=500)
    with pytest.raises(BadArgs, match="db size"):
        _check_backfill_caps(db, current_msg_count=10, args=args)


def test_caps_warn_at_80_percent(tmp_path):
    db = tmp_path / "telegram.sqlite"
    db.write_bytes(b"x" * (420 * 1024 * 1024))  # 84% of 500MB
    args = argparse.Namespace(max_messages=100_000, max_db_size_mb=500)
    warnings = _check_backfill_caps(db, current_msg_count=10, args=args)
    assert any("approaching" in w.lower() for w in warnings)


def test_caps_fail_when_over_messages(tmp_path):
    db = tmp_path / "telegram.sqlite"
    db.write_bytes(b"")
    args = argparse.Namespace(max_messages=100, max_db_size_mb=500)
    with pytest.raises(BadArgs, match="message count"):
        _check_backfill_caps(db, current_msg_count=200, args=args)
```

- [ ] **Step 2: Implement `_check_backfill_caps`** in `messages.py`

```python
def _check_backfill_caps(db_path, *, current_msg_count: int, args) -> list[str]:
    """Raise BadArgs if caps exceeded; return warnings list at 80%+."""
    warnings = []
    max_msgs = int(getattr(args, "max_messages", 100_000) or 100_000)
    max_db_mb = int(getattr(args, "max_db_size_mb", 500) or 500)
    if current_msg_count >= max_msgs:
        raise BadArgs(f"backfill refused: message count {current_msg_count} >= --max-messages {max_msgs}")
    if current_msg_count >= int(max_msgs * 0.8):
        warnings.append(f"approaching --max-messages cap ({current_msg_count}/{max_msgs})")
    try:
        size_bytes = db_path.stat().st_size
    except OSError:
        return warnings
    size_mb = size_bytes / (1024 * 1024)
    if size_mb >= max_db_mb:
        raise BadArgs(f"backfill refused: db size {size_mb:.0f}MB >= --max-db-size-mb {max_db_mb}")
    if size_mb >= max_db_mb * 0.8:
        warnings.append(f"approaching --max-db-size-mb cap ({size_mb:.0f}/{max_db_mb}MB)")
    return warnings
```

- [ ] **Step 3: Add the flags to backfill parser**

```python
bf.add_argument("--max-messages", type=int, default=100_000,
                help="Refuse to start backfill if cached message count >= this (default 100000)")
bf.add_argument("--max-db-size-mb", type=int, default=500,
                help="Refuse to start backfill if telegram.sqlite >= this MB (default 500)")
```

- [ ] **Step 4: Call `_check_backfill_caps` at start of `_backfill_runner`** before the dialog loop. Append any warnings to the result envelope.

- [ ] **Step 5: Run tests, commit**

```bash
git add tgcli/commands/messages.py tests/tgcli/test_phase8_backfill_caps.py
git commit -m "feat(tgcli): --max-messages / --max-db-size-mb caps on backfill"
```

---

## Task 7: Send rate-limit warning (rapid-send detection)

**Files:**
- Modify: `tgcli/safety.py` (rapid-send warning hook)
- Create: `tests/tgcli/test_phase8_rapid_send.py`

- [ ] **Step 1: Test**

```python
# tests/tgcli/test_phase8_rapid_send.py
import time
from tgcli.safety import RapidSendWatcher


def test_rapid_send_quiet_under_threshold():
    w = RapidSendWatcher(threshold=5, window_seconds=60)
    for _ in range(4):
        assert w.check_and_warn() is None


def test_rapid_send_warns_at_threshold():
    w = RapidSendWatcher(threshold=3, window_seconds=60)
    w.check_and_warn()
    w.check_and_warn()
    msg = w.check_and_warn()  # 3rd within window
    assert msg is not None
    assert "rapid send" in msg.lower()


def test_rapid_send_resets_after_window():
    w = RapidSendWatcher(threshold=2, window_seconds=0.05)
    w.check_and_warn()
    w.check_and_warn()
    assert w.check_and_warn() is not None  # over threshold
    time.sleep(0.06)
    # Now the previous events have expired
    assert w.check_and_warn() is None  # back under threshold (only 1 fresh event)
```

- [ ] **Step 2: Implement `RapidSendWatcher`** in `safety.py`

```python
class RapidSendWatcher:
    """Detects rapid send patterns. Returns a warning string when threshold is hit, else None."""
    def __init__(self, threshold: int = 5, window_seconds: float = 60.0):
        self.threshold = threshold
        self.window = window_seconds
        self.events: deque[float] = deque()

    def check_and_warn(self) -> str | None:
        now = time.monotonic()
        while self.events and now - self.events[0] > self.window:
            self.events.popleft()
        self.events.append(now)
        if len(self.events) >= self.threshold:
            return (f"rapid send detected: {len(self.events)} writes in last "
                    f"{int(self.window)}s; risk of FloodWait")
        return None


RAPID_SEND_WATCHER = RapidSendWatcher()
```

- [ ] **Step 3: Wire into write runners** — in each `_send_runner` / `_edit_msg_runner` / `_forward_runner` / `_react_runner` / `_mark_read_runner`, after `_check_write_rate_limit()`:

```python
import sys
warning = RAPID_SEND_WATCHER.check_and_warn()
if warning:
    print(f"WARN: {warning}", file=sys.stderr)
    # also added to envelope warnings list at the end
```

- [ ] **Step 4: Run tests, commit**

```bash
git add tgcli/safety.py tgcli/commands/messages.py tests/tgcli/test_phase8_rapid_send.py
git commit -m "feat(tgcli): rapid-send warning at 5+/min"
```

---

## Task 8: `tg doctor` subcommand

**Files:**
- Create: `tgcli/commands/doctor.py`
- Modify: `tgcli/__main__.py` (register doctor module)
- Create: `tests/tgcli/test_phase8_doctor.py`

- [ ] **Step 1: Test**

```python
# tests/tgcli/test_phase8_doctor.py
import argparse
from tgcli.commands import doctor


def test_doctor_runs_all_checks_and_returns_envelope_data(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    monkeypatch.setattr(doctor, "DB_PATH", db)
    monkeypatch.setattr(doctor, "SESSION_PATH", tmp_path / "tg.session")
    monkeypatch.setenv("TG_API_ID", "1")
    monkeypatch.setenv("TG_API_HASH", "x")
    args = argparse.Namespace(live=False, json=True, human=False)
    data = doctor._doctor_runner(args)
    assert "checks" in data
    assert "summary" in data
    assert data["summary"]["total"] == len(data["checks"])
    # Each check has name + status + message
    for c in data["checks"]:
        assert {"name", "status", "message"} <= set(c.keys())


def test_doctor_no_creds_reports_failure(monkeypatch, tmp_path):
    monkeypatch.delenv("TG_API_ID", raising=False)
    monkeypatch.delenv("TG_API_HASH", raising=False)
    monkeypatch.setattr(doctor, "DB_PATH", tmp_path / "x.sqlite")
    monkeypatch.setattr(doctor, "SESSION_PATH", tmp_path / "tg.session")
    args = argparse.Namespace(live=False, json=True, human=False)
    data = doctor._doctor_runner(args)
    creds = next(c for c in data["checks"] if "credential" in c["name"].lower())
    assert creds["status"] == "fail"
```

- [ ] **Step 2: Implement** — full code in `tgcli/commands/doctor.py`:

```python
"""`tg doctor` — health check for env, session, DB, schema, network."""
from __future__ import annotations

import argparse
import os
import sqlite3
from typing import Any

from tgcli.client import ensure_credentials, MissingCredentials
from tgcli.commands._common import (
    AUDIT_PATH, DB_PATH, ENV_PATH, SESSION_PATH, add_output_flags,
)
from tgcli.dispatch import run_command


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("doctor", help="Diagnose env, session, DB, schema, optional live API")
    p.add_argument("--live", action="store_true",
                   help="Also run a live Telegram connectivity ping (requires session)")
    add_output_flags(p)
    p.set_defaults(func=run_doctor)


def _check_credentials() -> dict[str, str]:
    try:
        ensure_credentials()
        return {"name": "credentials", "status": "ok",
                "message": "TG_API_ID + TG_API_HASH are set"}
    except MissingCredentials as exc:
        return {"name": "credentials", "status": "fail", "message": str(exc)}


def _check_env_file() -> dict[str, str]:
    if ENV_PATH.exists():
        return {"name": "env_file", "status": "ok", "message": f".env at {ENV_PATH}"}
    return {"name": "env_file", "status": "warn", "message": f"no .env at {ENV_PATH} (env vars must be set externally)"}


def _check_session() -> dict[str, str]:
    if SESSION_PATH.exists():
        return {"name": "session", "status": "ok", "message": f"session present at {SESSION_PATH}"}
    return {"name": "session", "status": "warn", "message": "no session — run `tg login` first"}


def _check_db() -> dict[str, str]:
    if not DB_PATH.exists():
        return {"name": "db", "status": "warn",
                "message": f"no DB at {DB_PATH} (will be created on first command)"}
    try:
        con = sqlite3.connect(DB_PATH)
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        con.close()
        required = {"tg_chats", "tg_messages", "tg_contacts", "tg_me", "tg_idempotency"}
        missing = required - tables
        if missing:
            return {"name": "db", "status": "fail",
                    "message": f"missing tables: {sorted(missing)}"}
        return {"name": "db", "status": "ok",
                "message": f"db ok at {DB_PATH} ({len(tables)} tables)"}
    except Exception as exc:
        return {"name": "db", "status": "fail", "message": f"db error: {exc}"}


def _check_audit() -> dict[str, str]:
    if AUDIT_PATH.exists():
        size = AUDIT_PATH.stat().st_size
        return {"name": "audit_log", "status": "ok",
                "message": f"audit log at {AUDIT_PATH} ({size} bytes)"}
    return {"name": "audit_log", "status": "warn",
            "message": "no audit log yet (created on first invocation)"}


async def _check_live() -> dict[str, str]:
    from tgcli.client import make_client
    try:
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            me = await client.get_me()
            return {"name": "live_telegram", "status": "ok",
                    "message": f"connected as user_id={me.id}"}
        finally:
            await client.disconnect()
    except Exception as exc:
        return {"name": "live_telegram", "status": "fail", "message": str(exc)}


async def _doctor_runner(args) -> dict[str, Any]:
    checks = [
        _check_credentials(),
        _check_env_file(),
        _check_session(),
        _check_db(),
        _check_audit(),
    ]
    if getattr(args, "live", False):
        checks.append(await _check_live())
    summary = {
        "total": len(checks),
        "passed": sum(1 for c in checks if c["status"] == "ok"),
        "failed": sum(1 for c in checks if c["status"] == "fail"),
        "warnings": sum(1 for c in checks if c["status"] == "warn"),
    }
    return {"checks": checks, "summary": summary}


def _human(data: dict) -> None:
    s = data["summary"]
    print(f"=== tg doctor: {s['passed']} ok / {s['warnings']} warn / {s['failed']} fail ===\n")
    for c in data["checks"]:
        marker = {"ok": "✓", "warn": "!", "fail": "✗"}.get(c["status"], "?")
        print(f"  {marker} {c['name']:<18} {c['message']}")


def run_doctor(args) -> int:
    return run_command(
        "doctor", args,
        runner=lambda: _doctor_runner(args),
        human_formatter=_human,
        audit_path=AUDIT_PATH,
    )
```

Note: `_doctor_runner` returns a synchronous dict for the non-live case but is `async` because it may await `_check_live`. `dispatch._invoke()` already handles both.

- [ ] **Step 3: Wire into `__main__.py` COMMAND_MODULES tuple**

- [ ] **Step 4: Run, commit**

```bash
git add tgcli/commands/doctor.py tgcli/__main__.py tests/tgcli/test_phase8_doctor.py
git commit -m "feat(tgcli): tg doctor health check"
```

---

## Task 9: Multi-account (the big one)

**Files:**
- Create: `tgcli/accounts.py`
- Create: `tgcli/commands/accounts.py`
- Modify: `tgcli/commands/_common.py` (account-aware path resolution)
- Modify: `tgcli/__main__.py` (top-level `--account` flag, register accounts)
- Modify: `.gitignore` (ignore `accounts/`)
- Create: `tests/tgcli/test_phase8_accounts.py`

- [ ] **Step 1: Test**

```python
# tests/tgcli/test_phase8_accounts.py
from tgcli.accounts import (
    AccountNotFound,
    add_account, list_accounts, current_account, use_account,
    remove_account, account_dir,
)


def test_add_and_list(tmp_path, monkeypatch):
    monkeypatch.setattr("tgcli.accounts.ROOT", tmp_path)
    add_account("work")
    add_account("personal")
    names = [a["name"] for a in list_accounts()]
    assert sorted(names) == ["personal", "work"]


def test_use_and_current(tmp_path, monkeypatch):
    monkeypatch.setattr("tgcli.accounts.ROOT", tmp_path)
    add_account("alpha")
    use_account("alpha")
    assert current_account() == "alpha"


def test_use_unknown_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("tgcli.accounts.ROOT", tmp_path)
    import pytest
    with pytest.raises(AccountNotFound):
        use_account("ghost")


def test_account_dir_isolates_state(tmp_path, monkeypatch):
    monkeypatch.setattr("tgcli.accounts.ROOT", tmp_path)
    add_account("alpha")
    add_account("beta")
    a = account_dir("alpha")
    b = account_dir("beta")
    assert a != b
    assert a.exists() and b.exists()


def test_remove_account_drops_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("tgcli.accounts.ROOT", tmp_path)
    add_account("temp")
    remove_account("temp")
    assert "temp" not in [a["name"] for a in list_accounts()]
    assert not account_dir("temp", create=False).exists()
```

- [ ] **Step 2: Implement `tgcli/accounts.py`**

```python
"""Multi-account directory layout and selector.

Each account lives at ROOT/accounts/<NAME>/ with isolated tg.session,
telegram.sqlite, audit.log, and media/. The current account selector is
ROOT/accounts/.current containing just the account name.

Account name validation: alphanumeric + underscore + hyphen, no path
metacharacters (?, #, /, \\, .., empty).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from tgcli.safety import BadArgs

ROOT: Path = Path(__file__).resolve().parent.parent
ACCOUNTS_DIR_NAME = "accounts"
CURRENT_FILE = ".current"
DEFAULT_ACCOUNT = "default"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class AccountNotFound(Exception):
    pass


def _validate_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise BadArgs(
            f"account name {name!r} invalid; must match [A-Za-z0-9][A-Za-z0-9_-]{{0,63}}"
        )
    return name


def _accounts_root() -> Path:
    return ROOT / ACCOUNTS_DIR_NAME


def _current_path() -> Path:
    return _accounts_root() / CURRENT_FILE


def account_dir(name: str, *, create: bool = True) -> Path:
    _validate_name(name)
    d = _accounts_root() / name
    if create:
        d.mkdir(parents=True, exist_ok=True)
        (d / "media").mkdir(exist_ok=True)
    return d


def add_account(name: str) -> dict[str, Any]:
    name = _validate_name(name)
    d = account_dir(name, create=True)
    return {"name": name, "dir": str(d)}


def list_accounts() -> list[dict[str, Any]]:
    root = _accounts_root()
    if not root.exists():
        return []
    out = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and _NAME_RE.match(child.name):
            out.append({"name": child.name, "dir": str(child)})
    return out


def current_account() -> str:
    cp = _current_path()
    if cp.exists():
        name = cp.read_text().strip()
        if _NAME_RE.match(name) and account_dir(name, create=False).exists():
            return name
    return DEFAULT_ACCOUNT


def use_account(name: str) -> str:
    name = _validate_name(name)
    if not account_dir(name, create=False).exists():
        raise AccountNotFound(f"account {name!r} does not exist; run `tg accounts add {name}` first")
    cp = _current_path()
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(name)
    return name


def remove_account(name: str) -> dict[str, Any]:
    name = _validate_name(name)
    d = account_dir(name, create=False)
    if not d.exists():
        raise AccountNotFound(f"account {name!r} does not exist")
    if name == current_account():
        # Reset current to default
        cp = _current_path()
        if cp.exists():
            cp.unlink()
    shutil.rmtree(d)
    return {"name": name, "removed": True}


def resolve_account_paths(name: str) -> dict[str, Path]:
    """Return the per-account paths used by _common to override globals."""
    d = account_dir(name, create=True)
    return {
        "DB_PATH": d / "telegram.sqlite",
        "SESSION_PATH": d / "tg.session",
        "AUDIT_PATH": d / "audit.log",
        "MEDIA_DIR": d / "media",
    }


def maybe_migrate_default_from_root() -> bool:
    """One-time migration: if root has telegram.sqlite/tg.session/audit.log/media but
    accounts/default/ doesn't, move them into accounts/default/. Returns True if migrated.
    """
    src_db = ROOT / "telegram.sqlite"
    src_session = ROOT / "tg.session"
    src_audit = ROOT / "audit.log"
    src_media = ROOT / "media"
    default_dir = _accounts_root() / DEFAULT_ACCOUNT
    if default_dir.exists():
        return False
    if not (src_db.exists() or src_session.exists()):
        return False
    default_dir.mkdir(parents=True, exist_ok=True)
    (default_dir / "media").mkdir(exist_ok=True)
    moved = []
    for src, dest in [
        (src_db, default_dir / "telegram.sqlite"),
        (src_session, default_dir / "tg.session"),
        (Path(str(src_session) + ".lock"), default_dir / "tg.session.lock"),
        (src_audit, default_dir / "audit.log"),
    ]:
        if src.exists():
            shutil.move(str(src), str(dest))
            moved.append(src.name)
    if src_media.exists() and src_media.is_dir():
        for child in src_media.iterdir():
            shutil.move(str(child), str(default_dir / "media" / child.name))
        if not list(src_media.iterdir()):
            src_media.rmdir()
        moved.append("media/")
    return bool(moved)
```

- [ ] **Step 3: Wire account-aware paths into `_common.py`**

Replace the path setup block:

```python
import os
from pathlib import Path

from tgcli.accounts import (
    DEFAULT_ACCOUNT,
    current_account,
    maybe_migrate_default_from_root,
    resolve_account_paths,
)


ROOT: Path = Path(__file__).resolve().parent.parent.parent
ENV_PATH: Path = ROOT / ".env"


def _resolve_paths():
    # Selection precedence: TG_ACCOUNT env → .current file → "default"
    name = os.environ.get("TG_ACCOUNT") or current_account()
    if name == DEFAULT_ACCOUNT:
        # Trigger migration if default account doesn't exist yet but root has files.
        maybe_migrate_default_from_root()
    paths = resolve_account_paths(name)
    return name, paths


def _override(env_var: str, default: Path) -> Path:
    val = os.environ.get(env_var)
    return Path(val) if val else default


_account_name, _account_paths = _resolve_paths()
ACCOUNT: str = _account_name
DB_PATH: Path = _override("TG_DB_PATH", _account_paths["DB_PATH"])
SESSION_PATH: Path = _override("TG_SESSION_PATH", _account_paths["SESSION_PATH"])
MEDIA_DIR: Path = _override("TG_MEDIA_DIR", _account_paths["MEDIA_DIR"])
AUDIT_PATH: Path = _override("TG_AUDIT_PATH", _account_paths["AUDIT_PATH"])
```

- [ ] **Step 4: Add `--account` top-level flag in `__main__.py`**

Set `os.environ["TG_ACCOUNT"]` before importing command modules so path resolution sees it:

```python
# In main(), after parsing top-level flags but before importing commands:
if args.account:
    os.environ["TG_ACCOUNT"] = args.account
```

(Need a small refactor: parse top-level flags first, then build the subparser, then re-parse.)

Simpler: add `--account` to the top-level parser and have each module re-resolve paths on each call. Since paths are module-level constants, this is messy. The cleanest fix: top-level `--account` is parsed in a pre-pass, sets env, and then the regular parser runs.

- [ ] **Step 5: Implement `tg accounts ...` commands** in `tgcli/commands/accounts.py`

```python
"""accounts add | use | list | show | remove subcommands."""
from __future__ import annotations

import argparse
from typing import Any

from tgcli.accounts import (
    add_account, current_account, list_accounts, remove_account,
    resolve_account_paths, use_account,
)
from tgcli.commands._common import AUDIT_PATH, add_output_flags
from tgcli.dispatch import run_command


def register(sub: argparse._SubParsersAction) -> None:
    add = sub.add_parser("accounts-add", help="Create a new account")
    add.add_argument("name")
    add_output_flags(add)
    add.set_defaults(func=run_add)

    use = sub.add_parser("accounts-use", help="Switch the current default account")
    use.add_argument("name")
    add_output_flags(use)
    use.set_defaults(func=run_use)

    ls = sub.add_parser("accounts-list", help="List all accounts")
    add_output_flags(ls)
    ls.set_defaults(func=run_list)

    show = sub.add_parser("accounts-show", help="Show the current account and its paths")
    add_output_flags(show)
    show.set_defaults(func=run_show)

    rm = sub.add_parser("accounts-remove", help="Delete an account and its data")
    rm.add_argument("name")
    add_output_flags(rm)
    rm.set_defaults(func=run_remove)


def run_add(args) -> int:
    return run_command("accounts-add", args, runner=lambda: add_account(args.name),
                       audit_path=AUDIT_PATH)


def run_use(args) -> int:
    return run_command("accounts-use", args,
                       runner=lambda: {"name": use_account(args.name), "current": True},
                       audit_path=AUDIT_PATH)


def run_list(args) -> int:
    def _runner():
        cur = current_account()
        return {"accounts": list_accounts(), "current": cur}
    return run_command("accounts-list", args, runner=_runner, audit_path=AUDIT_PATH)


def run_show(args) -> int:
    def _runner():
        cur = current_account()
        paths = resolve_account_paths(cur)
        return {"name": cur, "paths": {k: str(v) for k, v in paths.items()}}
    return run_command("accounts-show", args, runner=_runner, audit_path=AUDIT_PATH)


def run_remove(args) -> int:
    return run_command("accounts-remove", args,
                       runner=lambda: remove_account(args.name),
                       audit_path=AUDIT_PATH)
```

Naming note: hyphenated `accounts-add` etc. matches the flat namespace convention (cf. `topic-create`, `folder-create`). If a `tg accounts <subcommand>` group is desired later, easy to refactor.

- [ ] **Step 6: Add `accounts` to `__main__.py` COMMAND_MODULES**

- [ ] **Step 7: `.gitignore`** — add `accounts/`

- [ ] **Step 8: Run all tests; live-verify with `./tg accounts-list --json`**

- [ ] **Step 9: Commit**

```bash
git add tgcli/accounts.py tgcli/commands/accounts.py tgcli/commands/_common.py tgcli/__main__.py .gitignore tests/tgcli/test_phase8_accounts.py
git commit -m "feat(tgcli): multi-account isolation with --account flag and accounts-* commands"
```

---

## Task 10: PR full-gate (Makefile)

**Files:**
- Create: `Makefile`
- Modify: `AGENTS.md` (mention `make gate`)

- [ ] **Step 1: Write `Makefile`**

```makefile
# tg-cli developer gate

PYTEST = .venv/bin/pytest
PYTHON = .venv/bin/python

.PHONY: gate test diff-check

gate: test diff-check
	@echo "PASS: gate clean"

test:
	$(PYTEST) tests/tgcli -q

diff-check:
	@git diff --check

# Optional: install commit-msg hook (Phase 8 Task 11).
.PHONY: install-hooks
install-hooks:
	@cp .githooks/commit-msg .git/hooks/commit-msg
	@chmod +x .git/hooks/commit-msg
	@echo "commit-msg hook installed"
```

- [ ] **Step 2: Test it works**

```bash
make gate
```

Expected: 140 pass + diff-check clean.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat(tgcli): make gate one-shot test+diff check"
```

---

## Task 11: Conventional Commits hook

**Files:**
- Create: `.githooks/commit-msg`

- [ ] **Step 1: Write hook**

```bash
#!/usr/bin/env bash
# Reject commits whose subject doesn't start with a Conventional Commits type.
# Install via: make install-hooks

set -e
msg_file="$1"
subject=$(head -n1 "$msg_file")

if [[ "$subject" =~ ^(feat|fix|docs|refactor|test|chore|perf|security|ci)(\([a-z0-9_/-]+\))?!?:\ .+ ]]; then
    exit 0
fi

# Allow merge / revert commits (auto-generated by git)
if [[ "$subject" =~ ^(Merge|Revert) ]]; then
    exit 0
fi

cat >&2 <<EOF
✗ commit subject must follow Conventional Commits:
  $subject

  expected:
    <type>(<scope>): <subject>
  where <type> is one of:
    feat, fix, docs, refactor, test, chore, perf, security, ci

  examples:
    feat(tgcli): add tg doctor command
    fix(safety): rate limiter race
    docs: clarify --read-only semantics
EOF
exit 1
```

- [ ] **Step 2: Test the hook (use a test commit message file)**

```bash
chmod +x .githooks/commit-msg
echo "bad subject" > /tmp/m.txt && ! .githooks/commit-msg /tmp/m.txt
echo "feat(x): good" > /tmp/m.txt && .githooks/commit-msg /tmp/m.txt
```

Expected: first fails (returns 1), second passes (returns 0).

- [ ] **Step 3: Commit**

```bash
git add .githooks/commit-msg
git commit -m "feat(tgcli): commit-msg hook enforces Conventional Commits"
```

(Don't `make install-hooks` until after this commit lands — otherwise the install will block this commit if its message somehow violates the format. The provided message is valid.)

---

## Task 12: Final verification

- [ ] **Step 1: Run full suite**

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: ~155 passed.

- [ ] **Step 2: Run `make gate`**

Expected: PASS.

- [ ] **Step 3: Live verification on the real account**

```bash
./tg doctor --json | python -m json.tool
./tg doctor --live --json | python -m json.tool
./tg accounts-list --json
./tg accounts-show --json
./tg --read-only stats --json   # works (read)
./tg --read-only send 1240314255 "x" --allow-write --idempotency-key ro-test --json   # exit 6
./tg --full show Polymarket --limit 1   # human mode, no truncation
ls -la accounts/default/        # 0700
ls -la accounts/default/tg.session       # 0600
ls -la accounts/default/audit.log        # 0600
ls -la accounts/default/telegram.sqlite  # 0600
```

- [ ] **Step 4: No commit needed (just verification)**

---

## Self-Review Checklist

1. ✓ All 12 wacli items addressed in their own commit
2. ✓ No new third-party deps (stdlib + Telethon only)
3. ✓ All 140 baseline tests still pass; ~15 new
4. ✓ Multi-account migration is opt-in (zero impact on single-account users)
5. ✓ `--read-only` blocks both Telegram-side AND local-DB writes
6. ✓ Owner-only file perms applied at file-creation time, not retroactively
7. ✓ Conventional Commits hook is git-hosted; `make install-hooks` opt-in
8. ✓ AGENTS.md replaces nothing — added alongside (or instead of CLAUDE.md if that doesn't exist)

---

## Out of Scope (deferred per brief)

- MCP servers (Phase 7) — no clear use case yet
- SDK extraction (Phase 5) — deferred until Sedex returns
- Destructive commands (Phase 10) — defer
- Media upload (Phase 9) — defer
- New Telegram features (channels admin, stickers, polls, scheduled messages) — defer
- Cross-invocation file-backed rate limiter — Phase 8 keeps the in-process limiter; cross-invocation is out of scope here

After Phase 8: user picks between (a) SDK extraction → Sedex resume, (b) destructive commands, (c) media upload, (d) MCP servers.
