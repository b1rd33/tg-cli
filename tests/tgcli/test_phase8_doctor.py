"""Phase 8 — tg doctor."""

from __future__ import annotations

import argparse
import asyncio

from tgcli.commands import doctor


def _args(**kw):
    defaults = {"live": False, "json": True, "human": False}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def test_doctor_returns_envelope_data(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "DB_PATH", tmp_path / "telegram.sqlite")
    monkeypatch.setattr(doctor, "SESSION_PATH", tmp_path / "tg.session")
    monkeypatch.setenv("TG_API_ID", "1")
    monkeypatch.setenv("TG_API_HASH", "x")
    data = asyncio.run(doctor._doctor_runner(_args()))
    assert "checks" in data
    assert "summary" in data
    assert data["summary"]["total"] == len(data["checks"])
    for c in data["checks"]:
        assert {"name", "status", "message"} <= set(c.keys())


def test_doctor_no_creds_reports_failure(monkeypatch, tmp_path):
    monkeypatch.delenv("TG_API_ID", raising=False)
    monkeypatch.delenv("TG_API_HASH", raising=False)
    monkeypatch.setattr(doctor, "DB_PATH", tmp_path / "x.sqlite")
    monkeypatch.setattr(doctor, "SESSION_PATH", tmp_path / "tg.session")
    data = asyncio.run(doctor._doctor_runner(_args()))
    creds = next(c for c in data["checks"] if "credential" in c["name"].lower())
    assert creds["status"] == "fail"
