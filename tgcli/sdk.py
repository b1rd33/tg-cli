"""SDK surface — `from tgcli import Client`.

Wraps existing command runners. Each method synthesizes an args
SimpleNamespace and calls the same `_runner(args)` the CLI uses, then
returns the runner's dict result directly (no JSON envelope wrapping).

Account scoping: the command modules read DB_PATH/SESSION_PATH/AUDIT_PATH
from TG_ACCOUNT at module import time. Once imported, those globals
are frozen. The Client therefore validates that TG_ACCOUNT (set BEFORE
the first tgcli import) matches the requested account, and raises
RuntimeError on mismatch. Multi-account-in-process is out of scope.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any


def _ns(**kwargs: Any) -> SimpleNamespace:
    """Build a Namespace-shaped object the runners expect.

    Defaults every flag that any runner reads via getattr so missing
    kwargs surface as predictable behavior, not AttributeError.
    """
    defaults: dict[str, Any] = {
        "json": True,
        "human": False,
        "_request_id": None,
        "read_only": False,
        "allow_write": False,
        "fuzzy": False,
        "dry_run": False,
        "confirm": None,
        "idempotency_key": None,
        "full": False,
        "lock_wait": None,
        "account": None,
        "reply_to": None,
        "topic": None,
        "silent": False,
        "no_webpage": False,
        "include_deleted": False,
        "reverse": False,
        "limit": 50,
        "pattern": None,
        "chat_id": None,
        "min_msgs": 0,
        "closed": False,
        "reopen": False,
        "hidden": False,
        "unhidden": False,
        "title": None,
        "emoticon": None,
        "clear_include": False,
        "clear_exclude": False,
        "include_chat": None,
        "exclude_chat": None,
        "contacts": False,
        "non_contacts": False,
        "groups": False,
        "broadcasts": False,
        "bots": False,
        "exclude_muted": False,
        "exclude_read": False,
        "exclude_archived": False,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _invoke(runner, args: SimpleNamespace) -> Any:
    result = runner(args)
    if inspect.iscoroutine(result):
        return asyncio.run(result)
    return result


def _frozen_account() -> str:
    from tgcli.commands import _common

    return _common.ACCOUNT


class Client:
    """SDK entry point.

    Multi-account: set TG_ACCOUNT=<name> BEFORE importing tgcli, then
    construct Client(account="<name>"). Mismatched constructions raise
    RuntimeError so silent wrong-account writes are impossible.
    """

    def __init__(self, account: str = "default") -> None:
        frozen = _frozen_account()
        if account != frozen:
            raise RuntimeError(
                f"Client(account={account!r}) but tgcli was imported with TG_ACCOUNT={frozen!r}. "
                f"Set TG_ACCOUNT={account!r} BEFORE importing tgcli, or instantiate "
                f"Client(account={frozen!r}). v0.4.0 SDK is single-account-per-process."
            )
        self.account = account
        self.messages = _Messages(self)
        self.chats = _Chats(self)
        self.topics = _Topics(self)
        self.folders = _Folders(self)
        self.contacts = _Contacts(self)
        self.media = _Media(self)
        self.accounts = _Accounts(self)
        self.admin = _Admin(self)

    def __repr__(self) -> str:
        return f"Client(account={self.account!r})"

    def _call(self, runner, *, takes_args: bool = True, **kwargs: Any) -> Any:
        if not takes_args:
            result = runner()
            if inspect.iscoroutine(result):
                return asyncio.run(result)
            return result
        return _invoke(runner, _ns(**kwargs))

    def me(self) -> dict[str, Any]:
        from tgcli.commands.auth import _me_offline_runner

        return self._call(_me_offline_runner, takes_args=False)

    def stats(self, *, min_msgs: int = 0) -> dict[str, Any]:
        from tgcli.commands.stats import _gather

        return self._call(_gather, min_msgs=min_msgs)


class _Namespace:
    def __init__(self, client: Client) -> None:
        self._c = client


class _Messages(_Namespace):
    def show(
        self,
        *,
        chat_id: int | None = None,
        pattern: str | None = None,
        limit: int = 50,
        reverse: bool = False,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        from tgcli.commands.messages import _show_runner

        return self._c._call(
            _show_runner,
            chat_id=chat_id,
            pattern=pattern,
            limit=limit,
            reverse=reverse,
            include_deleted=include_deleted,
        )

    def send(
        self,
        *,
        chat: int | str,
        text: str,
        allow_write: bool = False,
        idempotency_key: str | None = None,
        fuzzy: bool = False,
        dry_run: bool = False,
        reply_to: int | None = None,
        topic: int | None = None,
        silent: bool = False,
        no_webpage: bool = False,
    ) -> dict[str, Any]:
        from tgcli.commands.messages import _send_runner

        return self._c._call(
            _send_runner,
            chat=chat,
            text=text,
            allow_write=allow_write,
            idempotency_key=idempotency_key,
            fuzzy=fuzzy,
            dry_run=dry_run,
            reply_to=reply_to,
            topic=topic,
            silent=silent,
            no_webpage=no_webpage,
        )


class _Chats(_Namespace):
    pass


class _Topics(_Namespace):
    pass


class _Folders(_Namespace):
    pass


class _Contacts(_Namespace):
    pass


class _Media(_Namespace):
    pass


class _Accounts(_Namespace):
    pass


class _Admin(_Namespace):
    def chat_title(
        self,
        *,
        chat: int | str,
        title: str,
        allow_write: bool = False,
        idempotency_key: str | None = None,
        fuzzy: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        from tgcli.commands.admin import _chat_title_runner

        return self._c._call(
            _chat_title_runner,
            chat=chat,
            title=title,
            allow_write=allow_write,
            idempotency_key=idempotency_key,
            fuzzy=fuzzy,
            dry_run=dry_run,
        )
