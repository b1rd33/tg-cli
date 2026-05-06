"""Chat-related subcommands. Phase 1 port: discover."""
from __future__ import annotations

import argparse

from tgcli.client import make_client
from tgcli.commands._common import DB_PATH, SESSION_PATH
from tgcli.commands.messages import _upsert_chat
from tgcli.db import connect


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("discover", help="Fast scan of every dialog (no messages)")
    p.set_defaults(func=run_discover)


async def run_discover(args) -> int:
    client = make_client(SESSION_PATH)
    await client.start()
    con = connect(DB_PATH)

    n = 0
    async for dialog in client.iter_dialogs():
        _upsert_chat(con, dialog.entity)
        n += 1
        if n % 50 == 0:
            con.commit()
            print(f"  ...{n} dialogs")

    con.commit()
    con.close()
    await client.disconnect()
    print(f"Discovered {n} dialogs in tg_chats")
    return 0
