"""`tg stats` - DB summary.

Read-only: queries telegram.sqlite, returns counts + top chats + media-by-type.
"""
from __future__ import annotations

import argparse
from typing import Any

from tgcli.commands._common import AUDIT_PATH, DB_PATH, add_output_flags
from tgcli.db import connect_readonly
from tgcli.dispatch import run_command


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("stats", help="DB summary")
    p.add_argument(
        "--min-msgs",
        type=int,
        default=0,
        help="Only include top chats with at least N cached messages",
    )
    add_output_flags(p)
    p.set_defaults(func=run)


def _min_msgs(args) -> int:
    return max(int(getattr(args, "min_msgs", 0) or 0), 0)


def _gather(args) -> dict[str, Any]:
    min_msgs = _min_msgs(args)
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
        HAVING COUNT(*) >= ?
        ORDER BY n DESC
        LIMIT 10
        """,
        (min_msgs,),
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
        "filters": {"min_msgs": min_msgs},
        "chats": chats,
        "chats_by_kind": by_kind,
        "messages": messages,
        "contacts": contacts,
        "latest_message": (
            {"date": last[0], "chat_id": last[1]} if last else None
        ),
        "top_chats": [{"title": title, "messages": n} for title, n in top_chats],
        "media_by_type": [
            {"type": media_type or "?", "seen": total, "downloaded": downloaded or 0}
            for media_type, total, downloaded in media_rows
        ],
    }


def _human(data: dict) -> None:
    print(f"DB:       {data['db_path']} ({data['db_kb']} KB)")
    print(f"Chats:    {data['chats']}  ({data['chats_by_kind']})")
    print(f"Messages: {data['messages']}")
    print(f"Contacts: {data['contacts']}")
    if data["latest_message"]:
        latest = data["latest_message"]
        print(f"Latest:   {latest['date']}  (chat_id {latest['chat_id']})")
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
        runner=lambda: _gather(args),
        human_formatter=_human,
        audit_path=AUDIT_PATH,
    )
