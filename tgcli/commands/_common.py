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
ENV_PATH: Path = ROOT / ".env"


def _resolve_account_paths() -> tuple[str, dict[str, Path]]:
    """Selection precedence: TG_ACCOUNT env → .current file → "default".

    For "default", attempt one-time migration from root-level files into
    accounts/default/ so single-account users upgrade transparently.
    """
    from tgcli.accounts import (
        DEFAULT_ACCOUNT,
        current_account,
        maybe_migrate_default_from_root,
        resolve_account_paths,
    )

    name = os.environ.get("TG_ACCOUNT") or current_account()
    if name == DEFAULT_ACCOUNT:
        maybe_migrate_default_from_root()
    paths = resolve_account_paths(name)
    return name, paths


_account_name, _account_paths = _resolve_account_paths()
ACCOUNT: str = _account_name
DB_PATH: Path = _override("TG_DB_PATH", _account_paths["DB_PATH"])
SESSION_PATH: Path = _override("TG_SESSION_PATH", _account_paths["SESSION_PATH"])
MEDIA_DIR: Path = _override("TG_MEDIA_DIR", _account_paths["MEDIA_DIR"])
AUDIT_PATH: Path = _override("TG_AUDIT_PATH", _account_paths["AUDIT_PATH"])


def add_output_flags(parser: argparse.ArgumentParser) -> None:
    """`--json` / `--human` for any subcommand. Auto-detects from TTY when neither is set."""
    g = parser.add_mutually_exclusive_group()
    g.add_argument(
        "--json",
        action="store_true",
        help="Force JSON envelope output (default when stdout is not a TTY)",
    )
    g.add_argument(
        "--human", action="store_true", help="Force human-readable output (default on a TTY)"
    )


def add_write_flags(parser: argparse.ArgumentParser, *, destructive: bool = False) -> None:
    """Write-side gates for Telegram-side mutations."""
    parser.add_argument(
        "--allow-write", action="store_true", help="Required for any Telegram write"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved payload and exit before calling Telegram",
    )
    parser.add_argument(
        "--idempotency-key",
        default=None,
        help="Return a cached result when this write key was already completed",
    )
    parser.add_argument(
        "--fuzzy",
        action="store_true",
        help="Allow title-based fuzzy chat resolution for this write",
    )
    if destructive:
        parser.add_argument(
            "--confirm",
            type=str,
            default=None,
            help=(
                "Required for destructive ops. Must equal the resolved "
                "chat_id / user_id / session_hash (post-resolver). "
                "Bare --confirm without a value is not accepted."
            ),
        )


def _chmod_owner_only(path) -> None:
    """Best-effort chmod to 0600 (file) / 0700 (dir). Silent on missing path or perm errors."""
    import stat as _stat

    p = Path(path)
    try:
        if not p.exists():
            return
        target = 0o700 if p.is_dir() else 0o600
        current = _stat.S_IMODE(os.stat(p).st_mode)
        if current != target:
            os.chmod(p, target)
    except (OSError, PermissionError):
        # Security-best-effort; never fail the operation.
        pass


def _safe_user_path(value: str) -> str:
    """Reject user-supplied paths that contain SQLite URI metacharacters.

    `?` and `#` would let an attacker inject URI parameters or fragment
    segments into a sqlite3 connection string. Reject either at any boundary
    that flows into a path or URI.
    """
    from tgcli.safety import BadArgs

    for ch in ("?", "#"):
        if ch in value:
            raise BadArgs(f"path {value!r} contains forbidden character {ch!r}")
    return value


def decode_raw_json(value: str | None):
    """Return parsed raw_json when possible, preserving invalid cached text."""
    if value is None or value == "":
        return None
    import json

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
