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
