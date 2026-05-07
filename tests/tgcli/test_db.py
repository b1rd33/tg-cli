"""Tests for tgcli.db — schema, migration, read-only mode."""

from __future__ import annotations

import sqlite3

import pytest

from tgcli.db import DatabaseMissing, connect, connect_readonly


def test_connect_creates_schema(tmp_path):
    db = tmp_path / "fresh.sqlite"
    con = connect(db)
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"tg_chats", "tg_messages", "tg_contacts"}.issubset(tables)
    cols = {row[1] for row in con.execute("PRAGMA table_info(tg_messages)")}
    assert "media_path" in cols  # included in CREATE, not added by migration


def test_connect_migrates_old_db_missing_media_path(tmp_path):
    """Mirror the pre-media_path schema; verify _migrate adds the column."""
    db = tmp_path / "legacy.sqlite"
    raw = sqlite3.connect(db)
    raw.execute(
        """
        CREATE TABLE tg_messages (
            chat_id INTEGER, message_id INTEGER, sender_id INTEGER, date TEXT,
            text TEXT, is_outgoing INTEGER, reply_to_msg_id INTEGER,
            has_media INTEGER, media_type TEXT, raw_json TEXT,
            PRIMARY KEY (chat_id, message_id)
        )
        """
    )
    raw.commit()
    raw.close()

    cols_before = {row[1] for row in sqlite3.connect(db).execute("PRAGMA table_info(tg_messages)")}
    assert "media_path" not in cols_before

    con = connect(db)
    cols_after = {row[1] for row in con.execute("PRAGMA table_info(tg_messages)")}
    assert "media_path" in cols_after  # added by _migrate


def test_connect_idempotent_on_already_migrated_db(tmp_path):
    db = tmp_path / "twice.sqlite"
    connect(db).close()
    connect(db).close()  # second call must not raise


def test_connect_readonly_rejects_missing_db(tmp_path):
    with pytest.raises(DatabaseMissing):
        connect_readonly(tmp_path / "nope.sqlite")


def test_connect_readonly_blocks_writes(tmp_path):
    db = tmp_path / "ro.sqlite"
    connect(db).close()  # create the file
    ro = connect_readonly(db)
    rows = ro.execute("SELECT COUNT(*) FROM tg_chats").fetchone()
    assert rows == (0,)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO tg_chats(chat_id) VALUES (1)")
