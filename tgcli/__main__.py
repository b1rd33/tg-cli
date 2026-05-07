"""Argparse dispatcher for the `tg` CLI."""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from importlib import import_module

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
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tg",
        description="Telegram agent CLI — read/write/listen against your own Telegram account.",
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
