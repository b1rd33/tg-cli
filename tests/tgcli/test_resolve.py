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
            # Two diacritics (ø, ü) exercise strip_accents on multiple characters.
            (1, "user", "Bjørn Müller", "diacritic_test_user"),
            # Shares the 'Bj' prefix with #1 to drive the Ambiguous case below.
            (2, "user", "Bjarne Test Group", None),
            (3, "user", "Casefold Fixture", None),
        ],
    )
    return con


def test_resolve_by_int():
    con = setup_db()
    assert resolve_chat_db(con, "3") == (3, "Casefold Fixture")


def test_resolve_by_username():
    con = setup_db()
    assert resolve_chat_db(con, "@diacritic_test_user") == (1, "Bjørn Müller")


def test_resolve_by_fuzzy():
    con = setup_db()
    # 'müller' must match 'Bjørn Müller' through accent stripping AND case folding.
    assert resolve_chat_db(con, "müller") == (1, "Bjørn Müller")


def test_resolve_ambiguous_raises():
    con = setup_db()
    with pytest.raises(Ambiguous) as exc:
        resolve_chat_db(con, "Bj")
    assert exc.value.raw == "Bj"
    assert exc.value.candidates == [(1, "Bjørn Müller"), (2, "Bjarne Test Group")]


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
