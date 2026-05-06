"""`tg contacts` (list) and `tg sync-contacts` (pull phone-book)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from telethon.tl.functions.contacts import GetContactsRequest

from tgcli.client import make_client
from tgcli.commands._common import DB_PATH, SESSION_PATH
from tgcli.db import DatabaseMissing, connect, connect_readonly


def register(sub: argparse._SubParsersAction) -> None:
    co = sub.add_parser("contacts", help="List synced contacts with phone numbers")
    co.add_argument("--limit", type=int, default=200)
    co.add_argument("--with-phone-only", action="store_true",
                    help="Hide contacts with no phone number")
    co.add_argument("--chatted", action="store_true",
                    help="Only contacts with whom you have a dialog (run 'discover' first)")
    co.set_defaults(func=run_list)

    sy = sub.add_parser("sync-contacts", help="Pull phone-book contacts from Telegram")
    sy.set_defaults(func=run_sync)


def run_list(args) -> int:
    try:
        con = connect_readonly(DB_PATH)
    except DatabaseMissing:
        print("DB not yet created. Run 'sync-contacts' first.")
        return 1

    join = ("INNER JOIN tg_chats ch ON ch.chat_id = c.user_id"
            if args.chatted else
            "LEFT  JOIN tg_chats ch ON ch.chat_id = c.user_id")
    wheres = []
    if args.with_phone_only:
        wheres.append("(c.phone IS NOT NULL AND c.phone != '')")
    where_sql = (" WHERE " + " AND ".join(wheres)) if wheres else ""

    sql = f"""
        SELECT c.first_name, c.last_name, c.phone, c.username, c.is_mutual,
               (ch.chat_id IS NOT NULL) AS has_dialog,
               (SELECT COUNT(*) FROM tg_messages WHERE chat_id = c.user_id) AS n_msgs,
               (SELECT MAX(date)  FROM tg_messages WHERE chat_id = c.user_id) AS last_msg
        FROM tg_contacts c
        {join}
        {where_sql}
        ORDER BY n_msgs DESC, COALESCE(c.first_name, ''), COALESCE(c.last_name, '')
        LIMIT ?
    """
    rows = con.execute(sql, (args.limit,)).fetchall()
    if not rows:
        print("No contacts match. If using --chatted, run 'discover' first.")
        return 0

    flags = []
    if args.chatted:
        flags.append("chatted only")
    if args.with_phone_only:
        flags.append("with phone")
    flag_str = f" [{', '.join(flags)}]" if flags else ""
    print(f"=== Contacts ({len(rows)} shown){flag_str} ===\n")

    for fn, ln, phone, un, mut, has_dialog, n_msgs, last_msg in rows:
        name = " ".join(p for p in [fn, ln] if p) or "?"
        un_str = f"@{un}" if un else ""
        phone_str = f"+{phone}" if phone else "(no phone)"
        mut_str = " ✓" if mut else "  "
        if n_msgs:
            last_short = (last_msg or "")[:10]
            tail = f"  · {n_msgs:>4} msgs · last {last_short}"
        elif has_dialog:
            tail = "  · dialog exists, 0 msgs cached"
        else:
            tail = "  · no chat"
        print(f"  {name:<28}  {phone_str:<18}  {un_str:<18}{mut_str}{tail}")
    return 0


async def run_sync(args) -> int:
    client = make_client(SESSION_PATH)
    await client.start()
    con = connect(DB_PATH)

    result = await client(GetContactsRequest(hash=0))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    n = 0
    for user in result.users:
        con.execute(
            """
            INSERT INTO tg_contacts (
                user_id, phone, first_name, last_name, username, is_mutual, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                phone      = excluded.phone,
                first_name = excluded.first_name,
                last_name  = excluded.last_name,
                username   = excluded.username,
                is_mutual  = excluded.is_mutual,
                synced_at  = excluded.synced_at
            """,
            (
                user.id,
                getattr(user, "phone", None),
                getattr(user, "first_name", None),
                getattr(user, "last_name", None),
                getattr(user, "username", None),
                int(bool(getattr(user, "mutual_contact", False))),
                now,
            ),
        )
        n += 1

    con.commit()
    con.close()
    await client.disconnect()
    print(f"Synced {n} contacts to {DB_PATH}")
    return 0
