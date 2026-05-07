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

from tgcli.client import make_client
from tgcli.commands._common import (
    AUDIT_PATH, DB_PATH, MEDIA_DIR, ROOT, SESSION_PATH, add_output_flags,
)
from tgcli.db import connect, connect_readonly
from tgcli.dispatch import run_command
from tgcli.resolve import resolve_chat_db
from tgcli.safety import BadArgs


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
    add_output_flags(sh)
    sh.set_defaults(func=run_show)

    bf = sub.add_parser("backfill", help="Pull historical messages")
    bf.add_argument("--per-chat", type=int, default=200)
    bf.add_argument("--max-chats", type=int, default=100)
    bf.add_argument("--throttle", type=float, default=1.0)
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
    rows = con.execute(
        f"""
        SELECT date, is_outgoing, text, media_type
        FROM tg_messages
        WHERE chat_id = ?
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
            body = m["text"]
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


# ---------- backfill ----------

async def _backfill_runner(args) -> dict[str, Any]:
    client = make_client(SESSION_PATH)
    await client.start()
    con = connect(DB_PATH)
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
