"""JSON/human output envelope, exit codes, and request-id generation.

Pure stdlib. No Telethon, no DB. Safe to import from anywhere.

Envelope shape (success):
    {"ok": True, "command": str, "request_id": str, "data": Any, "warnings": [str]}

Envelope shape (failure):
    {"ok": False, "command": str, "request_id": str,
     "error": {"code": str, "message": str, **extra}}
"""
from __future__ import annotations

import enum
import json
import sys
import uuid
from typing import Any, Callable


class ExitCode(enum.IntEnum):
    """Process exit codes. Integer values are part of the public CLI contract."""

    OK = 0
    GENERIC = 1
    BAD_ARGS = 2
    NOT_AUTHED = 3
    NOT_FOUND = 4
    FLOOD_WAIT = 5
    WRITE_DISALLOWED = 6
    NEEDS_CONFIRM = 7
    LOCAL_RATE_LIMIT = 8
    PREMIUM_REQUIRED = 9


def new_request_id() -> str:
    """Short request ID for log/envelope correlation."""
    return f"req-{uuid.uuid4().hex[:8]}"


def is_tty_stdout() -> bool:
    return sys.stdout.isatty()


def success(
    command: str,
    data: Any,
    *,
    request_id: str,
    warnings: list[str] | None = None,
) -> dict:
    return {
        "ok": True,
        "command": command,
        "request_id": request_id,
        "data": data,
        "warnings": list(warnings) if warnings else [],
    }


def fail(
    command: str,
    code: ExitCode,
    message: str,
    *,
    request_id: str,
    **extra: Any,
) -> dict:
    return {
        "ok": False,
        "command": command,
        "request_id": request_id,
        "error": {"code": code.name, "message": message, **extra},
    }


def emit(
    envelope: dict,
    *,
    json_mode: bool,
    human_formatter: Callable[[Any], None] | None = None,
) -> int:
    """Print envelope and return process exit code."""
    if json_mode:
        print(json.dumps(envelope, ensure_ascii=False, default=str))
    elif envelope["ok"]:
        if human_formatter is not None:
            human_formatter(envelope["data"])
        else:
            # Default human formatter: pretty-print the data dict.
            print(json.dumps(envelope["data"], ensure_ascii=False, indent=2, default=str))
    else:
        err = envelope["error"]
        print(f"ERROR [{err['code']}]: {err['message']}", file=sys.stderr)

    if envelope["ok"]:
        return ExitCode.OK
    return ExitCode[envelope["error"]["code"]]
