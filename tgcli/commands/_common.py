"""Paths and shared argparse helpers for command modules.

All paths are env-overridable so tests (and multi-account agents) can isolate state.
The defaults preserve Phase 1 behaviour: <repo>/telegram.sqlite, <repo>/tg.session, etc.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def _override(env_var: str, default: Path) -> Path:
    val = os.environ.get(env_var)
    return Path(val) if val else default


ROOT: Path = Path(__file__).resolve().parent.parent.parent
DB_PATH: Path = _override("TG_DB_PATH", ROOT / "telegram.sqlite")
SESSION_PATH: Path = _override("TG_SESSION_PATH", ROOT / "tg.session")
ENV_PATH: Path = ROOT / ".env"
MEDIA_DIR: Path = _override("TG_MEDIA_DIR", ROOT / "media")
AUDIT_PATH: Path = _override("TG_AUDIT_PATH", ROOT / "audit.log")


def add_output_flags(parser: argparse.ArgumentParser) -> None:
    """`--json` / `--human` for any subcommand. Auto-detects from TTY when neither is set."""
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true",
                   help="Force JSON envelope output (default when stdout is not a TTY)")
    g.add_argument("--human", action="store_true",
                   help="Force human-readable output (default on a TTY)")


def add_write_flags(parser: argparse.ArgumentParser, *, destructive: bool = False) -> None:
    """Write-side gates. Phase 5+ commands attach these; Phase 2 ships them ready.

    `--allow-write` is required for any TG-side write.
    `--confirm` is additionally required for destructive ops (delete/leave/block).
    `--dry-run` prints what would happen and exits before calling Telegram.
    """
    parser.add_argument("--allow-write", action="store_true",
                        help="Required for any Telegram write (TG_ALLOW_WRITE=1 also works)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print intent and exit before calling Telegram")
    if destructive:
        parser.add_argument("--confirm", action="store_true",
                            help="Required in addition to --allow-write for destructive ops")


def decode_raw_json(value: str | None):
    """Return parsed raw_json when possible, preserving invalid cached text."""
    if value is None or value == "":
        return None
    import json

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
