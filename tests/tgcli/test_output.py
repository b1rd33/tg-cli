import io
import json
import re
import pytest

from tgcli.output import (
    ExitCode,
    emit,
    fail,
    is_tty_stdout,
    new_request_id,
    success,
)


def test_success_envelope_shape():
    env = success("stats", {"chats": 5}, request_id="req-abc")
    assert env == {
        "ok": True,
        "command": "stats",
        "request_id": "req-abc",
        "data": {"chats": 5},
        "warnings": [],
    }
    json.dumps(env)  # must serialise


def test_success_envelope_with_warnings():
    env = success("stats", {}, request_id="r", warnings=["truncated"])
    assert env["warnings"] == ["truncated"]


def test_fail_envelope_shape():
    env = fail(
        "messages.send",
        ExitCode.FLOOD_WAIT,
        "wait 30s",
        request_id="req-xyz",
        retry_after_seconds=30,
    )
    assert env["ok"] is False
    assert env["command"] == "messages.send"
    assert env["request_id"] == "req-xyz"
    assert env["error"] == {
        "code": "FLOOD_WAIT",
        "message": "wait 30s",
        "retry_after_seconds": 30,
    }
    json.dumps(env)


def test_exit_code_values_are_stable():
    # These integer values are part of the public CLI contract.
    assert ExitCode.OK == 0
    assert ExitCode.GENERIC == 1
    assert ExitCode.BAD_ARGS == 2
    assert ExitCode.NOT_AUTHED == 3
    assert ExitCode.NOT_FOUND == 4
    assert ExitCode.FLOOD_WAIT == 5
    assert ExitCode.WRITE_DISALLOWED == 6
    assert ExitCode.NEEDS_CONFIRM == 7
    assert ExitCode.LOCAL_RATE_LIMIT == 8


def test_emit_json_success_returns_zero(capsys):
    code = emit(success("stats", {"x": 1}, request_id="r"), json_mode=True)
    assert code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["ok"] is True
    assert parsed["data"] == {"x": 1}


def test_emit_json_failure_returns_mapped_exit_code(capsys):
    env = fail("x", ExitCode.NOT_FOUND, "missing", request_id="r")
    code = emit(env, json_mode=True)
    assert code == ExitCode.NOT_FOUND
    err_line = capsys.readouterr().err
    # In JSON mode, the envelope still goes to stdout, not stderr.
    assert err_line == ""


def test_emit_human_uses_formatter(capsys):
    captured = []

    def fmt(data):
        captured.append(data)

    env = success("stats", {"chats": 9}, request_id="r")
    emit(env, json_mode=False, human_formatter=fmt)
    assert captured == [{"chats": 9}]


def test_emit_human_failure_writes_stderr(capsys):
    env = fail("stats", ExitCode.NOT_FOUND, "no DB", request_id="r")
    code = emit(env, json_mode=False)
    assert code == ExitCode.NOT_FOUND
    cap = capsys.readouterr()
    assert cap.out == ""
    assert "NOT_FOUND" in cap.err
    assert "no DB" in cap.err


def test_request_id_format():
    rid = new_request_id()
    # Format: req-<8 hex chars>
    assert re.fullmatch(r"req-[0-9a-f]{8}", rid)
    # Different each call
    assert new_request_id() != rid


def test_is_tty_stdout_returns_bool():
    # Just exercise the call — capsys redirects stdout so it is non-TTY here.
    assert is_tty_stdout() is False
