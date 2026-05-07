import sqlite3

import pytest

from tgcli.resolve import Ambiguous, NotFound, resolve_chat_db


def setup_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute(
        """
        CREATE TABLE tg_chats (
            chat_id INTEGER PRIMARY KEY,
            type TEXT,
            title TEXT,
            username TEXT,
            phone TEXT,
            first_name TEXT,
            last_name TEXT,
            is_bot INTEGER,
            last_seen_at TEXT,
            raw_json TEXT
        )
        """
    )
    con.executemany(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        [
            (1, "user", "Hamïd Ijadi", "HRALEyn"),  # diacritic exercises strip_accents
            (2, "user", "Hamburger Verein", None),
            (3, "user", "Joel", None),
        ],
    )
    return con


def test_resolve_by_int():
    con = setup_db()
    assert resolve_chat_db(con, "3") == (3, "Joel")


def test_resolve_by_username():
    con = setup_db()
    assert resolve_chat_db(con, "@HRALEyn") == (1, "Hamïd Ijadi")


def test_resolve_by_fuzzy():
    con = setup_db()
    # 'ijadi' must match 'Hamïd Ijadi' through accent stripping AND case folding.
    assert resolve_chat_db(con, "ijadi") == (1, "Hamïd Ijadi")


def test_resolve_ambiguous_raises():
    con = setup_db()
    with pytest.raises(Ambiguous) as exc:
        resolve_chat_db(con, "Ham")
    assert exc.value.raw == "Ham"
    assert exc.value.candidates == [(1, "Hamïd Ijadi"), (2, "Hamburger Verein")]


def test_resolve_not_found_raises():
    con = setup_db()
    with pytest.raises(NotFound):
        resolve_chat_db(con, "nonexistent")


def test_resolve_malformed_int_falls_through_to_fuzzy():
    """'--123' must not be mistaken for an integer chat_id (would crash with ValueError)."""
    con = setup_db()
    # No title contains '--123', so we expect NotFound from the fuzzy path,
    # NOT a leaked ValueError.
    with pytest.raises(NotFound):
        resolve_chat_db(con, "--123")
