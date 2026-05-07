"""Chat-related subcommands. Phase 1 port: discover."""
from __future__ import annotations

import argparse
from typing import Any

from tgcli.client import make_client
from tgcli.commands._common import AUDIT_PATH, DB_PATH, SESSION_PATH, add_output_flags
from tgcli.commands.messages import _upsert_chat
from tgcli.db import connect
from tgcli.dispatch import run_command


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("discover", help="Fast scan of every dialog (no messages)")
    add_output_flags(p)
    p.set_defaults(func=run_discover)


async def _discover_runner(args) -> dict[str, Any]:
    import sys
    client = make_client(SESSION_PATH)
    await client.start()
    quiet = bool(getattr(args, "json", False))
    try:
        con = connect(DB_PATH)
        n = 0
        async for dialog in client.iter_dialogs():
            _upsert_chat(con, dialog.entity)
            n += 1
            if n % 50 == 0:
                con.commit()
                if not quiet:
                    print(f"  ...{n} dialogs", file=sys.stderr)
        con.commit()
        con.close()
    finally:
        await client.disconnect()
    return {"discovered": n, "db_path": str(DB_PATH)}


def _human(data: dict) -> None:
    print(f"Discovered {data['discovered']} dialogs in tg_chats")


def run_discover(args) -> int:
    return run_command(
        "discover", args,
        runner=lambda: _discover_runner(args),
        human_formatter=_human,
        audit_path=AUDIT_PATH,
    )
