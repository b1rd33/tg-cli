"""Phase 8 — --read-only / TG_READONLY=1 gate."""

from __future__ import annotations

import argparse

import pytest

from tgcli.safety import (
    WriteDisallowed,
    require_write_allowed,
    require_writes_not_readonly,
)


def _args(**kw):
    return argparse.Namespace(**kw)


def test_require_writes_not_readonly_passes_when_unset(monkeypatch):
    monkeypatch.delenv("TG_READONLY", raising=False)
    require_writes_not_readonly(_args())


def test_require_writes_not_readonly_raises_with_flag(monkeypatch):
    monkeypatch.delenv("TG_READONLY", raising=False)
    with pytest.raises(WriteDisallowed, match="read-only"):
        require_writes_not_readonly(_args(read_only=True))


def test_require_writes_not_readonly_raises_with_env(monkeypatch):
    monkeypatch.setenv("TG_READONLY", "1")
    with pytest.raises(WriteDisallowed, match="read-only"):
        require_writes_not_readonly(_args())


def test_require_write_allowed_cascades_into_readonly(monkeypatch):
    """require_write_allowed should ALSO reject when --read-only is on."""
    monkeypatch.delenv("TG_ALLOW_WRITE", raising=False)
    monkeypatch.delenv("TG_READONLY", raising=False)
    with pytest.raises(WriteDisallowed, match="read-only"):
        require_write_allowed(_args(allow_write=True, read_only=True))


def test_require_write_allowed_passes_with_flag_no_readonly(monkeypatch):
    monkeypatch.delenv("TG_READONLY", raising=False)
    require_write_allowed(_args(allow_write=True))
