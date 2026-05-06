"""`tg stats` — DB summary.

Read-only: queries telegram.sqlite, prints chat / message / contact counts,
top-10 chats by message volume, and a media-by-type breakdown.
"""
from __future__ import annotations

import argparse

from tgcli.commands._common import DB_PATH
from tgcli.db import DatabaseMissing, connect_readonly


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("stats", help="DB summary")
    p.set_defaults(func=run)


def run(args) -> int:
    try:
        con = connect_readonly(DB_PATH)
    except DatabaseMissing:
        print(f"DB not yet created at {DB_PATH}. Run 'login' then 'backfill'.")
        return 1
    chats = con.execute("SELECT COUNT(*) FROM tg_chats").fetchone()[0]
    messages = con.execute("SELECT COUNT(*) FROM tg_messages").fetchone()[0]
    contacts = con.execute("SELECT COUNT(*) FROM tg_contacts").fetchone()[0]
    by_kind = dict(con.execute("SELECT type, COUNT(*) FROM tg_chats GROUP BY type").fetchall())

    size_kb = DB_PATH.stat().st_size // 1024
    print(f"DB:       {DB_PATH} ({size_kb} KB)")
    print(f"Chats:    {chats}  ({by_kind})")
    print(f"Messages: {messages}")
    print(f"Contacts: {contacts}")

    last = con.execute(
        "SELECT date, chat_id FROM tg_messages WHERE date IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if last:
        print(f"Latest:   {last[0]}  (chat_id {last[1]})")

    print("\nTop 10 chats by message count:")
    rows = con.execute(
        """
        SELECT c.title, COUNT(*) AS n
        FROM tg_messages m
        JOIN tg_chats c ON c.chat_id = m.chat_id
        GROUP BY m.chat_id
        ORDER BY n DESC
        LIMIT 10
        """
    ).fetchall()
    for title, n in rows:
        print(f"  {n:>6}  {title}")

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
    if media_rows:
        print("\nMedia by type:")
        for mtype, total, dled in media_rows:
            print(f"  {(mtype or '?'):>12}  {total:>5} seen, {dled or 0:>5} downloaded")
    return 0
