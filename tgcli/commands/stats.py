"""`tg stats` — DB summary.

Read-only: queries telegram.sqlite, returns counts + top-10 chats + media-by-type.
"""
from __future__ import annotations

import argparse
from typing import Any

from tgcli.commands._common import AUDIT_PATH, DB_PATH, add_output_flags
from tgcli.db import connect_readonly
from tgcli.dispatch import run_command


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("stats", help="DB summary")
    add_output_flags(p)
    p.set_defaults(func=run)


def _gather() -> dict[str, Any]:
    con = connect_readonly(DB_PATH)
    chats = con.execute("SELECT COUNT(*) FROM tg_chats").fetchone()[0]
    messages = con.execute("SELECT COUNT(*) FROM tg_messages").fetchone()[0]
    contacts = con.execute("SELECT COUNT(*) FROM tg_contacts").fetchone()[0]
    by_kind = dict(con.execute("SELECT type, COUNT(*) FROM tg_chats GROUP BY type").fetchall())
    last = con.execute(
        "SELECT date, chat_id FROM tg_messages WHERE date IS NOT NULL "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    top_chats = con.execute(
        """
        SELECT c.title, COUNT(*) AS n
        FROM tg_messages m
        JOIN tg_chats c ON c.chat_id = m.chat_id
        GROUP BY m.chat_id
        ORDER BY n DESC
        LIMIT 10
        """
    ).fetchall()
    media_rows = con.execute(
        """
        SELECT media_type,
               COUNT(*) AS total,
               SUM(CASE WHEN media_path IS NOT NULL THEN 1 ELSE 0 END) AS dled
        FROM tg_messages
        WHERE has_media = 1
        GROUP BY media_type
        ORDER BY total DESC
        """
    ).fetchall()
    return {
        "db_path": str(DB_PATH),
        "db_kb": DB_PATH.stat().st_size // 1024,
        "chats": chats,
        "chats_by_kind": by_kind,
        "messages": messages,
        "contacts": contacts,
        "latest_message": (
            {"date": last[0], "chat_id": last[1]} if last else None
        ),
        "top_chats": [{"title": t, "messages": n} for t, n in top_chats],
        "media_by_type": [
            {"type": mtype or "?", "seen": total, "downloaded": dled or 0}
            for mtype, total, dled in media_rows
        ],
    }


def _human(data: dict) -> None:
    print(f"DB:       {data['db_path']} ({data['db_kb']} KB)")
    print(f"Chats:    {data['chats']}  ({data['chats_by_kind']})")
    print(f"Messages: {data['messages']}")
    print(f"Contacts: {data['contacts']}")
    if data["latest_message"]:
        lm = data["latest_message"]
        print(f"Latest:   {lm['date']}  (chat_id {lm['chat_id']})")
    if data["top_chats"]:
        print("\nTop 10 chats by message count:")
        for row in data["top_chats"]:
            print(f"  {row['messages']:>6}  {row['title']}")
    if data["media_by_type"]:
        print("\nMedia by type:")
        for row in data["media_by_type"]:
            print(f"  {row['type']:>12}  {row['seen']:>5} seen, {row['downloaded']:>5} downloaded")


def run(args) -> int:
    return run_command(
        "stats", args,
        runner=_gather,
        human_formatter=_human,
        audit_path=AUDIT_PATH,
    )
