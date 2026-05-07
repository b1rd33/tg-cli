"""Phase 8 — owner-only file perms (0600/0700)."""
from __future__ import annotations

import os
import stat

from tgcli.commands._common import _chmod_owner_only


def test_chmod_owner_only_file(tmp_path):
    f = tmp_path / "secret.dat"
    f.write_text("x")
    _chmod_owner_only(f)
    mode = stat.S_IMODE(os.stat(f).st_mode)
    assert mode == 0o600


def test_chmod_owner_only_dir(tmp_path):
    d = tmp_path / "secret_dir"
    d.mkdir()
    _chmod_owner_only(d)
    mode = stat.S_IMODE(os.stat(d).st_mode)
    assert mode == 0o700


def test_chmod_owner_only_idempotent(tmp_path):
    f = tmp_path / "again.dat"
    f.write_text("x")
    _chmod_owner_only(f)
    _chmod_owner_only(f)
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600


def test_chmod_owner_only_missing_path_is_silent(tmp_path):
    _chmod_owner_only(tmp_path / "does-not-exist")
