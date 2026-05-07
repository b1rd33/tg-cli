"""Phase 8 — path injection guard."""

from __future__ import annotations

import pytest

from tgcli.commands._common import _safe_user_path
from tgcli.safety import BadArgs


def test_safe_user_path_passes_normal_paths(tmp_path):
    p = _safe_user_path(str(tmp_path / "subdir"))
    assert "subdir" in p


def test_safe_user_path_rejects_question_mark():
    with pytest.raises(BadArgs, match="forbidden character"):
        _safe_user_path("/tmp/foo?mode=ro")


def test_safe_user_path_rejects_hash():
    with pytest.raises(BadArgs, match="forbidden character"):
        _safe_user_path("/tmp/foo#fragment")


def test_safe_user_path_allows_unicode_and_spaces(tmp_path):
    p = _safe_user_path(str(tmp_path / "Hellö World"))
    assert "Hellö World" in p
