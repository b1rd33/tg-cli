"""`tg contacts` (list) and `tg sync-contacts` (pull phone-book)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any

from telethon.tl.functions.contacts import GetContactsRequest

from tgcli.client import make_client
from tgcli.commands._common import AUDIT_PATH, DB_PATH, SESSION_PATH, add_output_flags
from tgcli.db import connect, connect_readonly
from tgcli.dispatch import run_command


def register(sub: argparse._SubParsersAction) -> None:
    co = sub.add_parser("contacts", help="List synced contacts with phone numbers")
    co.add_argument("--limit", type=int, default=200)
    co.add_argument("--with-phone-only", action="store_true",
                    help="Hide contacts with no phone number")
    co.add_argument("--chatted", action="store_true",
                    help="Only contacts with whom you have a dialog (run 'discover' first)")
    add_output_flags(co)
    co.set_defaults(func=run_list)

    sy = sub.add_parser("sync-contacts", help="Pull phone-book contacts from Telegram")
    add_output_flags(sy)
    sy.set_defaults(func=run_sync)


# ---------- contacts (read) ----------

def _list_data(args) -> dict[str, Any]:
    con = connect_readonly(DB_PATH)
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
    return {
        "filters": {"chatted": args.chatted, "with_phone_only": args.with_phone_only,
                    "limit": args.limit},
        "contacts": [
            {
                "first_name": fn,
                "last_name": ln,
                "phone": phone,
                "username": un,
                "is_mutual": bool(mut),
                "has_dialog": bool(has_dialog),
                "messages": n_msgs,
                "last_message": last_msg,
            }
            for fn, ln, phone, un, mut, has_dialog, n_msgs, last_msg in rows
        ],
    }


def _list_human(data: dict) -> None:
    contacts = data["contacts"]
    flags = []
    if data["filters"]["chatted"]:
        flags.append("chatted only")
    if data["filters"]["with_phone_only"]:
        flags.append("with phone")
    flag_str = f" [{', '.join(flags)}]" if flags else ""
    print(f"=== Contacts ({len(contacts)} shown){flag_str} ===\n")
    if not contacts:
        print("No contacts match. If using --chatted, run 'discover' first.")
        return
    for c in contacts:
        name = " ".join(p for p in [c["first_name"], c["last_name"]] if p) or "?"
        un_str = f"@{c['username']}" if c["username"] else ""
        phone_str = f"+{c['phone']}" if c["phone"] else "(no phone)"
        mut_str = " ✓" if c["is_mutual"] else "  "
        if c["messages"]:
            last_short = (c["last_message"] or "")[:10]
            tail = f"  · {c['messages']:>4} msgs · last {last_short}"
        elif c["has_dialog"]:
            tail = "  · dialog exists, 0 msgs cached"
        else:
            tail = "  · no chat"
        print(f"  {name:<28}  {phone_str:<18}  {un_str:<18}{mut_str}{tail}")


def run_list(args) -> int:
    return run_command(
        "contacts", args,
        runner=lambda: _list_data(args),
        human_formatter=_list_human,
        audit_path=AUDIT_PATH,
    )


# ---------- sync-contacts (writes local DB) ----------

async def _sync_runner() -> dict[str, Any]:
    client = make_client(SESSION_PATH)
    await client.start()
    try:
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
    finally:
        await client.disconnect()
    return {"synced": n, "db_path": str(DB_PATH)}


def _sync_human(data: dict) -> None:
    print(f"Synced {data['synced']} contacts to {data['db_path']}")


def run_sync(args) -> int:
    return run_command(
        "sync-contacts", args,
        runner=_sync_runner,
        human_formatter=_sync_human,
        audit_path=AUDIT_PATH,
    )
