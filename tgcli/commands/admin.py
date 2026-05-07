"""Channel/group administration commands."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any

from telethon.errors.rpcerrorlist import (
    ChatAdminRequiredError,
    RightForbiddenError,
    UserAdminInvalidError,
)
from telethon.tl.functions.channels import (
    EditAdminRequest,
    EditBannedRequest,
    EditPhotoRequest,
    EditTitleRequest,
    GetParticipantsRequest,
)
from telethon.tl.functions.messages import (
    EditChatAboutRequest,
    EditChatDefaultBannedRightsRequest,
    EditChatPhotoRequest,
    EditChatTitleRequest,
    EditExportedChatInviteRequest,
    ExportChatInviteRequest,
    SearchRequest,
)
from telethon.tl.types import (
    ChannelParticipantsRecent,
    ChatAdminRights,
    ChatBannedRights,
    InputChatUploadedPhoto,
    InputMessagesFilterPinned,
)

from tgcli.client import make_client
from tgcli.commands._common import (
    AUDIT_PATH,
    DB_PATH,
    SESSION_PATH,
    add_output_flags,
    add_write_flags,
)
from tgcli.commands.media import _detect_photo_mime, _safe_upload_path
from tgcli.commands.messages import (
    _check_write_rate_limit,
    _display_title,
    _dry_run_envelope,
    _request_id,
    _resolve_write_chat,
    _run_write_command,
    _write_result,
)
from tgcli.db import connect, connect_readonly
from tgcli.dispatch import run_command
from tgcli.idempotency import lookup as lookup_idempotency
from tgcli.idempotency import record as record_idempotency
from tgcli.resolve import resolve_chat_db
from tgcli.safety import BadArgs, audit_pre, require_typed_confirm, require_write_allowed

_ADMIN_RIGHT_FLAGS = (
    "change_info",
    "post_messages",
    "edit_messages",
    "delete_messages",
    "ban_users",
    "invite_users",
    "pin_messages",
    "add_admins",
    "anonymous",
    "manage_call",
    "other",
    "manage_topics",
)

_DEFAULT_PROMOTE_RIGHTS = {
    "change_info": True,
    "delete_messages": True,
    "ban_users": True,
    "invite_users": True,
    "pin_messages": True,
    "manage_call": True,
    "manage_topics": True,
}

_BANNED_RIGHT_FLAGS = (
    "send_messages",
    "send_media",
    "send_stickers",
    "send_gifs",
    "send_games",
    "send_inline",
    "embed_links",
    "send_polls",
    "change_info",
    "invite_users",
    "pin_messages",
    "manage_topics",
    "send_photos",
    "send_videos",
    "send_roundvideos",
    "send_audios",
    "send_voices",
    "send_docs",
    "send_plain",
)


def register(sub: argparse._SubParsersAction) -> None:
    title = sub.add_parser("chat-title", help="Rename a group, supergroup, or channel")
    title.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    title.add_argument("title", help="New chat title")
    add_write_flags(title, destructive=False)
    add_output_flags(title)
    title.set_defaults(func=run_chat_title)

    photo = sub.add_parser("chat-photo", help="Set a group, supergroup, or channel photo")
    photo.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    photo.add_argument("file", help="Local JPEG/PNG/WebP/GIF file")
    photo.add_argument("--max-size-mb", type=int, default=10, help="Default 10")
    add_write_flags(photo, destructive=False)
    add_output_flags(photo)
    photo.set_defaults(func=run_chat_photo)

    about = sub.add_parser("chat-description", help="Set a group/channel description")
    about.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    about.add_argument("description", help="New description text")
    add_write_flags(about, destructive=False)
    add_output_flags(about)
    about.set_defaults(func=run_chat_description)

    promote = sub.add_parser("promote", help="Promote a chat member to admin")
    _add_admin_target_args(promote)
    _add_admin_right_flags(promote)
    promote.add_argument("--rank", default=None, help="Optional admin rank")
    add_write_flags(promote, destructive=True)
    add_output_flags(promote)
    promote.set_defaults(func=run_promote)

    demote = sub.add_parser("demote", help="Demote a chat admin")
    _add_admin_target_args(demote)
    add_write_flags(demote, destructive=True)
    add_output_flags(demote)
    demote.set_defaults(func=run_demote)

    ban = sub.add_parser("ban-from-chat", help="Ban a user from a group/channel")
    _add_admin_target_args(ban)
    ban.add_argument("--until", default=None, help="UTC expiry as YYYY-MM-DDTHH:MM:SS")
    add_write_flags(ban, destructive=True)
    add_output_flags(ban)
    ban.set_defaults(func=run_ban_from_chat)

    kick = sub.add_parser("kick", help="Remove a user without leaving them banned")
    _add_admin_target_args(kick)
    add_write_flags(kick, destructive=True)
    add_output_flags(kick)
    kick.set_defaults(func=run_kick)

    unban = sub.add_parser("unban-from-chat", help="Lift a chat ban")
    _add_admin_target_args(unban)
    add_write_flags(unban, destructive=False)
    add_output_flags(unban)
    unban.set_defaults(func=run_unban_from_chat)

    perms = sub.add_parser("set-permissions", help="Set default member permissions")
    perms.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    _add_permission_flags(perms)
    perms.add_argument("--review", action="store_true", help="Show intended changes only")
    add_write_flags(perms, destructive=False)
    add_output_flags(perms)
    perms.set_defaults(func=run_set_permissions)

    invite = sub.add_parser("chat-invite-link", help="Generate or revoke a chat invite link")
    invite.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    invite.add_argument("--revoke", action="store_true", help="Revoke an exported invite link")
    invite.add_argument("--link", default=None, help="Invite link to revoke")
    invite.add_argument("--title", default=None, help="Invite link title")
    invite.add_argument("--expire", default=None, help="UTC expiry as YYYY-MM-DDTHH:MM:SS")
    invite.add_argument("--usage-limit", type=int, default=None, help="Maximum joins")
    invite.add_argument("--request-needed", action="store_true", help="Require join approval")
    add_write_flags(invite, destructive=False)
    add_output_flags(invite)
    invite.set_defaults(func=run_chat_invite_link)

    pinned = sub.add_parser("chat-pinned-list", help="List pinned messages in a chat")
    pinned.add_argument("chat", help="Chat selector resolved from the local DB")
    pinned.add_argument("--limit", type=int, default=50, help="Number of messages")
    add_output_flags(pinned)
    pinned.set_defaults(func=run_chat_pinned_list)

    members = sub.add_parser("chat-members", help="List group/channel members")
    members.add_argument("chat", help="Chat selector resolved from the local DB")
    members.add_argument("--limit", type=int, default=50, help="Number of members")
    members.add_argument("--offset", type=int, default=0, help="Offset for paging")
    add_output_flags(members)
    members.set_defaults(func=run_chat_members)


def _add_admin_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    parser.add_argument("user", help="User id, @username, or fuzzy title with --fuzzy")


def _add_admin_right_flags(parser: argparse.ArgumentParser) -> None:
    for field in _ADMIN_RIGHT_FLAGS:
        parser.add_argument(f"--{field.replace('_', '-')}", dest=field, action="store_true")


def _add_permission_flags(parser: argparse.ArgumentParser) -> None:
    for field in _BANNED_RIGHT_FLAGS:
        flag = field.replace("_", "-")
        group = parser.add_mutually_exclusive_group()
        group.add_argument(f"--{flag}", dest=field, action="store_true", default=None)
        group.add_argument(f"--no-{flag}", dest=field, action="store_false")


def _write_human(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _run_admin_write(name: str, args, runner) -> int:
    return _run_write_command(name, args, runner)


def _chat_type(con, chat_id: int) -> str | None:
    row = con.execute("SELECT type FROM tg_chats WHERE chat_id = ?", (chat_id,)).fetchone()
    return row[0] if row else None


def _is_channelish(chat_type: str | None) -> bool:
    return chat_type in {"channel", "supergroup"}


def _resolve_admin_user(con, args) -> dict[str, Any]:
    proxy = argparse.Namespace(**vars(args))
    proxy.chat = args.user
    user = _resolve_write_chat(con, proxy, args.user)
    row = con.execute(
        """
        SELECT type, title, first_name, last_name, username
        FROM tg_chats
        WHERE chat_id = ?
        """,
        (user["chat_id"],),
    ).fetchone()
    if row is None or row[0] not in {"user", "bot"}:
        actual = row[0] if row else "(uncached)"
        raise BadArgs(f"user selector resolved to {actual!r}; expected user or bot")
    display = user["title"]
    if row[2] or row[3]:
        display = " ".join(p for p in (row[2], row[3]) if p).strip()
    return {"user_id": int(user["chat_id"]), "display_name": display}


def _selected_admin_rights(args) -> dict[str, bool]:
    selected = {field: True for field in _ADMIN_RIGHT_FLAGS if bool(getattr(args, field, False))}
    return selected or dict(_DEFAULT_PROMOTE_RIGHTS)


def _admin_rights(rights: dict[str, bool]) -> ChatAdminRights:
    return ChatAdminRights(**{field: rights.get(field) for field in _ADMIN_RIGHT_FLAGS})


def _empty_admin_rights() -> ChatAdminRights:
    return ChatAdminRights(**{field: None for field in _ADMIN_RIGHT_FLAGS})


def _until_date(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise BadArgs(f"invalid --until/--expire {raw!r}; expected ISO datetime") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _ban_rights(*, banned: bool, until: datetime | None = None) -> ChatBannedRights:
    return ChatBannedRights(until_date=until, view_messages=banned)


def _permissions_from_args(args) -> dict[str, bool]:
    return {
        field: value
        for field in _BANNED_RIGHT_FLAGS
        if (value := getattr(args, field, None)) is not None
    }


def _default_banned_rights(permissions: dict[str, bool]) -> ChatBannedRights:
    # CLI flags express allowed permissions. Telegram banned rights use inverse booleans.
    return ChatBannedRights(
        until_date=None,
        **{field: not allowed for field, allowed in permissions.items()},
    )


def _message_summary(msg) -> dict[str, Any]:
    return {
        "message_id": int(getattr(msg, "id", 0)),
        "sender_id": getattr(msg, "sender_id", None),
        "date": getattr(getattr(msg, "date", None), "isoformat", lambda: None)(),
        "text": getattr(msg, "text", None) or None,
    }


def _user_summary(user) -> dict[str, Any]:
    parts = [getattr(user, "first_name", None), getattr(user, "last_name", None)]
    display_name = " ".join(p for p in parts if p).strip() or _display_title(user)
    return {
        "user_id": int(user.id),
        "display_name": display_name,
        "username": getattr(user, "username", None),
        "is_bot": bool(getattr(user, "bot", False)),
    }


async def _chat_title_runner(args) -> dict[str, Any]:
    command = "chat-title"
    request_id = _request_id(args)
    require_write_allowed(args)
    if not args.title.strip():
        raise BadArgs("title cannot be empty")
    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        chat = _resolve_write_chat(con, args, args.chat)
        chat_type = _chat_type(con, chat["chat_id"])
        method = (
            "channels.EditTitleRequest"
            if _is_channelish(chat_type)
            else "messages.EditChatTitleRequest"
        )
        payload = {"chat": chat, "title": args.title, "telethon_method": method}
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
            if _is_channelish(chat_type):
                entity = await client.get_input_entity(chat["chat_id"])
                await client(EditTitleRequest(channel=entity, title=args.title))
            else:
                await client(
                    EditChatTitleRequest(chat_id=abs(int(chat["chat_id"])), title=args.title)
                )
            data = {
                "chat": chat,
                "title": args.title,
                "renamed": True,
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


async def _chat_photo_runner(args) -> dict[str, Any]:
    command = "chat-photo"
    request_id = _request_id(args)
    require_write_allowed(args)
    path = _safe_upload_path(args.file, max_size_mb=getattr(args, "max_size_mb", 10))
    mime_type = _detect_photo_mime(path)
    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        chat = _resolve_write_chat(con, args, args.chat)
        chat_type = _chat_type(con, chat["chat_id"])
        method = (
            "channels.EditPhotoRequest"
            if _is_channelish(chat_type)
            else "messages.EditChatPhotoRequest"
        )
        payload = {
            "chat": chat,
            "file_path": str(path),
            "mime_type": mime_type,
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
            uploaded = await client.upload_file(str(path))
            photo = InputChatUploadedPhoto(file=uploaded)
            if _is_channelish(chat_type):
                entity = await client.get_input_entity(chat["chat_id"])
                await client(EditPhotoRequest(channel=entity, photo=photo))
            else:
                await client(EditChatPhotoRequest(chat_id=abs(int(chat["chat_id"])), photo=photo))
            data = {
                "chat": chat,
                "photo_set": True,
                "file_path": str(path),
                "mime_type": mime_type,
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


async def _chat_description_runner(args) -> dict[str, Any]:
    command = "chat-description"
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
            "description": args.description,
            "telethon_method": "messages.EditChatAboutRequest",
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
            telethon_method="messages.EditChatAboutRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_input_entity(chat["chat_id"])
            await client(EditChatAboutRequest(peer=entity, about=args.description))
            data = {
                "chat": chat,
                "description": args.description,
                "description_set": True,
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


async def _admin_rights_runner(args, *, command: str, promote: bool) -> dict[str, Any]:
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
        user = _resolve_admin_user(con, args)
        rights = _selected_admin_rights(args) if promote else {}
        payload = {
            "chat": chat,
            "user": user,
            "admin_rights": rights,
            "rank": getattr(args, "rank", None),
            "telethon_method": "channels.EditAdminRequest",
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
            telethon_method="channels.EditAdminRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            channel = await client.get_input_entity(chat["chat_id"])
            input_user = await client.get_input_entity(user["user_id"])
            admin_rights = _admin_rights(rights) if promote else _empty_admin_rights()
            try:
                await client(
                    EditAdminRequest(
                        channel=channel,
                        user_id=input_user,
                        admin_rights=admin_rights,
                        rank=getattr(args, "rank", None),
                    )
                )
            except (ChatAdminRequiredError, RightForbiddenError, UserAdminInvalidError) as exc:
                raise BadArgs(f"Telegram refused admin rights change: {exc}") from exc
            data = {
                "chat": chat,
                "user": user,
                "promoted": promote,
                "demoted": not promote,
                "admin_rights": rights,
                "rank": getattr(args, "rank", None),
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


async def _promote_runner(args) -> dict[str, Any]:
    return await _admin_rights_runner(args, command="promote", promote=True)


async def _demote_runner(args) -> dict[str, Any]:
    return await _admin_rights_runner(args, command="demote", promote=False)


async def _banned_runner(args, *, command: str, action: str) -> dict[str, Any]:
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
        if command in {"ban-from-chat", "kick"}:
            require_typed_confirm(args, expected=chat["chat_id"], slot="chat_id")
        user = _resolve_admin_user(con, args)
        payload = {
            "chat": chat,
            "user": user,
            "action": action,
            "telethon_method": "channels.EditBannedRequest",
        }
        if getattr(args, "until", None):
            payload["until"] = args.until
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
            telethon_method="channels.EditBannedRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            channel = await client.get_input_entity(chat["chat_id"])
            participant = await client.get_input_entity(user["user_id"])
            if action == "ban":
                await client(
                    EditBannedRequest(
                        channel=channel,
                        participant=participant,
                        banned_rights=_ban_rights(banned=True, until=_until_date(args.until)),
                    )
                )
            elif action == "unban":
                await client(
                    EditBannedRequest(
                        channel=channel,
                        participant=participant,
                        banned_rights=_ban_rights(banned=False),
                    )
                )
            else:
                await client(
                    EditBannedRequest(
                        channel=channel,
                        participant=participant,
                        banned_rights=_ban_rights(banned=True),
                    )
                )
                await client(
                    EditBannedRequest(
                        channel=channel,
                        participant=participant,
                        banned_rights=_ban_rights(banned=False),
                    )
                )
            data = {
                "chat": chat,
                "user": user,
                "banned": action == "ban",
                "unbanned": action == "unban",
                "kicked": action == "kick",
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


async def _ban_from_chat_runner(args) -> dict[str, Any]:
    return await _banned_runner(args, command="ban-from-chat", action="ban")


async def _unban_from_chat_runner(args) -> dict[str, Any]:
    return await _banned_runner(args, command="unban-from-chat", action="unban")


async def _kick_runner(args) -> dict[str, Any]:
    return await _banned_runner(args, command="kick", action="kick")


async def _set_permissions_runner(args) -> dict[str, Any]:
    command = "set-permissions"
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
        permissions = _permissions_from_args(args)
        if not permissions:
            raise BadArgs("set-permissions requires at least one permission flag")
        payload = {
            "chat": chat,
            "permissions": permissions,
            "telethon_method": "messages.EditChatDefaultBannedRightsRequest",
        }
        if args.review:
            return {"review": True, "payload": payload}
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
            telethon_method="messages.EditChatDefaultBannedRightsRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            peer = await client.get_input_entity(chat["chat_id"])
            await client(
                EditChatDefaultBannedRightsRequest(
                    peer=peer,
                    banned_rights=_default_banned_rights(permissions),
                )
            )
            data = {
                "chat": chat,
                "permissions": permissions,
                "permissions_set": True,
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


async def _chat_invite_link_runner(args) -> dict[str, Any]:
    command = "chat-invite-link"
    request_id = _request_id(args)
    require_write_allowed(args)
    if args.revoke and not args.link:
        raise BadArgs("--revoke requires --link")
    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        chat = _resolve_write_chat(con, args, args.chat)
        method = (
            "messages.EditExportedChatInviteRequest"
            if args.revoke
            else "messages.ExportChatInviteRequest"
        )
        payload = {
            "chat": chat,
            "revoke": bool(args.revoke),
            "link": args.link,
            "title": args.title,
            "expire": args.expire,
            "usage_limit": args.usage_limit,
            "request_needed": bool(args.request_needed),
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
            peer = await client.get_input_entity(chat["chat_id"])
            if args.revoke:
                result = await client(
                    EditExportedChatInviteRequest(peer=peer, link=args.link, revoked=True)
                )
            else:
                result = await client(
                    ExportChatInviteRequest(
                        peer=peer,
                        expire_date=_until_date(args.expire),
                        usage_limit=args.usage_limit,
                        request_needed=bool(args.request_needed) or None,
                        title=args.title,
                    )
                )
            data = {
                "chat": chat,
                "link": getattr(result, "link", args.link),
                "revoked": bool(args.revoke),
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


async def _chat_pinned_list_runner(args) -> dict[str, Any]:
    con = connect_readonly(DB_PATH)
    try:
        chat_id, chat_title = resolve_chat_db(con, args.chat)
    finally:
        con.close()
    client = make_client(SESSION_PATH)
    await client.start()
    try:
        peer = await client.get_input_entity(chat_id)
        result = await client(
            SearchRequest(
                peer=peer,
                q="",
                filter=InputMessagesFilterPinned(),
                min_date=None,
                max_date=None,
                offset_id=0,
                add_offset=0,
                limit=max(int(args.limit), 1),
                max_id=0,
                min_id=0,
                hash=0,
            )
        )
        messages = [_message_summary(msg) for msg in getattr(result, "messages", [])]
        return {"chat": {"chat_id": chat_id, "title": chat_title}, "messages": messages}
    finally:
        await client.disconnect()


async def _chat_members_runner(args) -> dict[str, Any]:
    con = connect_readonly(DB_PATH)
    try:
        chat_id, chat_title = resolve_chat_db(con, args.chat)
    finally:
        con.close()
    limit = max(int(args.limit), 1)
    offset = max(int(args.offset), 0)
    client = make_client(SESSION_PATH)
    await client.start()
    try:
        entity = await client.get_input_entity(chat_id)
        result = await client(
            GetParticipantsRequest(
                channel=entity,
                filter=ChannelParticipantsRecent(),
                offset=offset,
                limit=limit,
                hash=0,
            )
        )
        members = [_user_summary(user) for user in getattr(result, "users", [])]
        return {
            "chat": {"chat_id": chat_id, "title": chat_title},
            "paging": {"limit": limit, "offset": offset, "returned": len(members)},
            "members": members,
        }
    finally:
        await client.disconnect()


def run_chat_title(args) -> int:
    return _run_admin_write("chat-title", args, _chat_title_runner)


def run_chat_photo(args) -> int:
    return _run_admin_write("chat-photo", args, _chat_photo_runner)


def run_chat_description(args) -> int:
    return _run_admin_write("chat-description", args, _chat_description_runner)


def run_promote(args) -> int:
    return _run_admin_write("promote", args, _promote_runner)


def run_demote(args) -> int:
    return _run_admin_write("demote", args, _demote_runner)


def run_ban_from_chat(args) -> int:
    return _run_admin_write("ban-from-chat", args, _ban_from_chat_runner)


def run_kick(args) -> int:
    return _run_admin_write("kick", args, _kick_runner)


def run_unban_from_chat(args) -> int:
    return _run_admin_write("unban-from-chat", args, _unban_from_chat_runner)


def run_set_permissions(args) -> int:
    return _run_admin_write("set-permissions", args, _set_permissions_runner)


def run_chat_invite_link(args) -> int:
    return _run_admin_write("chat-invite-link", args, _chat_invite_link_runner)


def run_chat_pinned_list(args) -> int:
    return run_command(
        "chat-pinned-list",
        args,
        runner=lambda: _chat_pinned_list_runner(args),
        human_formatter=_write_human,
        audit_path=AUDIT_PATH,
    )


def run_chat_members(args) -> int:
    return run_command(
        "chat-members",
        args,
        runner=lambda: _chat_members_runner(args),
        human_formatter=_write_human,
        audit_path=AUDIT_PATH,
    )
