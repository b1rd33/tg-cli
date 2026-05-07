"""account-sessions and terminate-session (Phase 9)."""

from __future__ import annotations

import argparse
from typing import Any

from telethon.tl.functions.account import (
    GetAuthorizationsRequest,
    ResetAuthorizationRequest,
)

from tgcli.client import make_client
from tgcli.commands._common import (
    AUDIT_PATH,
    DB_PATH,
    SESSION_PATH,
    add_output_flags,
    add_write_flags,
)
from tgcli.commands.messages import (
    _check_write_rate_limit,
    _dry_run_envelope,
    _request_id,
    _run_write_command,
    _write_result,
)
from tgcli.db import connect
from tgcli.dispatch import run_command
from tgcli.idempotency import lookup as lookup_idempotency
from tgcli.idempotency import record as record_idempotency
from tgcli.safety import (
    BadArgs,
    audit_pre,
    require_typed_confirm,
    require_write_allowed,
)


def register(sub: argparse._SubParsersAction) -> None:
    s = sub.add_parser("account-sessions", help="List authenticated Telegram sessions")
    add_output_flags(s)
    s.set_defaults(func=run_account_sessions)

    t = sub.add_parser("terminate-session", help="Terminate a Telegram session")
    t.add_argument("session_hash", type=int, help="Session hash from account-sessions")
    add_write_flags(t, destructive=True)
    add_output_flags(t)
    t.set_defaults(func=run_terminate_session)


def _summarize_auth(a) -> dict[str, Any]:
    return {
        "hash": int(a.hash),
        "device_model": a.device_model,
        "platform": a.platform,
        "system_version": a.system_version,
        "app_name": a.app_name,
        "app_version": a.app_version,
        "ip": a.ip,
        "country": a.country,
        "region": a.region,
        "date_created": a.date_created.isoformat() if a.date_created else None,
        "date_active": a.date_active.isoformat() if a.date_active else None,
        "current": bool(a.current),
        "official_app": bool(a.official_app),
    }


async def _account_sessions_runner(args) -> dict[str, Any]:
    client = make_client(SESSION_PATH)
    await client.start()
    try:
        result = await client(GetAuthorizationsRequest())
        auths = list(getattr(result, "authorizations", []))
        sessions = [_summarize_auth(a) for a in auths]
        current = next((s["hash"] for s in sessions if s["current"]), None)
        return {"sessions": sessions, "total": len(sessions), "current_hash": current}
    finally:
        await client.disconnect()


def run_account_sessions(args) -> int:
    return run_command(
        "account-sessions",
        args,
        runner=lambda: _account_sessions_runner(args),
        audit_path=AUDIT_PATH,
    )


async def _terminate_session_runner(args) -> dict[str, Any]:
    from tgcli.resolve import NotFound

    command = "terminate-session"
    request_id = _request_id(args)
    require_write_allowed(args)
    require_typed_confirm(args, expected=args.session_hash, slot="session_hash")

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data

        client = make_client(SESSION_PATH)
        await client.start()
        try:
            result = await client(GetAuthorizationsRequest())
            auths = list(getattr(result, "authorizations", []))
            target = next(
                (a for a in auths if int(a.hash) == int(args.session_hash)),
                None,
            )
            if target is None:
                raise NotFound(f"session_hash {args.session_hash} not found")
            if bool(target.current):
                raise BadArgs(
                    f"session hash {args.session_hash} is the current session; "
                    f"terminating it would log you out. Use a different session."
                )

            payload = {
                "session_hash": int(args.session_hash),
                "device_model": target.device_model,
                "telethon_method": "ResetAuthorizationRequest",
            }
            if args.dry_run:
                return _dry_run_envelope(command, request_id, payload)

            _check_write_rate_limit()
            audit_pre(
                AUDIT_PATH,
                cmd=command,
                request_id=request_id,
                resolved_chat_id=0,
                resolved_chat_title="(account)",
                payload_preview=payload,
                telethon_method="ResetAuthorizationRequest",
                dry_run=False,
            )
            await client(ResetAuthorizationRequest(hash=int(args.session_hash)))
            data = {
                "session_hash": int(args.session_hash),
                "device_model": target.device_model,
                "terminated": True,
                "idempotent_replay": False,
            }
            record_idempotency(
                con,
                args.idempotency_key,
                command,
                request_id,
                _write_result(command, request_id, data),
            )
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_terminate_session(args) -> int:
    return _run_write_command("terminate-session", args, _terminate_session_runner)
