"""Live event subcommands. Phase 1 port: listen."""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any

from telethon import events

from tgcli.client import make_client
from tgcli.commands._common import AUDIT_PATH, DB_PATH, SESSION_PATH, add_output_flags
from tgcli.commands.messages import (
    _display_title,
    _download_media,
    _upsert_chat,
    _upsert_message,
)
from tgcli.db import connect
from tgcli.dispatch import run_command


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("listen", help="Capture new incoming messages forever")
    p.add_argument(
        "--notify",
        action="store_true",
        help="Echo each incoming message to your own Saved Messages",
    )
    p.add_argument(
        "--download-media",
        action="store_true",
        help="Also download photos / voice / video / documents to media/<chat_id>/",
    )
    add_output_flags(p)
    p.set_defaults(func=run_listen)


async def _runner(args) -> dict[str, Any]:
    from tgcli.safety import require_writes_not_readonly

    require_writes_not_readonly(args)
    client = make_client(SESSION_PATH)
    await client.start()
    con = connect(DB_PATH)
    me = await client.get_me()
    counters = {"messages_seen": 0, "media_downloaded": 0, "errors": 0}
    quiet = bool(getattr(args, "json", False))
    if not quiet:
        print(f"Listening as {_display_title(me)} (id {me.id})")
        print(f"  notify={'ON (echo to Saved Messages)' if args.notify else 'OFF'}")
        print(f"  download_media={'ON' if args.download_media else 'OFF'}")
        print("  Ctrl+C to stop\n")

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        try:
            chat = await event.get_chat()
            sender = await event.get_sender()
            _upsert_chat(con, chat)
            if sender is not None and getattr(sender, "id", None) != getattr(chat, "id", None):
                _upsert_chat(con, sender)
            media_path = None
            if args.download_media and getattr(event.message, "media", None):
                media_path = await _download_media(client, event.message, event.chat_id)
                if media_path:
                    counters["media_downloaded"] += 1
            _upsert_message(con, event.message, event.chat_id, media_path=media_path)
            con.commit()
            counters["messages_seen"] += 1
            sender_name = _display_title(sender) if sender else "?"
            chat_name = _display_title(chat) if chat else "DM"
            preview = (event.text or "[media]").replace("\n", " ")[:200]
            ts = datetime.now().strftime("%H:%M:%S")
            if not quiet:
                print(f"  [{ts}] {sender_name} in {chat_name}: {preview}")
            if args.notify:
                line = f"📨 {sender_name} ({chat_name}): {preview}"
                await client.send_message("me", line[:4000])
        except Exception as e:
            counters["errors"] += 1
            if not quiet:
                print(f"  ERROR: {e}")

    try:
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        pass
    finally:
        con.close()
        await client.disconnect()
    return counters


def _human(data: dict) -> None:
    print(
        f"\nListener stopped. Seen {data['messages_seen']} messages, "
        f"{data['media_downloaded']} media downloaded, {data['errors']} errors."
    )


def run_listen(args) -> int:
    return run_command(
        "listen",
        args,
        runner=lambda: _runner(args),
        human_formatter=_human,
        audit_path=AUDIT_PATH,
    )
