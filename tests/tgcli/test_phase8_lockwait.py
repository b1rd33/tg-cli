"""Phase 8 — --lock-wait DURATION."""

from __future__ import annotations

import fcntl
import threading
import time
from pathlib import Path

import pytest

import tgcli.client as client_mod
from tgcli.client import SessionLocked, acquire_session_lock


def test_lock_wait_zero_succeeds_when_free(tmp_path, monkeypatch):
    monkeypatch.setattr(client_mod, "_lock_handle", None)
    sp = tmp_path / "tg.session"
    acquire_session_lock(sp, wait_seconds=0)


def test_lock_wait_releases_after_held(tmp_path, monkeypatch):
    """If a held lock is released during the wait window, we acquire it."""
    monkeypatch.setattr(client_mod, "_lock_handle", None)
    sp = tmp_path / "tg.session"
    lock_path = Path(str(sp) + ".lock")
    holder = lock_path.open("w")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release():
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()

    threading.Timer(0.2, _release).start()
    start = time.monotonic()
    acquire_session_lock(sp, wait_seconds=1)
    elapsed = time.monotonic() - start
    assert 0.15 < elapsed < 0.6


def test_lock_wait_timeout_raises(tmp_path, monkeypatch):
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
