"""Auth subcommands. Phase 1: login."""
from __future__ import annotations

import argparse

from tgcli.client import make_client
from tgcli.commands._common import SESSION_PATH
from tgcli.commands.messages import _display_title


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("login", help="One-time interactive auth")
    p.set_defaults(func=run_login)


async def run_login(args) -> int:
    client = make_client(SESSION_PATH)
    await client.start()
    me = await client.get_me()
    name = _display_title(me)
    print(f"Logged in as {name} (@{me.username}) — id {me.id}")
    print(f"Session saved to {SESSION_PATH}")
    await client.disconnect()
    return 0
