"""accounts-add | accounts-use | accounts-list | accounts-show | accounts-remove."""

from __future__ import annotations

import argparse

from tgcli.accounts import (
    add_account,
    current_account,
    list_accounts,
    remove_account,
    resolve_account_paths,
    use_account,
)
from tgcli.commands._common import AUDIT_PATH, add_output_flags
from tgcli.dispatch import run_command


def register(sub: argparse._SubParsersAction) -> None:
    add = sub.add_parser("accounts-add", help="Create a new account")
    add.add_argument("name")
    add_output_flags(add)
    add.set_defaults(func=run_add)

    use = sub.add_parser("accounts-use", help="Switch the current default account")
    use.add_argument("name")
    add_output_flags(use)
    use.set_defaults(func=run_use)

    ls = sub.add_parser("accounts-list", help="List all accounts")
    add_output_flags(ls)
    ls.set_defaults(func=run_list)

    show = sub.add_parser("accounts-show", help="Show the current account and its paths")
    add_output_flags(show)
    show.set_defaults(func=run_show)

    rm = sub.add_parser("accounts-remove", help="Delete an account and its data")
    rm.add_argument("name")
    add_output_flags(rm)
    rm.set_defaults(func=run_remove)


def run_add(args) -> int:
    return run_command(
        "accounts-add", args, runner=lambda: add_account(args.name), audit_path=AUDIT_PATH
    )


def run_use(args) -> int:
    return run_command(
        "accounts-use",
        args,
        runner=lambda: {"name": use_account(args.name), "current": True},
        audit_path=AUDIT_PATH,
    )


def run_list(args) -> int:
    def _runner():
        return {"accounts": list_accounts(), "current": current_account()}

    return run_command("accounts-list", args, runner=_runner, audit_path=AUDIT_PATH)


def run_show(args) -> int:
    def _runner():
        cur = current_account()
        paths = resolve_account_paths(cur)
        return {"name": cur, "paths": {k: str(v) for k, v in paths.items()}}

    return run_command("accounts-show", args, runner=_runner, audit_path=AUDIT_PATH)


def run_remove(args) -> int:
    return run_command(
        "accounts-remove", args, runner=lambda: remove_account(args.name), audit_path=AUDIT_PATH
    )
