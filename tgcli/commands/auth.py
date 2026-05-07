"""Auth subcommands. Phase 1: login."""
from __future__ import annotations

import argparse
from typing import Any

from tgcli.client import make_client
from tgcli.commands._common import AUDIT_PATH, SESSION_PATH, add_output_flags
from tgcli.commands.messages import _display_title
from tgcli.dispatch import run_command


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("login", help="One-time interactive auth")
    add_output_flags(p)
    p.set_defaults(func=run_login)


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
        "login", args,
        runner=_runner,
        human_formatter=_human,
        audit_path=AUDIT_PATH,
    )
