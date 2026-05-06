"""Paths shared across command modules."""
from __future__ import annotations

from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent.parent
DB_PATH: Path = ROOT / "telegram.sqlite"
SESSION_PATH: Path = ROOT / "tg.session"
ENV_PATH: Path = ROOT / ".env"
MEDIA_DIR: Path = ROOT / "media"
