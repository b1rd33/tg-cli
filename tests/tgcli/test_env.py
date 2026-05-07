"""Tests for tgcli.env — the .env loader."""

from __future__ import annotations

import os

from tgcli.env import load_env_file


def test_load_env_file_basic(tmp_path, monkeypatch):
    monkeypatch.delenv("TG_API_ID", raising=False)
    monkeypatch.delenv("TG_API_HASH", raising=False)
    p = tmp_path / ".env"
    p.write_text('# comment\nTG_API_ID=99999\nTG_API_HASH="abc123"\nEMPTY=\n')
    load_env_file(p)
    assert os.environ["TG_API_ID"] == "99999"
    assert os.environ["TG_API_HASH"] == "abc123"


def test_load_env_file_skips_when_missing(tmp_path):
    load_env_file(tmp_path / "nonexistent.env")  # must not raise


def test_load_env_file_does_not_override_shell_export(tmp_path, monkeypatch):
    monkeypatch.setenv("TG_API_ID", "from-shell")
    p = tmp_path / ".env"
    p.write_text("TG_API_ID=from-file\n")
    load_env_file(p)
    assert os.environ["TG_API_ID"] == "from-shell"


def test_load_env_file_strips_quotes_and_comments(tmp_path, monkeypatch):
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("BAR", raising=False)
    p = tmp_path / ".env"
    p.write_text("# header\nFOO='single'\nBAR=\"double\"\n")
    load_env_file(p)
    assert os.environ["FOO"] == "single"
    assert os.environ["BAR"] == "double"
