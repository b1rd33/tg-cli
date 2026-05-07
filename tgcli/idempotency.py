"""Idempotency helpers for Telegram-side write commands."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from tgcli.safety import BadArgs


def lookup(con: sqlite3.Connection, key: str | None, command: str) -> dict[str, Any] | None:
    """Return a cached result envelope for key+command, if one exists."""
    if not key:
        return None
    row = con.execute(
        """
        SELECT command, result_json
        FROM tg_idempotency
        WHERE key = ?
        """,
        (key,),
    ).fetchone()
    if row is None:
        return None
    recorded_command, result_json = row
    if recorded_command != command:
        raise BadArgs(f"Idempotency key {key!r} was already used for command {recorded_command!r}")
    return json.loads(result_json)


def record(
    con: sqlite3.Connection,
    key: str | None,
    command: str,
    request_id: str,
    result_envelope: dict[str, Any],
) -> None:
    """Persist a successful write result envelope for later replay."""
    if not key:
        return
    con.execute(
        """
        INSERT INTO tg_idempotency(key, command, request_id, result_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            key,
            command,
            request_id,
            json.dumps(result_envelope, ensure_ascii=False, default=str),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    con.commit()
