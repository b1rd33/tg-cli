"""Single chokepoint that wraps every command's logic.

Responsibilities:
- Generate a request ID for log/envelope correlation.
- Run the runner, which may be sync or async.
- Map known exceptions to fail envelopes with stable exit codes.
- Route output through `output.emit()` honoring --json, --human, and TTY auto.
- Append one entry to the audit log per invocation.
"""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any, Awaitable, Callable

from telethon.errors import FloodWaitError

from tgcli.client import MissingCredentials, SessionLocked
from tgcli.db import DatabaseMissing
from tgcli.output import ExitCode, emit, fail, is_tty_stdout, new_request_id, success
from tgcli.resolve import Ambiguous, NotFound
from tgcli.safety import (
    BadArgs,
    LocalRateLimited,
    NeedsConfirm,
    WriteDisallowed,
    audit_write,
)

Runner = Callable[[], Any] | Callable[[], Awaitable[Any]]


def _resolve_json_mode(args) -> bool:
    """Honor --json / --human, else auto-detect from TTY."""
    if getattr(args, "json", False):
        return True
    if getattr(args, "human", False):
        return False
    return not is_tty_stdout()


def _args_repr(args) -> dict[str, Any]:
    """Best-effort dict copy of argparse Namespace for the audit log."""
    return {k: v for k, v in vars(args).items() if not k.startswith("_") and k != "func"}


def _classify_exception(exc: BaseException) -> tuple[ExitCode, str, dict[str, Any]]:
    """Map a known exception to (exit_code, message, extra-fields-for-envelope)."""
    if isinstance(exc, Ambiguous):
        return ExitCode.BAD_ARGS, str(exc), {"candidates": exc.candidates}
    if isinstance(exc, NotFound):
        return ExitCode.NOT_FOUND, str(exc), {}
    if isinstance(exc, BadArgs):
        return ExitCode.BAD_ARGS, str(exc), {}
    if isinstance(exc, DatabaseMissing):
        return ExitCode.NOT_FOUND, str(exc), {}
    if isinstance(exc, MissingCredentials):
        return ExitCode.NOT_AUTHED, str(exc), {}
    if isinstance(exc, SessionLocked):
        return ExitCode.GENERIC, str(exc), {}
    if isinstance(exc, WriteDisallowed):
        return ExitCode.WRITE_DISALLOWED, str(exc), {}
    if isinstance(exc, NeedsConfirm):
        return ExitCode.NEEDS_CONFIRM, str(exc), {}
    if isinstance(exc, LocalRateLimited):
        return (
            ExitCode.LOCAL_RATE_LIMIT,
            str(exc),
            {"retry_after_seconds": exc.retry_after_seconds},
        )
    if isinstance(exc, FloodWaitError):
        return (
            ExitCode.FLOOD_WAIT,
            f"Telegram FloodWait: wait {exc.seconds}s",
            {"retry_after_seconds": exc.seconds},
        )
    return ExitCode.GENERIC, f"{type(exc).__name__}: {exc}", {}


def _invoke(runner: Runner) -> Any:
    """Call sync or async runner, returning its data."""
    result = runner()
    if inspect.iscoroutine(result):
        return asyncio.run(result)
    return result


def run_command(
    name: str,
    args,
    runner: Runner,
    *,
    human_formatter: Callable[[Any], None] | None = None,
    audit_path: Path,
) -> int:
    """Run a command and return its process exit code."""
    request_id = new_request_id()
    json_mode = _resolve_json_mode(args)

    try:
        data = _invoke(runner)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        code, message, extra = _classify_exception(exc)
        envelope = fail(name, code, message, request_id=request_id, **extra)
        audit_write(
            audit_path,
            cmd=name,
            request_id=request_id,
            args_repr=_args_repr(args),
            result="fail",
            error_code=code.name,
        )
        return emit(envelope, json_mode=json_mode)

    envelope = success(name, data, request_id=request_id)
    audit_write(
        audit_path,
        cmd=name,
        request_id=request_id,
        args_repr=_args_repr(args),
        result="ok",
    )
    return emit(envelope, json_mode=json_mode, human_formatter=human_formatter)
