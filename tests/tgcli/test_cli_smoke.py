"""Subprocess-level smoke tests for the tgcli CLI surface."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON = ROOT / ".venv" / "bin" / "python"


def test_module_help_exits_zero():
    r = subprocess.run(
        [str(PYTHON), "-m", "tgcli", "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "usage:" in r.stdout.lower()


import json as _json
import os as _os
import subprocess as _subprocess
import sys as _sys
from pathlib import Path as _Path


def _run_stats_subprocess(tmp_path: _Path, *, db: _Path | None) -> _subprocess.CompletedProcess:
    """Invoke `python -m tgcli stats --json` with TG_DB_PATH/TG_AUDIT_PATH redirected to tmp_path."""
    project = _Path(__file__).resolve().parents[2]
    py = project / ".venv" / "bin" / "python"
    env = {
        **_os.environ,
        # Bypass credential guard (stats is read-only and doesn't connect to TG):
        "TG_API_ID": "1",
        "TG_API_HASH": "x",
        "TG_AUDIT_PATH": str(tmp_path / "audit.log"),
    }
    if db is not None:
        env["TG_DB_PATH"] = str(db)
    else:
        # Force a non-existent DB path so we don't accidentally hit the dev DB.
        env["TG_DB_PATH"] = str(tmp_path / "does-not-exist.sqlite")
    return _subprocess.run(
        [str(py), "-m", "tgcli", "stats", "--json"],
        cwd=str(project), capture_output=True, text=True, env=env,
    )


def test_stats_json_envelope_with_seeded_db(tmp_path):
    """With a freshly seeded DB, `tg stats --json` MUST return exit 0 + success envelope."""
    from tgcli.db import connect
    seed_db = tmp_path / "seeded.sqlite"
    con = connect(seed_db)  # creates schema
    con.execute("INSERT INTO tg_chats(chat_id, type, title) VALUES (1, 'user', 'Alice')")
    con.commit()
    con.close()

    r = _run_stats_subprocess(tmp_path, db=seed_db)
    assert r.returncode == 0, f"stderr: {r.stderr}"
    payload = _json.loads(r.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "stats"
    assert payload["request_id"].startswith("req-")
    assert payload["data"]["chats"] == 1


def test_stats_json_envelope_no_db_returns_not_found(tmp_path):
    """Without a DB, the envelope MUST be a structured failure with exit code 4."""
    r = _run_stats_subprocess(tmp_path, db=None)
    assert r.returncode == 4
    payload = _json.loads(r.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "NOT_FOUND"


def test_min_msgs_flags_are_accepted(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "seeded.sqlite"
    con = connect(db)
    con.execute("INSERT INTO tg_chats(chat_id, type, title) VALUES (1, 'user', 'Busy')")
    con.execute("INSERT INTO tg_contacts(user_id, first_name, is_mutual) VALUES (1, 'Busy', 1)")
    con.execute(
        """
        INSERT INTO tg_messages(chat_id, message_id, date, text, is_outgoing, has_media)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (1, 1, "2026-05-01T10:00:00", "hello", 0, 0),
    )
    con.commit()
    con.close()

    env = {
        **_os.environ,
        "TG_API_ID": "1",
        "TG_API_HASH": "x",
        "TG_DB_PATH": str(db),
        "TG_AUDIT_PATH": str(tmp_path / "audit.log"),
    }

    stats_result = _subprocess.run(
        [str(PYTHON), "-m", "tgcli", "stats", "--min-msgs", "1", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert stats_result.returncode == 0, f"stderr: {stats_result.stderr}"
    assert _json.loads(stats_result.stdout)["ok"] is True

    contacts_result = _subprocess.run(
        [
            str(PYTHON),
            "-m",
            "tgcli",
            "contacts",
            "--chatted",
            "--min-msgs",
            "1",
            "--json",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert contacts_result.returncode == 0, f"stderr: {contacts_result.stderr}"
    assert _json.loads(contacts_result.stdout)["ok"] is True


def test_phase4_me_offline_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "seeded.sqlite"
    con = connect(db)
    con.execute(
        """
        INSERT INTO tg_me(
            key, user_id, username, phone, first_name, last_name,
            display_name, is_bot, cached_at, raw_json
        ) VALUES ('self', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            42,
            "alice",
            "15550001000",
            "Alice",
            "Example",
            "Alice Example",
            0,
            "2026-05-07T10:00:00+00:00",
            "{\"id\": 42}",
        ),
    )
    con.commit()
    con.close()

    env = {
        **_os.environ,
        "TG_API_ID": "1",
        "TG_API_HASH": "x",
        "TG_DB_PATH": str(db),
        "TG_AUDIT_PATH": str(tmp_path / "audit.log"),
    }
    result = _subprocess.run(
        [str(PYTHON), "-m", "tgcli", "me", "--offline", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    payload = _json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["source"] == "cache"
    assert payload["data"]["user_id"] == 42


def test_phase4_message_read_commands_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "seeded.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "user", "Alpha Chat", "alpha"),
    )
    con.execute(
        """
        INSERT INTO tg_messages(
            chat_id, message_id, sender_id, date, text,
            is_outgoing, reply_to_msg_id, has_media, media_type, media_path, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            123,
            1,
            11,
            "2026-05-01T10:00:00",
            "Hello from cache",
            0,
            None,
            0,
            None,
            None,
            "{\"id\": 1}",
        ),
    )
    con.commit()
    con.close()

    env = {
        **_os.environ,
        "TG_API_ID": "1",
        "TG_API_HASH": "x",
        "TG_DB_PATH": str(db),
        "TG_AUDIT_PATH": str(tmp_path / "audit.log"),
    }

    commands = [
        [str(PYTHON), "-m", "tgcli", "search", "@alpha", "Hello", "--json"],
        [str(PYTHON), "-m", "tgcli", "list-msgs", "@alpha", "--since", "2026-05-01", "--json"],
        [str(PYTHON), "-m", "tgcli", "get-msg", "@alpha", "1", "--json"],
    ]
    for command in commands:
        result = _subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, f"command: {command} stderr: {result.stderr}"
        payload = _json.loads(result.stdout)
        assert payload["ok"] is True


def test_phase4_chats_info_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "seeded.sqlite"
    con = connect(db)
    con.execute(
        """
        INSERT INTO tg_chats(
            chat_id, type, title, username, raw_json
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            900,
            "supergroup",
            "Alpha Group",
            "alpha_group",
            "{\"id\": 900, \"participants_count\": 123}",
        ),
    )
    con.commit()
    con.close()

    env = {
        **_os.environ,
        "TG_API_ID": "1",
        "TG_API_HASH": "x",
        "TG_DB_PATH": str(db),
        "TG_AUDIT_PATH": str(tmp_path / "audit.log"),
    }
    result = _subprocess.run(
        [str(PYTHON), "-m", "tgcli", "chats-info", "@alpha_group", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    payload = _json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["chat_id"] == 900
    assert payload["data"]["member_count"] == 123


def test_phase6_write_commands_have_help():
    commands = ["send", "edit-msg", "forward", "pin-msg", "unpin-msg", "react", "mark-read"]
    for command in commands:
        result = _subprocess.run(
            [str(PYTHON), "-m", "tgcli", command, "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"command: {command} stderr: {result.stderr}"
        assert "--allow-write" in result.stdout
        assert "--dry-run" in result.stdout
        assert "--idempotency-key" in result.stdout
        assert "--fuzzy" in result.stdout


def test_phase6_write_gate_smoke_blocks_without_allow_write(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "user", "Alpha Chat", "alpha"),
    )
    con.commit()
    con.close()

    env = {
        **_os.environ,
        "TG_API_ID": "1",
        "TG_API_HASH": "x",
        "TG_DB_PATH": str(db),
        "TG_AUDIT_PATH": str(tmp_path / "audit.log"),
    }
    result = _subprocess.run(
        [str(PYTHON), "-m", "tgcli", "send", "@alpha", "hello", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 6
    payload = _json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "WRITE_DISALLOWED"


def test_phase6_send_dry_run_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "user", "Alpha Chat", "alpha"),
    )
    con.commit()
    con.close()

    env = {
        **_os.environ,
        "TG_API_ID": "1",
        "TG_API_HASH": "x",
        "TG_DB_PATH": str(db),
        "TG_AUDIT_PATH": str(tmp_path / "audit.log"),
    }
    result = _subprocess.run(
        [
            str(PYTHON),
            "-m",
            "tgcli",
            "send",
            "@alpha",
            "hello",
            "--allow-write",
            "--dry-run",
            "--json",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    payload = _json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["payload"]["chat"]["chat_id"] == 123


def test_phase6_fuzzy_write_gate_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute("INSERT INTO tg_chats(chat_id, type, title) VALUES (?, ?, ?)", (123, "user", "Alpha Chat"))
    con.commit()
    con.close()

    env = {
        **_os.environ,
        "TG_API_ID": "1",
        "TG_API_HASH": "x",
        "TG_DB_PATH": str(db),
        "TG_AUDIT_PATH": str(tmp_path / "audit.log"),
    }
    result = _subprocess.run(
        [
            str(PYTHON),
            "-m",
            "tgcli",
            "send",
            "Alpha",
            "hello",
            "--allow-write",
            "--dry-run",
            "--json",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 2
    payload = _json.loads(result.stdout)
    assert payload["error"]["code"] == "BAD_ARGS"
    assert "pass --fuzzy" in payload["error"]["message"]


def test_phase6_other_write_dry_run_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "user", "Alpha Chat", "alpha"),
    )
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (456, "user", "Beta Chat", "beta"),
    )
    con.commit()
    con.close()

    env = {
        **_os.environ,
        "TG_API_ID": "1",
        "TG_API_HASH": "x",
        "TG_DB_PATH": str(db),
        "TG_AUDIT_PATH": str(tmp_path / "audit.log"),
    }
    commands = [
        [str(PYTHON), "-m", "tgcli", "edit-msg", "@alpha", "1", "updated", "--allow-write", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "forward", "@alpha", "1", "@beta", "--allow-write", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "pin-msg", "@alpha", "1", "--allow-write", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "unpin-msg", "@alpha", "1", "--allow-write", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "react", "@alpha", "1", "👍", "--allow-write", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "mark-read", "@alpha", "--allow-write", "--dry-run", "--json"],
    ]
    for command in commands:
        result = _subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, f"command: {command} stderr: {result.stderr}"
        payload = _json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["dry_run"] is True
