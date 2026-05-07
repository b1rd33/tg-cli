"""Media upload write commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Literal

from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo

from tgcli.client import make_client
from tgcli.commands._common import (
    AUDIT_PATH,
    DB_PATH,
    SESSION_PATH,
    _safe_user_path,
    add_output_flags,
    add_write_flags,
)
from tgcli.commands.messages import (
    _check_write_rate_limit,
    _dry_run_envelope,
    _request_id,
    _resolve_write_chat,
    _run_write_command,
    _write_result,
)
from tgcli.db import connect
from tgcli.idempotency import lookup as lookup_idempotency
from tgcli.idempotency import record as record_idempotency
from tgcli.safety import BadArgs, audit_pre, require_write_allowed

MediaKind = Literal["photo", "voice", "video", "document"]


def register(sub: argparse._SubParsersAction) -> None:
    photo = sub.add_parser("upload-photo", help="Upload an image")
    _add_media_args(photo, allow_ttl=True)
    photo.set_defaults(func=run_upload_photo)

    voice = sub.add_parser("upload-voice", help="Upload an OGG/Opus voice note")
    _add_media_args(voice, allow_ttl=False)
    voice.set_defaults(func=run_upload_voice)

    video = sub.add_parser("upload-video", help="Upload a video")
    _add_media_args(video, allow_ttl=True)
    video.set_defaults(func=run_upload_video)

    document = sub.add_parser("upload-document", help="Upload any file as a document")
    _add_media_args(document, allow_ttl=False)
    document.set_defaults(func=run_upload_document)


def _add_media_args(parser: argparse.ArgumentParser, *, allow_ttl: bool) -> None:
    parser.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    parser.add_argument("file", help="Local file path to upload")
    parser.add_argument("--caption", default=None, help="Optional media caption")
    parser.add_argument(
        "--reply-to", type=int, default=None, help="Reply to this Telegram message id"
    )
    parser.add_argument("--silent", action="store_true", help="Send without notification")
    if allow_ttl:
        parser.add_argument("--ttl", type=int, default=None, help="Self-destruct timer in seconds")
    parser.add_argument(
        "--max-size-mb",
        type=int,
        default=100,
        help="Refuse files larger than this many MB (default 100)",
    )
    add_write_flags(parser, destructive=False)
    add_output_flags(parser)


def _safe_upload_path(raw: str, *, max_size_mb: int) -> Path:
    _safe_user_path(raw)
    path = Path(raw).expanduser()
    if any(part == ".." for part in path.parts):
        raise BadArgs(f"path traversal is not allowed in upload path {raw!r}")
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise BadArgs(f"invalid upload path {raw!r}: {exc}") from exc
    if not resolved.exists():
        raise BadArgs(f"upload file {str(resolved)!r} does not exist")
    if not resolved.is_file():
        raise BadArgs(f"upload path {str(resolved)!r} is not a regular file")
    if max_size_mb < 0:
        raise BadArgs("--max-size-mb must be >= 0")
    size = resolved.stat().st_size
    max_bytes = max_size_mb * 1024 * 1024
    if size > max_bytes:
        raise BadArgs(
            f"upload file {str(resolved)!r} is {size} bytes; exceeds --max-size-mb {max_size_mb}"
        )
    return resolved


def _read_prefix(path: Path, length: int = 512) -> bytes:
    with path.open("rb") as f:
        return f.read(length)


def _detect_photo_mime(path: Path) -> str:
    head = _read_prefix(path, 32)
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image/gif"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    raise BadArgs("unsupported photo MIME magic bytes; expected JPEG, PNG, WebP, or GIF")


def _detect_voice_mime(path: Path) -> str:
    head = _read_prefix(path, 4096)
    if not head.startswith(b"OggS"):
        raise BadArgs("unsupported voice MIME magic bytes; expected OGG container")
    if b"OpusHead" not in head:
        raise BadArgs("unsupported voice codec; expected OGG/Opus")
    return "audio/ogg; codecs=opus"


def _detect_video_mime(path: Path) -> tuple[str, list[str]]:
    head = _read_prefix(path, 512)
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm", []
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand == b"qt  ":
            return "video/quicktime", ["MOV upload accepted; MP4 is usually more Telegram-friendly"]
        return "video/mp4", []
    raise BadArgs("unsupported video MIME magic bytes; expected MP4, WebM, or MOV")


def _validate_mime(kind: MediaKind, path: Path) -> tuple[str | None, list[str]]:
    if kind == "photo":
        return _detect_photo_mime(path), []
    if kind == "voice":
        return _detect_voice_mime(path), []
    if kind == "video":
        return _detect_video_mime(path)
    return None, []


def _media_attributes(kind: MediaKind) -> list[Any] | None:
    if kind == "voice":
        return [DocumentAttributeAudio(duration=0, voice=True)]
    if kind == "video":
        return [DocumentAttributeVideo(duration=0, w=0, h=0, supports_streaming=True)]
    return None


def _send_file_kwargs(args, kind: MediaKind, mime_type: str | None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "caption": args.caption,
        "reply_to": args.reply_to,
        "silent": bool(args.silent),
    }
    if kind in {"photo", "video"} and getattr(args, "ttl", None) is not None:
        kwargs["ttl"] = args.ttl
    attrs = _media_attributes(kind)
    if attrs is not None:
        kwargs["attributes"] = attrs
    if kind == "document":
        kwargs["force_document"] = True
    if mime_type is not None:
        kwargs["mime_type"] = mime_type
    return kwargs


def _payload(
    *,
    kind: MediaKind,
    chat: dict[str, Any],
    path: Path,
    args,
    mime_type: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    payload = {
        "chat": chat,
        "media_type": kind,
        "file_path": str(path),
        "file_size": path.stat().st_size,
        "mime_type": mime_type,
        "caption": args.caption,
        "reply_to": args.reply_to,
        "silent": bool(args.silent),
        "telethon_method": "client.send_file",
        "warnings": warnings,
    }
    if kind in {"photo", "video"}:
        payload["ttl"] = getattr(args, "ttl", None)
    return payload


async def _upload_runner(args, *, command: str, kind: MediaKind) -> dict[str, Any]:
    request_id = _request_id(args)
    require_write_allowed(args)
    path = _safe_upload_path(args.file, max_size_mb=args.max_size_mb)
    mime_type, warnings = _validate_mime(kind, path)

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data

        chat = _resolve_write_chat(con, args, args.chat)
        payload = _payload(
            kind=kind,
            chat=chat,
            path=path,
            args=args,
            mime_type=mime_type,
            warnings=warnings,
        )
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
            telethon_method="client.send_file",
            dry_run=False,
        )

        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_entity(chat["chat_id"])
            sent = await client.send_file(
                entity,
                str(path),
                **_send_file_kwargs(args, kind, mime_type),
            )
            data = {
                "chat": chat,
                "message_id": int(sent.id),
                "media_type": kind,
                "file_path": str(path),
                "file_size": path.stat().st_size,
                "mime_type": mime_type,
                "caption": args.caption,
                "reply_to": args.reply_to,
                "silent": bool(args.silent),
                "warnings": warnings,
                "idempotent_replay": False,
            }
            if kind in {"photo", "video"}:
                data["ttl"] = getattr(args, "ttl", None)
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


async def _upload_photo_runner(args) -> dict[str, Any]:
    return await _upload_runner(args, command="upload-photo", kind="photo")


async def _upload_voice_runner(args) -> dict[str, Any]:
    return await _upload_runner(args, command="upload-voice", kind="voice")


async def _upload_video_runner(args) -> dict[str, Any]:
    return await _upload_runner(args, command="upload-video", kind="video")


async def _upload_document_runner(args) -> dict[str, Any]:
    return await _upload_runner(args, command="upload-document", kind="document")


def _write_human(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def run_upload_photo(args) -> int:
    return _run_write_command("upload-photo", args, _upload_photo_runner)


def run_upload_voice(args) -> int:
    return _run_write_command("upload-voice", args, _upload_voice_runner)


def run_upload_video(args) -> int:
    return _run_write_command("upload-video", args, _upload_video_runner)


def run_upload_document(args) -> int:
    return _run_write_command("upload-document", args, _upload_document_runner)
