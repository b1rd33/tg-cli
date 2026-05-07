"""Phase 9 — account-sessions + terminate-session."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

import pytest

from tgcli.commands import account
from tgcli.safety import BadArgs


def _args(**kw):
    defaults = {"allow_write": True, "dry_run": False, "idempotency_key": "k1",
                "fuzzy": False, "json": True, "human": False, "read_only": False,
                "confirm": None}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _make_auth(*, hash_, current=False, model="X"):
    from telethon.tl.types import Authorization
    return Authorization(
        hash=hash_, device_model=model, platform="x", system_version="x",
        api_id=1, app_name="x", app_version="x",
        date_created=datetime(2026, 1, 1, tzinfo=timezone.utc),
        date_active=datetime(2026, 5, 1, tzinfo=timezone.utc),
        ip="1.2.3.4", country="DE", region="X",
        current=current,
    )


def _make_fake_client(*auths):
    class FakeClient:
        def __init__(self):
            self.calls = []
        async def start(self): pass
        async def __call__(self, request):
            self.calls.append(request)
            return type("Auths", (), {"authorizations": list(auths)})()
        async def disconnect(self): pass
    return FakeClient()


def test_account_sessions_lists_authorizations(monkeypatch, tmp_path):
    monkeypatch.setattr(account, "SESSION_PATH", tmp_path / "tg.session")
    fake = _make_fake_client(
        _make_auth(hash_=11111, current=True, model="MacBook"),
        _make_auth(hash_=22222, current=False, model="iPhone"),
    )
    monkeypatch.setattr(account, "make_client", lambda s: fake)
    data = asyncio.run(account._account_sessions_runner(_args()))
    assert data["total"] == 2
    assert data["current_hash"] == 11111
    assert data["sessions"][0]["current"] is True


def _isolated_db(monkeypatch, tmp_path):
    """Per-test fresh DB so idempotency cache doesn't leak across tests."""
    from tgcli.db import connect as db_connect
    db = tmp_path / "telegram.sqlite"
    db_connect(db).close()
    monkeypatch.setattr(account, "DB_PATH", db)


def test_terminate_session_refuses_current(monkeypatch, tmp_path):
    _isolated_db(monkeypatch, tmp_path)
    monkeypatch.setattr(account, "SESSION_PATH", tmp_path / "tg.session")
    fake = _make_fake_client(_make_auth(hash_=11111, current=True))
    monkeypatch.setattr(account, "make_client", lambda s: fake)
    args = _args(session_hash=11111, confirm="11111", idempotency_key="refuse-cur-1")
    with pytest.raises(BadArgs, match="current session"):
        asyncio.run(account._terminate_session_runner(args))


def test_terminate_session_requires_typed_confirm(monkeypatch, tmp_path):
    _isolated_db(monkeypatch, tmp_path)
    monkeypatch.setattr(account, "SESSION_PATH", tmp_path / "tg.session")
    fake = _make_fake_client(
        _make_auth(hash_=11111, current=True),
        _make_auth(hash_=22222, current=False),
    )
    monkeypatch.setattr(account, "make_client", lambda s: fake)
    args = _args(session_hash=22222, confirm="999", idempotency_key="typed-cf-1")
    with pytest.raises(BadArgs, match="must equal"):
        asyncio.run(account._terminate_session_runner(args))


def test_terminate_session_calls_reset_authorization(monkeypatch, tmp_path):
    _isolated_db(monkeypatch, tmp_path)
    monkeypatch.setattr(account, "SESSION_PATH", tmp_path / "tg.session")
    fake = _make_fake_client(
        _make_auth(hash_=11111, current=True),
        _make_auth(hash_=22222, current=False, model="OldPhone"),
    )
    monkeypatch.setattr(account, "make_client", lambda s: fake)
    args = _args(session_hash=22222, confirm="22222", idempotency_key="reset-auth-1")
    data = asyncio.run(account._terminate_session_runner(args))
    assert data["terminated"] is True
    assert data["session_hash"] == 22222
    assert any(r.__class__.__name__ == "ResetAuthorizationRequest" for r in fake.calls)


def test_terminate_session_unknown_hash_returns_not_found(monkeypatch, tmp_path):
    from tgcli.resolve import NotFound
    db = tmp_path / "telegram.sqlite"
    # Initialize fresh DB so idempotency cache is empty.
    from tgcli.db import connect as db_connect
    db_connect(db).close()
    monkeypatch.setattr(account, "DB_PATH", db)
    monkeypatch.setattr(account, "SESSION_PATH", tmp_path / "tg.session")
    fake = _make_fake_client(_make_auth(hash_=11111, current=True))
    monkeypatch.setattr(account, "make_client", lambda s: fake)
    args = _args(session_hash=99999, confirm="99999",
                 idempotency_key="unknown-hash-test-isolated")
    with pytest.raises(NotFound):
        asyncio.run(account._terminate_session_runner(args))
