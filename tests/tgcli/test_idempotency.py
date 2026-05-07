import pytest

from tgcli.db import connect
from tgcli.idempotency import lookup, record
from tgcli.safety import BadArgs


def test_lookup_returns_none_without_key(tmp_path):
    con = connect(tmp_path / "telegram.sqlite")
    try:
        assert lookup(con, None, "send") is None
        assert lookup(con, "", "send") is None
    finally:
        con.close()


def test_record_and_lookup_round_trip_envelope(tmp_path):
    con = connect(tmp_path / "telegram.sqlite")
    try:
        envelope = {
            "ok": True,
            "command": "send",
            "request_id": "req-1",
            "data": {"message_id": 77},
            "warnings": [],
        }
        record(con, "key-1", "send", "req-1", envelope)
        assert lookup(con, "key-1", "send") == envelope
    finally:
        con.close()


def test_lookup_rejects_key_reused_for_different_command(tmp_path):
    con = connect(tmp_path / "telegram.sqlite")
    try:
        record(
            con,
            "key-1",
            "send",
            "req-1",
            {
                "ok": True,
                "command": "send",
                "request_id": "req-1",
                "data": {"message_id": 77},
                "warnings": [],
            },
        )
        with pytest.raises(BadArgs, match="already used"):
            lookup(con, "key-1", "edit-msg")
    finally:
        con.close()
