"""SQLite connection + schema.

Two entrypoints:
- `connect()` opens read-write, applies schema, runs idempotent migrations.
  Use from any command that writes (sync-contacts, backfill, listen, etc).
- `connect_readonly()` opens read-only via SQLite URI; never mutates the file.
  Use from pure read commands (stats, show, contacts list).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

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

CREATE TABLE IF NOT EXISTS tg_me (
    key          TEXT PRIMARY KEY CHECK (key = 'self'),
    user_id      INTEGER,
    username     TEXT,
    phone        TEXT,
    first_name   TEXT,
    last_name    TEXT,
    display_name TEXT,
    is_bot       INTEGER,
    cached_at    TEXT,
    raw_json     TEXT
);
"""


class DatabaseMissing(FileNotFoundError):
    """Raised by connect_readonly() when the DB file doesn't exist yet."""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the DB read-write, apply schema, run migrations."""
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the DB read-only — never writes to disk, never migrates."""
    if not db_path.exists():
        raise DatabaseMissing(db_path)
    uri = f"file:{db_path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _migrate(con: sqlite3.Connection) -> None:
    """Idempotent schema upgrades. Cheaper than try/except — only writes when needed."""
    cols = {row[1] for row in con.execute("PRAGMA table_info(tg_messages)").fetchall()}
    if "media_path" not in cols:
        con.execute("ALTER TABLE tg_messages ADD COLUMN media_path TEXT")
