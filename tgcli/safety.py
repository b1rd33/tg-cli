"""Safety gates, rate limiter, audit log.

Stdlib only. No Telethon, no DB. Pure functions plus one tiny stateful class.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BadArgs(Exception):
    """Raised when caller passed contradictory or insufficient args (maps to BAD_ARGS=2)."""


class WriteDisallowed(Exception):
    """Raised when a write op is invoked without --allow-write / TG_ALLOW_WRITE=1."""


class NeedsConfirm(Exception):
    """Raised when a destructive op is invoked without --confirm."""


class LocalRateLimited(Exception):
    """Raised when an in-process rate limiter blocks an op (vs. server FloodWait)."""

    def __init__(self, message: str, retry_after_seconds: float):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def require_write_allowed(args) -> None:
    """Raise WriteDisallowed unless --allow-write or TG_ALLOW_WRITE=1."""
    if getattr(args, "allow_write", False):
        return
    if os.environ.get("TG_ALLOW_WRITE") == "1":
        return
    raise WriteDisallowed(
        "Write operations require --allow-write or TG_ALLOW_WRITE=1"
    )


def require_confirm(args, action: str) -> None:
    """Raise NeedsConfirm unless --confirm was passed."""
    if getattr(args, "confirm", False):
        return
    raise NeedsConfirm(
        f"Destructive op '{action}' requires --confirm"
    )


_EXPLICIT_INT_RE = re.compile(r"^[+-]?\d+$")


def _is_explicit_chat_selector(raw_selector: str) -> bool:
    value = str(raw_selector).strip()
    return bool(_EXPLICIT_INT_RE.fullmatch(value) or (value.startswith("@") and len(value) > 1))


def require_explicit_or_fuzzy(args, raw_selector: str) -> None:
    """Require --fuzzy before a write command may use title-based chat resolution."""
    if _is_explicit_chat_selector(raw_selector):
        return
    if getattr(args, "fuzzy", False):
        return
    raise BadArgs(
        f"{raw_selector!r} looks like a fuzzy title match; pass --fuzzy to allow it "
        "for write operations, or use the chat_id directly."
    )


class RateLimiter:
    """Sliding-window in-process rate limiter.

    `check()` returns 0.0 if the call is allowed (and records it),
    or seconds-to-wait if blocked (and does NOT record it).
    """

    def __init__(self, max_per_window: int, window_seconds: float):
        self.max = max_per_window
        self.window = window_seconds
        self.events: deque[float] = deque()

    def check(self) -> float:
        now = time.monotonic()
        while self.events and now - self.events[0] > self.window:
            self.events.popleft()
        if len(self.events) >= self.max:
            return self.window - (now - self.events[0])
        self.events.append(now)
        return 0.0


OUTBOUND_WRITE_LIMITER = RateLimiter(max_per_window=20, window_seconds=60.0)


def audit_pre(
    audit_path: Path,
    *,
    cmd: str,
    request_id: str,
    resolved_chat_id: int,
    resolved_chat_title: str,
    payload_preview: dict[str, Any],
    telethon_method: str,
    dry_run: bool,
) -> None:
    """Append the pre-call write audit entry."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "phase": "before",
        "cmd": cmd,
        "request_id": request_id,
        "resolved_chat_id": resolved_chat_id,
        "resolved_chat_title": resolved_chat_title,
        "telethon_method": telethon_method,
        "payload_preview": payload_preview,
        "dry_run": dry_run,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def audit_write(
    audit_path: Path,
    *,
    cmd: str,
    request_id: str,
    args_repr: dict[str, Any],
    result: str,
    **extra: Any,
) -> None:
    """Append one JSONL entry to the audit log. Creates parent dirs as needed."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cmd": cmd,
        "request_id": request_id,
        "args": args_repr,
        "result": result,
        **extra,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
