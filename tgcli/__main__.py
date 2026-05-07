"""Argparse dispatcher for the `tg` CLI."""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sys
from importlib import import_module


def _pre_parse_account_flag(argv: list[str] | None) -> None:
    """Set TG_ACCOUNT before any tgcli module is imported.

    Path resolution in tgcli.commands._common runs at import time and reads
    TG_ACCOUNT, so --account must be propagated before that module loads.
    """
    args = list(argv) if argv is not None else sys.argv[1:]
    for i, tok in enumerate(args):
        if tok == "--account" and i + 1 < len(args):
            os.environ["TG_ACCOUNT"] = args[i + 1]
            return
        if tok.startswith("--account="):
            os.environ["TG_ACCOUNT"] = tok.split("=", 1)[1]
            return


_pre_parse_account_flag(None)

from tgcli.commands._common import AUDIT_PATH, ENV_PATH
from tgcli.env import load_env_file
from tgcli.output import ExitCode, fail, is_tty_stdout, new_request_id
from tgcli.safety import audit_write

load_env_file(ENV_PATH)

COMMAND_MODULES: tuple[str, ...] = (
    "tgcli.commands.auth",
    "tgcli.commands.stats",
    "tgcli.commands.contacts",
    "tgcli.commands.messages",
    "tgcli.commands.chats",
    "tgcli.commands.events",
    "tgcli.commands.doctor",
    "tgcli.commands.accounts",
    "tgcli.commands.account",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tg",
        description="Telegram agent CLI — read/write/listen against your own Telegram account.",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Reject any write to Telegram or local DB. Also via TG_READONLY=1.",
    )
    parser.add_argument(
        "--lock-wait",
        type=float,
        default=0,
        help="Seconds to wait for the Telethon session lock (default 0 = fail-fast).",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Disable column truncation in human-mode output.",
    )
    parser.add_argument(
        "--account",
        default=None,
        help="Account name (uses accounts/<NAME>/). Default selected via accounts-use or TG_ACCOUNT env.",
    )
    sub = parser.add_subparsers(dest="cmd")
    for mod_name in COMMAND_MODULES:
        import_module(mod_name).register(sub)
    return parser


def _emit_top_level_failure(msg: str, code: ExitCode) -> int:
    """Used only when something fails before any command's run() is reached."""
    request_id = new_request_id()
    env = fail("(top-level)", code, msg, request_id=request_id)
    if is_tty_stdout():
        print(f"ERROR [{code.name}]: {msg}", file=sys.stderr)
    else:
        print(json.dumps(env, ensure_ascii=False, default=str))
    try:
        audit_write(AUDIT_PATH, cmd="(top-level)", request_id=request_id,
                    args_repr={}, result="fail", error_code=code.name)
    except OSError:
        pass
    return code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        # argparse exits 2 for usage errors; preserve that contract.
        return int(e.code or 0)
    if not args.cmd:
        parser.print_help(sys.stderr)
        return 0
    # Propagate top-level flags via env so command modules don't need to thread them.
    if getattr(args, "lock_wait", 0):
        import os as _os
        _os.environ["TG_LOCK_WAIT"] = str(args.lock_wait)
    if getattr(args, "read_only", False):
        import os as _os
        _os.environ["TG_READONLY"] = "1"
    if getattr(args, "full", False):
        import os as _os
        _os.environ["TG_FULL"] = "1"
    try:
        result = args.func(args)
        if inspect.iscoroutine(result):
            return int(asyncio.run(result) or 0)
        return int(result or 0)
    except KeyboardInterrupt:
        return _emit_top_level_failure("Interrupted by user", ExitCode.GENERIC)
    except SystemExit:
        raise


if __name__ == "__main__":
    sys.exit(main())
