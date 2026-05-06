"""Argparse dispatcher for the `tg` CLI."""
from __future__ import annotations

import argparse
import asyncio
import inspect
import sys
from importlib import import_module

from tgcli.commands._common import ENV_PATH
from tgcli.env import load_env_file

# Load .env before any command parses args (commands may read env at import time).
load_env_file(ENV_PATH)

# Each command area exposes a `register(subparsers)` function.
# Order: read first, then write, then destructive — for help-output readability.
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help(sys.stderr)
        return 0
    result = args.func(args)
    if inspect.iscoroutine(result):
        return int(asyncio.run(result) or 0)
    return int(result or 0)


if __name__ == "__main__":
    sys.exit(main())
