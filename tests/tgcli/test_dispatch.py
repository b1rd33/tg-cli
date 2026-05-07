import argparse
import asyncio
import json
import re

import pytest

from tgcli.client import MissingCredentials, SessionLocked
from tgcli.db import DatabaseMissing
from tgcli.dispatch import run_command
from tgcli.output import ExitCode
from tgcli.resolve import Ambiguous, NotFound
from tgcli.safety import BadArgs, LocalRateLimited, NeedsConfirm, WriteDisallowed


def make_args(**kw):
    ns = argparse.Namespace()
    ns.json = kw.get("json", True)
    ns.human = kw.get("human", False)
    ns.allow_write = kw.get("allow_write", False)
    ns.confirm = kw.get("confirm", False)
    ns.dry_run = kw.get("dry_run", False)
    return ns


def _read_stdout(capsys) -> dict:
    out = capsys.readouterr().out.strip()
    return json.loads(out)


def test_run_command_success_emits_envelope(capsys, tmp_path):
    args = make_args()
    code = run_command(
        "stats", args,
        runner=lambda: {"chats": 4},
        audit_path=tmp_path / "audit.log",
    )
    assert code == 0
    env = _read_stdout(capsys)
    assert env["ok"] is True
    assert env["command"] == "stats"
    assert env["data"] == {"chats": 4}
    assert re.fullmatch(r"req-[0-9a-f]{8}", env["request_id"])


def test_run_command_writes_audit_entry(tmp_path, capsys):
    log = tmp_path / "audit.log"
    run_command("stats", make_args(), runner=lambda: {"chats": 1}, audit_path=log)
    line = log.read_text().splitlines()[0]
    entry = json.loads(line)
    assert entry["cmd"] == "stats"
    assert entry["result"] == "ok"
    assert entry["request_id"].startswith("req-")


def test_run_command_async_runner(capsys, tmp_path):
    async def runner():
        await asyncio.sleep(0)
        return {"value": 42}

    code = run_command("x", make_args(), runner=runner, audit_path=tmp_path / "audit.log")
    assert code == 0
    assert _read_stdout(capsys)["data"] == {"value": 42}


@pytest.mark.parametrize("exc, expected_code", [
    (BadArgs("missing pattern"), ExitCode.BAD_ARGS),
    (DatabaseMissing("no DB"), ExitCode.NOT_FOUND),
    (MissingCredentials("no creds"), ExitCode.NOT_AUTHED),
    (SessionLocked("locked"), ExitCode.GENERIC),
    (WriteDisallowed("nope"), ExitCode.WRITE_DISALLOWED),
    (NeedsConfirm("confirm"), ExitCode.NEEDS_CONFIRM),
    (LocalRateLimited("slow", 1.5), ExitCode.LOCAL_RATE_LIMIT),
])
def test_run_command_maps_known_exceptions(exc, expected_code, capsys, tmp_path):
    def boom():
        raise exc

    code = run_command("x", make_args(), runner=boom, audit_path=tmp_path / "audit.log")
    assert code == expected_code
    env = _read_stdout(capsys)
    assert env["ok"] is False
    assert env["error"]["code"] == expected_code.name


def test_run_command_maps_resolver_exceptions(capsys, tmp_path):
    def missing():
        raise NotFound("no chat title contains 'zzz'")

    code = run_command("show", make_args(), runner=missing, audit_path=tmp_path / "audit.log")
    env = _read_stdout(capsys)
    assert code == ExitCode.NOT_FOUND
    assert env["ok"] is False
    assert env["error"]["code"] == "NOT_FOUND"
    assert env["error"]["message"] == "no chat title contains 'zzz'"

    def ambiguous():
        raise Ambiguous("Al", [(1, "Alpha"), (2, "Alpine")])

    code = run_command("show", make_args(), runner=ambiguous, audit_path=tmp_path / "audit.log")
    env = _read_stdout(capsys)
    assert code == ExitCode.BAD_ARGS
    assert env["ok"] is False
    assert env["error"]["code"] == "BAD_ARGS"
    assert env["error"]["candidates"] == [[1, "Alpha"], [2, "Alpine"]]


def test_run_command_unknown_exception_becomes_generic(capsys, tmp_path):
    def boom():
        raise RuntimeError("kaboom")

    code = run_command("x", make_args(), runner=boom, audit_path=tmp_path / "audit.log")
    assert code == ExitCode.GENERIC
    env = _read_stdout(capsys)
    assert env["error"]["code"] == "GENERIC"
    assert "kaboom" in env["error"]["message"]


def test_run_command_failure_writes_audit_entry(tmp_path, capsys):
    log = tmp_path / "audit.log"

    def boom():
        raise DatabaseMissing("no DB")

    run_command("stats", make_args(), runner=lambda: boom(), audit_path=log)
    entry = json.loads(log.read_text().splitlines()[0])
    assert entry["result"] == "fail"
    assert entry["error_code"] == "NOT_FOUND"


def test_run_command_local_rate_limited_includes_retry_after(capsys, tmp_path):
    def boom():
        raise LocalRateLimited("slow down", 2.5)

    run_command("x", make_args(), runner=boom, audit_path=tmp_path / "audit.log")
    env = _read_stdout(capsys)
    assert env["error"]["retry_after_seconds"] == 2.5


def test_run_command_human_mode_uses_formatter(capsys, tmp_path):
    captured: list = []

    def fmt(data):
        captured.append(data)

    run_command(
        "stats",
        make_args(json=False, human=True),
        runner=lambda: {"chats": 7},
        human_formatter=fmt,
        audit_path=tmp_path / "audit.log",
    )
    assert captured == [{"chats": 7}]


def test_run_command_telethon_floodwait_maps_to_flood_wait(capsys, tmp_path):
    from telethon.errors import FloodWaitError

    def boom():
        raise FloodWaitError(request=None, capture=30)

    code = run_command("x", make_args(), runner=boom, audit_path=tmp_path / "audit.log")
    assert code == ExitCode.FLOOD_WAIT
    env = _read_stdout(capsys)
    assert env["error"]["code"] == "FLOOD_WAIT"
    assert env["error"]["retry_after_seconds"] == 30
