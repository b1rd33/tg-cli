"""Phase 8 — multi-account."""

from __future__ import annotations

import pytest

from tgcli.accounts import (
    AccountNotFound,
    account_dir,
    add_account,
    current_account,
    list_accounts,
    remove_account,
    use_account,
)


def test_add_and_list(tmp_path, monkeypatch):
    monkeypatch.setattr("tgcli.accounts.ROOT", tmp_path)
    add_account("work")
    add_account("personal")
    names = sorted(a["name"] for a in list_accounts())
    assert names == ["personal", "work"]


def test_use_and_current(tmp_path, monkeypatch):
    monkeypatch.setattr("tgcli.accounts.ROOT", tmp_path)
    add_account("alpha")
    use_account("alpha")
    assert current_account() == "alpha"


def test_use_unknown_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("tgcli.accounts.ROOT", tmp_path)
    with pytest.raises(AccountNotFound):
        use_account("ghost")


def test_account_dir_isolates_state(tmp_path, monkeypatch):
    monkeypatch.setattr("tgcli.accounts.ROOT", tmp_path)
    add_account("alpha")
    add_account("beta")
    a = account_dir("alpha")
    b = account_dir("beta")
    assert a != b
    assert a.exists() and b.exists()


def test_remove_account_drops_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("tgcli.accounts.ROOT", tmp_path)
    add_account("temp")
    remove_account("temp")
    assert "temp" not in [a["name"] for a in list_accounts()]
    assert not account_dir("temp", create=False).exists()


def test_invalid_name_rejected(tmp_path, monkeypatch):
    from tgcli.safety import BadArgs

    monkeypatch.setattr("tgcli.accounts.ROOT", tmp_path)
    with pytest.raises(BadArgs):
        add_account("../escape")
    with pytest.raises(BadArgs):
        add_account("with?mark")
