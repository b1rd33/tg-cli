"""Telethon client factory + credential guard + session lock.

Only one process at a time may hold the Telethon SQLite session; concurrent
holders corrupt it. We acquire a non-blocking flock on `<session>.lock` at
client construction; the OS releases it when the process exits.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

from telethon import TelegramClient


class MissingCredentials(RuntimeError):
    """Raised when TG_API_ID / TG_API_HASH aren't set or are malformed."""


class SessionLocked(RuntimeError):
    """Raised when another process is already using the Telethon session."""


# Held for the lifetime of the process so the flock isn't released.
_lock_handle = None


def ensure_credentials() -> tuple[int, str]:
    raw_id = os.environ.get("TG_API_ID", "0") or "0"
    api_hash = os.environ.get("TG_API_HASH", "")
    try:
        api_id = int(raw_id)
    except ValueError as e:
        raise MissingCredentials(
            f"TG_API_ID must be an integer (got {raw_id!r}). "
            "Register an app at https://my.telegram.org/apps"
        ) from e
    if not api_id or not api_hash:
        raise MissingCredentials(
            "TG_API_ID and TG_API_HASH must be set as env vars or in .env. "
            "Register a personal app at https://my.telegram.org/apps"
        )
    return api_id, api_hash


def acquire_session_lock(session_path: Path, *, wait_seconds: float = 0) -> None:
    """Take an exclusive flock on <session>.lock. Idempotent within a process.

    wait_seconds=0 fails fast (current behavior). Positive value retries
    every 100ms until acquired or timeout.
    """
    import time as _time

    global _lock_handle
    if _lock_handle is not None:
        return
    lock_path = Path(str(session_path) + ".lock")
    deadline = _time.monotonic() + max(wait_seconds, 0)
    while True:
        f = lock_path.open("w")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            f.write(str(os.getpid()))
            f.flush()
            _lock_handle = f
            from tgcli.commands._common import _chmod_owner_only

            _chmod_owner_only(lock_path)
            actual_session = Path(str(session_path) + ".session")
            _chmod_owner_only(actual_session)
            return
        except BlockingIOError as e:
            f.close()
            if _time.monotonic() >= deadline:
                try:
                    existing_pid = lock_path.read_text().strip() or "?"
                except OSError:
                    existing_pid = "?"
                raise SessionLocked(
                    f"Another tg process holds the Telethon session (PID {existing_pid}). "
                    f"Wait for it to finish, or kill it with: kill {existing_pid}"
                ) from e
            _time.sleep(0.1)


def make_client(session_path: Path, *, lock_wait: float | None = None) -> TelegramClient:
    api_id, api_hash = ensure_credentials()
    if lock_wait is None:
        try:
            lock_wait = float(os.environ.get("TG_LOCK_WAIT", "0"))
        except ValueError:
            lock_wait = 0
    acquire_session_lock(session_path, wait_seconds=lock_wait)
    return TelegramClient(str(session_path), api_id, api_hash)
