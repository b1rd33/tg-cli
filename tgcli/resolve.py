"""DB-only chat resolution helpers.

Resolution order:
1. Integer chat_id.
2. @username against cached tg_chats.username.
3. Case- and accent-insensitive title substring match.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from tgcli.text import strip_accents


class NotFound(Exception):
    """Raised when a chat selector has no match in the local DB."""


class Ambiguous(Exception):
    """Raised when fuzzy title resolution matches more than one chat."""

    def __init__(self, raw: str, candidates: Sequence[tuple[int, str]]):
        self.raw = raw
        self.candidates = list(candidates)
        super().__init__(f"{raw!r} is ambiguous: {len(self.candidates)} matches")


def _title_or_id(chat_id: int, title: str | None) -> str:
    return title or f"chat_{chat_id}"


def _try_int(value: str) -> int | None:
    """Return int if value parses as a single signed integer, else None."""
    try:
        return int(value)
    except ValueError:
        return None


def resolve_chat_db(con: sqlite3.Connection, raw: str) -> tuple[int, str]:
    """Resolve a user-supplied chat selector using only the local SQLite DB."""
    value = str(raw).strip()
    if not value:
        raise NotFound("empty chat selector")

    chat_id_int = _try_int(value)
    if chat_id_int is not None:
        row = con.execute(
            "SELECT chat_id, title FROM tg_chats WHERE chat_id = ?",
            (chat_id_int,),
        ).fetchone()
        if row:
            return int(row[0]), _title_or_id(int(row[0]), row[1])
        raise NotFound(f"chat_id {value} not in DB")

    if value.startswith("@"):
        username = value[1:]
        if not username:
            raise NotFound("empty username")
        row = con.execute(
            "SELECT chat_id, title FROM tg_chats WHERE LOWER(username) = LOWER(?)",
            (username,),
        ).fetchone()
        if row:
            return int(row[0]), _title_or_id(int(row[0]), row[1])
        raise NotFound(f"username {value} not in DB")

    needle = strip_accents(value)
    rows = con.execute(
        "SELECT chat_id, title FROM tg_chats ORDER BY chat_id"
    ).fetchall()
    matches = [
        (int(chat_id), _title_or_id(int(chat_id), title))
        for chat_id, title in rows
        if needle in strip_accents(title)
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise NotFound(f"no chat title contains {value!r}")
    raise Ambiguous(value, matches)
