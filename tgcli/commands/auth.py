"""Auth subcommands. Phase 1: login."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from tgcli.client import make_client
from tgcli.commands._common import (
    AUDIT_PATH,
    DB_PATH,
    SESSION_PATH,
    add_output_flags,
    decode_raw_json,
)
from tgcli.commands.messages import _display_title
from tgcli.db import connect, connect_readonly
from tgcli.dispatch import run_command
from tgcli.resolve import NotFound


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("login", help="One-time interactive auth")
    add_output_flags(p)
    p.set_defaults(func=run_login)

    me = sub.add_parser("me", help="Print authenticated user info")
    me.add_argument(
        "--offline",
        action="store_true",
        help="Read cached self user info without connecting to Telegram",
    )
    add_output_flags(me)
    me.set_defaults(func=run_me)


async def _runner() -> dict[str, Any]:
    client = make_client(SESSION_PATH)
    await client.start()
    try:
        me = await client.get_me()
        return {
            "user_id": me.id,
            "username": getattr(me, "username", None),
            "display_name": _display_title(me),
            "session_path": str(SESSION_PATH),
        }
    finally:
        await client.disconnect()


def _human(data: dict) -> None:
    un = f"@{data['username']}" if data["username"] else "(no username)"
    print(f"Logged in as {data['display_name']} ({un}) — id {data['user_id']}")
    print(f"Session saved to {data['session_path']}")


def run_login(args) -> int:
    return run_command(
        "login",
        args,
        runner=_runner,
        human_formatter=_human,
        audit_path=AUDIT_PATH,
    )


# ---------- me ----------


def _cached_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _me_public(row: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "user_id": row["user_id"],
        "username": row["username"],
        "phone": row["phone"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "display_name": row["display_name"],
        "is_bot": bool(row["is_bot"]),
        "cached_at": row["cached_at"],
        "session_path": str(SESSION_PATH),
        "raw_json": decode_raw_json(row["raw_json"]),
    }


def _row_from_user(user) -> dict[str, Any]:
    raw_json = json.dumps(user.to_dict(), ensure_ascii=False, default=str)[:50000]
    return {
        "user_id": user.id,
        "username": getattr(user, "username", None),
        "phone": getattr(user, "phone", None),
        "first_name": getattr(user, "first_name", None),
        "last_name": getattr(user, "last_name", None),
        "display_name": _display_title(user),
        "is_bot": int(bool(getattr(user, "bot", False))),
        "cached_at": _cached_at(),
        "raw_json": raw_json,
    }


def _write_me_cache(row: dict[str, Any]) -> None:
    con = connect(DB_PATH)
    try:
        con.execute(
            """
            INSERT INTO tg_me(
                key, user_id, username, phone, first_name, last_name,
                display_name, is_bot, cached_at, raw_json
            ) VALUES ('self', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                user_id      = excluded.user_id,
                username     = excluded.username,
                phone        = excluded.phone,
                first_name   = excluded.first_name,
                last_name    = excluded.last_name,
                display_name = excluded.display_name,
                is_bot       = excluded.is_bot,
                cached_at    = excluded.cached_at,
                raw_json     = excluded.raw_json
            """,
            (
                row["user_id"],
                row["username"],
                row["phone"],
                row["first_name"],
                row["last_name"],
                row["display_name"],
                row["is_bot"],
                row["cached_at"],
                row["raw_json"],
            ),
        )
        con.commit()
    finally:
        con.close()


def _me_offline_runner() -> dict[str, Any]:
    con = connect_readonly(DB_PATH)
    try:
        row = con.execute(
            """
            SELECT user_id, username, phone, first_name, last_name,
                   display_name, is_bot, cached_at, raw_json
            FROM tg_me
            WHERE key = 'self'
            """
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise NotFound("No cached self user info. Run 'tg me' once before using --offline.")
    keys = [
        "user_id",
        "username",
        "phone",
        "first_name",
        "last_name",
        "display_name",
        "is_bot",
        "cached_at",
        "raw_json",
    ]
    return _me_public(dict(zip(keys, row)), source="cache")


async def _me_live_runner() -> dict[str, Any]:
    client = make_client(SESSION_PATH)
    await client.start()
    try:
        me = await client.get_me()
        row = _row_from_user(me)
        _write_me_cache(row)
        return _me_public(row, source="live")
    finally:
        await client.disconnect()


def _me_human(data: dict) -> None:
    username = f"@{data['username']}" if data["username"] else "(no username)"
    print(f"{data['display_name']} ({username}) id {data['user_id']}")
    print(f"Source: {data['source']}  Cached: {data['cached_at']}")


def run_me(args) -> int:
    runner = _me_offline_runner if args.offline else _me_live_runner
    return run_command(
        "me",
        args,
        runner=runner,
        human_formatter=_me_human,
        audit_path=AUDIT_PATH,
    )
