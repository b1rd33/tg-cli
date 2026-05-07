"""Tests for tgcli.client — credential guard, session lock, factory."""

from __future__ import annotations

import multiprocessing as mp
import time

import pytest

from tgcli.client import (
    MissingCredentials,
    SessionLocked,
    acquire_session_lock,
    ensure_credentials,
)


def test_missing_credentials_raises(monkeypatch):
    monkeypatch.delenv("TG_API_ID", raising=False)
    monkeypatch.delenv("TG_API_HASH", raising=False)
    with pytest.raises(MissingCredentials):
        ensure_credentials()


def test_zero_api_id_raises(monkeypatch):
    monkeypatch.setenv("TG_API_ID", "0")
    monkeypatch.setenv("TG_API_HASH", "abc")
    with pytest.raises(MissingCredentials):
        ensure_credentials()


def test_empty_api_hash_raises(monkeypatch):
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "")
    with pytest.raises(MissingCredentials):
        ensure_credentials()


def test_valid_credentials_returns_int_and_str(monkeypatch):
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "abcdef0123456789abcdef0123456789")
    api_id, api_hash = ensure_credentials()
    assert api_id == 12345
    assert api_hash == "abcdef0123456789abcdef0123456789"


def test_non_numeric_api_id_raises_missing_creds(monkeypatch):
    monkeypatch.setenv("TG_API_ID", "not-a-number")
    monkeypatch.setenv("TG_API_HASH", "abc")
    with pytest.raises(MissingCredentials):
        ensure_credentials()


def _hold_lock_for(seconds: float, session_path_str: str):
    """Subprocess helper: take the lock and sleep, releasing on exit."""
    from pathlib import Path
    from tgcli.client import acquire_session_lock

    acquire_session_lock(Path(session_path_str))
    time.sleep(seconds)


def test_session_lock_blocks_concurrent_acquire(tmp_path):
    session = tmp_path / "x.session"
    holder = mp.Process(target=_hold_lock_for, args=(2.0, str(session)))
    holder.start()
    try:
        time.sleep(0.3)  # let the child grab the lock
        with pytest.raises(SessionLocked) as exc_info:
            acquire_session_lock(session)
        assert "PID" in str(exc_info.value)
    finally:
        holder.join(timeout=5)


def test_session_lock_releases_after_holder_exits(tmp_path):
    session = tmp_path / "y.session"
    holder = mp.Process(target=_hold_lock_for, args=(0.2, str(session)))
    holder.start()
    holder.join(timeout=5)
    # After the holder exits, the lock must be free.
    acquire_session_lock(session)  # no raise
