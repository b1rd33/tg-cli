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


def acquire_session_lock(session_path: Path) -> None:
    """Take an exclusive flock on <session>.lock. Idempotent within a process."""
    global _lock_handle
    if _lock_handle is not None:
        return
    lock_path = Path(str(session_path) + ".lock")
    f = lock_path.open("w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as e:
        try:
            existing_pid = lock_path.read_text().strip() or "?"
        except OSError:
            existing_pid = "?"
        f.close()
        raise SessionLocked(
            f"Another tg process holds the Telethon session (PID {existing_pid}). "
            f"Wait for it to finish, or kill it with: kill {existing_pid}"
        ) from e
    f.write(str(os.getpid()))
    f.flush()
    _lock_handle = f


def make_client(session_path: Path) -> TelegramClient:
    api_id, api_hash = ensure_credentials()
    acquire_session_lock(session_path)
    return TelegramClient(str(session_path), api_id, api_hash)
