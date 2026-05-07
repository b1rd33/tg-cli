"""Shared text-normalization helpers."""

from __future__ import annotations

import unicodedata


def strip_accents(value: str | None) -> str:
    """Return lowercase text with combining accent marks removed."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn").lower()
