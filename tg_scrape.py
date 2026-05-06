"""
Telegram read-only scraper.

Logs in as your account, captures incoming messages, backfills history,
syncs contacts. All to local SQLite. Never sends a message except optionally
a one-line summary to your own Saved Messages.

Usage:
    export TG_API_ID=12345678
    export TG_API_HASH=abcdef0123456789abcdef0123456789

    python tg_scrape.py login                              # one-time SMS login
    python tg_scrape.py stats                              # DB summary
    python tg_scrape.py backfill --per-chat 200            # pull recent history
    python tg_scrape.py sync-contacts                      # pull phone-book
    python tg_scrape.py listen                             # capture incoming forever
    python tg_scrape.py listen --notify                    #   + echo to Saved Messages
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient, events
from telethon.tl.functions.contacts import GetContactsRequest
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

ROOT = Path(__file__).parent
DB_PATH = ROOT / "telegram.sqlite"
SESSION_PATH = ROOT / "tg.session"
ENV_PATH = ROOT / ".env"


def _load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines from .env into os.environ (shell exports still win)."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_env_file(ENV_PATH)

API_ID = int(os.environ.get("TG_API_ID", "0") or 0)
API_HASH = os.environ.get("TG_API_HASH", "")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tg_chats (
    chat_id      INTEGER PRIMARY KEY,
    type         TEXT,
    title        TEXT,
    username     TEXT,
    phone        TEXT,
    first_name   TEXT,
    last_name    TEXT,
    is_bot       INTEGER,
    last_seen_at TEXT,
    raw_json     TEXT
);

CREATE TABLE IF NOT EXISTS tg_messages (
    chat_id          INTEGER,
    message_id       INTEGER,
    sender_id        INTEGER,
    date             TEXT,
    text             TEXT,
    is_outgoing      INTEGER,
    reply_to_msg_id  INTEGER,
    has_media        INTEGER,
    media_type       TEXT,
    media_path       TEXT,
    raw_json         TEXT,
    PRIMARY KEY (chat_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_date ON tg_messages(chat_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_messages_date ON tg_messages(date DESC);

CREATE TABLE IF NOT EXISTS tg_contacts (
    user_id    INTEGER PRIMARY KEY,
    phone      TEXT,
    first_name TEXT,
    last_name  TEXT,
    username   TEXT,
    is_mutual  INTEGER,
    synced_at  TEXT
);
"""


def db_connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    # Upgrade DBs created before media_path existed
    try:
        con.execute("ALTER TABLE tg_messages ADD COLUMN media_path TEXT")
    except sqlite3.OperationalError:
        pass
    return con


def make_client() -> TelegramClient:
    if not API_ID or not API_HASH:
        sys.exit(
            "ERROR: TG_API_ID and TG_API_HASH must be set as env vars.\n"
            "Register a personal app at https://my.telegram.org/apps"
        )
    return TelegramClient(str(SESSION_PATH), API_ID, API_HASH)


def chat_kind(entity) -> str:
    if isinstance(entity, User):
        return "bot" if getattr(entity, "bot", False) else "user"
    if isinstance(entity, Chat):
        return "group"
    if isinstance(entity, Channel):
        return "channel" if getattr(entity, "broadcast", False) else "supergroup"
    return "unknown"


def display_title(entity) -> str:
    if isinstance(entity, User):
        parts = [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]
        name = " ".join(p for p in parts if p).strip()
        return name or getattr(entity, "username", None) or f"user_{entity.id}"
    return getattr(entity, "title", None) or f"chat_{getattr(entity, 'id', '?')}"


def upsert_chat(con: sqlite3.Connection, entity) -> None:
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
            chat_kind(entity),
            display_title(entity),
            getattr(entity, "username", None),
            getattr(entity, "phone", None),
            getattr(entity, "first_name", None),
            getattr(entity, "last_name", None),
            int(bool(getattr(entity, "bot", False))),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps(entity.to_dict(), default=str)[:50000],
        ),
    )


def media_type_of(msg) -> str | None:
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


def upsert_message(con: sqlite3.Connection, msg, chat_id: int,
                   media_path: str | None = None) -> None:
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
            media_type_of(msg),
            str(media_path) if media_path else None,
            json.dumps(msg.to_dict(), default=str)[:50000],
        ),
    )


async def _download_media(client, msg, chat_id: int) -> str | None:
    """Save msg's media into media/<chat_id>/<msg_id>.<ext>. Returns path or None."""
    if not getattr(msg, "media", None):
        return None
    media_dir = ROOT / "media" / str(chat_id)
    media_dir.mkdir(parents=True, exist_ok=True)
    try:
        path = await client.download_media(msg, file=str(media_dir / str(msg.id)))
        return str(path) if path else None
    except Exception as e:
        print(f"    download failed: chat {chat_id} msg {msg.id}: {e}")
        return None


async def cmd_login() -> None:
    client = make_client()
    await client.start()
    me = await client.get_me()
    name = display_title(me)
    print(f"Logged in as {name} (@{me.username}) — id {me.id}")
    print(f"Session saved to {SESSION_PATH}")
    await client.disconnect()


async def cmd_stats() -> None:
    if not DB_PATH.exists():
        print(f"DB not yet created at {DB_PATH}. Run 'login' then 'backfill'.")
        return
    con = db_connect()
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


async def cmd_contacts(limit: int, with_phone_only: bool,
                        chatted_only: bool) -> None:
    if not DB_PATH.exists():
        print("DB not yet created. Run 'sync-contacts' first.")
        return
    con = db_connect()

    join = ("INNER JOIN tg_chats ch ON ch.chat_id = c.user_id"
            if chatted_only else
            "LEFT  JOIN tg_chats ch ON ch.chat_id = c.user_id")
    wheres = []
    if with_phone_only:
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
    rows = con.execute(sql, (limit,)).fetchall()
    if not rows:
        print("No contacts match. If using --chatted, run 'discover' first.")
        return

    flags = []
    if chatted_only:
        flags.append("chatted only")
    if with_phone_only:
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


async def cmd_backfill(per_chat: int, max_chats: int, throttle: float,
                       download_media: bool = False) -> None:
    client = make_client()
    await client.start()
    con = db_connect()

    chat_count = 0
    msg_total = 0
    media_total = 0

    async for dialog in client.iter_dialogs():
        if chat_count >= max_chats:
            break
        chat_count += 1
        upsert_chat(con, dialog.entity)
        con.commit()

        added = 0
        media_added = 0
        try:
            async for msg in client.iter_messages(dialog.entity, limit=per_chat):
                media_path = None
                if download_media and getattr(msg, "media", None):
                    media_path = await _download_media(client, msg, dialog.id)
                    if media_path:
                        media_added += 1
                upsert_message(con, msg, dialog.id, media_path=media_path)
                added += 1
            con.commit()
        except Exception as e:
            print(f"  [{chat_count:>3}/{max_chats}] {display_title(dialog.entity)[:40]:40s}  SKIP ({e})")
            continue

        msg_total += added
        media_total += media_added
        media_note = f", {media_added} media" if download_media else ""
        print(f"  [{chat_count:>3}/{max_chats}] {display_title(dialog.entity)[:40]:40s}  +{added:>4} msgs{media_note}  (running {msg_total})")
        await asyncio.sleep(throttle)

    con.close()
    await client.disconnect()
    media_note = f", {media_total} media files" if download_media else ""
    print(f"\nBackfill done: {chat_count} chats, {msg_total} messages{media_note}")


async def cmd_discover() -> None:
    """Fast scan: upsert every dialog into tg_chats. No messages pulled, no media."""
    client = make_client()
    await client.start()
    con = db_connect()
    n = 0
    async for dialog in client.iter_dialogs():
        upsert_chat(con, dialog.entity)
        n += 1
        if n % 50 == 0:
            con.commit()
            print(f"  ...{n} dialogs")
    con.commit()
    con.close()
    await client.disconnect()
    print(f"Discovered {n} dialogs in tg_chats")


async def cmd_sync_contacts() -> None:
    client = make_client()
    await client.start()
    con = db_connect()

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


def _strip_accents(s: str | None) -> str:
    """Lowercase + drop diacritics, so 'Hamid' matches 'Hamïd'."""
    if not s:
        return ""
    decomposed = unicodedata.normalize("NFD", s)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").lower()


async def cmd_show(pattern: str | None, chat_id: int | None,
                   limit: int, reverse: bool) -> None:
    if pattern is None and chat_id is None:
        print("Need a pattern or --chat-id. Example: python tg_scrape.py show Ijadi")
        return
    if not DB_PATH.exists():
        print(f"DB not yet at {DB_PATH}. Run 'backfill' first.")
        return

    con = db_connect()
    chat_title = None

    if chat_id is None:
        rows = con.execute("SELECT chat_id, title, type FROM tg_chats").fetchall()
        needle = _strip_accents(pattern)
        matches = [r for r in rows if needle in _strip_accents(r[1])]
        if not matches:
            print(f"No chat title contains '{pattern}'.")
            return
        if len(matches) > 1:
            print(f"Multiple chats match '{pattern}':")
            for cid, title, kind in matches:
                print(f"  chat_id={cid:>14}  [{kind:>10}]  {title}")
            print("\nDisambiguate with --chat-id <id>")
            return
        chat_id, chat_title, _ = matches[0]
    else:
        row = con.execute("SELECT title FROM tg_chats WHERE chat_id=?", (chat_id,)).fetchone()
        if not row:
            print(f"chat_id {chat_id} not in DB")
            return
        chat_title = row[0]

    order = "ASC" if reverse else "DESC"
    rows = con.execute(
        f"""
        SELECT date, is_outgoing, text, media_type
        FROM tg_messages
        WHERE chat_id = ?
        ORDER BY date {order}
        LIMIT ?
        """,
        (chat_id, limit),
    ).fetchall()

    if not rows:
        print(f"No messages stored for '{chat_title}' (chat_id {chat_id}).")
        return

    direction = "oldest first" if reverse else "newest first"
    print(f"=== {chat_title}  ·  chat_id {chat_id}  ·  {len(rows)} messages, {direction} ===\n")
    for date, is_out, text, media in rows:
        arrow = "→ you " if is_out else "← them"
        ts = (date or "")[:19].replace("T", " ")
        if text:
            body = text
        elif media:
            body = f"[{media}]"
        else:
            body = "[empty]"
        print(f"  {ts}  {arrow}  {body}")


async def cmd_listen(notify: bool, download_media: bool = False) -> None:
    client = make_client()
    await client.start()
    con = db_connect()
    me = await client.get_me()

    print(f"Listening as {display_title(me)} (id {me.id})")
    print(f"  notify={'ON (echo to Saved Messages)' if notify else 'OFF'}")
    print(f"  download_media={'ON' if download_media else 'OFF'}")
    print("  Ctrl+C to stop\n")

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        try:
            chat = await event.get_chat()
            sender = await event.get_sender()

            upsert_chat(con, chat)
            if sender is not None and getattr(sender, "id", None) != getattr(chat, "id", None):
                upsert_chat(con, sender)

            media_path = None
            if download_media and getattr(event.message, "media", None):
                media_path = await _download_media(client, event.message, event.chat_id)
            upsert_message(con, event.message, event.chat_id, media_path=media_path)
            con.commit()

            sender_name = display_title(sender) if sender else "?"
            chat_name = display_title(chat) if chat else "DM"
            preview = (event.text or "[media]").replace("\n", " ")[:200]

            ts = datetime.now().strftime("%H:%M:%S")
            print(f"  [{ts}] {sender_name} in {chat_name}: {preview}")

            if notify:
                line = f"📨 {sender_name} ({chat_name}): {preview}"
                await client.send_message("me", line[:4000])
        except Exception as e:
            print(f"  ERROR: {e}")

    await client.run_until_disconnected()


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram read-only scraper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="One-time interactive auth")
    sub.add_parser("stats", help="DB summary")
    sub.add_parser("sync-contacts", help="Pull phone-book contacts")
    sub.add_parser("discover", help="Fast scan of every dialog (no messages)")

    co = sub.add_parser("contacts", help="List synced contacts with phone numbers")
    co.add_argument("--limit", type=int, default=200)
    co.add_argument("--with-phone-only", action="store_true",
                    help="Hide contacts with no phone number")
    co.add_argument("--chatted", action="store_true",
                    help="Only contacts with whom you have a dialog (run 'discover' first)")

    bf = sub.add_parser("backfill", help="Pull historical messages")
    bf.add_argument("--per-chat", type=int, default=200,
                    help="Max messages per chat (default 200)")
    bf.add_argument("--max-chats", type=int, default=100,
                    help="Max chats to visit (default 100)")
    bf.add_argument("--throttle", type=float, default=1.0,
                    help="Seconds between chats (default 1.0)")
    bf.add_argument("--download-media", action="store_true",
                    help="Also download photos / voice / video / documents to media/<chat_id>/")

    li = sub.add_parser("listen", help="Capture new incoming messages forever")
    li.add_argument("--notify", action="store_true",
                    help="Echo each incoming message to your own Saved Messages")
    li.add_argument("--download-media", action="store_true",
                    help="Also download photos / voice / video / documents to media/<chat_id>/")

    sh = sub.add_parser("show", help="Print messages from one chat")
    sh.add_argument("pattern", nargs="?", default=None,
                    help="Substring of chat title (case- and accent-insensitive)")
    sh.add_argument("--chat-id", type=int, default=None,
                    help="Use exact chat_id instead of pattern")
    sh.add_argument("--limit", type=int, default=50,
                    help="Number of messages (default 50)")
    sh.add_argument("--reverse", action="store_true",
                    help="Oldest first instead of newest first")

    args = parser.parse_args()

    coros = {
        "login": lambda: cmd_login(),
        "stats": lambda: cmd_stats(),
        "sync-contacts": lambda: cmd_sync_contacts(),
        "discover": lambda: cmd_discover(),
        "contacts": lambda: cmd_contacts(args.limit, args.with_phone_only,
                                          args.chatted),
        "backfill": lambda: cmd_backfill(args.per_chat, args.max_chats,
                                          args.throttle, args.download_media),
        "listen": lambda: cmd_listen(notify=args.notify,
                                      download_media=args.download_media),
        "show": lambda: cmd_show(args.pattern, args.chat_id, args.limit, args.reverse),
    }
    asyncio.run(coros[args.cmd]())


if __name__ == "__main__":
    main()
