import argparse
import json
import time
from pathlib import Path

import pytest

from tgcli.safety import (
    BadArgs,
    LocalRateLimited,
    NeedsConfirm,
    RateLimiter,
    WriteDisallowed,
    audit_pre,
    audit_write,
    require_confirm,
    require_explicit_or_fuzzy,
    require_write_allowed,
)


def test_bad_args_is_an_exception():
    with pytest.raises(BadArgs):
        raise BadArgs("missing --pattern or --chat-id")


def make_args(**kw):
    ns = argparse.Namespace()
    ns.allow_write = kw.get("allow_write", False)
    ns.confirm = kw.get("confirm", False)
    ns.dry_run = kw.get("dry_run", False)
    return ns


def test_write_gate_disallows_by_default(monkeypatch):
    monkeypatch.delenv("TG_ALLOW_WRITE", raising=False)
    with pytest.raises(WriteDisallowed):
        require_write_allowed(make_args())


def test_write_gate_passes_with_flag(monkeypatch):
    monkeypatch.delenv("TG_ALLOW_WRITE", raising=False)
    require_write_allowed(make_args(allow_write=True))


def test_write_gate_passes_with_env(monkeypatch):
    monkeypatch.setenv("TG_ALLOW_WRITE", "1")
    require_write_allowed(make_args())


def test_write_gate_ignores_other_env_values(monkeypatch):
    monkeypatch.setenv("TG_ALLOW_WRITE", "yes")
    with pytest.raises(WriteDisallowed):
        require_write_allowed(make_args())


def test_confirm_gate_requires_flag():
    with pytest.raises(NeedsConfirm):
        require_confirm(make_args(allow_write=True), action="messages.delete")


def test_confirm_gate_passes_with_flag():
    require_confirm(
        make_args(allow_write=True, confirm=True),
        action="messages.delete",
    )


def test_rate_limiter_allows_under_max():
    rl = RateLimiter(max_per_window=3, window_seconds=10)
    assert rl.check() == 0.0
    assert rl.check() == 0.0
    assert rl.check() == 0.0


def test_rate_limiter_blocks_when_full():
    rl = RateLimiter(max_per_window=2, window_seconds=10)
    rl.check()
    rl.check()
    wait = rl.check()
    assert wait > 0
    assert wait <= 10


def test_rate_limiter_recovers_after_window():
    rl = RateLimiter(max_per_window=1, window_seconds=0.05)
    assert rl.check() == 0.0
    assert rl.check() > 0
    time.sleep(0.06)
    assert rl.check() == 0.0


def test_audit_write_appends_jsonl(tmp_path: Path):
    log = tmp_path / "subdir" / "audit.log"
    audit_write(log, cmd="stats", request_id="r1", args_repr={"--json": True}, result="ok")
    audit_write(
        log, cmd="stats", request_id="r2", args_repr={}, result="fail", error_code="NOT_FOUND"
    )

    lines = log.read_text().splitlines()
    assert len(lines) == 2
    e1 = json.loads(lines[0])
    e2 = json.loads(lines[1])
    assert e1["cmd"] == "stats"
    assert e1["request_id"] == "r1"
    assert e1["result"] == "ok"
    assert "ts" in e1
    assert e2["error_code"] == "NOT_FOUND"


def test_require_explicit_or_fuzzy_allows_integer_selector():
    require_explicit_or_fuzzy(make_args(), "12345")


def test_require_explicit_or_fuzzy_allows_username_selector():
    require_explicit_or_fuzzy(make_args(), "@alpha")


def test_require_explicit_or_fuzzy_rejects_title_without_flag():
    with pytest.raises(BadArgs, match="pass --fuzzy"):
        require_explicit_or_fuzzy(make_args(), "Alpha Chat")


def test_require_explicit_or_fuzzy_allows_title_with_flag():
    args = make_args()
    args.fuzzy = True
    require_explicit_or_fuzzy(args, "Alpha Chat")


def test_audit_pre_appends_before_entry(tmp_path: Path):
    log = tmp_path / "audit.log"
    audit_pre(
        log,
        cmd="send",
        request_id="req-pre",
        resolved_chat_id=123,
        resolved_chat_title="Alpha",
        payload_preview={"text": "hello"},
        telethon_method="client.send_message",
        dry_run=False,
    )

    entry = json.loads(log.read_text().splitlines()[0])
    assert entry["phase"] == "before"
    assert entry["cmd"] == "send"
    assert entry["request_id"] == "req-pre"
    assert entry["resolved_chat_id"] == 123
    assert entry["payload_preview"] == {"text": "hello"}
    assert entry["telethon_method"] == "client.send_message"
    assert entry["dry_run"] is False
