"""Phase 8 — backfill caps."""

from __future__ import annotations

import argparse

import pytest

from tgcli.commands.messages import _check_backfill_caps
from tgcli.safety import BadArgs


def test_caps_pass_when_under_threshold(tmp_path):
    db = tmp_path / "telegram.sqlite"
    db.write_bytes(b"x" * 1000)
    args = argparse.Namespace(max_messages=100_000, max_db_size_mb=500)
    warnings = _check_backfill_caps(db, current_msg_count=10, args=args)
    assert warnings == []


def test_caps_fail_when_over_db_size(tmp_path):
    db = tmp_path / "telegram.sqlite"
    db.write_bytes(b"x" * (600 * 1024 * 1024))
    args = argparse.Namespace(max_messages=100_000, max_db_size_mb=500)
    with pytest.raises(BadArgs, match="db size"):
        _check_backfill_caps(db, current_msg_count=10, args=args)


def test_caps_warn_at_80_percent(tmp_path):
    db = tmp_path / "telegram.sqlite"
    db.write_bytes(b"x" * (420 * 1024 * 1024))
    args = argparse.Namespace(max_messages=100_000, max_db_size_mb=500)
    warnings = _check_backfill_caps(db, current_msg_count=10, args=args)
    assert any("approaching" in w.lower() for w in warnings)


def test_caps_fail_when_over_messages(tmp_path):
    db = tmp_path / "telegram.sqlite"
    db.write_bytes(b"")
    args = argparse.Namespace(max_messages=100, max_db_size_mb=500)
    with pytest.raises(BadArgs, match="message count"):
        _check_backfill_caps(db, current_msg_count=200, args=args)
