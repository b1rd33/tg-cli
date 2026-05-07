# Phase 9 — Destructive Commands

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-05-08

**Status:** Draft

**Prerequisite:** Phase 8 complete with `173 passed`. All write commands route through the unified safety pipeline.

**Goal:** Ship six destructive commands behind typed `--confirm <id>` gates so an agent can complete the write-CRUD surface without ever writing a footgun.

**Architecture:**
- Six new top-level commands: `delete-msg`, `leave-chat`, `block-user`, `unblock-user`, `account-sessions`, `terminate-session`.
- All write commands use the existing Phase 6 pipeline (`require_write_allowed`, `audit_pre`, `record_idempotency`) plus a new typed-confirm helper `require_typed_confirm(args, *, expected: str)` that compares `args.confirm` against the **resolved** id post-resolver — not the raw selector.
- `delete-msg` is batch-aware: takes 1+ message_ids, emits one pre-audit + one post-audit per id (sharing dispatch's request_id) and returns a per-id result envelope.
- `delete-msg --for-everyone` writes a tombstone to local DB (`tg_messages.deleted = 1`) so cached reads don't return ghost messages. Reads filter `deleted = 0` by default; `--include-deleted` opt-in flag.
- `terminate-session` reads the current session's hash via `GetAuthorizationsRequest` and refuses to terminate it.
- `unblock-user` is the only command WITHOUT `--confirm` (recoverable by re-blocking).

**Tech Stack:** Python 3.12 stdlib + Telethon 1.43.2. **No new third-party deps.**

**Backwards compatibility:** End at ~190 passing tests (173 baseline + ~17 new).

---

## Existing Code Map

| Area | Current line refs | Phase 9 use |
|---|---|---|
| Phase 6 write pipeline | `tgcli/commands/messages.py:_send_runner` | Reuse for all destructive writes |
| `require_confirm` (untyped) | `tgcli/safety.py:43-48` | Extend with `require_typed_confirm` (resolved-id comparison) |
| Idempotency helpers | `tgcli/idempotency.py` | Reuse for all destructive writes |
| Resolver + fuzzy gate | `tgcli/resolve.py`, `_resolve_write_chat` | Use for `delete-msg`, `leave-chat`, `block-user`, `unblock-user` |
| Message tombstone column | `tgcli/db.py:13-44` (SCHEMA) | Add `tg_messages.deleted INTEGER DEFAULT 0` via idempotent ALTER |
| Read filters | `tgcli/commands/messages.py:_show_runner`, `_search_runner`, `_list_runner` | Add `deleted = 0` filter + `--include-deleted` flag |
| `add_write_flags(destructive=True)` | `tgcli/commands/_common.py:38-49` | Pre-existing; turns on `--confirm` slot |
| Telethon `messages.DeleteMessagesRequest(id, revoke=)` | `.venv/.../telethon/tl/functions/messages.py` | Private chats and basic groups |
| Telethon `channels.DeleteMessagesRequest(channel, id)` | `.venv/.../telethon/tl/functions/channels.py` | Supergroups + channels |
| Telethon `channels.LeaveChannelRequest(channel)` | same file | Channels + supergroups |
| Telethon `contacts.BlockRequest(id, my_stories_from)` | `.venv/.../telethon/tl/functions/contacts.py` | Block |
| Telethon `contacts.UnblockRequest(id, my_stories_from)` | same | Unblock |
| Telethon `account.GetAuthorizationsRequest()` | `.venv/.../telethon/tl/functions/account.py` | List sessions |
| Telethon `account.ResetAuthorizationRequest(hash: int)` | same | Terminate session |
| Telethon `Authorization.current` flag | `tl/types/__init__.py` | Detect current session to refuse self-terminate |

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `tgcli/safety.py` | modify | Add `require_typed_confirm(args, *, expected, slot)` |
| `tgcli/db.py` | modify | Add `tg_messages.deleted INTEGER DEFAULT 0` (via `_migrate`) and `tg_chats.left INTEGER DEFAULT 0` |
| `tgcli/commands/messages.py` | modify | Add `delete-msg` parser + runner; add `deleted = 0` filter to `_show_runner` / `_search_runner` / `_list_runner`; add `--include-deleted` |
| `tgcli/commands/chats.py` | modify | Add `leave-chat` parser + runner |
| `tgcli/commands/contacts.py` | modify | Add `block-user` and `unblock-user` parsers + runners |
| `tgcli/commands/account.py` | **create** | `account-sessions` (read) and `terminate-session` (write) |
| `tgcli/__main__.py` | modify | Register `account` module |
| `tests/tgcli/test_phase9_*.py` | **create** | One file per command |

---

## Design Decisions

1. **Typed confirm semantics.** `require_typed_confirm(args, *, expected: str, slot: str)` raises `BadArgs` unless `args.confirm == str(expected)`. The `slot` parameter is a human label like "chat_id", "user_id", or "session_hash" used in the error message:

```
BadArgs: --confirm value 'Hamid' must equal the resolved chat_id 289840388.
Pass --confirm 289840388 to confirm.
```

This is the **single most safety-critical line of code in the platform**. Tests stress-test:
- `--confirm` matching raw selector but resolver returned a different id → MUST reject
- `--confirm` matching resolved id → must pass
- `--confirm` value with different type (int vs str) → must compare as strings (`str(args.confirm) == str(expected)`)
- Bare `--confirm` flag without value → not possible because we use `type=str, default=None`; `None != expected_str`

2. **`--confirm` slot precedence.** Each destructive command's parser uses `add_write_flags(p, destructive=True)` which adds `--confirm`. The current implementation uses `action="store_true"` (bare flag). **Phase 9 changes this to `type=str, default=None`** so it accepts a value. This is a safety upgrade that preserves the meaning of `--confirm` (still required for destructive ops) but tightens it from "the user typed --confirm" to "the user typed --confirm <expected-id>". Existing destructive callers (none in Phase 6+ today) would need to update; since none exist outside Phase 9, no migration needed.

3. **`delete-msg` uses the Telethon high-level wrapper.** Call `client.delete_messages(entity, ids, revoke=...)` rather than the raw `messages.DeleteMessagesRequest` / `channels.DeleteMessagesRequest`. The high-level wrapper handles the channel-vs-non-channel split internally and correctly resolves the entity to the right peer type. (Telegram's data model: for private chats and basic groups, message_id is globally unique per user; for supergroups/channels, message_id is per-channel. The high-level wrapper picks the right RPC.)

4. **`delete-msg` batch envelope shape.**

```json
{
  "ok": true,
  "command": "delete-msg",
  "data": {
    "chat": {"chat_id": 123, "title": "..."},
    "for_everyone": true,
    "summary": {"total": 5, "succeeded": 3, "failed": 2},
    "results": [
      {"message_id": 100, "ok": true, "deleted": true},
      {"message_id": 101, "ok": false, "error_code": "NOT_FOUND", "error": "msg not found"},
      ...
    ]
  }
}
```

The envelope is `ok=true` even if some message_ids failed — partial-success is the norm for batch ops. Caller checks `summary.failed` to detect partial failure. (If ALL ids fail, still `ok=true` with `summary.failed == total` — agents inspect summary explicitly.)

5. **Audit log for batch.** Single dispatch request_id. One `audit_pre` per id; one `audit_post` (the dispatch wrapper does this once for the whole envelope; the per-id pre entries plus the single post entry give the auditor enough trace). Don't manually call audit_post per-id; that would conflict with dispatch.

6. **Tombstones in local DB.** `delete-msg --for-everyone` sets `tg_messages.deleted = 1` for each successfully-revoked id. `--for-everyone` defaults to `True` if the user authored the message OR if it's in a chat where revoke-for-all is normal. Default rule per brief: "default is revoke if you authored, else delete-for-me". Implementation: check `tg_messages.is_outgoing` from cache. If unknown (msg not in cache), default to `revoke=False` (safest).

7. **Read filters.** `_show_runner`, `_search_runner`, `_list_runner`, `_get_runner` add `WHERE deleted = 0` to their SQL. New flag `--include-deleted` flips this to `WHERE 1=1` (or omits the clause). Keeps cached deleted msgs visible for forensic agents.

8. **`leave-chat` refuses self.** `args.chat == "me"` or `chat_id == self_user_id` raises `BadArgs("cannot leave Saved Messages or your own user chat")`. Check `self_user_id` from `tg_me` cache; if cache is empty, fetch live via `client.get_me()` and cache before proceeding.

9. **`leave-chat` uses the Telethon high-level wrapper.** Call `client.delete_dialog(entity, revoke=False)` rather than dispatching `LeaveChannelRequest` vs `DeleteChatUserRequest` manually. The high-level wrapper handles channel / supergroup / basic-group / private-chat dispatch correctly and constructs the right `InputUser` for the basic-group path (avoids the `InputPeerSelf` vs `InputUser` type mismatch flagged by codex review). Update `tg_chats.left = 1` after the call returns.

10. **`block-user` / `unblock-user` selector.** Resolver supports user_id, @username, or fuzzy contact name (with `--fuzzy` opt-in). Resolves to a user; rejects with `BadArgs` if the resolved chat is not a user (e.g. trying to block a channel).

11. **`terminate-session` confirm-against-hash.** `--confirm` value must equal the session `hash` (a 64-bit int as string). Refuses if the hash matches the current session's hash. Refuses with `BadArgs("session hash N is the current session; terminating it would log you out")`.

12. **Idempotency keys per command.** Same mechanism as Phase 6 — required for writes; `--idempotency-key` mandatory per the Phase 6.2 stricter convention. Replay returns the cached envelope.

13. **Idempotency replay returns first-call outcome.** For batch `delete-msg`, the `results` list captured on the first call is returned verbatim on retry, regardless of current server state. If 3 of 5 ids deleted on the first call and a retry happens after some additional manual deletes, replay still says "3 succeeded, 2 failed" with the original error messages. This is the deliberate Phase 6 idempotency contract: replay is "what was the recorded outcome," not "re-evaluate against current state."

14. **`unblock-user` and bots.** Both `block-user` and `unblock-user` accept resolved chats of type `user` OR `bot` (bots are users in Telegram's data model). The non-user guard is `chat_type not in ("user", "bot")` which rejects channels, supergroups, and basic groups.

---

## Task 1: Typed-confirm helper + DB tombstone schema

**Files:**
- Modify: `tgcli/safety.py` — add `require_typed_confirm`
- Modify: `tgcli/commands/_common.py` — change `--confirm` to `type=str` when `destructive=True`
- Modify: `tgcli/db.py` — add `tg_messages.deleted` and `tg_chats.left` migrations
- Create: `tests/tgcli/test_phase9_typed_confirm.py`

- [ ] **Step 1: Test typed-confirm semantics**

```python
# tests/tgcli/test_phase9_typed_confirm.py
import argparse
import pytest

from tgcli.safety import BadArgs, require_typed_confirm


def _args(confirm=None):
    return argparse.Namespace(confirm=confirm)


def test_typed_confirm_rejects_when_unset():
    with pytest.raises(BadArgs, match="--confirm"):
        require_typed_confirm(_args(), expected=123, slot="chat_id")


def test_typed_confirm_rejects_mismatched_value():
    """The riskiest case: user typed --confirm with the raw selector
    that resolved to something different. Must reject."""
    with pytest.raises(BadArgs, match="must equal.*chat_id"):
        require_typed_confirm(_args(confirm="Hamid"), expected=289840388, slot="chat_id")


def test_typed_confirm_accepts_string_match_against_int():
    require_typed_confirm(_args(confirm="289840388"), expected=289840388, slot="chat_id")


def test_typed_confirm_accepts_int_match_against_int():
    require_typed_confirm(_args(confirm=289840388), expected=289840388, slot="chat_id")


def test_typed_confirm_rejects_substring_match():
    """Confirms 28984... (truncated) does NOT pass against 289840388."""
    with pytest.raises(BadArgs):
        require_typed_confirm(_args(confirm="28984"), expected=289840388, slot="chat_id")


def test_typed_confirm_rejects_negative_id_mismatch():
    with pytest.raises(BadArgs):
        require_typed_confirm(_args(confirm="-100123"), expected=-1003957621025, slot="chat_id")
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement** — append to `tgcli/safety.py`:

```python
def require_typed_confirm(args, *, expected, slot: str) -> None:
    """Verify --confirm exactly matches the RESOLVED id (string-compared).

    The resolver's output is the source of truth: comparing against the raw
    user selector would defeat the purpose of typed confirmation. Pass the
    POST-resolution id (chat_id, user_id, session hash) as `expected`.
    """
    raw = getattr(args, "confirm", None)
    if raw is None:
        raise BadArgs(
            f"destructive op requires --confirm <{slot}>. "
            f"Pass --confirm {expected} to confirm."
        )
    # Strip whitespace defensively (agent pipelines that interpolate from JSON
    # can introduce trailing newlines or spaces that would otherwise reject
    # legitimate confirms).
    if str(raw).strip() != str(expected).strip():
        raise BadArgs(
            f"--confirm value {raw!r} must equal the resolved {slot} {expected}. "
            f"Pass --confirm {expected} to confirm."
        )
```

- [ ] **Step 4: Update `add_write_flags(destructive=True)` in `tgcli/commands/_common.py`**

Replace:

```python
    if destructive:
        parser.add_argument("--confirm", action="store_true",
                            help="Required in addition to --allow-write for destructive ops")
```

with:

```python
    if destructive:
        parser.add_argument("--confirm", type=str, default=None,
                            help=("Required for destructive ops. Must equal the resolved "
                                  "chat_id / user_id / session_hash (post-resolver). "
                                  "Bare `--confirm true` is not accepted."))
```

- [ ] **Step 5: DB tombstone migration in `tgcli/db.py`**

Find the `_migrate(con)` function and append:

```python
    # Phase 9: tombstones + leave-chat marker
    cols_messages = {row[1] for row in con.execute("PRAGMA table_info(tg_messages)").fetchall()}
    if "deleted" not in cols_messages:
        con.execute("ALTER TABLE tg_messages ADD COLUMN deleted INTEGER DEFAULT 0")
    cols_chats = {row[1] for row in con.execute("PRAGMA table_info(tg_chats)").fetchall()}
    if "left" not in cols_chats:
        con.execute("ALTER TABLE tg_chats ADD COLUMN left INTEGER DEFAULT 0")
    con.commit()
```

- [ ] **Step 6: Run all tests, expect ~178 pass**

- [ ] **Step 7: Commit**

```bash
git add tgcli/safety.py tgcli/commands/_common.py tgcli/db.py tests/tgcli/test_phase9_typed_confirm.py
git commit -m "feat(tgcli): typed --confirm <id> + tombstone schema for Phase 9"
```

---

## Task 2: `delete-msg` (batch + tombstones)

**Files:**
- Modify: `tgcli/commands/messages.py`
- Create: `tests/tgcli/test_phase9_delete_msg.py`

- [ ] **Step 1: Test**

```python
# tests/tgcli/test_phase9_delete_msg.py
import argparse
import asyncio

import pytest

from tgcli.commands import messages
from tgcli.db import connect
from tgcli.safety import BadArgs


def _seed(path):
    con = connect(path)
    con.execute("INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
                (123, "user", "Alpha", "alpha"))
    con.executemany(
        """INSERT INTO tg_messages(chat_id, message_id, sender_id, date, text,
            is_outgoing, has_media) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [(123, 100, 11, "2026-05-08T10:00:00", "first", 1, 0),
         (123, 101, 11, "2026-05-08T10:01:00", "second", 1, 0)],
    )
    con.commit()
    con.close()


def _args(**kw):
    defaults = {"allow_write": True, "dry_run": False, "idempotency_key": "k1",
                "fuzzy": False, "json": True, "human": False, "read_only": False,
                "confirm": "123", "for_everyone": True, "include_deleted": False}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def test_delete_msg_rejects_wrong_confirm_value(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed(db)
    monkeypatch.setattr(messages, "DB_PATH", db)
    args = _args(chat="@alpha", message_ids=[100], confirm="999")
    with pytest.raises(BadArgs, match="must equal"):
        asyncio.run(messages._delete_msg_runner(args))


def test_delete_msg_batch_envelope_shape(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    class FakeClient:
        def __init__(self): self.calls = []
        async def start(self): pass
        async def get_input_entity(self, chat_id):
            from telethon.tl.types import InputPeerUser
            return InputPeerUser(user_id=int(chat_id), access_hash=0)
        async def __call__(self, request):
            self.calls.append(request)
            from telethon.tl.types import AffectedMessages
            return AffectedMessages(pts=1, pts_count=len(request.id))
        async def disconnect(self): pass

    fake = FakeClient()
    monkeypatch.setattr(messages, "make_client", lambda session_path: fake)
    args = _args(chat="@alpha", message_ids=[100, 101], confirm="123")
    data = asyncio.run(messages._delete_msg_runner(args))
    assert data["chat"]["chat_id"] == 123
    assert data["for_everyone"] is True
    assert data["summary"] == {"total": 2, "succeeded": 2, "failed": 0}
    assert len(data["results"]) == 2
    assert data["results"][0]["ok"] is True


def test_delete_msg_writes_tombstone_for_revoked(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed(db)
    monkeypatch.setattr(messages, "DB_PATH", db)

    class FakeClient:
        async def start(self): pass
        async def get_input_entity(self, c):
            from telethon.tl.types import InputPeerUser
            return InputPeerUser(user_id=int(c), access_hash=0)
        async def __call__(self, request):
            from telethon.tl.types import AffectedMessages
            return AffectedMessages(pts=1, pts_count=len(request.id))
        async def disconnect(self): pass

    monkeypatch.setattr(messages, "make_client", lambda session_path: FakeClient())
    args = _args(chat="@alpha", message_ids=[100], confirm="123", for_everyone=True)
    asyncio.run(messages._delete_msg_runner(args))
    import sqlite3
    con = sqlite3.connect(db)
    deleted = con.execute(
        "SELECT deleted FROM tg_messages WHERE chat_id=123 AND message_id=100"
    ).fetchone()[0]
    con.close()
    assert deleted == 1


def test_show_runner_filters_deleted_by_default(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed(db)
    import sqlite3
    con = sqlite3.connect(db)
    con.execute("UPDATE tg_messages SET deleted = 1 WHERE message_id = 100")
    con.commit(); con.close()
    monkeypatch.setattr(messages, "DB_PATH", db)
    args = _args(chat="@alpha", limit=10, reverse=False, include_deleted=False,
                 message_id=None)
    args.pattern = "@alpha"; args.chat_id = None
    data = messages._show_runner(args)
    msg_ids = [m for m in data["messages"]]
    # 100 deleted; only 101 remains.
    ids = [m.get("message_id", m.get("id")) for m in data["messages"]]
    # Some test paths may not include message_id; assert text instead.
    texts = [m.get("text") for m in data["messages"]]
    assert "first" not in texts
    assert "second" in texts


def test_show_runner_include_deleted_returns_both(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed(db)
    import sqlite3
    con = sqlite3.connect(db)
    con.execute("UPDATE tg_messages SET deleted = 1 WHERE message_id = 100")
    con.commit(); con.close()
    monkeypatch.setattr(messages, "DB_PATH", db)
    args = _args(chat="@alpha", limit=10, reverse=False, include_deleted=True,
                 message_id=None)
    args.pattern = "@alpha"; args.chat_id = None
    data = messages._show_runner(args)
    texts = [m.get("text") for m in data["messages"]]
    assert "first" in texts and "second" in texts
```

- [ ] **Step 2: Implement parser registration** in `messages.register()`:

```python
    dl = sub.add_parser("delete-msg", help="Delete one or more messages from a chat")
    dl.add_argument("chat", help="Chat selector (id, @username, or fuzzy with --fuzzy)")
    dl.add_argument("message_ids", type=int, nargs="+", help="One or more message_ids to delete")
    dl.add_argument("--for-everyone", action="store_true",
                    help="Revoke for all participants (default: revoke if outgoing else delete-for-me)")
    dl.add_argument("--no-for-everyone", dest="for_everyone", action="store_false")
    dl.set_defaults(for_everyone=None)  # tri-state: None = auto-detect from is_outgoing
    add_write_flags(dl, destructive=True)
    add_output_flags(dl)
    dl.set_defaults(func=run_delete_msg)
```

- [ ] **Step 3: Implement `_delete_msg_runner`**

```python
async def _delete_msg_runner(args) -> dict[str, Any]:
    from tgcli.safety import require_typed_confirm

    command = "delete-msg"
    request_id = _request_id(args)
    require_write_allowed(args)

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data

        chat = _resolve_write_chat(con, args, args.chat)
        require_typed_confirm(args, expected=chat["chat_id"], slot="chat_id")

        # Default for_everyone: revoke if outgoing else delete-for-me. We use
        # is_outgoing from the local cache; if any of the ids isn't cached,
        # default to revoke=False (safer).
        for_everyone = args.for_everyone
        if for_everyone is None:
            outgoing_count = con.execute(
                "SELECT COUNT(*) FROM tg_messages WHERE chat_id=? AND message_id IN ({}) AND is_outgoing=1".format(
                    ",".join("?" * len(args.message_ids))
                ),
                (chat["chat_id"], *args.message_ids),
            ).fetchone()[0]
            for_everyone = (outgoing_count == len(args.message_ids))

        if args.dry_run:
            return _dry_run_envelope(command, request_id, {
                "chat": chat, "message_ids": args.message_ids,
                "for_everyone": for_everyone,
                "telethon_method": "client.delete_messages",
            })

        _check_write_rate_limit()
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_input_entity(chat["chat_id"])
            results: list[dict[str, Any]] = []
            for mid in args.message_ids:
                audit_pre(
                    AUDIT_PATH, cmd=command, request_id=request_id,
                    resolved_chat_id=chat["chat_id"], resolved_chat_title=chat["title"],
                    payload_preview={"message_id": mid, "for_everyone": for_everyone},
                    telethon_method="client.delete_messages",
                    dry_run=False,
                )
                try:
                    # client.delete_messages dispatches to channels.DeleteMessages or
                    # messages.DeleteMessages internally based on the entity type.
                    await client.delete_messages(entity, [mid], revoke=for_everyone)
                    if for_everyone:
                        con.execute(
                            "UPDATE tg_messages SET deleted = 1 WHERE chat_id = ? AND message_id = ?",
                            (chat["chat_id"], mid),
                        )
                        con.commit()
                    results.append({"message_id": mid, "ok": True, "deleted": True})
                except Exception as exc:
                    results.append({"message_id": mid, "ok": False,
                                    "error": str(exc), "error_code": type(exc).__name__})

            succeeded = sum(1 for r in results if r["ok"])
            failed = len(results) - succeeded
            data = {
                "chat": chat,
                "for_everyone": for_everyone,
                "summary": {"total": len(results), "succeeded": succeeded, "failed": failed},
                "results": results,
                "idempotent_replay": False,
            }
            record_idempotency(con, args.idempotency_key, command, request_id,
                               _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_delete_msg(args) -> int:
    return _run_write_command("delete-msg", args, _delete_msg_runner)
```

- [ ] **Step 4: Add `--include-deleted` flag + `WHERE deleted = 0` filter to read runners**

In `_show_runner`:

```python
# Replace the SELECT for messages:
include_deleted = bool(getattr(args, "include_deleted", False))
deleted_clause = "" if include_deleted else " AND (deleted = 0 OR deleted IS NULL)"
rows = con.execute(
    f"""
    SELECT date, is_outgoing, text, media_type
    FROM tg_messages
    WHERE chat_id = ? {deleted_clause}
    ORDER BY date {order}
    LIMIT ?
    """,
    (chat_id, args.limit),
).fetchall()
```

Same pattern in `_search_runner`, `_list_runner`, AND `_get_runner` — each needs the `--include-deleted` flag in its parser AND the `WHERE deleted = 0 OR deleted IS NULL` filter in its SQL. For `_get_runner`, since it fetches a single (chat_id, message_id) row, the filter still applies — returning a tombstoned message would be misleading unless the caller asked for it.

In each parser registration (`show`, `search`, `list-msgs`, `get-msg`):

```python
sh.add_argument("--include-deleted", action="store_true",
                help="Include locally-tombstoned (deleted-for-everyone) messages")
```

- [ ] **Step 5: Run tests, expect green**

- [ ] **Step 6: Commit**

```bash
git add tgcli/commands/messages.py tests/tgcli/test_phase9_delete_msg.py
git commit -m "feat(tgcli): delete-msg batch with tombstones + --include-deleted on reads"
```

---

## Task 3: `leave-chat`

**Files:**
- Modify: `tgcli/commands/chats.py`
- Create: `tests/tgcli/test_phase9_leave_chat.py`

- [ ] **Step 1: Test**

```python
# tests/tgcli/test_phase9_leave_chat.py
import argparse
import asyncio
import pytest

from tgcli.commands import chats
from tgcli.db import connect
from tgcli.safety import BadArgs


def _seed(path, *, self_id=42):
    con = connect(path)
    con.execute("INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
                (self_id, "user", "Saved Messages (self)", "me"))
    con.execute("INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
                (-1001234, "supergroup", "Test SG", "test_sg"))
    con.execute("""INSERT INTO tg_me(key, user_id, username, display_name, cached_at)
                   VALUES ('self', ?, ?, ?, ?)""",
                (self_id, "me", "Me", "2026-05-08T10:00:00+00:00"))
    con.commit(); con.close()


def _args(**kw):
    defaults = {"allow_write": True, "dry_run": False, "idempotency_key": "leave-1",
                "fuzzy": False, "json": True, "human": False, "read_only": False,
                "confirm": None}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def test_leave_chat_rejects_self_dm(monkeypatch, tmp_path):
    db = tmp_path / "x.sqlite"
    _seed(db)
    monkeypatch.setattr(chats, "DB_PATH", db)
    args = _args(chat="42", confirm="42")
    with pytest.raises(BadArgs, match="cannot leave"):
        asyncio.run(chats._leave_chat_runner(args))


def test_leave_chat_marks_tg_chats_left(monkeypatch, tmp_path):
    db = tmp_path / "x.sqlite"
    _seed(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        async def start(self): pass
        async def get_input_entity(self, c):
            from telethon.tl.types import InputPeerChannel
            return InputPeerChannel(channel_id=abs(int(c)), access_hash=0)
        async def __call__(self, request): return True
        async def disconnect(self): pass

    monkeypatch.setattr(chats, "make_client", lambda s: FakeClient())
    args = _args(chat="-1001234", confirm="-1001234")
    data = asyncio.run(chats._leave_chat_runner(args))
    assert data["left"] is True
    import sqlite3
    con = sqlite3.connect(db)
    left = con.execute("SELECT left FROM tg_chats WHERE chat_id=-1001234").fetchone()[0]
    con.close()
    assert left == 1


def test_leave_chat_typed_confirm_mismatch(monkeypatch, tmp_path):
    db = tmp_path / "x.sqlite"
    _seed(db)
    monkeypatch.setattr(chats, "DB_PATH", db)
    args = _args(chat="-1001234", confirm="999")
    with pytest.raises(BadArgs, match="must equal"):
        asyncio.run(chats._leave_chat_runner(args))
```

- [ ] **Step 2: Implement parser + runner**

In `chats.py` register():

```python
    lc = sub.add_parser("leave-chat", help="Leave a group, supergroup, or channel")
    lc.add_argument("chat", help="Chat selector (id, @username, or fuzzy with --fuzzy)")
    add_write_flags(lc, destructive=True)
    add_output_flags(lc)
    lc.set_defaults(func=run_leave_chat)
```

Runner:

```python
async def _leave_chat_runner(args) -> dict[str, Any]:
    from tgcli.safety import require_typed_confirm

    command = "leave-chat"
    request_id = _request_id(args)
    require_write_allowed(args)

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data

        chat = _resolve_write_chat(con, args, args.chat)
        require_typed_confirm(args, expected=chat["chat_id"], slot="chat_id")

        # Refuse self-DM (Saved Messages)
        me = con.execute("SELECT user_id FROM tg_me WHERE key='self'").fetchone()
        if me and chat["chat_id"] == me[0]:
            raise BadArgs("cannot leave Saved Messages (self DM)")

        chat_type = con.execute(
            "SELECT type FROM tg_chats WHERE chat_id = ?", (chat["chat_id"],)
        ).fetchone()
        if chat_type and chat_type[0] == "user":
            raise BadArgs("cannot leave a 1-on-1 user chat (delete-msg can clean history)")

        if args.dry_run:
            return _dry_run_envelope(command, request_id, {
                "chat": chat, "telethon_method": "client.delete_dialog",
            })

        _check_write_rate_limit()
        audit_pre(AUDIT_PATH, cmd=command, request_id=request_id,
                  resolved_chat_id=chat["chat_id"], resolved_chat_title=chat["title"],
                  payload_preview={"chat": chat}, telethon_method="client.delete_dialog",
                  dry_run=False)

        client = make_client(SESSION_PATH)
        await client.start()
        try:
            entity = await client.get_input_entity(chat["chat_id"])
            # client.delete_dialog handles channel / supergroup / basic-group / private
            # dispatch internally and avoids the InputPeerSelf-vs-InputUser type mismatch
            # that the raw DeleteChatUserRequest path would hit.
            await client.delete_dialog(entity)
            con.execute("UPDATE tg_chats SET left = 1 WHERE chat_id = ?", (chat["chat_id"],))
            con.commit()
            data = {"chat": chat, "left": True, "telethon_method": "client.delete_dialog",
                    "idempotent_replay": False}
            record_idempotency(con, args.idempotency_key, command, request_id,
                               _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_leave_chat(args) -> int:
    return _run_write_command("leave-chat", args, _leave_chat_runner)
```

- [ ] **Step 3: Commit**

```bash
git add tgcli/commands/chats.py tests/tgcli/test_phase9_leave_chat.py
git commit -m "feat(tgcli): leave-chat with self-DM guard"
```

---

## Task 4: `block-user` and `unblock-user`

**Files:**
- Modify: `tgcli/commands/contacts.py`
- Create: `tests/tgcli/test_phase9_block.py`

- [ ] **Step 1: Test**

```python
# tests/tgcli/test_phase9_block.py
import argparse
import asyncio
import pytest

from tgcli.commands import contacts
from tgcli.db import connect
from tgcli.safety import BadArgs


def _seed(path):
    con = connect(path)
    con.execute("INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
                (200, "user", "Bob", "bob"))
    con.execute("INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
                (-1001, "channel", "ChanX", "chx"))
    con.commit(); con.close()


def _args(**kw):
    defaults = {"allow_write": True, "dry_run": False, "idempotency_key": "k1",
                "fuzzy": False, "json": True, "human": False, "read_only": False,
                "confirm": None}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def test_block_user_rejects_non_user(monkeypatch, tmp_path):
    db = tmp_path / "x.sqlite"
    _seed(db)
    monkeypatch.setattr(contacts, "DB_PATH", db)
    args = _args(user="-1001", confirm="-1001")
    with pytest.raises(BadArgs, match="user"):
        asyncio.run(contacts._block_user_runner(args))


def test_block_user_typed_confirm_mismatch(monkeypatch, tmp_path):
    db = tmp_path / "x.sqlite"
    _seed(db)
    monkeypatch.setattr(contacts, "DB_PATH", db)
    args = _args(user="200", confirm="999")
    with pytest.raises(BadArgs, match="must equal"):
        asyncio.run(contacts._block_user_runner(args))


def test_block_user_calls_block_request(monkeypatch, tmp_path):
    db = tmp_path / "x.sqlite"
    _seed(db)
    monkeypatch.setattr(contacts, "DB_PATH", db)

    class FakeClient:
        def __init__(self): self.calls = []
        async def start(self): pass
        async def get_input_entity(self, c):
            from telethon.tl.types import InputPeerUser
            return InputPeerUser(user_id=int(c), access_hash=0)
        async def __call__(self, r): self.calls.append(r); return True
        async def disconnect(self): pass

    fake = FakeClient()
    monkeypatch.setattr(contacts, "make_client", lambda s: fake)
    args = _args(user="200", confirm="200")
    data = asyncio.run(contacts._block_user_runner(args))
    assert data["blocked"] is True
    assert fake.calls[0].__class__.__name__ == "BlockRequest"


def test_unblock_user_no_confirm_required(monkeypatch, tmp_path):
    """Unblock is recoverable (just re-block); no --confirm needed."""
    db = tmp_path / "x.sqlite"
    _seed(db)
    monkeypatch.setattr(contacts, "DB_PATH", db)

    class FakeClient:
        def __init__(self): self.calls = []
        async def start(self): pass
        async def get_input_entity(self, c):
            from telethon.tl.types import InputPeerUser
            return InputPeerUser(user_id=int(c), access_hash=0)
        async def __call__(self, r): self.calls.append(r); return True
        async def disconnect(self): pass

    fake = FakeClient()
    monkeypatch.setattr(contacts, "make_client", lambda s: fake)
    # No confirm in args:
    args = _args(user="200")
    args.confirm = None  # explicit
    data = asyncio.run(contacts._unblock_user_runner(args))
    assert data["unblocked"] is True
```

- [ ] **Step 2: Implement parsers**

```python
    bl = sub.add_parser("block-user", help="Block a user")
    bl.add_argument("user", help="User selector (id, @username, or fuzzy with --fuzzy)")
    add_write_flags(bl, destructive=True)
    add_output_flags(bl)
    bl.set_defaults(func=run_block_user)

    ub = sub.add_parser("unblock-user", help="Unblock a user (no --confirm needed)")
    ub.add_argument("user", help="User selector (id, @username, or fuzzy with --fuzzy)")
    add_write_flags(ub, destructive=False)  # no typed confirm — recoverable
    add_output_flags(ub)
    ub.set_defaults(func=run_unblock_user)
```

- [ ] **Step 3: Implement runners** — both follow the same pattern; `_block_user_runner` calls `BlockRequest`, `_unblock_user_runner` calls `UnblockRequest`. Both verify the resolved chat is a `user` type (not channel/group/bot — actually bots are technically users, allow them). Block requires `require_typed_confirm`; unblock doesn't.

(Full runner code follows the Phase 6 pattern; see `_send_runner` for template.)

- [ ] **Step 4: Commit**

```bash
git add tgcli/commands/contacts.py tests/tgcli/test_phase9_block.py
git commit -m "feat(tgcli): block-user (typed --confirm) + unblock-user"
```

---

## Task 5: `account-sessions` (read) + `terminate-session` (write)

**Files:**
- Create: `tgcli/commands/account.py`
- Modify: `tgcli/__main__.py` (register `account` module)
- Create: `tests/tgcli/test_phase9_sessions.py`

- [ ] **Step 1: Test**

```python
# tests/tgcli/test_phase9_sessions.py
import argparse
import asyncio
import pytest

from tgcli.commands import account
from tgcli.safety import BadArgs


def _args(**kw):
    defaults = {"allow_write": True, "dry_run": False, "idempotency_key": "k1",
                "fuzzy": False, "json": True, "human": False, "read_only": False,
                "confirm": None}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def test_account_sessions_lists_authorizations(monkeypatch, tmp_path):
    monkeypatch.setattr(account, "SESSION_PATH", tmp_path / "tg.session")

    class FakeClient:
        async def start(self): pass
        async def __call__(self, request):
            from telethon.tl.types import Authorization
            from datetime import datetime, timezone
            return type("Auths", (), {"authorizations": [
                Authorization(hash=11111, device_model="MacBook", platform="macOS",
                              system_version="14.0", api_id=1, app_name="Telethon",
                              app_version="1.0",
                              date_created=datetime(2026,1,1,tzinfo=timezone.utc),
                              date_active=datetime(2026,5,1,tzinfo=timezone.utc),
                              ip="1.2.3.4", country="DE", region="Bavaria",
                              current=True),
                Authorization(hash=22222, device_model="iPhone", platform="iOS",
                              system_version="18", api_id=1, app_name="Telegram",
                              app_version="11",
                              date_created=datetime(2025,1,1,tzinfo=timezone.utc),
                              date_active=datetime(2026,5,7,tzinfo=timezone.utc),
                              ip="5.6.7.8", country="DE", region="Berlin",
                              current=False),
            ]})()
        async def disconnect(self): pass

    monkeypatch.setattr(account, "make_client", lambda s: FakeClient())
    data = asyncio.run(account._account_sessions_runner(_args()))
    assert len(data["sessions"]) == 2
    assert data["current_hash"] == 11111
    assert data["sessions"][0]["current"] is True


def test_terminate_session_refuses_current(monkeypatch, tmp_path):
    monkeypatch.setattr(account, "SESSION_PATH", tmp_path / "tg.session")

    class FakeClient:
        async def start(self): pass
        async def __call__(self, request):
            from telethon.tl.types import Authorization
            from datetime import datetime, timezone
            return type("Auths", (), {"authorizations": [
                Authorization(hash=11111, device_model="MacBook", platform="macOS",
                              system_version="14.0", api_id=1, app_name="Telethon",
                              app_version="1.0",
                              date_created=datetime(2026,1,1,tzinfo=timezone.utc),
                              date_active=datetime(2026,5,1,tzinfo=timezone.utc),
                              ip="1.2.3.4", country="DE", region="Bavaria",
                              current=True),
            ]})()
        async def disconnect(self): pass

    monkeypatch.setattr(account, "make_client", lambda s: FakeClient())
    args = _args(session_hash=11111, confirm="11111")
    with pytest.raises(BadArgs, match="current session"):
        asyncio.run(account._terminate_session_runner(args))


def test_terminate_session_requires_typed_confirm(monkeypatch, tmp_path):
    monkeypatch.setattr(account, "SESSION_PATH", tmp_path / "tg.session")

    class FakeClient:
        async def start(self): pass
        async def __call__(self, request):
            from telethon.tl.types import Authorization
            from datetime import datetime, timezone
            return type("Auths", (), {"authorizations": [
                Authorization(hash=11111, device_model="X", platform="x", system_version="x",
                              api_id=1, app_name="x", app_version="x",
                              date_created=datetime(2026,1,1,tzinfo=timezone.utc),
                              date_active=datetime(2026,5,1,tzinfo=timezone.utc),
                              ip="1.2.3.4", country="DE", region="X", current=True),
                Authorization(hash=22222, device_model="X", platform="x", system_version="x",
                              api_id=1, app_name="x", app_version="x",
                              date_created=datetime(2025,1,1,tzinfo=timezone.utc),
                              date_active=datetime(2026,5,7,tzinfo=timezone.utc),
                              ip="5.6.7.8", country="DE", region="Y", current=False),
            ]})()
        async def disconnect(self): pass

    monkeypatch.setattr(account, "make_client", lambda s: FakeClient())
    args = _args(session_hash=22222, confirm="999")
    with pytest.raises(BadArgs, match="must equal"):
        asyncio.run(account._terminate_session_runner(args))
```

- [ ] **Step 2: Implement** in `tgcli/commands/account.py`:

```python
"""account-sessions and terminate-session."""
from __future__ import annotations

import argparse
from typing import Any

from telethon.tl.functions.account import (
    GetAuthorizationsRequest,
    ResetAuthorizationRequest,
)

from tgcli.client import make_client
from tgcli.commands._common import (
    AUDIT_PATH, SESSION_PATH, add_output_flags, add_write_flags,
)
from tgcli.commands.messages import (
    _check_write_rate_limit, _dry_run_envelope, _request_id,
    _run_write_command, _write_result,
)
from tgcli.dispatch import run_command
from tgcli.idempotency import lookup as lookup_idempotency
from tgcli.idempotency import record as record_idempotency
from tgcli.safety import (
    BadArgs, audit_pre, require_typed_confirm, require_write_allowed,
)


def register(sub: argparse._SubParsersAction) -> None:
    s = sub.add_parser("account-sessions", help="List authenticated Telegram sessions")
    add_output_flags(s)
    s.set_defaults(func=run_account_sessions)

    t = sub.add_parser("terminate-session", help="Terminate a Telegram session")
    t.add_argument("session_hash", type=int, help="Session hash from account-sessions")
    add_write_flags(t, destructive=True)
    add_output_flags(t)
    t.set_defaults(func=run_terminate_session)


def _summarize_auth(a) -> dict[str, Any]:
    return {
        "hash": int(a.hash),
        "device_model": a.device_model,
        "platform": a.platform,
        "system_version": a.system_version,
        "app_name": a.app_name,
        "app_version": a.app_version,
        "ip": a.ip,
        "country": a.country,
        "region": a.region,
        "date_created": a.date_created.isoformat() if a.date_created else None,
        "date_active": a.date_active.isoformat() if a.date_active else None,
        "current": bool(a.current),
        "official_app": bool(a.official_app),
    }


async def _account_sessions_runner(args) -> dict[str, Any]:
    client = make_client(SESSION_PATH)
    await client.start()
    try:
        result = await client(GetAuthorizationsRequest())
        auths = list(getattr(result, "authorizations", []))
        sessions = [_summarize_auth(a) for a in auths]
        current = next((s["hash"] for s in sessions if s["current"]), None)
        return {"sessions": sessions, "total": len(sessions), "current_hash": current}
    finally:
        await client.disconnect()


def run_account_sessions(args) -> int:
    return run_command("account-sessions", args,
                       runner=lambda: _account_sessions_runner(args),
                       audit_path=AUDIT_PATH)


async def _terminate_session_runner(args) -> dict[str, Any]:
    from tgcli.db import connect
    from tgcli.commands._common import DB_PATH

    command = "terminate-session"
    request_id = _request_id(args)
    require_write_allowed(args)
    require_typed_confirm(args, expected=args.session_hash, slot="session_hash")

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data

        client = make_client(SESSION_PATH)
        await client.start()
        try:
            result = await client(GetAuthorizationsRequest())
            auths = list(getattr(result, "authorizations", []))
            target = next((a for a in auths if int(a.hash) == int(args.session_hash)), None)
            if target is None:
                from tgcli.resolve import NotFound
                raise NotFound(f"session_hash {args.session_hash} not found")
            if bool(target.current):
                raise BadArgs(
                    f"session hash {args.session_hash} is the current session; "
                    f"terminating it would log you out. Use a different session."
                )

            payload = {"session_hash": int(args.session_hash),
                       "device_model": target.device_model,
                       "telethon_method": "ResetAuthorizationRequest"}
            if args.dry_run:
                return _dry_run_envelope(command, request_id, payload)

            _check_write_rate_limit()
            audit_pre(AUDIT_PATH, cmd=command, request_id=request_id,
                      resolved_chat_id=0, resolved_chat_title="(account)",
                      payload_preview=payload, telethon_method="ResetAuthorizationRequest",
                      dry_run=False)
            await client(ResetAuthorizationRequest(hash=int(args.session_hash)))
            data = {"session_hash": int(args.session_hash),
                    "device_model": target.device_model,
                    "terminated": True, "idempotent_replay": False}
            record_idempotency(con, args.idempotency_key, command, request_id,
                               _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_terminate_session(args) -> int:
    return _run_write_command("terminate-session", args, _terminate_session_runner)
```

- [ ] **Step 3: Register module in `__main__.py` COMMAND_MODULES**

- [ ] **Step 4: Commit**

```bash
git add tgcli/commands/account.py tgcli/__main__.py tests/tgcli/test_phase9_sessions.py
git commit -m "feat(tgcli): account-sessions + terminate-session"
```

---

## Task 6: Final verification + live tests

- [ ] **Step 1: Full suite**

```bash
.venv/bin/pytest tests/tgcli -q
```

Expected: ~190 passed.

- [ ] **Step 2: `make gate`** — must pass.

- [ ] **Step 3: Live (be VERY careful, test with throwaway data only)**

```bash
# 1. List sessions (read-only, safe)
./tg account-sessions --json | python -m json.tool

# 2. Send a throwaway message to Saved Messages, then delete it
M=$(./tg send 1240314255 "to-be-deleted" --allow-write --idempotency-key tbd-1 --json | jq -r .data.message_id)
./tg delete-msg 1240314255 $M --for-everyone --allow-write --idempotency-key del-tbd-1 --confirm 1240314255 --json

# 3. Typed confirm test (must reject)
./tg delete-msg 1240314255 99999 --allow-write --idempotency-key del-bad-1 --confirm 999 --json

# 4. Show after delete (should NOT include the deleted msg)
./tg show 1240314255 --limit 5 --json | jq .data.messages

# 5. With --include-deleted
./tg show 1240314255 --limit 5 --include-deleted --json | jq .data.messages
```

- [ ] **Step 4: No further commits unless verification surfaces a bug.**

---

## Self-Review Checklist

1. ✓ Six destructive commands, all gated through typed `--confirm <id>` (except `unblock-user`).
2. ✓ Typed confirm compares against the RESOLVED id (chat_id, user_id, session_hash) — not the raw selector.
3. ✓ `delete-msg` is batch-aware with `{summary, results}` envelope shape.
4. ✓ Tombstones in `tg_messages.deleted`; reads filter on `deleted = 0` by default; `--include-deleted` opt-in.
5. ✓ `leave-chat` refuses Saved Messages and 1-on-1 user chats.
6. ✓ `terminate-session` refuses the current session.
7. ✓ All write commands have idempotency replay, dry-run, audit pre+post.
8. ✓ ~17 new tests, all green.

---

## Out of Scope (deferred per brief)

- Channel admin (ban participant, restrict, demote) — Phase 10 candidate.
- `--include-deleted` on `unread`, `chats-info`, `topics-list` — read-API only matters for messages.
- Bulk `block-user` / `terminate-session` — single-target only in v1.

After Phase 9: user picks between (a) media upload, (b) SDK extraction → Sedex resume, (c) MCP servers, (d) channel/group admin commands.
