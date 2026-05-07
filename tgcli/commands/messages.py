"""Message-related subcommands: show, backfill (Phase 1 ports).

Future split (Phase 5+): messages_read.py + messages_write.py.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Any

from telethon.tl.types import (
    Channel,
    Chat,
    DocumentAttributeAudio,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
    MessageMediaWebPage,
    User,
)
from telethon.tl.functions.messages import ForwardMessagesRequest, SendReactionRequest
from telethon.tl.types import ReactionEmoji

from tgcli.client import make_client
from tgcli.commands._common import (
    AUDIT_PATH, DB_PATH, MEDIA_DIR, ROOT, SESSION_PATH, add_output_flags,
    add_write_flags, decode_raw_json,
)
from tgcli.db import connect, connect_readonly
from tgcli.dispatch import run_command
from tgcli.idempotency import lookup as lookup_idempotency
from tgcli.idempotency import record as record_idempotency
from tgcli.resolve import NotFound, resolve_chat_db
from tgcli.safety import (
    BadArgs,
    LocalRateLimited,
    OUTBOUND_WRITE_LIMITER,
    audit_pre,
    require_explicit_or_fuzzy,
    require_write_allowed,
)


def register(sub: argparse._SubParsersAction) -> None:
    sh = sub.add_parser("show", help="Print messages from one chat")
    sh.add_argument("pattern", nargs="?", default=None,
                    help="Substring of chat title (case- and accent-insensitive)")
    sh.add_argument("--chat-id", type=int, default=None,
                    help="Use exact chat_id instead of pattern")
    sh.add_argument("--limit", type=int, default=50,
                    help="Number of messages (default 50)")
    sh.add_argument("--reverse", action="store_true",
                    help="Oldest first instead of newest first")
    sh.add_argument("--include-deleted", action="store_true",
                    help="Include locally-tombstoned (deleted-for-everyone) messages")
    add_output_flags(sh)
    sh.set_defaults(func=run_show)

    se = sub.add_parser("search", help="Search cached messages in one chat")
    se.add_argument("chat", help="Chat selector resolved from the local DB")
    se.add_argument("query", help="Text query to search in cached message text")
    se.add_argument("--limit", type=int, default=50,
                    help="Number of messages (default 50)")
    se.add_argument("--case-sensitive", action="store_true",
                    help="Require exact case match after the DB LIKE scan")
    se.add_argument("--include-deleted", action="store_true",
                    help="Include locally-tombstoned messages")
    add_output_flags(se)
    se.set_defaults(func=run_search)

    ls = sub.add_parser("list-msgs", help="List cached messages from one chat")
    ls.add_argument("chat", help="Chat selector resolved from the local DB")
    ls.add_argument("--limit", type=int, default=50,
                    help="Number of messages (default 50)")
    ls.add_argument("--since", default=None,
                    help="Only include messages on or after YYYY-MM-DD")
    ls.add_argument("--until", default=None,
                    help="Only include messages on or before YYYY-MM-DD")
    ls.add_argument("--reverse", action="store_true",
                    help="Oldest first instead of newest first")
    ls.add_argument("--include-deleted", action="store_true",
                    help="Include locally-tombstoned messages")
    add_output_flags(ls)
    ls.set_defaults(func=run_list)

    gm = sub.add_parser("get-msg", help="Get one cached message by id")
    gm.add_argument("chat", help="Chat selector resolved from the local DB")
    gm.add_argument("message_id", type=int, help="Cached Telegram message id")
    gm.add_argument("--include-deleted", action="store_true",
                    help="Include a locally-tombstoned message if it matches")
    add_output_flags(gm)
    gm.set_defaults(func=run_get)

    snd = sub.add_parser("send", help="Send a text message")
    snd.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    snd.add_argument("text", help="Message text, or '-' to read from stdin")
    snd.add_argument("--reply-to", type=int, default=None,
                     help="Reply to this Telegram message id")
    snd.add_argument("--topic", type=int, default=None,
                     help="Forum topic root message id; ignored when --reply-to is provided")
    snd.add_argument("--silent", action="store_true",
                     help="Send without notification")
    snd.add_argument("--no-webpage", action="store_true",
                     help="Disable link preview")
    add_write_flags(snd, destructive=False)
    add_output_flags(snd)
    snd.set_defaults(func=run_send)

    edit = sub.add_parser("edit-msg", help="Edit one of your own text messages")
    edit.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    edit.add_argument("message_id", type=int, help="Telegram message id to edit")
    edit.add_argument("text", help="Replacement text, or '-' to read from stdin")
    add_write_flags(edit, destructive=False)
    add_output_flags(edit)
    edit.set_defaults(func=run_edit_msg)

    fwd = sub.add_parser("forward", help="Forward one cached message")
    fwd.add_argument("from_chat", help="Source chat id, @username, or fuzzy title with --fuzzy")
    fwd.add_argument("message_id", type=int, help="Telegram message id to forward")
    fwd.add_argument("to_chat", help="Destination chat id, @username, or fuzzy title with --fuzzy")
    fwd.add_argument("--topic", type=int, default=None,
                     help="Destination forum topic root message id (forwards into a topic in the destination chat)")
    add_write_flags(fwd, destructive=False)
    add_output_flags(fwd)
    fwd.set_defaults(func=run_forward)

    pin = sub.add_parser("pin-msg", help="Pin a message")
    pin.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    pin.add_argument("message_id", type=int, help="Telegram message id to pin")
    add_write_flags(pin, destructive=False)
    add_output_flags(pin)
    pin.set_defaults(func=run_pin_msg)

    unpin = sub.add_parser("unpin-msg", help="Unpin a message")
    unpin.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    unpin.add_argument("message_id", type=int, help="Telegram message id to unpin")
    add_write_flags(unpin, destructive=False)
    add_output_flags(unpin)
    unpin.set_defaults(func=run_unpin_msg)

    dl = sub.add_parser("delete-msg", help="Delete one or more messages from a chat")
    dl.add_argument("chat", help="Chat selector (id, @username, or fuzzy with --fuzzy)")
    dl.add_argument("message_ids", type=int, nargs="+", help="One or more message_ids to delete")
    dl.add_argument("--for-everyone", dest="for_everyone", action="store_true", default=None,
                    help="Revoke for all participants (default: True if all ids are outgoing)")
    dl.add_argument("--no-for-everyone", dest="for_everyone", action="store_false")
    add_write_flags(dl, destructive=True)
    add_output_flags(dl)
    dl.set_defaults(func=run_delete_msg)

    react = sub.add_parser("react", help="Add a reaction to a message")
    react.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    react.add_argument("message_id", type=int, help="Telegram message id to react to")
    react.add_argument("emoji", help="Reaction emoji")
    add_write_flags(react, destructive=False)
    add_output_flags(react)
    react.set_defaults(func=run_react)

    mark = sub.add_parser("mark-read", help="Mark all messages in a chat as read")
    mark.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    add_write_flags(mark, destructive=False)
    add_output_flags(mark)
    mark.set_defaults(func=run_mark_read)

    bf = sub.add_parser("backfill", help="Pull historical messages")
    bf.add_argument("--per-chat", type=int, default=200)
    bf.add_argument("--max-chats", type=int, default=100)
    bf.add_argument("--throttle", type=float, default=1.0)
    bf.add_argument("--max-messages", type=int, default=100_000,
                    help="Refuse to start backfill if cached message count >= this (default 100000)")
    bf.add_argument("--max-db-size-mb", type=int, default=500,
                    help="Refuse to start backfill if telegram.sqlite >= this MB (default 500)")
    bf.add_argument("--download-media", action="store_true",
                    help="Also download photos / voice / video / documents to media/<chat_id>/")
    add_output_flags(bf)
    bf.set_defaults(func=run_backfill)


def _chat_kind(entity) -> str:
    if isinstance(entity, User):
        return "bot" if getattr(entity, "bot", False) else "user"
    if isinstance(entity, Chat):
        return "group"
    if isinstance(entity, Channel):
        return "channel" if getattr(entity, "broadcast", False) else "supergroup"
    return "unknown"


def _display_title(entity) -> str:
    if isinstance(entity, User):
        parts = [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]
        name = " ".join(p for p in parts if p).strip()
        return name or getattr(entity, "username", None) or f"user_{entity.id}"
    return getattr(entity, "title", None) or f"chat_{getattr(entity, 'id', '?')}"


def _media_type_of(msg) -> str | None:
    media = getattr(msg, "media", None)
    if media is None:
        return None
    if isinstance(media, MessageMediaPhoto):
        return "photo"
    if isinstance(media, MessageMediaDocument):
        doc = getattr(media, "document", None)
        if doc is not None:
            for attr in (doc.attributes or []):
                if isinstance(attr, DocumentAttributeAudio):
                    return "voice" if getattr(attr, "voice", False) else "audio"
                if isinstance(attr, DocumentAttributeVideo):
                    return "video_note" if getattr(attr, "round_message", False) else "video"
            mime = getattr(doc, "mime_type", "") or ""
            if mime.startswith("video/"):
                return "video"
            if mime.startswith("audio/"):
                return "audio"
            if mime == "image/webp":
                return "sticker"
            if mime.startswith("image/"):
                return "image"
        return "document"
    if isinstance(media, MessageMediaWebPage):
        return "webpage"
    return type(media).__name__


def _upsert_chat(con, entity) -> None:
    if entity is None or not hasattr(entity, "id"):
        return
    con.execute(
        """
        INSERT INTO tg_chats (
            chat_id, type, title, username, phone,
            first_name, last_name, is_bot, last_seen_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            type         = excluded.type,
            title        = excluded.title,
            username     = excluded.username,
            phone        = excluded.phone,
            first_name   = excluded.first_name,
            last_name    = excluded.last_name,
            is_bot       = excluded.is_bot,
            last_seen_at = excluded.last_seen_at
        """,
        (
            entity.id,
            _chat_kind(entity),
            _display_title(entity),
            getattr(entity, "username", None),
            getattr(entity, "phone", None),
            getattr(entity, "first_name", None),
            getattr(entity, "last_name", None),
            int(bool(getattr(entity, "bot", False))),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps(entity.to_dict(), default=str)[:50000],
        ),
    )


def _upsert_message(con, msg, chat_id: int, media_path: str | None = None) -> None:
    reply_to = getattr(msg, "reply_to", None)
    reply_to_id = getattr(reply_to, "reply_to_msg_id", None) if reply_to else None
    con.execute(
        """
        INSERT INTO tg_messages (
            chat_id, message_id, sender_id, date, text,
            is_outgoing, reply_to_msg_id, has_media, media_type, media_path, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, message_id) DO UPDATE SET
            text       = excluded.text,
            has_media  = excluded.has_media,
            media_type = excluded.media_type,
            media_path = COALESCE(excluded.media_path, tg_messages.media_path)
        """,
        (
            chat_id,
            msg.id,
            getattr(msg, "sender_id", None),
            msg.date.isoformat() if getattr(msg, "date", None) else None,
            msg.text or "",
            1 if getattr(msg, "out", False) else 0,
            reply_to_id,
            1 if getattr(msg, "media", None) else 0,
            _media_type_of(msg),
            str(media_path) if media_path else None,
            json.dumps(msg.to_dict(), default=str)[:50000],
        ),
    )


async def _download_media(client, msg, chat_id: int) -> str | None:
    if not getattr(msg, "media", None):
        return None
    media_dir = MEDIA_DIR / str(chat_id)
    media_dir.mkdir(parents=True, exist_ok=True)
    try:
        path = await client.download_media(msg, file=str(media_dir / str(msg.id)))
        return str(path) if path else None
    except Exception as e:
        print(f"    download failed: chat {chat_id} msg {msg.id}: {e}")
        return None


# ---------- show ----------

def _show_runner(args) -> dict[str, Any]:
    if args.pattern is None and args.chat_id is None:
        raise BadArgs("Need a pattern or --chat-id. Example: tg show Ijadi")

    con = connect_readonly(DB_PATH)
    raw_selector = str(args.chat_id) if args.chat_id is not None else args.pattern
    chat_id, chat_title = resolve_chat_db(con, raw_selector)

    order = "ASC" if args.reverse else "DESC"
    deleted_clause = "" if getattr(args, "include_deleted", False) else " AND (deleted = 0 OR deleted IS NULL)"
    rows = con.execute(
        f"""
        SELECT date, is_outgoing, text, media_type
        FROM tg_messages
        WHERE chat_id = ?{deleted_clause}
        ORDER BY date {order}
        LIMIT ?
        """,
        (chat_id, args.limit),
    ).fetchall()

    return {
        "chat": {"chat_id": chat_id, "title": chat_title},
        "order": "oldest_first" if args.reverse else "newest_first",
        "messages": [
            {
                "date": date,
                "is_outgoing": bool(is_out),
                "text": text or None,
                "media_type": media,
            }
            for date, is_out, text, media in rows
        ],
    }


def _truncate_human(text: str, *, limit: int = 200) -> str:
    """Trim text to `limit` chars in human mode unless TG_FULL=1."""
    import os as _os
    if _os.environ.get("TG_FULL") == "1":
        return text
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _show_human(data: dict) -> None:
    chat = data["chat"]
    msgs = data["messages"]
    if not msgs:
        print(f"No messages stored for '{chat['title']}' (chat_id {chat['chat_id']}).")
        return
    direction = "oldest first" if data["order"] == "oldest_first" else "newest first"
    print(f"=== {chat['title']}  ·  chat_id {chat['chat_id']}  ·  {len(msgs)} messages, {direction} ===\n")
    for m in msgs:
        arrow = "→ you " if m["is_outgoing"] else "← them"
        ts = (m["date"] or "")[:19].replace("T", " ")
        if m["text"]:
            body = _truncate_human(m["text"])
        elif m["media_type"]:
            body = f"[{m['media_type']}]"
        else:
            body = "[empty]"
        print(f"  {ts}  {arrow}  {body}")


def run_show(args) -> int:
    return run_command(
        "show", args,
        runner=lambda: _show_runner(args),
        human_formatter=_show_human,
        audit_path=AUDIT_PATH,
    )


# ---------- search / list / get ----------

def _positive_limit(value: int, *, default: int = 50) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 1)


def _like_pattern(query: str) -> str:
    escaped = (
        query
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


def _date_start(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise BadArgs(f"Invalid --since date {value!r}; expected YYYY-MM-DD") from exc
    return f"{value}T00:00:00"


def _date_end(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise BadArgs(f"Invalid --until date {value!r}; expected YYYY-MM-DD") from exc
    return f"{value}T23:59:59"


def _message_summary(row) -> dict[str, Any]:
    message_id, date, is_outgoing, text, media_type = row
    return {
        "message_id": int(message_id),
        "date": date,
        "is_outgoing": bool(is_outgoing),
        "text": text or None,
        "media_type": media_type,
    }


def _full_message(row) -> dict[str, Any]:
    (
        chat_id,
        message_id,
        sender_id,
        date,
        text,
        is_outgoing,
        reply_to_msg_id,
        has_media,
        media_type,
        media_path,
        raw_json,
    ) = row
    return {
        "chat_id": int(chat_id),
        "message_id": int(message_id),
        "sender_id": sender_id,
        "date": date,
        "text": text or None,
        "is_outgoing": bool(is_outgoing),
        "reply_to_msg_id": reply_to_msg_id,
        "has_media": bool(has_media),
        "media_type": media_type,
        "media_path": media_path,
        "raw_json": decode_raw_json(raw_json),
    }


def _search_runner(args) -> dict[str, Any]:
    query = str(args.query)
    if query == "":
        raise BadArgs("Search query cannot be empty")

    con = connect_readonly(DB_PATH)
    try:
        chat_id, chat_title = resolve_chat_db(con, args.chat)
        params: list[Any] = [chat_id, _like_pattern(query)]
        case_clause = ""
        if args.case_sensitive:
            case_clause = " AND instr(text, ?) > 0"
            params.append(query)
        params.append(_positive_limit(args.limit))
        deleted_clause = "" if getattr(args, "include_deleted", False) else " AND (deleted = 0 OR deleted IS NULL)"
        rows = con.execute(
            f"""
            SELECT message_id, date, is_outgoing, text, media_type
            FROM tg_messages
            WHERE chat_id = ?
              AND text IS NOT NULL
              AND text LIKE ? ESCAPE '\\'
              {case_clause}{deleted_clause}
            ORDER BY date DESC, message_id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    finally:
        con.close()

    return {
        "chat": {"chat_id": chat_id, "title": chat_title},
        "query": query,
        "case_sensitive": bool(args.case_sensitive),
        "limit": _positive_limit(args.limit),
        "messages": [_message_summary(row) for row in rows],
    }


def _search_human(data: dict) -> None:
    chat = data["chat"]
    print(f"=== Search {data['query']!r} in {chat['title']} (chat_id {chat['chat_id']}) ===\n")
    if not data["messages"]:
        print("No cached messages matched.")
        return
    for message in data["messages"]:
        ts = (message["date"] or "")[:19].replace("T", " ")
        if message["text"]:
            body = _truncate_human(message["text"])
        elif message["media_type"]:
            body = f"[{message['media_type']}]"
        else:
            body = "[empty]"
        print(f"  #{message['message_id']:<6} {ts}  {body}")


def run_search(args) -> int:
    return run_command(
        "search", args,
        runner=lambda: _search_runner(args),
        human_formatter=_search_human,
        audit_path=AUDIT_PATH,
    )


def _list_runner(args) -> dict[str, Any]:
    since = _date_start(args.since)
    until = _date_end(args.until)
    order = "ASC" if args.reverse else "DESC"
    where = ["chat_id = ?"]
    params: list[Any] = []

    con = connect_readonly(DB_PATH)
    try:
        chat_id, chat_title = resolve_chat_db(con, args.chat)
        params.append(chat_id)
        if since is not None:
            where.append("date >= ?")
            params.append(since)
        if until is not None:
            where.append("date <= ?")
            params.append(until)
        params.append(_positive_limit(args.limit))
        if not getattr(args, "include_deleted", False):
            where.append("(deleted = 0 OR deleted IS NULL)")
        rows = con.execute(
            f"""
            SELECT message_id, date, is_outgoing, text, media_type
            FROM tg_messages
            WHERE {" AND ".join(where)}
            ORDER BY date {order}, message_id {order}
            LIMIT ?
            """,
            params,
        ).fetchall()
    finally:
        con.close()

    return {
        "chat": {"chat_id": chat_id, "title": chat_title},
        "order": "oldest_first" if args.reverse else "newest_first",
        "filters": {
            "limit": _positive_limit(args.limit),
            "since": args.since,
            "until": args.until,
        },
        "messages": [_message_summary(row) for row in rows],
    }


def _list_human(data: dict) -> None:
    chat = data["chat"]
    msgs = data["messages"]
    if not msgs:
        print(f"No cached messages for '{chat['title']}' matched the filters.")
        return
    direction = "oldest first" if data["order"] == "oldest_first" else "newest first"
    print(f"=== {chat['title']}  chat_id {chat['chat_id']}  {len(msgs)} messages, {direction} ===\n")
    for message in msgs:
        arrow = "you" if message["is_outgoing"] else "them"
        ts = (message["date"] or "")[:19].replace("T", " ")
        if message["text"]:
            body = _truncate_human(message["text"])
        elif message["media_type"]:
            body = f"[{message['media_type']}]"
        else:
            body = "[empty]"
        print(f"  #{message['message_id']:<6} {ts}  {arrow:<4}  {body}")


def run_list(args) -> int:
    return run_command(
        "list-msgs", args,
        runner=lambda: _list_runner(args),
        human_formatter=_list_human,
        audit_path=AUDIT_PATH,
    )


def _get_runner(args) -> dict[str, Any]:
    con = connect_readonly(DB_PATH)
    try:
        chat_id, chat_title = resolve_chat_db(con, args.chat)
        deleted_clause = "" if getattr(args, "include_deleted", False) else " AND (deleted = 0 OR deleted IS NULL)"
        row = con.execute(
            f"""
            SELECT chat_id, message_id, sender_id, date, text,
                   is_outgoing, reply_to_msg_id, has_media, media_type,
                   media_path, raw_json
            FROM tg_messages
            WHERE chat_id = ? AND message_id = ?{deleted_clause}
            """,
            (chat_id, args.message_id),
        ).fetchone()
    finally:
        con.close()

    if row is None:
        raise NotFound(f"message {args.message_id} not cached in chat {chat_id}")
    return {
        "chat": {"chat_id": chat_id, "title": chat_title},
        "message": _full_message(row),
    }


def _get_human(data: dict) -> None:
    chat = data["chat"]
    message = data["message"]
    print(f"{chat['title']} (chat_id {chat['chat_id']}) message #{message['message_id']}")
    print(json.dumps(message, ensure_ascii=False, indent=2, default=str))


def run_get(args) -> int:
    return run_command(
        "get-msg", args,
        runner=lambda: _get_runner(args),
        human_formatter=_get_human,
        audit_path=AUDIT_PATH,
    )


# ---------- text writes ----------

def _read_text_arg(value: str) -> str:
    text = sys.stdin.read() if value == "-" else value
    text = text.rstrip("\n")
    if text.strip() == "":
        raise BadArgs("Text cannot be empty")
    return text


def _request_id(args) -> str:
    return getattr(args, "_request_id", "req-direct")


def _check_write_rate_limit() -> None:
    wait = OUTBOUND_WRITE_LIMITER.check()
    if wait > 0:
        raise LocalRateLimited("Local outbound write rate limit hit", wait)


def _dry_run_envelope(command: str, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "dry_run": True,
        "request_id": request_id,
        "command": command,
        "payload": payload,
    }


def _topic_reply_to(*, reply_to: int | None, topic: int | None) -> tuple[int | None, list[str]]:
    if reply_to is not None and topic is not None:
        return reply_to, ["--topic ignored because --reply-to was provided"]
    if reply_to is not None:
        return reply_to, []
    return topic, []


def _write_result(command: str, request_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "command": command,
        "request_id": request_id,
        "data": data,
        "warnings": [],
    }


def _resolve_write_chat(con, args, raw_selector: str) -> dict[str, Any]:
    require_explicit_or_fuzzy(args, raw_selector)
    chat_id, chat_title = resolve_chat_db(con, raw_selector)
    return {"chat_id": chat_id, "title": chat_title}


def _write_human(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _run_write_command(name: str, args, runner) -> int:
    return run_command(
        name,
        args,
        runner=lambda: runner(args),
        human_formatter=_write_human,
        audit_path=AUDIT_PATH,
    )


async def _send_runner(args) -> dict[str, Any]:
    command = "send"
    request_id = _request_id(args)
    require_write_allowed(args)
    text = _read_text_arg(args.text)

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data

        chat = _resolve_write_chat(con, args, args.chat)
        reply_to, warnings = _topic_reply_to(reply_to=args.reply_to, topic=getattr(args, "topic", None))
        payload = {
            "chat": chat,
            "text": text,
            "reply_to": reply_to,
            "topic_id": getattr(args, "topic", None),
            "silent": bool(args.silent),
            "link_preview": not bool(args.no_webpage),
            "telethon_method": "client.send_message",
            "warnings": warnings,
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)

        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=chat["chat_id"],
            resolved_chat_title=chat["title"],
            payload_preview=payload,
            telethon_method="client.send_message",
            dry_run=False,
        )

        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            sent = await client.send_message(
                entity,
                text,
                reply_to=reply_to,
                silent=bool(args.silent),
                link_preview=not bool(args.no_webpage),
            )
            data = {
                "chat": chat,
                "message_id": int(sent.id),
                "text": text,
                "reply_to": reply_to,
                "topic_id": getattr(args, "topic", None),
                "warnings": warnings,
                "idempotent_replay": False,
            }
            record_idempotency(
                con,
                args.idempotency_key,
                command,
                request_id,
                _write_result(command, request_id, data),
            )
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_send(args) -> int:
    return _run_write_command("send", args, _send_runner)


async def _edit_msg_runner(args) -> dict[str, Any]:
    command = "edit-msg"
    request_id = _request_id(args)
    require_write_allowed(args)
    text = _read_text_arg(args.text)

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        chat = _resolve_write_chat(con, args, args.chat)
        payload = {
            "chat": chat,
            "message_id": int(args.message_id),
            "text": text,
            "telethon_method": "client.edit_message",
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)
        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=chat["chat_id"],
            resolved_chat_title=chat["title"],
            payload_preview=payload,
            telethon_method="client.edit_message",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            edited = await client.edit_message(entity, int(args.message_id), text)
            data = {
                "chat": chat,
                "message_id": int(getattr(edited, "id", args.message_id)),
                "text": text,
                "idempotent_replay": False,
            }
            record_idempotency(
                con,
                args.idempotency_key,
                command,
                request_id,
                _write_result(command, request_id, data),
            )
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_edit_msg(args) -> int:
    return _run_write_command("edit-msg", args, _edit_msg_runner)


async def _forward_runner(args) -> dict[str, Any]:
    command = "forward"
    request_id = _request_id(args)
    require_write_allowed(args)

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        from_chat = _resolve_write_chat(con, args, args.from_chat)
        to_chat = _resolve_write_chat(con, args, args.to_chat)
        topic_id = getattr(args, "topic", None)
        method = (
            "client(ForwardMessagesRequest)" if topic_id is not None
            else "client.forward_messages"
        )
        payload = {
            "from_chat": from_chat,
            "to_chat": to_chat,
            "message_id": int(args.message_id),
            "topic_id": topic_id,
            "telethon_method": method,
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)
        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=to_chat["chat_id"],
            resolved_chat_title=to_chat["title"],
            payload_preview=payload,
            telethon_method=method,
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            from_entity = await client.get_entity(from_chat["chat_id"])
            to_entity = await client.get_entity(to_chat["chat_id"])
            if topic_id is not None:
                # Raw request: high-level forward_messages() doesn't accept top_msg_id.
                from_input = await client.get_input_entity(from_entity)
                to_input = await client.get_input_entity(to_entity)
                result = await client(ForwardMessagesRequest(
                    from_peer=from_input,
                    id=[int(args.message_id)],
                    to_peer=to_input,
                    top_msg_id=topic_id,
                ))
                forwarded_id = None
                for upd in getattr(result, "updates", []):
                    msg = getattr(upd, "message", None)
                    if msg is not None:
                        forwarded_id = msg.id
                        break
                if forwarded_id is None:
                    raise BadArgs("forward response did not include message_id")
            else:
                forwarded = await client.forward_messages(
                    to_entity,
                    messages=int(args.message_id),
                    from_peer=from_entity,
                )
                forwarded_id = forwarded.id if not isinstance(forwarded, list) else forwarded[0].id
            data = {
                "from_chat": from_chat,
                "to_chat": to_chat,
                "source_message_id": int(args.message_id),
                "message_id": int(forwarded_id),
                "topic_id": topic_id,
                "idempotent_replay": False,
            }
            record_idempotency(
                con,
                args.idempotency_key,
                command,
                request_id,
                _write_result(command, request_id, data),
            )
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_forward(args) -> int:
    return _run_write_command("forward", args, _forward_runner)


async def _pin_state_runner(args, *, command: str, pinned: bool) -> dict[str, Any]:
    request_id = _request_id(args)
    require_write_allowed(args)
    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        chat = _resolve_write_chat(con, args, args.chat)
        method = "client.pin_message" if pinned else "client.unpin_message"
        payload = {
            "chat": chat,
            "message_id": int(args.message_id),
            "pinned": pinned,
            "telethon_method": method,
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)
        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=chat["chat_id"],
            resolved_chat_title=chat["title"],
            payload_preview=payload,
            telethon_method=method,
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            if pinned:
                await client.pin_message(entity, int(args.message_id))
            else:
                await client.unpin_message(entity, int(args.message_id))
            data = {
                "chat": chat,
                "message_id": int(args.message_id),
                "pinned": pinned,
                "idempotent_replay": False,
            }
            record_idempotency(
                con,
                args.idempotency_key,
                command,
                request_id,
                _write_result(command, request_id, data),
            )
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


async def _pin_msg_runner(args) -> dict[str, Any]:
    return await _pin_state_runner(args, command="pin-msg", pinned=True)


def run_pin_msg(args) -> int:
    return _run_write_command("pin-msg", args, _pin_msg_runner)


async def _unpin_msg_runner(args) -> dict[str, Any]:
    return await _pin_state_runner(args, command="unpin-msg", pinned=False)


def run_unpin_msg(args) -> int:
    return _run_write_command("unpin-msg", args, _unpin_msg_runner)


async def _react_runner(args) -> dict[str, Any]:
    command = "react"
    request_id = _request_id(args)
    require_write_allowed(args)
    if str(args.emoji).strip() == "":
        raise BadArgs("Emoji cannot be empty")
    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        chat = _resolve_write_chat(con, args, args.chat)
        payload = {
            "chat": chat,
            "message_id": int(args.message_id),
            "emoji": args.emoji,
            "telethon_method": "SendReactionRequest",
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)
        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=chat["chat_id"],
            resolved_chat_title=chat["title"],
            payload_preview=payload,
            telethon_method="SendReactionRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            await client(
                SendReactionRequest(
                    peer=entity,
                    msg_id=int(args.message_id),
                    reaction=[ReactionEmoji(emoticon=args.emoji)],
                )
            )
            data = {
                "chat": chat,
                "message_id": int(args.message_id),
                "emoji": args.emoji,
                "idempotent_replay": False,
            }
            record_idempotency(
                con,
                args.idempotency_key,
                command,
                request_id,
                _write_result(command, request_id, data),
            )
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_react(args) -> int:
    return _run_write_command("react", args, _react_runner)


async def _mark_read_runner(args) -> dict[str, Any]:
    command = "mark-read"
    request_id = _request_id(args)
    require_write_allowed(args)
    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        chat = _resolve_write_chat(con, args, args.chat)
        payload = {
            "chat": chat,
            "telethon_method": "client.send_read_acknowledge",
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)
        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=chat["chat_id"],
            resolved_chat_title=chat["title"],
            payload_preview=payload,
            telethon_method="client.send_read_acknowledge",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            await client.send_read_acknowledge(entity)
            data = {
                "chat": chat,
                "marked_read": True,
                "idempotent_replay": False,
            }
            record_idempotency(
                con,
                args.idempotency_key,
                command,
                request_id,
                _write_result(command, request_id, data),
            )
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_mark_read(args) -> int:
    return _run_write_command("mark-read", args, _mark_read_runner)


# ---------- delete-msg (Phase 9) ----------

async def _delete_msg_runner(args) -> dict[str, Any]:
    from tgcli.safety import require_typed_confirm

    command = "delete-msg"
    request_id = _request_id(args)
    require_write_allowed(args)

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data

        chat = _resolve_write_chat(con, args, args.chat)
        require_typed_confirm(args, expected=chat["chat_id"], slot="chat_id")

        # Default for_everyone: revoke if ALL ids are outgoing (cached); else delete-for-me.
        for_everyone = args.for_everyone
        if for_everyone is None:
            placeholders = ",".join("?" * len(args.message_ids))
            outgoing_count = con.execute(
                f"SELECT COUNT(*) FROM tg_messages WHERE chat_id=? "
                f"AND message_id IN ({placeholders}) AND is_outgoing=1",
                (chat["chat_id"], *args.message_ids),
            ).fetchone()[0]
            for_everyone = (outgoing_count == len(args.message_ids))

        if args.dry_run:
            return _dry_run_envelope(command, request_id, {
                "chat": chat, "message_ids": list(args.message_ids),
                "for_everyone": for_everyone,
                "telethon_method": "client.delete_messages",
            })

        _check_write_rate_limit()
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_input_entity(chat["chat_id"])
            results: list[dict[str, Any]] = []
            for mid in args.message_ids:
                audit_pre(
                    AUDIT_PATH, cmd=command, request_id=request_id,
                    resolved_chat_id=chat["chat_id"], resolved_chat_title=chat["title"],
                    payload_preview={"message_id": mid, "for_everyone": for_everyone},
                    telethon_method="client.delete_messages",
                    dry_run=False,
                )
                try:
                    await client.delete_messages(entity, [mid], revoke=for_everyone)
                    if for_everyone:
                        con.execute(
                            "UPDATE tg_messages SET deleted = 1 "
                            "WHERE chat_id = ? AND message_id = ?",
                            (chat["chat_id"], mid),
                        )
                        con.commit()
                    results.append({"message_id": mid, "ok": True, "deleted": True})
                except Exception as exc:
                    results.append({"message_id": mid, "ok": False,
                                    "error": str(exc),
                                    "error_code": type(exc).__name__})

            succeeded = sum(1 for r in results if r["ok"])
            failed = len(results) - succeeded
            data = {
                "chat": chat,
                "for_everyone": for_everyone,
                "summary": {"total": len(results), "succeeded": succeeded, "failed": failed},
                "results": results,
                "idempotent_replay": False,
            }
            record_idempotency(con, args.idempotency_key, command, request_id,
                               _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_delete_msg(args) -> int:
    return _run_write_command("delete-msg", args, _delete_msg_runner)


# ---------- backfill ----------

def _check_backfill_caps(db_path, *, current_msg_count: int, args) -> list[str]:
    """Raise BadArgs if caps exceeded; return warnings list at 80%+."""
    warnings: list[str] = []
    max_msgs = int(getattr(args, "max_messages", 100_000) or 100_000)
    max_db_mb = int(getattr(args, "max_db_size_mb", 500) or 500)
    if current_msg_count >= max_msgs:
        raise BadArgs(
            f"backfill refused: message count {current_msg_count} >= --max-messages {max_msgs}"
        )
    if current_msg_count >= int(max_msgs * 0.8):
        warnings.append(f"approaching --max-messages cap ({current_msg_count}/{max_msgs})")
    try:
        size_bytes = db_path.stat().st_size
    except OSError:
        return warnings
    size_mb = size_bytes / (1024 * 1024)
    if size_mb >= max_db_mb:
        raise BadArgs(
            f"backfill refused: db size {size_mb:.0f}MB >= --max-db-size-mb {max_db_mb}"
        )
    if size_mb >= max_db_mb * 0.8:
        warnings.append(f"approaching --max-db-size-mb cap ({size_mb:.0f}/{max_db_mb}MB)")
    return warnings


async def _backfill_runner(args) -> dict[str, Any]:
    from tgcli.safety import require_writes_not_readonly
    require_writes_not_readonly(args)
    client = make_client(SESSION_PATH)
    await client.start()
    con = connect(DB_PATH)
    # Phase 8: cap check before the heavy work.
    current_count = con.execute("SELECT COUNT(*) FROM tg_messages").fetchone()[0]
    cap_warnings = _check_backfill_caps(DB_PATH, current_msg_count=current_count, args=args)
    quiet = bool(getattr(args, "json", False))

    chat_count = 0
    msg_total = 0
    media_total = 0
    skipped: list[dict] = []
    per_chat: list[dict] = []

    try:
        async for dialog in client.iter_dialogs():
            if chat_count >= args.max_chats:
                break
            chat_count += 1
            _upsert_chat(con, dialog.entity)
            con.commit()

            added = 0
            media_added = 0
            try:
                async for msg in client.iter_messages(dialog.entity, limit=args.per_chat):
                    media_path = None
                    if args.download_media and getattr(msg, "media", None):
                        media_path = await _download_media(client, msg, dialog.id)
                        if media_path:
                            media_added += 1
                    _upsert_message(con, msg, dialog.id, media_path=media_path)
                    added += 1
                con.commit()
            except Exception as e:
                title = _display_title(dialog.entity)
                skipped.append({"chat_id": dialog.id, "title": title, "error": str(e)})
                if not quiet:
                    print(f"  [{chat_count:>3}/{args.max_chats}] {title[:40]:40s}  SKIP ({e})", file=sys.stderr)
                continue

            msg_total += added
            media_total += media_added
            per_chat.append({
                "chat_id": dialog.id,
                "title": _display_title(dialog.entity),
                "messages_added": added,
                "media_added": media_added,
            })
            if not quiet:
                media_note = f", {media_added} media" if args.download_media else ""
                print(
                    f"  [{chat_count:>3}/{args.max_chats}] "
                    f"{_display_title(dialog.entity)[:40]:40s}  +{added:>4} msgs{media_note}  "
                    f"(running {msg_total})",
                    file=sys.stderr,
                )
            await asyncio.sleep(args.throttle)
    finally:
        con.close()
        await client.disconnect()

    return {
        "chats_processed": chat_count,
        "messages_inserted": msg_total,
        "media_downloaded": media_total,
        "skipped": skipped,
        "per_chat": per_chat,
        "cap_warnings": cap_warnings,
    }


def _backfill_human(data: dict) -> None:
    media_note = f", {data['media_downloaded']} media files" if data["media_downloaded"] else ""
    print(
        f"\nBackfill done: {data['chats_processed']} chats, "
        f"{data['messages_inserted']} messages{media_note}"
    )
    if data["skipped"]:
        print(f"  ({len(data['skipped'])} chats skipped due to errors)")


def run_backfill(args) -> int:
    return run_command(
        "backfill", args,
        runner=lambda: _backfill_runner(args),
        human_formatter=_backfill_human,
        audit_path=AUDIT_PATH,
    )
