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
