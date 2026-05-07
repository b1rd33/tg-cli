"""`tg doctor` — health check for env, session, DB, schema, optional live API."""
from __future__ import annotations

import argparse
import sqlite3
from typing import Any

from tgcli.client import MissingCredentials, ensure_credentials
from tgcli.commands._common import (
    AUDIT_PATH,
    DB_PATH,
    ENV_PATH,
    SESSION_PATH,
    add_output_flags,
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
    return {"name": "env_file", "status": "warn",
            "message": f"no .env at {ENV_PATH} (env vars must be set externally)"}


def _check_session() -> dict[str, str]:
    if SESSION_PATH.exists() or SESSION_PATH.with_suffix(".session").exists():
        return {"name": "session", "status": "ok",
                "message": f"session present at {SESSION_PATH}"}
    return {"name": "session", "status": "warn", "message": "no session — run `tg login` first"}


def _check_db() -> dict[str, str]:
    if not DB_PATH.exists():
        return {"name": "db", "status": "warn",
                "message": f"no DB at {DB_PATH} (will be created on first command)"}
    try:
        con = sqlite3.connect(DB_PATH)
        tables = {
            r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
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
