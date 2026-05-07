"""Chat-related subcommands. Phase 1 port: discover."""
from __future__ import annotations

import argparse
import json
from typing import Any

from tgcli.client import make_client
from tgcli.commands._common import (
    AUDIT_PATH,
    DB_PATH,
    SESSION_PATH,
    add_output_flags,
    decode_raw_json,
)
from tgcli.commands.messages import _chat_kind, _display_title, _upsert_chat
from tgcli.db import connect, connect_readonly
from tgcli.dispatch import run_command
from tgcli.resolve import NotFound, resolve_chat_db


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("discover", help="Fast scan of every dialog (no messages)")
    add_output_flags(p)
    p.set_defaults(func=run_discover)

    unread = sub.add_parser("unread", help="List chats with unread messages")
    add_output_flags(unread)
    unread.set_defaults(func=run_unread)

    info = sub.add_parser("chats-info", help="Show cached chat metadata")
    info.add_argument("chat", help="Chat selector resolved from the local DB")
    add_output_flags(info)
    info.set_defaults(func=run_chats_info)


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


# ---------- unread ----------

async def _unread_runner(args) -> dict[str, Any]:
    client = make_client(SESSION_PATH)
    await client.start()
    chats: list[dict[str, Any]] = []
    try:
        async for dialog in client.iter_dialogs():
            unread_count = int(getattr(dialog, "unread_count", 0) or 0)
            if unread_count <= 0:
                continue
            entity = getattr(dialog, "entity", None)
            chats.append(
                {
                    "chat_id": int(dialog.id),
                    "title": _display_title(entity) if entity is not None else f"chat_{dialog.id}",
                    "type": _chat_kind(entity) if entity is not None else "unknown",
                    "unread_count": unread_count,
                }
            )
    finally:
        await client.disconnect()
    return {
        "total_chats": len(chats),
        "total_unread": sum(row["unread_count"] for row in chats),
        "chats": chats,
    }


def _unread_human(data: dict) -> None:
    print(f"Unread: {data['total_unread']} messages across {data['total_chats']} chats")
    for row in data["chats"]:
        print(f"  {row['unread_count']:>4}  {row['title']}  (chat_id {row['chat_id']})")


def run_unread(args) -> int:
    return run_command(
        "unread", args,
        runner=lambda: _unread_runner(args),
        human_formatter=_unread_human,
        audit_path=AUDIT_PATH,
    )


# ---------- chats-info ----------

def _member_count(raw_json) -> int | None:
    if not isinstance(raw_json, dict):
        return None
    for key in ("participants_count", "members_count", "member_count"):
        value = raw_json.get(key)
        if isinstance(value, int):
            return value
    return None


def _chat_info_runner(args) -> dict[str, Any]:
    con = connect_readonly(DB_PATH)
    try:
        chat_id, resolved_title = resolve_chat_db(con, args.chat)
        row = con.execute(
            """
            SELECT chat_id, type, title, username, phone, first_name,
                   last_name, is_bot, last_seen_at, raw_json
            FROM tg_chats
            WHERE chat_id = ?
            """,
            (chat_id,),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise NotFound(f"chat {chat_id} not in DB")
    (
        chat_id,
        chat_type,
        title,
        username,
        phone,
        first_name,
        last_name,
        is_bot,
        last_seen_at,
        raw_json,
    ) = row
    decoded_raw = decode_raw_json(raw_json)
    return {
        "chat_id": int(chat_id),
        "title": title or resolved_title,
        "username": username,
        "type": chat_type,
        "phone": phone,
        "first_name": first_name,
        "last_name": last_name,
        "is_bot": bool(is_bot),
        "last_seen_at": last_seen_at,
        "member_count": _member_count(decoded_raw),
        "raw_json": decoded_raw,
    }


def _chats_info_human(data: dict) -> None:
    username = f"@{data['username']}" if data["username"] else "(no username)"
    member_count = data["member_count"] if data["member_count"] is not None else "unknown"
    print(f"{data['title']} ({username})")
    print(f"chat_id: {data['chat_id']}")
    print(f"type: {data['type']}")
    print(f"member_count: {member_count}")
    print(f"last_seen_at: {data['last_seen_at']}")
    print("raw_json:")
    print(json.dumps(data["raw_json"], ensure_ascii=False, indent=2, default=str))


def run_chats_info(args) -> int:
    return run_command(
        "chats-info", args,
        runner=lambda: _chat_info_runner(args),
        human_formatter=_chats_info_human,
        audit_path=AUDIT_PATH,
    )
