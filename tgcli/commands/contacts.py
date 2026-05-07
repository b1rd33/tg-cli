"""`tg contacts` (list) and `tg sync-contacts` (pull phone-book)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any

from telethon.tl.functions.contacts import (
    BlockRequest,
    GetContactsRequest,
    UnblockRequest,
)

from tgcli.client import make_client
from tgcli.commands._common import (
    AUDIT_PATH, DB_PATH, SESSION_PATH, add_output_flags, add_write_flags,
)
from tgcli.commands.messages import (
    _check_write_rate_limit, _dry_run_envelope, _request_id,
    _resolve_write_chat, _run_write_command, _write_result,
)
from tgcli.db import connect, connect_readonly
from tgcli.dispatch import run_command
from tgcli.idempotency import lookup as lookup_idempotency
from tgcli.idempotency import record as record_idempotency
from tgcli.safety import (
    BadArgs, audit_pre, require_typed_confirm, require_write_allowed,
)


def register(sub: argparse._SubParsersAction) -> None:
    co = sub.add_parser("contacts", help="List synced contacts with phone numbers")
    co.add_argument("--limit", type=int, default=200)
    co.add_argument("--with-phone-only", action="store_true",
                    help="Hide contacts with no phone number")
    co.add_argument("--chatted", action="store_true",
                    help="Only contacts with whom you have a dialog (run 'discover' first)")
    co.add_argument(
        "--min-msgs",
        type=int,
        default=0,
        help="With --chatted, require at least N cached messages",
    )
    add_output_flags(co)
    co.set_defaults(func=run_list)

    sy = sub.add_parser("sync-contacts", help="Pull phone-book contacts from Telegram")
    add_output_flags(sy)
    sy.set_defaults(func=run_sync)

    bl = sub.add_parser("block-user", help="Block a user (or bot)")
    bl.add_argument("user", help="User selector (id, @username, or fuzzy with --fuzzy)")
    add_write_flags(bl, destructive=True)
    add_output_flags(bl)
    bl.set_defaults(func=run_block_user)

    ub = sub.add_parser("unblock-user", help="Unblock a user (or bot); no --confirm needed")
    ub.add_argument("user", help="User selector (id, @username, or fuzzy with --fuzzy)")
    add_write_flags(ub, destructive=False)
    add_output_flags(ub)
    ub.set_defaults(func=run_unblock_user)


def _min_msgs(args) -> int:
    return max(int(getattr(args, "min_msgs", 0) or 0), 0)


# ---------- contacts (read) ----------

def _list_data(args) -> dict[str, Any]:
    min_msgs = _min_msgs(args)
    con = connect_readonly(DB_PATH)
    join = ("INNER JOIN tg_chats ch ON ch.chat_id = c.user_id"
            if args.chatted else
            "LEFT  JOIN tg_chats ch ON ch.chat_id = c.user_id")
    wheres = []
    params: list[Any] = []
    if args.with_phone_only:
        wheres.append("(c.phone IS NOT NULL AND c.phone != '')")
    if args.chatted and min_msgs > 0:
        wheres.append("(SELECT COUNT(*) FROM tg_messages WHERE chat_id = c.user_id) >= ?")
        params.append(min_msgs)
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
    rows = con.execute(sql, (*params, args.limit)).fetchall()
    return {
        "filters": {
            "chatted": args.chatted,
            "with_phone_only": args.with_phone_only,
            "limit": args.limit,
            "min_msgs": min_msgs,
        },
        "contacts": [
            {
                "first_name": first_name,
                "last_name": last_name,
                "phone": phone,
                "username": username,
                "is_mutual": bool(is_mutual),
                "has_dialog": bool(has_dialog),
                "messages": n_msgs,
                "last_message": last_msg,
            }
            for first_name, last_name, phone, username, is_mutual, has_dialog, n_msgs, last_msg in rows
        ],
    }


def _list_human(data: dict) -> None:
    contacts = data["contacts"]
    flags = []
    if data["filters"]["chatted"]:
        flags.append("chatted only")
    if data["filters"]["with_phone_only"]:
        flags.append("with phone")
    if data["filters"]["min_msgs"]:
        flags.append(f"min {data['filters']['min_msgs']} msgs")
    flag_str = f" [{', '.join(flags)}]" if flags else ""
    print(f"=== Contacts ({len(contacts)} shown){flag_str} ===\n")
    if not contacts:
        print("No contacts match. If using --chatted, run 'discover' first.")
        return
    for contact in contacts:
        name = " ".join(
            part for part in [contact["first_name"], contact["last_name"]]
            if part
        ) or "?"
        username_str = f"@{contact['username']}" if contact["username"] else ""
        phone_str = f"+{contact['phone']}" if contact["phone"] else "(no phone)"
        mutual_str = " ✓" if contact["is_mutual"] else "  "
        if contact["messages"]:
            last_short = (contact["last_message"] or "")[:10]
            tail = f"  · {contact['messages']:>4} msgs · last {last_short}"
        elif contact["has_dialog"]:
            tail = "  · dialog exists, 0 msgs cached"
        else:
            tail = "  · no chat"
        print(f"  {name:<28}  {phone_str:<18}  {username_str:<18}{mutual_str}{tail}")


def run_list(args) -> int:
    return run_command(
        "contacts", args,
        runner=lambda: _list_data(args),
        human_formatter=_list_human,
        audit_path=AUDIT_PATH,
    )


# ---------- sync-contacts (writes local DB) ----------

async def _sync_runner(args=None) -> dict[str, Any]:
    if args is not None:
        from tgcli.safety import require_writes_not_readonly
        require_writes_not_readonly(args)
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
        runner=lambda: _sync_runner(args),
        human_formatter=_sync_human,
        audit_path=AUDIT_PATH,
    )


# ---------- block-user / unblock-user (Phase 9) ----------

def _resolve_target_user(con, args, *, slot_name: str = "user") -> dict:
    """Resolve --user selector and ensure it's a user/bot, not a channel/group."""
    raw = getattr(args, "user", None)
    # _resolve_write_chat reads from args.chat; adapt by stashing.
    proxy = argparse.Namespace(**vars(args))
    proxy.chat = raw
    chat = _resolve_write_chat(con, proxy, raw)
    chat_type_row = con.execute(
        "SELECT type FROM tg_chats WHERE chat_id = ?", (chat["chat_id"],)
    ).fetchone()
    if chat_type_row is None or chat_type_row[0] not in ("user", "bot"):
        actual = chat_type_row[0] if chat_type_row else "(uncached)"
        raise BadArgs(
            f"chat {chat['chat_id']} is type {actual!r}; block/unblock only "
            f"works on user or bot chats (not channels/groups)"
        )
    return chat


async def _block_user_runner(args) -> dict[str, Any]:
    command = "block-user"
    request_id = _request_id(args)
    require_write_allowed(args)

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data

        target = _resolve_target_user(con, args)
        require_typed_confirm(args, expected=target["chat_id"], slot="user_id")

        if args.dry_run:
            return _dry_run_envelope(command, request_id, {
                "user": target, "telethon_method": "BlockRequest",
            })

        _check_write_rate_limit()
        audit_pre(AUDIT_PATH, cmd=command, request_id=request_id,
                  resolved_chat_id=target["chat_id"], resolved_chat_title=target["title"],
                  payload_preview={"user": target}, telethon_method="BlockRequest",
                  dry_run=False)

        client = make_client(SESSION_PATH)
        await client.start()
        try:
            input_peer = await client.get_input_entity(target["chat_id"])
            await client(BlockRequest(id=input_peer))
            data = {"user": target, "blocked": True,
                    "telethon_method": "BlockRequest", "idempotent_replay": False}
            record_idempotency(con, args.idempotency_key, command, request_id,
                               _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


async def _unblock_user_runner(args) -> dict[str, Any]:
    command = "unblock-user"
    request_id = _request_id(args)
    require_write_allowed(args)

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data

        target = _resolve_target_user(con, args)

        if args.dry_run:
            return _dry_run_envelope(command, request_id, {
                "user": target, "telethon_method": "UnblockRequest",
            })

        _check_write_rate_limit()
        audit_pre(AUDIT_PATH, cmd=command, request_id=request_id,
                  resolved_chat_id=target["chat_id"], resolved_chat_title=target["title"],
                  payload_preview={"user": target}, telethon_method="UnblockRequest",
                  dry_run=False)

        client = make_client(SESSION_PATH)
        await client.start()
        try:
            input_peer = await client.get_input_entity(target["chat_id"])
            await client(UnblockRequest(id=input_peer))
            data = {"user": target, "unblocked": True,
                    "telethon_method": "UnblockRequest", "idempotent_replay": False}
            record_idempotency(con, args.idempotency_key, command, request_id,
                               _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_block_user(args) -> int:
    return _run_write_command("block-user", args, _block_user_runner)


def run_unblock_user(args) -> int:
    return _run_write_command("unblock-user", args, _unblock_user_runner)
