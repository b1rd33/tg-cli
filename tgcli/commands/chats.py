"""Chat-related subcommands. Phase 1 port: discover."""

from __future__ import annotations

import argparse
import json
from typing import Any

from telethon.errors.rpcerrorlist import (
    BroadcastForbiddenError,
    ChannelForumMissingError,
)
from telethon.tl.functions.messages import (
    CreateForumTopicRequest,
    EditForumTopicRequest,
    GetDialogFiltersRequest,
    GetForumTopicsRequest,
    UpdateDialogFilterRequest,
    UpdateDialogFiltersOrderRequest,
    UpdatePinnedForumTopicRequest,
)
from telethon.tl.types import (
    DialogFilter,
    DialogFilterChatlist,
    DialogFilterDefault,
    TextWithEntities,
)

from tgcli.client import make_client
from tgcli.commands._common import (
    AUDIT_PATH,
    DB_PATH,
    SESSION_PATH,
    add_output_flags,
    add_write_flags,
    decode_raw_json,
)
from tgcli.commands.messages import (
    _chat_kind,
    _check_write_rate_limit,
    _display_title,
    _dry_run_envelope,
    _request_id,
    _resolve_write_chat,
    _run_write_command,
    _upsert_chat,
    _write_result,
)
from tgcli.db import connect, connect_readonly
from tgcli.dispatch import run_command
from tgcli.idempotency import lookup as lookup_idempotency
from tgcli.idempotency import record as record_idempotency
from tgcli.resolve import NotFound, resolve_chat_db
from tgcli.safety import BadArgs, audit_pre, require_write_allowed


_FOLDER_BOOL_FIELDS = (
    "contacts",
    "non_contacts",
    "groups",
    "broadcasts",
    "bots",
    "exclude_muted",
    "exclude_read",
    "exclude_archived",
)


def _folder_flag_name(field: str) -> str:
    return field.replace("_", "-")


def _add_folder_create_bool_flags(parser: argparse.ArgumentParser) -> None:
    for field in _FOLDER_BOOL_FIELDS:
        parser.add_argument(
            f"--{_folder_flag_name(field)}",
            dest=field,
            action="store_true",
            default=False,
        )


def _add_folder_edit_bool_flags(parser: argparse.ArgumentParser) -> None:
    for field in _FOLDER_BOOL_FIELDS:
        flag = _folder_flag_name(field)
        group = parser.add_mutually_exclusive_group()
        group.add_argument(f"--{flag}", dest=field, action="store_true", default=None)
        group.add_argument(f"--no-{flag}", dest=field, action="store_false")


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

    topics = sub.add_parser("topics-list", help="List forum topics in a supergroup")
    topics.add_argument("chat", help="Forum supergroup selector resolved from the local DB")
    topics.add_argument("--limit", type=int, default=50, help="Number of topics (default 50)")
    topics.add_argument("--query", default=None, help="Search topic titles")
    add_output_flags(topics)
    topics.set_defaults(func=run_topics_list)

    create = sub.add_parser("topic-create", help="Create a forum topic")
    create.add_argument("chat", help="Forum supergroup selector resolved from the local DB")
    create.add_argument("title", help="Topic title")
    create.add_argument("--icon-emoji-id", type=int, default=None, help="Telegram custom emoji id")
    add_write_flags(create, destructive=False)
    add_output_flags(create)
    create.set_defaults(func=run_topic_create)

    edit = sub.add_parser("topic-edit", help="Edit a forum topic")
    edit.add_argument("chat", help="Forum supergroup selector resolved from the local DB")
    edit.add_argument("topic_id", type=int, help="Topic root message id")
    edit.add_argument("--title", default=None, help="New topic title")
    edit.add_argument("--icon-emoji-id", type=int, default=None, help="Telegram custom emoji id")
    state = edit.add_mutually_exclusive_group()
    state.add_argument("--closed", action="store_true", help="Close the topic")
    state.add_argument("--reopen", action="store_true", help="Reopen the topic")
    visibility = edit.add_mutually_exclusive_group()
    visibility.add_argument("--hidden", action="store_true", help="Hide the topic")
    visibility.add_argument("--unhidden", action="store_true", help="Unhide the topic")
    add_write_flags(edit, destructive=False)
    add_output_flags(edit)
    edit.set_defaults(func=run_topic_edit)

    pin = sub.add_parser("topic-pin", help="Pin a forum topic")
    pin.add_argument("chat", help="Forum supergroup selector resolved from the local DB")
    pin.add_argument("topic_id", type=int, help="Topic root message id")
    add_write_flags(pin, destructive=False)
    add_output_flags(pin)
    pin.set_defaults(func=run_topic_pin)

    unpin = sub.add_parser("topic-unpin", help="Unpin a forum topic")
    unpin.add_argument("chat", help="Forum supergroup selector resolved from the local DB")
    unpin.add_argument("topic_id", type=int, help="Topic root message id")
    add_write_flags(unpin, destructive=False)
    add_output_flags(unpin)
    unpin.set_defaults(func=run_topic_unpin)

    folders = sub.add_parser("folders-list", help="List Telegram dialog folders")
    folders.add_argument("--query", default=None, help="Filter folders by title substring")
    add_output_flags(folders)
    folders.set_defaults(func=run_folders_list)

    folder_show = sub.add_parser("folder-show", help="Show one Telegram dialog folder")
    folder_show.add_argument("folder_id", type=int, help="Folder id")
    add_output_flags(folder_show)
    folder_show.set_defaults(func=run_folder_show)

    folder_create = sub.add_parser("folder-create", help="Create a Telegram dialog folder")
    folder_create.add_argument("title", help="Folder title")
    folder_create.add_argument("--emoticon", default=None, help="Folder emoji")
    folder_create.add_argument(
        "--include-chat", type=int, action="append", default=[], help="Integer chat_id to include"
    )
    folder_create.add_argument(
        "--exclude-chat", type=int, action="append", default=[], help="Integer chat_id to exclude"
    )
    _add_folder_create_bool_flags(folder_create)
    add_write_flags(folder_create, destructive=False)
    add_output_flags(folder_create)
    folder_create.set_defaults(func=run_folder_create)

    folder_edit = sub.add_parser("folder-edit", help="Edit a Telegram dialog folder")
    folder_edit.add_argument("folder_id", type=int, help="Folder id")
    folder_edit.add_argument("--title", default=None, help="New folder title")
    folder_edit.add_argument("--emoticon", default=None, help="New folder emoji")
    folder_edit.add_argument(
        "--clear-include", action="store_true", help="Clear include peers before adding"
    )
    folder_edit.add_argument(
        "--clear-exclude", action="store_true", help="Clear exclude peers before adding"
    )
    folder_edit.add_argument(
        "--include-chat", type=int, action="append", default=[], help="Integer chat_id to include"
    )
    folder_edit.add_argument(
        "--exclude-chat", type=int, action="append", default=[], help="Integer chat_id to exclude"
    )
    _add_folder_edit_bool_flags(folder_edit)
    add_write_flags(folder_edit, destructive=False)
    add_output_flags(folder_edit)
    folder_edit.set_defaults(func=run_folder_edit)

    folder_delete = sub.add_parser("folder-delete", help="Delete a Telegram dialog folder")
    folder_delete.add_argument("folder_id", type=int, help="Folder id")
    add_write_flags(folder_delete, destructive=False)
    add_output_flags(folder_delete)
    folder_delete.set_defaults(func=run_folder_delete)

    folder_add = sub.add_parser("folder-add-chat", help="Add a chat to a Telegram dialog folder")
    folder_add.add_argument("folder_id", type=int, help="Folder id")
    folder_add.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    add_write_flags(folder_add, destructive=False)
    add_output_flags(folder_add)
    folder_add.set_defaults(func=run_folder_add_chat)

    folder_remove = sub.add_parser(
        "folder-remove-chat", help="Remove a chat from a Telegram dialog folder"
    )
    folder_remove.add_argument("folder_id", type=int, help="Folder id")
    folder_remove.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    add_write_flags(folder_remove, destructive=False)
    add_output_flags(folder_remove)
    folder_remove.set_defaults(func=run_folder_remove_chat)

    folders_reorder = sub.add_parser("folders-reorder", help="Reorder Telegram dialog folders")
    folders_reorder.add_argument(
        "folder_ids", type=int, nargs="+", help="Folder ids in desired order"
    )
    add_write_flags(folders_reorder, destructive=False)
    add_output_flags(folders_reorder)
    folders_reorder.set_defaults(func=run_folders_reorder)

    lc = sub.add_parser("leave-chat", help="Leave a group, supergroup, or channel")
    lc.add_argument("chat", help="Chat selector (id, @username, or fuzzy with --fuzzy)")
    add_write_flags(lc, destructive=True)
    add_output_flags(lc)
    lc.set_defaults(func=run_leave_chat)


def _topic_edit_mutations(args) -> dict[str, Any]:
    if getattr(args, "closed", False) and getattr(args, "reopen", False):
        raise BadArgs("--closed and --reopen are mutually exclusive")
    if getattr(args, "hidden", False) and getattr(args, "unhidden", False):
        raise BadArgs("--hidden and --unhidden are mutually exclusive")

    mutations: dict[str, Any] = {}
    if args.title is not None:
        if str(args.title).strip() == "":
            raise BadArgs("topic title cannot be empty")
        mutations["title"] = args.title
    if args.icon_emoji_id is not None:
        mutations["icon_emoji_id"] = int(args.icon_emoji_id)
    if getattr(args, "closed", False):
        mutations["closed"] = True
    if getattr(args, "reopen", False):
        mutations["closed"] = False
    if getattr(args, "hidden", False):
        mutations["hidden"] = True
    if getattr(args, "unhidden", False):
        mutations["hidden"] = False
    if not mutations:
        raise BadArgs("nothing to edit")
    return mutations


def _folder_title(value: str) -> TextWithEntities:
    text = str(value).strip()
    if text == "":
        raise BadArgs("folder title cannot be empty")
    return TextWithEntities(text=text, entities=[])


def _folder_title_text(value) -> str:
    if isinstance(value, TextWithEntities):
        return value.text
    text = getattr(value, "text", None)
    if text is not None:
        return str(text)
    return str(value or "")


def _folder_type(folder) -> str:
    if isinstance(folder, DialogFilterDefault):
        return "default"
    if isinstance(folder, DialogFilterChatlist):
        return "chatlist"
    if isinstance(folder, DialogFilter):
        return "filter"
    return type(folder).__name__


def _folder_id(folder) -> int:
    return int(getattr(folder, "id", 0) or 0)


def _peer_count(folder, attr: str) -> int:
    return len(getattr(folder, attr, None) or [])


def _folder_flags(folder) -> dict[str, bool]:
    return {field: bool(getattr(folder, field, False)) for field in _FOLDER_BOOL_FIELDS}


def _folder_summary(folder) -> dict[str, Any]:
    return {
        "folder_id": _folder_id(folder),
        "title": "All chats"
        if isinstance(folder, DialogFilterDefault)
        else _folder_title_text(getattr(folder, "title", "")),
        "emoticon": getattr(folder, "emoticon", None),
        "type": _folder_type(folder),
        "is_default": isinstance(folder, DialogFilterDefault) or _folder_id(folder) == 0,
        "is_chatlist": isinstance(folder, DialogFilterChatlist),
        "pinned_peer_count": _peer_count(folder, "pinned_peers"),
        "include_peer_count": _peer_count(folder, "include_peers"),
        "exclude_peer_count": _peer_count(folder, "exclude_peers"),
        "flags": _folder_flags(folder),
    }


def _folders_from_result(result) -> list[Any]:
    if isinstance(result, (list, tuple)):
        return list(result)
    for attr in ("filters", "dialog_filters", "folders"):
        value = getattr(result, attr, None)
        if value is not None:
            return list(value)
    return []


def _matching_folder(filters: list[Any], folder_id: int):
    for folder in filters:
        if _folder_id(folder) == int(folder_id):
            return folder
    raise NotFound(f"folder {folder_id} not found")


def _require_folder_write_key(args) -> None:
    if not getattr(args, "idempotency_key", None):
        raise BadArgs("--idempotency-key is required for folder write commands")


def _ensure_mutable_folder(folder, folder_id: int) -> DialogFilter:
    if not isinstance(folder, DialogFilter):
        raise BadArgs(f"folder {folder_id} is not a mutable custom folder")
    return folder


def _folder_edit_mutations(args) -> dict[str, Any]:
    mutations: dict[str, Any] = {}
    if getattr(args, "title", None) is not None:
        mutations["title"] = _folder_title(args.title)
    if getattr(args, "emoticon", None) is not None:
        mutations["emoticon"] = args.emoticon
    for field in _FOLDER_BOOL_FIELDS:
        value = getattr(args, field, None)
        if value is not None:
            mutations[field] = bool(value)
    if getattr(args, "clear_include", False):
        mutations["clear_include"] = True
    if getattr(args, "clear_exclude", False):
        mutations["clear_exclude"] = True
    if getattr(args, "include_chat", None):
        mutations["include_chat"] = list(args.include_chat)
    if getattr(args, "exclude_chat", None):
        mutations["exclude_chat"] = list(args.exclude_chat)
    if not mutations:
        raise BadArgs("nothing to edit")
    return mutations


def _folder_surface_unavailable(command: str) -> dict[str, Any]:
    raise BadArgs(f"{command} runner is defined by a later Phase 6.2 task")


async def _folder_write_surface_runner(args, *, command: str) -> dict[str, Any]:
    require_write_allowed(args)
    _require_folder_write_key(args)
    return _folder_surface_unavailable(command)


def run_folders_list(args) -> int:
    return run_command(
        "folders-list",
        args,
        runner=lambda: _folder_surface_unavailable("folders-list"),
        human_formatter=_write_human,
        audit_path=AUDIT_PATH,
    )


def run_folder_show(args) -> int:
    return run_command(
        "folder-show",
        args,
        runner=lambda: _folder_surface_unavailable("folder-show"),
        human_formatter=_write_human,
        audit_path=AUDIT_PATH,
    )


def run_folder_create(args) -> int:
    return _run_write_command(
        "folder-create",
        args,
        lambda args: _folder_write_surface_runner(args, command="folder-create"),
    )


def run_folder_edit(args) -> int:
    return _run_write_command(
        "folder-edit",
        args,
        lambda args: _folder_write_surface_runner(args, command="folder-edit"),
    )


def run_folder_delete(args) -> int:
    return _run_write_command(
        "folder-delete",
        args,
        lambda args: _folder_write_surface_runner(args, command="folder-delete"),
    )


def run_folder_add_chat(args) -> int:
    return _run_write_command(
        "folder-add-chat",
        args,
        lambda args: _folder_write_surface_runner(args, command="folder-add-chat"),
    )


def run_folder_remove_chat(args) -> int:
    return _run_write_command(
        "folder-remove-chat",
        args,
        lambda args: _folder_write_surface_runner(args, command="folder-remove-chat"),
    )


def run_folders_reorder(args) -> int:
    return _run_write_command(
        "folders-reorder",
        args,
        lambda args: _folder_write_surface_runner(args, command="folders-reorder"),
    )


def _peer_id_value(peer) -> int | None:
    for attr in ("peer_id", "user_id", "chat_id", "channel_id", "id"):
        value = getattr(peer, attr, None)
        if value is not None:
            return int(value)
    return None


def _peer_summary(con, peer) -> dict[str, Any]:
    peer_id = _peer_id_value(peer)
    row = None
    if peer_id is not None:
        row = con.execute(
            "SELECT title, type FROM tg_chats WHERE chat_id = ?",
            (peer_id,),
        ).fetchone()
    data = {
        "peer_id": peer_id,
        "peer_type": type(peer).__name__,
        "cached": row is not None,
        "title": row[0] if row else None,
        "type": row[1] if row else None,
    }
    return data


def _folder_detail(folder, con) -> dict[str, Any]:
    summary = _folder_summary(folder)
    summary["pinned_peers"] = [
        _peer_summary(con, peer) for peer in (getattr(folder, "pinned_peers", None) or [])
    ]
    summary["include_peers"] = [
        _peer_summary(con, peer) for peer in (getattr(folder, "include_peers", None) or [])
    ]
    summary["exclude_peers"] = [
        _peer_summary(con, peer) for peer in (getattr(folder, "exclude_peers", None) or [])
    ]
    return summary


async def _fetch_dialog_filters() -> list[Any]:
    client = make_client(SESSION_PATH)
    await client.start()
    try:
        result = await client(GetDialogFiltersRequest())
        return _folders_from_result(result)
    finally:
        await client.disconnect()


async def _folders_list_runner(args) -> dict[str, Any]:
    filters = await _fetch_dialog_filters()
    query = getattr(args, "query", None)
    summaries = [_folder_summary(folder) for folder in filters]
    if query:
        needle = str(query).casefold()
        summaries = [folder for folder in summaries if needle in str(folder["title"]).casefold()]
    return {"query": query, "folders": summaries}


async def _folder_show_runner(args) -> dict[str, Any]:
    filters = await _fetch_dialog_filters()
    folder = _matching_folder(filters, int(args.folder_id))
    con = connect_readonly(DB_PATH)
    try:
        detail = _folder_detail(folder, con)
    finally:
        con.close()
    return {"folder": detail}


def _folders_human(data: dict) -> None:
    for folder in data["folders"]:
        default = " default" if folder["is_default"] else ""
        print(f"{folder['folder_id']:>4}  {folder['title']}  {folder['type']}{default}")


def _folder_show_human(data: dict) -> None:
    print(json.dumps(data["folder"], ensure_ascii=False, indent=2, default=str))


def run_folders_list(args) -> int:
    return run_command(
        "folders-list",
        args,
        runner=lambda: _folders_list_runner(args),
        human_formatter=_folders_human,
        audit_path=AUDIT_PATH,
    )


def run_folder_show(args) -> int:
    return run_command(
        "folder-show",
        args,
        runner=lambda: _folder_show_runner(args),
        human_formatter=_folder_show_human,
        audit_path=AUDIT_PATH,
    )


async def _input_peers_for_chat_ids(client, chat_ids: list[int]) -> list[Any]:
    peers = []
    for chat_id in chat_ids:
        peers.append(await client.get_input_entity(int(chat_id)))
    return peers


async def _check_emoticon_persisted(
    client, folder_id: int, requested_emoticon: str | None
) -> list[str]:
    """Round-trip check: did Telegram store the emoticon we sent?

    Telegram's curated allowlist silently drops most emojis. After write, read
    the folder back and compare. Returns a warnings list (empty if all good or
    no emoticon was requested).
    """
    if not requested_emoticon:
        return []
    try:
        result = await client(GetDialogFiltersRequest())
        for folder in _folders_from_result(result):
            if isinstance(folder, DialogFilterDefault):
                continue
            if _folder_id(folder) != folder_id:
                continue
            stored = getattr(folder, "emoticon", None) or ""
            if stored != requested_emoticon:
                return [
                    f"Telegram silently dropped emoticon {requested_emoticon!r} "
                    f"(stored as {stored!r}); only certain emojis are allowed"
                ]
            return []
    except Exception:
        # Round-trip is best-effort — never let it fail the main operation.
        pass
    return []


def _next_folder_id(filters: list[Any]) -> int:
    # Telegram reserves filter id 0 ("All chats") and id 1 ("Archive").
    # User-created folders must start at 2.
    ids = [_folder_id(folder) for folder in filters if _folder_id(folder) > 0]
    if not ids:
        return 2
    return max(max(ids) + 1, 2)


def _dialog_filter(
    *,
    folder_id: int,
    title,
    pinned_peers: list[Any],
    include_peers: list[Any],
    exclude_peers: list[Any],
    emoticon: str | None,
    flags: dict[str, bool | None],
) -> DialogFilter:
    return DialogFilter(
        id=int(folder_id),
        title=title,
        pinned_peers=list(pinned_peers),
        include_peers=list(include_peers),
        exclude_peers=list(exclude_peers),
        contacts=flags.get("contacts"),
        non_contacts=flags.get("non_contacts"),
        groups=flags.get("groups"),
        broadcasts=flags.get("broadcasts"),
        bots=flags.get("bots"),
        exclude_muted=flags.get("exclude_muted"),
        exclude_read=flags.get("exclude_read"),
        exclude_archived=flags.get("exclude_archived"),
        emoticon=emoticon,
    )


def _folder_create_flags(args) -> dict[str, bool | None]:
    return {field: bool(getattr(args, field, False)) or None for field in _FOLDER_BOOL_FIELDS}


async def _folder_create_runner(args) -> dict[str, Any]:
    command = "folder-create"
    request_id = _request_id(args)
    require_write_allowed(args)
    _require_folder_write_key(args)
    title = _folder_title(args.title)
    include_chat_ids = [int(chat_id) for chat_id in (args.include_chat or [])]
    exclude_chat_ids = [int(chat_id) for chat_id in (args.exclude_chat or [])]

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        payload = {
            "title": title.text,
            "emoticon": args.emoticon,
            "include_chat_ids": include_chat_ids,
            "exclude_chat_ids": exclude_chat_ids,
            "flags": _folder_create_flags(args),
            "telethon_method": "UpdateDialogFilterRequest",
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)

        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=0,
            resolved_chat_title="dialog folders",
            payload_preview=payload,
            telethon_method="UpdateDialogFilterRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            filters = _folders_from_result(await client(GetDialogFiltersRequest()))
            folder_id = _next_folder_id(filters)
            include_peers = await _input_peers_for_chat_ids(client, include_chat_ids)
            exclude_peers = await _input_peers_for_chat_ids(client, exclude_chat_ids)
            folder = _dialog_filter(
                folder_id=folder_id,
                title=title,
                pinned_peers=[],
                include_peers=include_peers,
                exclude_peers=exclude_peers,
                emoticon=args.emoticon,
                flags=_folder_create_flags(args),
            )
            await client(UpdateDialogFilterRequest(id=folder_id, filter=folder))
            warnings = await _check_emoticon_persisted(client, folder_id, args.emoticon)
            data = {
                "folder_id": folder_id,
                "title": title.text,
                "emoticon": args.emoticon,
                "include_peer_count": len(include_peers),
                "exclude_peer_count": len(exclude_peers),
                "flags": _folder_flags(folder),
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


def run_folder_create(args) -> int:
    return _run_write_command("folder-create", args, _folder_create_runner)


def _dedupe_peers(peers: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for peer in peers:
        key = _peer_id_value(peer)
        if key is None:
            key = id(peer)
        if key in seen:
            continue
        seen.add(key)
        out.append(peer)
    return out


def _flags_from_existing(existing: DialogFilter, updates: dict[str, Any]) -> dict[str, bool | None]:
    flags: dict[str, bool | None] = {}
    for field in _FOLDER_BOOL_FIELDS:
        if field in updates:
            flags[field] = bool(updates[field])
        else:
            flags[field] = getattr(existing, field, None)
    return flags


async def _updated_dialog_filter(
    client, existing: DialogFilter, args, updates: dict[str, Any]
) -> DialogFilter:
    include_peers = (
        [] if updates.get("clear_include") else list(getattr(existing, "include_peers", None) or [])
    )
    exclude_peers = (
        [] if updates.get("clear_exclude") else list(getattr(existing, "exclude_peers", None) or [])
    )
    include_peers.extend(
        await _input_peers_for_chat_ids(
            client, [int(chat_id) for chat_id in (args.include_chat or [])]
        )
    )
    exclude_peers.extend(
        await _input_peers_for_chat_ids(
            client, [int(chat_id) for chat_id in (args.exclude_chat or [])]
        )
    )
    title = updates.get("title", getattr(existing, "title", _folder_title("Folder")))
    emoticon = updates.get("emoticon", getattr(existing, "emoticon", None))
    return _dialog_filter(
        folder_id=int(existing.id),
        title=title,
        pinned_peers=list(getattr(existing, "pinned_peers", None) or []),
        include_peers=_dedupe_peers(include_peers),
        exclude_peers=_dedupe_peers(exclude_peers),
        emoticon=emoticon,
        flags=_flags_from_existing(existing, updates),
    )


async def _folder_edit_runner(args) -> dict[str, Any]:
    command = "folder-edit"
    request_id = _request_id(args)
    require_write_allowed(args)
    _require_folder_write_key(args)
    updates = _folder_edit_mutations(args)
    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        payload = {
            "folder_id": int(args.folder_id),
            "title": getattr(args, "title", None),
            "emoticon": getattr(args, "emoticon", None),
            "clear_include": bool(getattr(args, "clear_include", False)),
            "clear_exclude": bool(getattr(args, "clear_exclude", False)),
            "include_chat_ids": list(getattr(args, "include_chat", []) or []),
            "exclude_chat_ids": list(getattr(args, "exclude_chat", []) or []),
            "boolean_updates": {
                field: getattr(args, field)
                for field in _FOLDER_BOOL_FIELDS
                if getattr(args, field, None) is not None
            },
            "telethon_method": "UpdateDialogFilterRequest",
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)
        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=0,
            resolved_chat_title=f"folder {int(args.folder_id)}",
            payload_preview=payload,
            telethon_method="UpdateDialogFilterRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            filters = _folders_from_result(await client(GetDialogFiltersRequest()))
            existing = _ensure_mutable_folder(
                _matching_folder(filters, int(args.folder_id)), int(args.folder_id)
            )
            folder = await _updated_dialog_filter(client, existing, args, updates)
            await client(UpdateDialogFilterRequest(id=int(args.folder_id), filter=folder))
            warnings = []
            if args.emoticon is not None:
                warnings = await _check_emoticon_persisted(
                    client, int(args.folder_id), args.emoticon
                )
            data = {
                "folder_id": int(args.folder_id),
                "title": _folder_title_text(folder.title),
                "edited": True,
                "include_peer_count": len(folder.include_peers),
                "exclude_peer_count": len(folder.exclude_peers),
                "flags": _folder_flags(folder),
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


async def _folder_delete_runner(args) -> dict[str, Any]:
    command = "folder-delete"
    request_id = _request_id(args)
    require_write_allowed(args)
    _require_folder_write_key(args)
    folder_id = int(args.folder_id)
    if folder_id == 0:
        raise BadArgs("folder id 0 is reserved and cannot be deleted")
    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        payload = {
            "folder_id": folder_id,
            "telethon_method": "UpdateDialogFilterRequest",
            "filter": None,
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)
        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=0,
            resolved_chat_title=f"folder {folder_id}",
            payload_preview=payload,
            telethon_method="UpdateDialogFilterRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            await client(UpdateDialogFilterRequest(id=folder_id, filter=None))
            data = {"folder_id": folder_id, "deleted": True, "idempotent_replay": False}
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


def run_folder_edit(args) -> int:
    return _run_write_command("folder-edit", args, _folder_edit_runner)


def run_folder_delete(args) -> int:
    return _run_write_command("folder-delete", args, _folder_delete_runner)


def _remove_peer_by_id(peers: list[Any], peer_id: int) -> tuple[list[Any], bool]:
    out = []
    removed = False
    for peer in peers:
        if _peer_id_value(peer) == int(peer_id):
            removed = True
            continue
        out.append(peer)
    return out, removed


async def _folder_membership_runner(args, *, command: str, add: bool) -> dict[str, Any]:
    request_id = _request_id(args)
    require_write_allowed(args)
    _require_folder_write_key(args)
    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        chat = _resolve_write_chat(con, args, args.chat)
        payload = {
            "folder_id": int(args.folder_id),
            "chat": chat,
            "action": "add" if add else "remove",
            "telethon_method": "UpdateDialogFilterRequest",
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
            telethon_method="UpdateDialogFilterRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            filters = _folders_from_result(await client(GetDialogFiltersRequest()))
            existing = _ensure_mutable_folder(
                _matching_folder(filters, int(args.folder_id)), int(args.folder_id)
            )
            target_peer = await client.get_input_entity(chat["chat_id"])
            include_peers = list(getattr(existing, "include_peers", None) or [])
            exclude_peers = list(getattr(existing, "exclude_peers", None) or [])
            warnings: list[str] = []
            if add:
                include_peers = _dedupe_peers([*include_peers, target_peer])
                changed = True
            else:
                include_peers, removed = _remove_peer_by_id(include_peers, chat["chat_id"])
                in_exclude = any(_peer_id_value(peer) == chat["chat_id"] for peer in exclude_peers)
                if in_exclude and not removed:
                    warnings.append("chat was present in exclude_peers, not include_peers")
                changed = removed
            folder = _dialog_filter(
                folder_id=int(existing.id),
                title=getattr(existing, "title", _folder_title("Folder")),
                pinned_peers=list(getattr(existing, "pinned_peers", None) or []),
                include_peers=_dedupe_peers(include_peers),
                exclude_peers=_dedupe_peers(exclude_peers),
                emoticon=getattr(existing, "emoticon", None),
                flags={field: getattr(existing, field, None) for field in _FOLDER_BOOL_FIELDS},
            )
            await client(UpdateDialogFilterRequest(id=int(args.folder_id), filter=folder))
            data = {
                "folder_id": int(args.folder_id),
                "chat": chat,
                "added": bool(add and changed),
                "removed": bool((not add) and changed),
                "include_peer_count": len(folder.include_peers),
                "exclude_peer_count": len(folder.exclude_peers),
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


async def _folder_add_chat_runner(args) -> dict[str, Any]:
    return await _folder_membership_runner(args, command="folder-add-chat", add=True)


async def _folder_remove_chat_runner(args) -> dict[str, Any]:
    return await _folder_membership_runner(args, command="folder-remove-chat", add=False)


async def _folders_reorder_runner(args) -> dict[str, Any]:
    command = "folders-reorder"
    request_id = _request_id(args)
    require_write_allowed(args)
    _require_folder_write_key(args)
    order = [int(folder_id) for folder_id in args.folder_ids]
    if not order:
        raise BadArgs("at least one folder id is required")
    if len(order) != len(set(order)):
        raise BadArgs("folder ids in reorder list must be unique")
    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        payload = {"order": order, "telethon_method": "UpdateDialogFiltersOrderRequest"}
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)
        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=0,
            resolved_chat_title="dialog folders",
            payload_preview=payload,
            telethon_method="UpdateDialogFiltersOrderRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            existing = _folders_from_result(await client(GetDialogFiltersRequest()))
            existing_ids = {
                _folder_id(f)
                for f in existing
                if not isinstance(f, DialogFilterDefault) and _folder_id(f) > 0
            }
            if set(order) != existing_ids:
                raise BadArgs(
                    f"supplied ids {sorted(order)} must exactly match existing "
                    f"folder ids {sorted(existing_ids)}"
                )
            await client(UpdateDialogFiltersOrderRequest(order=order))
            data = {"order": order, "reordered": True, "idempotent_replay": False}
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


def run_folder_add_chat(args) -> int:
    return _run_write_command("folder-add-chat", args, _folder_add_chat_runner)


def run_folder_remove_chat(args) -> int:
    return _run_write_command("folder-remove-chat", args, _folder_remove_chat_runner)


def run_folders_reorder(args) -> int:
    return _run_write_command("folders-reorder", args, _folders_reorder_runner)


# Concrete Telethon error classes for forum detection. Avoid string-matching:
# the server's error_message text can change without notice, but the class
# names are stable.
_NON_FORUM_ERRORS: tuple[type[BaseException], ...] = (
    ChannelForumMissingError,
    BroadcastForbiddenError,
)


def _is_non_forum_error(exc: BaseException) -> bool:
    return isinstance(exc, _NON_FORUM_ERRORS)


def _topic_summary(topic) -> dict[str, Any]:
    return {
        "topic_id": int(getattr(topic, "id", getattr(topic, "topic_id", 0))),
        "title": getattr(topic, "title", None),
        "icon_emoji_id": getattr(topic, "icon_emoji_id", None),
        "closed": bool(getattr(topic, "closed", False)),
        "hidden": bool(getattr(topic, "hidden", False)),
        "top_message_id": getattr(topic, "top_message", getattr(topic, "top_message_id", None)),
        "unread_count": int(getattr(topic, "unread_count", 0) or 0),
    }


async def _topics_list_runner(args) -> dict[str, Any]:
    con = connect_readonly(DB_PATH)
    try:
        chat_id, chat_title = resolve_chat_db(con, args.chat)
    finally:
        con.close()

    client = make_client(SESSION_PATH)
    await client.start()
    try:
        entity = await client.get_entity(chat_id)
        try:
            result = await client(
                GetForumTopicsRequest(
                    peer=entity,
                    offset_date=None,
                    offset_id=0,
                    offset_topic=0,
                    limit=max(int(args.limit), 1),
                    q=args.query,
                )
            )
        except Exception as exc:
            if _is_non_forum_error(exc):
                raise BadArgs("not a forum supergroup") from exc
            raise
    finally:
        await client.disconnect()

    return {
        "chat": {"chat_id": chat_id, "title": chat_title},
        "limit": max(int(args.limit), 1),
        "query": args.query,
        "topics": [_topic_summary(topic) for topic in getattr(result, "topics", [])],
    }


def run_topics_list(args) -> int:
    return run_command(
        "topics-list",
        args,
        runner=lambda: _topics_list_runner(args),
        human_formatter=_topics_human,
        audit_path=AUDIT_PATH,
    )


def _topics_human(data: dict) -> None:
    print(f"{data['chat']['title']} topics ({len(data['topics'])})")
    for topic in data["topics"]:
        state = []
        if topic["closed"]:
            state.append("closed")
        if topic["hidden"]:
            state.append("hidden")
        suffix = f" [{' '.join(state)}]" if state else ""
        print(f"  {topic['topic_id']:>8}  {topic['title']}{suffix}")


def _created_topic_from_update(result, fallback_title: str) -> tuple[int, str]:
    for update in getattr(result, "updates", []) or []:
        topic_id = getattr(update, "id", None)
        if topic_id is None:
            topic_id = getattr(update, "topic_id", None)
        if topic_id is not None:
            return int(topic_id), getattr(update, "title", fallback_title)
    raise BadArgs("topic create response did not include topic_id")


async def _topic_create_runner(args) -> dict[str, Any]:
    command = "topic-create"
    request_id = _request_id(args)
    require_write_allowed(args)
    if str(args.title).strip() == "":
        raise BadArgs("topic title cannot be empty")

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
            "title": args.title,
            "icon_emoji_id": args.icon_emoji_id,
            "telethon_method": "CreateForumTopicRequest",
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
            telethon_method="CreateForumTopicRequest",
            dry_run=False,
        )

        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            result = await client(
                CreateForumTopicRequest(
                    peer=entity,
                    title=args.title,
                    icon_emoji_id=args.icon_emoji_id,
                )
            )
            topic_id, title = _created_topic_from_update(result, args.title)
            data = {
                "topic_id": topic_id,
                "title": title,
                "chat": chat,
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


def run_topic_create(args) -> int:
    return _run_write_command("topic-create", args, _topic_create_runner)


async def _topic_edit_runner(args) -> dict[str, Any]:
    command = "topic-edit"
    request_id = _request_id(args)
    require_write_allowed(args)
    mutations = _topic_edit_mutations(args)

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
            "topic_id": int(args.topic_id),
            **mutations,
            "telethon_method": "EditForumTopicRequest",
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
            telethon_method="EditForumTopicRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            # Telegram returns TOPIC_CLOSE_SEPARATELY when an Edit request
            # combines title/icon changes with closed/hidden toggles. Split
            # automatically: first the renaming, then the state change.
            content_keys = {"title", "icon_emoji_id"}
            state_keys = {"closed", "hidden"}
            content_mutations = {k: v for k, v in mutations.items() if k in content_keys}
            state_mutations = {k: v for k, v in mutations.items() if k in state_keys}
            calls_made = 0
            if content_mutations and state_mutations:
                await client(
                    EditForumTopicRequest(
                        peer=entity,
                        topic_id=int(args.topic_id),
                        **content_mutations,
                    )
                )
                await client(
                    EditForumTopicRequest(
                        peer=entity,
                        topic_id=int(args.topic_id),
                        **state_mutations,
                    )
                )
                calls_made = 2
            else:
                await client(
                    EditForumTopicRequest(
                        peer=entity,
                        topic_id=int(args.topic_id),
                        **mutations,
                    )
                )
                calls_made = 1
            data = {
                "chat": chat,
                "topic_id": int(args.topic_id),
                "edited": True,
                "telethon_calls": calls_made,
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


async def _topic_pin_state_runner(args, *, command: str, pinned: bool) -> dict[str, Any]:
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
            "topic_id": int(args.topic_id),
            "pinned": pinned,
            "telethon_method": "UpdatePinnedForumTopicRequest",
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
            telethon_method="UpdatePinnedForumTopicRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            await client(
                UpdatePinnedForumTopicRequest(
                    peer=entity, topic_id=int(args.topic_id), pinned=pinned
                )
            )
            data = {
                "chat": chat,
                "topic_id": int(args.topic_id),
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


async def _topic_pin_runner(args) -> dict[str, Any]:
    return await _topic_pin_state_runner(args, command="topic-pin", pinned=True)


async def _topic_unpin_runner(args) -> dict[str, Any]:
    return await _topic_pin_state_runner(args, command="topic-unpin", pinned=False)


def run_topic_edit(args) -> int:
    return _run_write_command("topic-edit", args, _topic_edit_runner)


def run_topic_pin(args) -> int:
    return _run_write_command("topic-pin", args, _topic_pin_runner)


def run_topic_unpin(args) -> int:
    return _run_write_command("topic-unpin", args, _topic_unpin_runner)


async def _discover_runner(args) -> dict[str, Any]:
    import sys
    from tgcli.safety import require_writes_not_readonly

    require_writes_not_readonly(args)
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
        "discover",
        args,
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
        "unread",
        args,
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
        "chats-info",
        args,
        runner=lambda: _chat_info_runner(args),
        human_formatter=_chats_info_human,
        audit_path=AUDIT_PATH,
    )


# ---------- leave-chat (Phase 9) ----------


async def _leave_chat_runner(args) -> dict[str, Any]:
    from tgcli.safety import require_typed_confirm

    command = "leave-chat"
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

        # Refuse self-DM (Saved Messages).
        me = con.execute("SELECT user_id FROM tg_me WHERE key='self'").fetchone()
        if me and chat["chat_id"] == me[0]:
            raise BadArgs("cannot leave Saved Messages (self DM)")

        chat_type = con.execute(
            "SELECT type FROM tg_chats WHERE chat_id = ?", (chat["chat_id"],)
        ).fetchone()
        if chat_type and chat_type[0] in ("user", "bot"):
            raise BadArgs("cannot leave a 1-on-1 user chat (use delete-msg to clean history)")

        if args.dry_run:
            return _dry_run_envelope(
                command,
                request_id,
                {
                    "chat": chat,
                    "telethon_method": "client.delete_dialog",
                },
            )

        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=chat["chat_id"],
            resolved_chat_title=chat["title"],
            payload_preview={"chat": chat},
            telethon_method="client.delete_dialog",
            dry_run=False,
        )

        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_input_entity(chat["chat_id"])
            await client.delete_dialog(entity)
            con.execute("UPDATE tg_chats SET left = 1 WHERE chat_id = ?", (chat["chat_id"],))
            con.commit()
            data = {
                "chat": chat,
                "left": True,
                "telethon_method": "client.delete_dialog",
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


def run_leave_chat(args) -> int:
    return _run_write_command("leave-chat", args, _leave_chat_runner)
