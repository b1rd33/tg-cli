"""Multi-account directory layout and selector.

Each account lives at ROOT/accounts/<NAME>/ with isolated tg.session,
telegram.sqlite, audit.log, and media/. The current account selector is
ROOT/accounts/.current containing just the account name.

Account name validation: starts with alphanumeric, then alphanumeric +
underscore + hyphen, no path metacharacters (?, #, /, \\, .., empty).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from tgcli.safety import BadArgs

ROOT: Path = Path(__file__).resolve().parent.parent
ACCOUNTS_DIR_NAME = "accounts"
CURRENT_FILE = ".current"
DEFAULT_ACCOUNT = "default"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class AccountNotFound(Exception):
    """Raised when an account name doesn't correspond to an existing directory."""


def _validate_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise BadArgs(f"account name {name!r} invalid; must match [A-Za-z0-9][A-Za-z0-9_-]{{0,63}}")
    return name


def _accounts_root() -> Path:
    return ROOT / ACCOUNTS_DIR_NAME


def _current_path() -> Path:
    return _accounts_root() / CURRENT_FILE


def account_dir(name: str, *, create: bool = True) -> Path:
    _validate_name(name)
    d = _accounts_root() / name
    if create:
        d.mkdir(parents=True, exist_ok=True)
        (d / "media").mkdir(exist_ok=True)
    return d


def add_account(name: str) -> dict[str, Any]:
    name = _validate_name(name)
    d = account_dir(name, create=True)
    return {"name": name, "dir": str(d)}


def list_accounts() -> list[dict[str, Any]]:
    root = _accounts_root()
    if not root.exists():
        return []
    out = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and _NAME_RE.match(child.name):
            out.append({"name": child.name, "dir": str(child)})
    return out


def current_account() -> str:
    cp = _current_path()
    if cp.exists():
        try:
            name = cp.read_text().strip()
        except OSError:
            return DEFAULT_ACCOUNT
        if _NAME_RE.match(name) and account_dir(name, create=False).exists():
            return name
    return DEFAULT_ACCOUNT


def use_account(name: str) -> str:
    name = _validate_name(name)
    if not account_dir(name, create=False).exists():
        raise AccountNotFound(
            f"account {name!r} does not exist; run `tg accounts-add {name}` first"
        )
    cp = _current_path()
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(name)
    return name


def remove_account(name: str) -> dict[str, Any]:
    name = _validate_name(name)
    d = account_dir(name, create=False)
    if not d.exists():
        raise AccountNotFound(f"account {name!r} does not exist")
    if name == current_account():
        cp = _current_path()
        if cp.exists():
            cp.unlink()
    shutil.rmtree(d)
    return {"name": name, "removed": True}


def resolve_account_paths(name: str) -> dict[str, Path]:
    """Return the per-account paths used by _common to override globals."""
    d = account_dir(name, create=True)
    return {
        "DB_PATH": d / "telegram.sqlite",
        "SESSION_PATH": d / "tg.session",
        "AUDIT_PATH": d / "audit.log",
        "MEDIA_DIR": d / "media",
    }


def maybe_migrate_default_from_root() -> bool:
    """One-time migration: if root has telegram.sqlite/tg.session/audit.log/media but
    accounts/default/ doesn't, move them into accounts/default/. Returns True if migrated.
    """
    src_db = ROOT / "telegram.sqlite"
    src_session = ROOT / "tg.session"
    src_session_lock = ROOT / "tg.session.lock"
    src_audit = ROOT / "audit.log"
    src_media = ROOT / "media"
    default_dir = _accounts_root() / DEFAULT_ACCOUNT
    if default_dir.exists():
        return False
    # Telethon's session file is the bare 'tg.session' (a SQLite DB), not
    # 'tg.session.session'. Old releases varied; check both for safety.
    if not (src_db.exists() or src_session.exists() or src_audit.exists()):
        return False
    default_dir.mkdir(parents=True, exist_ok=True)
    (default_dir / "media").mkdir(exist_ok=True)
    moved = []
    for src, dest in [
        (src_db, default_dir / "telegram.sqlite"),
        (src_session, default_dir / "tg.session"),
        (src_session_lock, default_dir / "tg.session.lock"),
        (src_audit, default_dir / "audit.log"),
    ]:
        if src.exists():
            shutil.move(str(src), str(dest))
            moved.append(src.name)
    if src_media.exists() and src_media.is_dir():
        for child in src_media.iterdir():
            shutil.move(str(child), str(default_dir / "media" / child.name))
        try:
            src_media.rmdir()
        except OSError:
            pass
        moved.append("media/")
    return bool(moved)
