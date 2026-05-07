# Phase 6.2 - Dialog Folder Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-05-07

**Author:** Codex

**Status:** Draft

**Prerequisite:** Phase 6.1 complete with `122 tests collected`; current topic commands (`topics-list`, `topic-create`, `topic-edit`, `topic-pin`, `topic-unpin`) and message topic routing remain green before starting.

**Goal:** Add Phase 6.2 dialog folder support: `folders-list`, `folder-show`, `folder-create`, `folder-edit`, `folder-delete`, `folder-add-chat`, `folder-remove-chat`, and `folders-reorder`.

**Architecture:**
- Keep the flat argparse surface and register the eight folder commands in `tgcli/commands/chats.py` beside the existing chat/topic commands.
- Folder reads call Telethon live request APIs and enrich peers from the local `tg_chats` cache; folder writes reuse the Phase 6 safety pipeline with `--allow-write`, `--dry-run`, `--idempotency-key`, fuzzy gating where chat selectors are accepted, rate limiting, pre-call audit, and `run_command()` post-call audit.
- Telethon folder requests are covered with monkeypatched async fake clients and request-shape assertions; subprocess smoke tests cover parser surfaces, write-gate paths, and dry-run paths without live Telegram calls.

**Tech Stack:** Python 3.12 stdlib (`argparse`, `asyncio`, `json`, `sqlite3`, `pathlib`), Telethon 1.43.2 already present in the project, existing pytest. **No new third-party deps.**

**Backwards compatibility:** Current Phase 6.1 suite is `122 tests collected`. Phase 6.2 targets 15-20 unit tests plus 3 smoke tests, so the expected final count is `140-145 tests collected`.

---

## Existing Code Map

| Area | Current line references | Phase 6.2 use |
|---|---:|---|
| Phase 6.1 structural template | `docs/superpowers/plans/2026-05-07-tg-agent-cli-phase-6-1.md:1-24`, `26-80`, `82-1435`, `1439-1525` | Match header, code map, file table, design decisions, task checklist format, verification, commit sequence, checklist, and out-of-scope sections |
| Current chat parser surface | `tgcli/commands/chats.py:47-103` | Add `folders-list`, `folder-show`, `folder-create`, `folder-edit`, `folder-delete`, `folder-add-chat`, `folder-remove-chat`, and `folders-reorder` beside existing discover/unread/info/topic parsers |
| Current topic imports and parser pattern | `tgcli/commands/chats.py:8-17`, `61-103` | Extend the existing Telethon import group and flat command registration style instead of creating a new command module |
| Current topic read lifecycle | `tgcli/commands/chats.py:157-201` | Reuse `make_client(SESSION_PATH)`, `await client.start()`, live request, `finally: await client.disconnect()`, and `run_command()` wrapping for read-only folder commands |
| Current topic write lifecycle | `tgcli/commands/chats.py:226-289`, `292-402` | Reuse write ordering: request id, write gate, idempotency lookup, DB resolution, dry-run short-circuit, rate limit, `audit_pre()`, Telethon call, idempotency record |
| Current cached chat info resolver | `tgcli/commands/chats.py:496-559` | Use `tg_chats.title` and `tg_chats.type` to enrich folder peer lists in `folder-show`; missing cache rows become `cached: false` |
| Current message parser surface | `tgcli/commands/messages.py:89-148` | Confirms flat hyphenated write command naming already used by `send`, `edit-msg`, `forward`, `pin-msg`, `unpin-msg`, `react`, and `mark-read` |
| Current message write helpers | `tgcli/commands/messages.py:619-673` | Reuse `_request_id()`, `_check_write_rate_limit()`, `_dry_run_envelope()`, `_resolve_write_chat()`, `_run_write_command()`, and `_write_result()` |
| Current send and forward idempotency shape | `tgcli/commands/messages.py:676-748`, `817-909` | Match replay behavior: `lookup_idempotency()` returns cached envelope data and skips the Telethon call |
| Common write flags | `tgcli/commands/_common.py:35-48` | Use existing `--allow-write`, `--dry-run`, `--idempotency-key`, and `--fuzzy` flags for folder writes; add a folder-local requirement that `--idempotency-key` is non-empty |
| Safety gates and audit | `tgcli/safety.py:37-75`, `99-127` | Reuse write gate, fuzzy selector gate, process-local limiter, and pre-call audit |
| Idempotency helpers | `tgcli/idempotency.py:12-57` | Reuse lookup/record mechanism; `folder-create` records the result envelope including the new `folder_id`; other folder writes skip API calls on replay |
| Dispatch envelope and request id | `tgcli/dispatch.py:89-127` | Runners receive `args._request_id`; success/failure envelopes and final audit are produced by `run_command()` |
| Resolver behavior | `tgcli/resolve.py:41-82` | `folder-add-chat` and `folder-remove-chat` resolve chat selectors with `resolve_chat_db()` through `_resolve_write_chat()` so title matches require `--fuzzy`; `folder-create/edit --include-chat/--exclude-chat` take integer ids only |
| SQLite cache schema | `tgcli/db.py:14-75` | `folder-show` enrichment reads `tg_chats(chat_id, type, title)` and idempotency persists in `tg_idempotency` |
| Existing smoke test patterns | `tests/tgcli/test_cli_smoke.py:284-329`, `332-457`, `459-557` | Append parser, write-gate, and dry-run subprocess tests matching Phase 6 and Phase 6.1 style |
| Telethon folder read request | `.venv/lib/python3.12/site-packages/telethon/tl/functions/messages.py:2762-2778` | `GetDialogFiltersRequest()` has no constructor args and returns dialog filters |
| Telethon folder update request | `.venv/lib/python3.12/site-packages/telethon/tl/functions/messages.py:10459-10494` | `UpdateDialogFilterRequest(id: int, filter: Optional[TypeDialogFilter]=None)` updates or deletes a folder |
| Telethon folder reorder request | `.venv/lib/python3.12/site-packages/telethon/tl/functions/messages.py:10497-10527` | `UpdateDialogFiltersOrderRequest(order: List[int])` reorders folders |
| Telethon `DialogFilter` title type | `.venv/lib/python3.12/site-packages/telethon/tl/types/__init__.py:8372-8428` | `DialogFilter.__init__` expects `title: TypeTextWithEntities`, and `_bytes()` calls `self.title._bytes()`, so pass `TextWithEntities`, not `str` |
| Telethon folder variants | `.venv/lib/python3.12/site-packages/telethon/tl/types/__init__.py:8475-8545`, `8548-8564` | Read commands must classify `DialogFilterChatlist` and `DialogFilterDefault`; write commands mutate only custom `DialogFilter` |
| Telethon `TextWithEntities` constructor | `.venv/lib/python3.12/site-packages/telethon/tl/types/__init__.py:40977-41011` | Build titles with `TextWithEntities(text=title, entities=[])` |

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| tgcli/commands/chats.py | modify | Add 8 folder commands beside existing topic commands |
| tests/tgcli/test_phase62_folders.py | create | Unit tests for all 8 commands + idempotency + dry-run |
| tests/tgcli/test_cli_smoke.py | modify | Append subprocess smoke tests for parser surfaces + write-gate |

---

## Design Decisions

1. **Naming: flat hyphenated names.** Use `folders-list`, `folder-show`, `folder-create`, `folder-edit`, `folder-delete`, `folder-add-chat`, `folder-remove-chat`, and `folders-reorder`. This matches the current flat command namespace in `tgcli/commands/chats.py:47-103` and `tgcli/commands/messages.py:89-148`.

2. **Title encoding: `TextWithEntities`, not `str`.** In the installed Telethon version, `DialogFilter.__init__` declares `title: TypeTextWithEntities` at `.venv/lib/python3.12/site-packages/telethon/tl/types/__init__.py:8376`, and serialization calls `self.title._bytes()` at `.venv/lib/python3.12/site-packages/telethon/tl/types/__init__.py:8423`. `TextWithEntities.__init__(text: str, entities: List[TypeMessageEntity])` is defined at `.venv/lib/python3.12/site-packages/telethon/tl/types/__init__.py:40981`, so Phase 6.2 must construct `TextWithEntities(text=title, entities=[])`.

3. **Chat selector split.** `folder-add-chat` and `folder-remove-chat` accept a chat selector and go through `_resolve_write_chat()`, which calls `require_explicit_or_fuzzy()` before `resolve_chat_db()` at `tgcli/commands/messages.py:656-659`. `folder-create` and `folder-edit` accept `--include-chat` and `--exclude-chat` as integer chat ids only, with no fuzzy resolution in v1.

4. **Include/exclude peers.** Every integer chat id passed through `--include-chat` or `--exclude-chat` is converted with `await client.get_input_peer(chat_id)` before building `DialogFilter`. This keeps Telethon request objects typed as `TypeInputPeer`.

5. **Idempotency for `folder-create`.** Record the normal success envelope after the Telethon update returns, including `folder_id`, `title`, flags, and peer counts. Replaying the same key returns cached data with `idempotent_replay: true` and makes no Telethon call.

6. **Idempotency for edit/delete/add-chat/remove-chat/reorder.** Each write runner checks `lookup_idempotency()` before any live Telethon work. On cache hit, it returns cached data with `idempotent_replay: true` and skips the API call.

7. **Folder id `0` is reserved.** `folders-list` includes id `0` with `is_default: true` when Telegram returns `DialogFilterDefault`; `folder-delete 0` raises `BadArgs("folder id 0 is reserved and cannot be deleted")`.

8. **`folder-show` peer enrichment.** Each peer in `pinned_peers`, `include_peers`, and `exclude_peers` is returned with extracted id fields plus `cached: true`, `title`, and `type` when `tg_chats` has a matching `chat_id`. Missing cache rows return `cached: false`.

9. **No live Telethon tests.** Unit tests use fake clients whose `__call__(request)` records request objects and returns stub filters/updates. Subprocess smoke tests stop at parser, write-gate, and dry-run paths.

---

## Task 1: Parser surfaces and shared folder helpers

**Goal:** Add the Phase 6.2 argparse surface, Telethon imports, and pure helper functions before implementing live behavior.

**Files:**
- Modify: `tgcli/commands/chats.py`
- Create: `tests/tgcli/test_phase62_folders.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Write failing parser/helper unit tests**

Create `tests/tgcli/test_phase62_folders.py`:

```python
import argparse
import asyncio

import pytest
from telethon.tl.types import DialogFilter, DialogFilterDefault, TextWithEntities

from tgcli.commands import chats
from tgcli.db import connect
from tgcli.safety import BadArgs


class FakeInputPeer:
    def __init__(self, peer_id):
        self.peer_id = int(peer_id)

    def to_dict(self):
        return {"_": "FakeInputPeer", "peer_id": self.peer_id}


def _seed_chat(path):
    con = connect(path)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "supergroup", "Alpha Forum", "alpha_forum"),
    )
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (456, "user", "Beta User", "beta_user"),
    )
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (789, "group", "Gamma Group", "gamma_group"),
    )
    con.commit()
    con.close()


def _title(text):
    return TextWithEntities(text=text, entities=[])


def _filter(folder_id=2, title="Ops", include=None, exclude=None):
    return DialogFilter(
        id=folder_id,
        title=_title(title),
        pinned_peers=[],
        include_peers=list(include or []),
        exclude_peers=list(exclude or []),
        contacts=True,
        non_contacts=False,
        groups=True,
        broadcasts=False,
        bots=False,
        exclude_muted=True,
        exclude_read=False,
        exclude_archived=False,
        emoticon="🗂",
    )


def _args(**kw):
    defaults = {
        "allow_write": True,
        "dry_run": False,
        "idempotency_key": "phase62-key",
        "fuzzy": False,
        "json": True,
        "human": False,
        "include_chat": [],
        "exclude_chat": [],
        "clear_include": False,
        "clear_exclude": False,
        "contacts": None,
        "non_contacts": None,
        "groups": None,
        "broadcasts": None,
        "bots": None,
        "exclude_muted": None,
        "exclude_read": None,
        "exclude_archived": None,
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def test_folder_title_helpers_use_text_with_entities():
    title = chats._folder_title("Ops")
    assert isinstance(title, TextWithEntities)
    assert title.text == "Ops"
    assert title.entities == []
    assert chats._folder_title_text(title) == "Ops"


def test_folder_title_rejects_empty_string():
    with pytest.raises(BadArgs, match="folder title cannot be empty"):
        chats._folder_title("   ")


def test_folder_summary_marks_default_and_counts_peers():
    default = chats._folder_summary(DialogFilterDefault())
    assert default["folder_id"] == 0
    assert default["is_default"] is True
    assert default["type"] == "default"

    summary = chats._folder_summary(
        _filter(include=[FakeInputPeer(123), FakeInputPeer(456)], exclude=[FakeInputPeer(789)])
    )
    assert summary["folder_id"] == 2
    assert summary["title"] == "Ops"
    assert summary["emoticon"] == "🗂"
    assert summary["include_peer_count"] == 2
    assert summary["exclude_peer_count"] == 1
    assert summary["flags"]["contacts"] is True
    assert summary["flags"]["groups"] is True
    assert summary["flags"]["exclude_muted"] is True
```

- [ ] **Step 2: Add failing smoke tests for help surfaces and write gates**

Append to `tests/tgcli/test_cli_smoke.py`:

```python
def test_phase62_folder_help_surfaces():
    read_commands = ["folders-list", "folder-show"]
    write_commands = [
        "folder-create",
        "folder-edit",
        "folder-delete",
        "folder-add-chat",
        "folder-remove-chat",
        "folders-reorder",
    ]
    for command in [*read_commands, *write_commands]:
        result = _subprocess.run(
            [str(PYTHON), "-m", "tgcli", command, "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"command: {command} stderr: {result.stderr}"
        assert "usage:" in result.stdout.lower()

    for command in write_commands:
        result = _subprocess.run(
            [str(PYTHON), "-m", "tgcli", command, "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert "--allow-write" in result.stdout
        assert "--dry-run" in result.stdout
        assert "--idempotency-key" in result.stdout
        assert "--fuzzy" in result.stdout


def test_phase62_folder_write_gate_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "supergroup", "Alpha Forum", "alpha_forum"),
    )
    con.commit()
    con.close()

    env = {
        **_os.environ,
        "TG_API_ID": "1",
        "TG_API_HASH": "x",
        "TG_DB_PATH": str(db),
        "TG_AUDIT_PATH": str(tmp_path / "audit.log"),
    }
    commands = [
        [str(PYTHON), "-m", "tgcli", "folder-create", "Ops", "--include-chat", "123", "--json"],
        [str(PYTHON), "-m", "tgcli", "folder-edit", "2", "--title", "Ops 2", "--json"],
        [str(PYTHON), "-m", "tgcli", "folder-delete", "2", "--json"],
        [str(PYTHON), "-m", "tgcli", "folder-add-chat", "2", "@alpha_forum", "--json"],
        [str(PYTHON), "-m", "tgcli", "folder-remove-chat", "2", "@alpha_forum", "--json"],
        [str(PYTHON), "-m", "tgcli", "folders-reorder", "2", "3", "--json"],
    ]
    for command in commands:
        result = _subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 6, f"command: {command} stderr: {result.stderr}"
        payload = _json.loads(result.stdout)
        assert payload["error"]["code"] == "WRITE_DISALLOWED"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase62_folders.py::test_folder_title_helpers_use_text_with_entities tests/tgcli/test_phase62_folders.py::test_folder_title_rejects_empty_string tests/tgcli/test_phase62_folders.py::test_folder_summary_marks_default_and_counts_peers tests/tgcli/test_cli_smoke.py::test_phase62_folder_help_surfaces tests/tgcli/test_cli_smoke.py::test_phase62_folder_write_gate_smoke -q
```

Expected: FAIL because folder helpers and parser registrations do not exist.

- [ ] **Step 4: Add Telethon imports and parser registrations**

In `tgcli/commands/chats.py`, extend the Telethon imports:

```python
from telethon.tl.functions.messages import (
    CreateForumTopicRequest,
    EditForumTopicRequest,
    GetDialogFiltersRequest,
    GetForumTopicsRequest,
    UpdateDialogFilterRequest,
    UpdateDialogFiltersOrderRequest,
    UpdatePinnedForumTopicRequest,
)
from telethon.tl.types import DialogFilter, DialogFilterChatlist, DialogFilterDefault, TextWithEntities
```

Add these parser helper functions above `register()`:

```python
_FOLDER_BOOL_FIELDS = (
    "contacts",
    "non_contacts",
    "groups",
    "broadcasts",
    "bots",
    "exclude_muted",
    "exclude_read",
    "exclude_archived",
)


def _folder_flag_name(field: str) -> str:
    return field.replace("_", "-")


def _add_folder_create_bool_flags(parser: argparse.ArgumentParser) -> None:
    for field in _FOLDER_BOOL_FIELDS:
        parser.add_argument(
            f"--{_folder_flag_name(field)}",
            dest=field,
            action="store_true",
            default=False,
        )


def _add_folder_edit_bool_flags(parser: argparse.ArgumentParser) -> None:
    for field in _FOLDER_BOOL_FIELDS:
        flag = _folder_flag_name(field)
        group = parser.add_mutually_exclusive_group()
        group.add_argument(f"--{flag}", dest=field, action="store_true", default=None)
        group.add_argument(f"--no-{flag}", dest=field, action="store_false")
```

Add the folder parsers after `topic-unpin` in `tgcli/commands/chats.py:98-103`:

```python
    folders = sub.add_parser("folders-list", help="List Telegram dialog folders")
    folders.add_argument("--query", default=None, help="Filter folders by title substring")
    add_output_flags(folders)
    folders.set_defaults(func=run_folders_list)

    folder_show = sub.add_parser("folder-show", help="Show one Telegram dialog folder")
    folder_show.add_argument("folder_id", type=int, help="Folder id")
    add_output_flags(folder_show)
    folder_show.set_defaults(func=run_folder_show)

    folder_create = sub.add_parser("folder-create", help="Create a Telegram dialog folder")
    folder_create.add_argument("title", help="Folder title")
    folder_create.add_argument("--emoticon", default=None, help="Folder emoji")
    folder_create.add_argument("--include-chat", type=int, action="append", default=[], help="Integer chat_id to include")
    folder_create.add_argument("--exclude-chat", type=int, action="append", default=[], help="Integer chat_id to exclude")
    _add_folder_create_bool_flags(folder_create)
    add_write_flags(folder_create, destructive=False)
    add_output_flags(folder_create)
    folder_create.set_defaults(func=run_folder_create)

    folder_edit = sub.add_parser("folder-edit", help="Edit a Telegram dialog folder")
    folder_edit.add_argument("folder_id", type=int, help="Folder id")
    folder_edit.add_argument("--title", default=None, help="New folder title")
    folder_edit.add_argument("--emoticon", default=None, help="New folder emoji")
    folder_edit.add_argument("--clear-include", action="store_true", help="Clear include peers before adding")
    folder_edit.add_argument("--clear-exclude", action="store_true", help="Clear exclude peers before adding")
    folder_edit.add_argument("--include-chat", type=int, action="append", default=[], help="Integer chat_id to include")
    folder_edit.add_argument("--exclude-chat", type=int, action="append", default=[], help="Integer chat_id to exclude")
    _add_folder_edit_bool_flags(folder_edit)
    add_write_flags(folder_edit, destructive=False)
    add_output_flags(folder_edit)
    folder_edit.set_defaults(func=run_folder_edit)

    folder_delete = sub.add_parser("folder-delete", help="Delete a Telegram dialog folder")
    folder_delete.add_argument("folder_id", type=int, help="Folder id")
    add_write_flags(folder_delete, destructive=False)
    add_output_flags(folder_delete)
    folder_delete.set_defaults(func=run_folder_delete)

    folder_add = sub.add_parser("folder-add-chat", help="Add a chat to a Telegram dialog folder")
    folder_add.add_argument("folder_id", type=int, help="Folder id")
    folder_add.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    add_write_flags(folder_add, destructive=False)
    add_output_flags(folder_add)
    folder_add.set_defaults(func=run_folder_add_chat)

    folder_remove = sub.add_parser("folder-remove-chat", help="Remove a chat from a Telegram dialog folder")
    folder_remove.add_argument("folder_id", type=int, help="Folder id")
    folder_remove.add_argument("chat", help="Chat id, @username, or fuzzy title with --fuzzy")
    add_write_flags(folder_remove, destructive=False)
    add_output_flags(folder_remove)
    folder_remove.set_defaults(func=run_folder_remove_chat)

    folders_reorder = sub.add_parser("folders-reorder", help="Reorder Telegram dialog folders")
    folders_reorder.add_argument("folder_ids", type=int, nargs="+", help="Folder ids in desired order")
    add_write_flags(folders_reorder, destructive=False)
    add_output_flags(folders_reorder)
    folders_reorder.set_defaults(func=run_folders_reorder)
```

- [ ] **Step 5: Add shared folder helpers and temporary runner stubs**

Add below `_topic_edit_mutations()`:

```python
def _folder_title(value: str) -> TextWithEntities:
    text = str(value).strip()
    if text == "":
        raise BadArgs("folder title cannot be empty")
    return TextWithEntities(text=text, entities=[])


def _folder_title_text(value) -> str:
    if isinstance(value, TextWithEntities):
        return value.text
    text = getattr(value, "text", None)
    if text is not None:
        return str(text)
    return str(value or "")


def _folder_type(folder) -> str:
    if isinstance(folder, DialogFilterDefault):
        return "default"
    if isinstance(folder, DialogFilterChatlist):
        return "chatlist"
    if isinstance(folder, DialogFilter):
        return "filter"
    return type(folder).__name__


def _folder_id(folder) -> int:
    return int(getattr(folder, "id", 0) or 0)


def _peer_count(folder, attr: str) -> int:
    return len(getattr(folder, attr, None) or [])


def _folder_flags(folder) -> dict[str, bool]:
    return {field: bool(getattr(folder, field, False)) for field in _FOLDER_BOOL_FIELDS}


def _folder_summary(folder) -> dict[str, Any]:
    return {
        "folder_id": _folder_id(folder),
        "title": "All chats" if isinstance(folder, DialogFilterDefault) else _folder_title_text(getattr(folder, "title", "")),
        "emoticon": getattr(folder, "emoticon", None),
        "type": _folder_type(folder),
        "is_default": isinstance(folder, DialogFilterDefault) or _folder_id(folder) == 0,
        "is_chatlist": isinstance(folder, DialogFilterChatlist),
        "pinned_peer_count": _peer_count(folder, "pinned_peers"),
        "include_peer_count": _peer_count(folder, "include_peers"),
        "exclude_peer_count": _peer_count(folder, "exclude_peers"),
        "flags": _folder_flags(folder),
    }


def _folders_from_result(result) -> list[Any]:
    if isinstance(result, (list, tuple)):
        return list(result)
    for attr in ("filters", "dialog_filters", "folders"):
        value = getattr(result, attr, None)
        if value is not None:
            return list(value)
    return []


def _matching_folder(filters: list[Any], folder_id: int):
    for folder in filters:
        if _folder_id(folder) == int(folder_id):
            return folder
    raise NotFound(f"folder {folder_id} not found")


def _require_folder_write_key(args) -> None:
    if not getattr(args, "idempotency_key", None):
        raise BadArgs("--idempotency-key is required for folder write commands")


def _ensure_mutable_folder(folder, folder_id: int) -> DialogFilter:
    if not isinstance(folder, DialogFilter):
        raise BadArgs(f"folder {folder_id} is not a mutable custom folder")
    return folder


def _folder_edit_mutations(args) -> dict[str, Any]:
    mutations: dict[str, Any] = {}
    if getattr(args, "title", None) is not None:
        mutations["title"] = _folder_title(args.title)
    if getattr(args, "emoticon", None) is not None:
        mutations["emoticon"] = args.emoticon
    for field in _FOLDER_BOOL_FIELDS:
        value = getattr(args, field, None)
        if value is not None:
            mutations[field] = bool(value)
    if getattr(args, "clear_include", False):
        mutations["clear_include"] = True
    if getattr(args, "clear_exclude", False):
        mutations["clear_exclude"] = True
    if getattr(args, "include_chat", None):
        mutations["include_chat"] = list(args.include_chat)
    if getattr(args, "exclude_chat", None):
        mutations["exclude_chat"] = list(args.exclude_chat)
    if not mutations:
        raise BadArgs("nothing to edit")
    return mutations


def _folder_surface_unavailable(command: str) -> dict[str, Any]:
    raise BadArgs(f"{command} runner is defined by a later Phase 6.2 task")


async def _folder_write_surface_runner(args, *, command: str) -> dict[str, Any]:
    require_write_allowed(args)
    _require_folder_write_key(args)
    return _folder_surface_unavailable(command)


def run_folders_list(args) -> int:
    return run_command(
        "folders-list",
        args,
        runner=lambda: _folder_surface_unavailable("folders-list"),
        human_formatter=_write_human,
        audit_path=AUDIT_PATH,
    )


def run_folder_show(args) -> int:
    return run_command(
        "folder-show",
        args,
        runner=lambda: _folder_surface_unavailable("folder-show"),
        human_formatter=_write_human,
        audit_path=AUDIT_PATH,
    )


def run_folder_create(args) -> int:
    return _run_write_command(
        "folder-create",
        args,
        lambda args: _folder_write_surface_runner(args, command="folder-create"),
    )


def run_folder_edit(args) -> int:
    return _run_write_command(
        "folder-edit",
        args,
        lambda args: _folder_write_surface_runner(args, command="folder-edit"),
    )


def run_folder_delete(args) -> int:
    return _run_write_command(
        "folder-delete",
        args,
        lambda args: _folder_write_surface_runner(args, command="folder-delete"),
    )


def run_folder_add_chat(args) -> int:
    return _run_write_command(
        "folder-add-chat",
        args,
        lambda args: _folder_write_surface_runner(args, command="folder-add-chat"),
    )


def run_folder_remove_chat(args) -> int:
    return _run_write_command(
        "folder-remove-chat",
        args,
        lambda args: _folder_write_surface_runner(args, command="folder-remove-chat"),
    )


def run_folders_reorder(args) -> int:
    return _run_write_command(
        "folders-reorder",
        args,
        lambda args: _folder_write_surface_runner(args, command="folders-reorder"),
    )
```

- [ ] **Step 6: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase62_folders.py::test_folder_title_helpers_use_text_with_entities tests/tgcli/test_phase62_folders.py::test_folder_title_rejects_empty_string tests/tgcli/test_phase62_folders.py::test_folder_summary_marks_default_and_counts_peers tests/tgcli/test_cli_smoke.py::test_phase62_folder_help_surfaces tests/tgcli/test_cli_smoke.py::test_phase62_folder_write_gate_smoke -q
```

Expected: PASS. The write-gate smoke passes because `run_command()` maps `WriteDisallowed` before the temporary runner stubs are reached.

- [ ] **Step 7: Run full suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: PASS with about `127 tests collected`.

- [ ] **Step 8: Commit**

```bash
git add tgcli/commands/chats.py tests/tgcli/test_phase62_folders.py tests/tgcli/test_cli_smoke.py
git commit -m "feat(tgcli): add folder parser surfaces"
```

---

## Task 2: `tg folders-list` and `tg folder-show`

**Goal:** Implement read-only folder listing and full folder inspection with cache-enriched peers.

**Files:**
- Modify: `tgcli/commands/chats.py`
- Modify: `tests/tgcli/test_phase62_folders.py`

- [ ] **Step 1: Add failing unit tests for read commands**

Append to `tests/tgcli/test_phase62_folders.py`:

```python
def test_folders_list_uses_get_dialog_filters_request(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.requests = []

        async def start(self):
            pass

        async def __call__(self, request):
            self.requests.append(request)
            return [
                DialogFilterDefault(),
                _filter(folder_id=2, title="Ops", include=[FakeInputPeer(123)]),
                _filter(folder_id=3, title="Family", include=[FakeInputPeer(456)]),
            ]

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    data = asyncio.run(chats._folders_list_runner(_args(query="op")))

    assert [folder["folder_id"] for folder in data["folders"]] == [2]
    assert data["folders"][0]["title"] == "Ops"
    request = fake.requests[0]
    assert request.__class__.__name__ == "GetDialogFiltersRequest"


def test_folder_show_enriches_peers_from_cache(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        async def start(self):
            pass

        async def __call__(self, request):
            return [
                DialogFilterDefault(),
                _filter(
                    folder_id=2,
                    title="Ops",
                    include=[FakeInputPeer(123), FakeInputPeer(999)],
                    exclude=[FakeInputPeer(456)],
                ),
            ]

        async def disconnect(self):
            pass

    monkeypatch.setattr(chats, "make_client", lambda session_path: FakeClient())
    data = asyncio.run(chats._folder_show_runner(_args(folder_id=2)))

    assert data["folder"]["folder_id"] == 2
    assert data["folder"]["include_peers"][0]["peer_id"] == 123
    assert data["folder"]["include_peers"][0]["cached"] is True
    assert data["folder"]["include_peers"][0]["title"] == "Alpha Forum"
    assert data["folder"]["include_peers"][0]["type"] == "supergroup"
    assert data["folder"]["include_peers"][1]["peer_id"] == 999
    assert data["folder"]["include_peers"][1]["cached"] is False
    assert data["folder"]["exclude_peers"][0]["title"] == "Beta User"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase62_folders.py::test_folders_list_uses_get_dialog_filters_request tests/tgcli/test_phase62_folders.py::test_folder_show_enriches_peers_from_cache -q
```

Expected: FAIL because `_folders_list_runner()` and `_folder_show_runner()` do not exist.

- [ ] **Step 3: Add peer enrichment and read runners**

Add below the helper block from Task 1:

```python
def _peer_id_value(peer) -> int | None:
    for attr in ("peer_id", "user_id", "chat_id", "channel_id", "id"):
        value = getattr(peer, attr, None)
        if value is not None:
            return int(value)
    return None


def _peer_summary(con, peer) -> dict[str, Any]:
    peer_id = _peer_id_value(peer)
    row = None
    if peer_id is not None:
        row = con.execute(
            "SELECT title, type FROM tg_chats WHERE chat_id = ?",
            (peer_id,),
        ).fetchone()
    data = {
        "peer_id": peer_id,
        "peer_type": type(peer).__name__,
        "cached": row is not None,
        "title": row[0] if row else None,
        "type": row[1] if row else None,
    }
    return data


def _folder_detail(folder, con) -> dict[str, Any]:
    summary = _folder_summary(folder)
    summary["pinned_peers"] = [_peer_summary(con, peer) for peer in (getattr(folder, "pinned_peers", None) or [])]
    summary["include_peers"] = [_peer_summary(con, peer) for peer in (getattr(folder, "include_peers", None) or [])]
    summary["exclude_peers"] = [_peer_summary(con, peer) for peer in (getattr(folder, "exclude_peers", None) or [])]
    return summary


async def _fetch_dialog_filters() -> list[Any]:
    client = make_client(SESSION_PATH)
    await client.start()
    try:
        result = await client(GetDialogFiltersRequest())
        return _folders_from_result(result)
    finally:
        await client.disconnect()


async def _folders_list_runner(args) -> dict[str, Any]:
    filters = await _fetch_dialog_filters()
    query = getattr(args, "query", None)
    summaries = [_folder_summary(folder) for folder in filters]
    if query:
        needle = str(query).casefold()
        summaries = [folder for folder in summaries if needle in str(folder["title"]).casefold()]
    return {"query": query, "folders": summaries}


async def _folder_show_runner(args) -> dict[str, Any]:
    filters = await _fetch_dialog_filters()
    folder = _matching_folder(filters, int(args.folder_id))
    con = connect_readonly(DB_PATH)
    try:
        detail = _folder_detail(folder, con)
    finally:
        con.close()
    return {"folder": detail}


def _folders_human(data: dict) -> None:
    for folder in data["folders"]:
        default = " default" if folder["is_default"] else ""
        print(f"{folder['folder_id']:>4}  {folder['title']}  {folder['type']}{default}")


def _folder_show_human(data: dict) -> None:
    print(json.dumps(data["folder"], ensure_ascii=False, indent=2, default=str))


def run_folders_list(args) -> int:
    return run_command(
        "folders-list",
        args,
        runner=lambda: _folders_list_runner(args),
        human_formatter=_folders_human,
        audit_path=AUDIT_PATH,
    )


def run_folder_show(args) -> int:
    return run_command(
        "folder-show",
        args,
        runner=lambda: _folder_show_runner(args),
        human_formatter=_folder_show_human,
        audit_path=AUDIT_PATH,
    )
```

Remove the temporary `run_folders_list()` and `run_folder_show()` stubs from Task 1.

- [ ] **Step 4: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase62_folders.py::test_folders_list_uses_get_dialog_filters_request tests/tgcli/test_phase62_folders.py::test_folder_show_enriches_peers_from_cache -q
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: PASS with about `129 tests collected`.

- [ ] **Step 6: Commit**

```bash
git add tgcli/commands/chats.py tests/tgcli/test_phase62_folders.py
git commit -m "feat(tgcli): list and show dialog folders"
```

---

## Task 3: `tg folder-create`

**Goal:** Implement `folder-create` with `UpdateDialogFilterRequest`, `DialogFilter`, `TextWithEntities`, input peer conversion, dry-run, audit, rate limiting, and idempotency replay.

**Files:**
- Modify: `tgcli/commands/chats.py`
- Modify: `tests/tgcli/test_phase62_folders.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Add failing unit and smoke tests for create**

Append to `tests/tgcli/test_phase62_folders.py`:

```python
def test_folder_create_builds_dialog_filter_and_replays_idempotency(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.requests = []
            self.input_peer_calls = []

        async def start(self):
            pass

        async def __call__(self, request):
            self.requests.append(request)
            if request.__class__.__name__ == "GetDialogFiltersRequest":
                return [DialogFilterDefault(), _filter(folder_id=2, title="Existing")]
            return True

        async def get_input_peer(self, chat_id):
            self.input_peer_calls.append(chat_id)
            return FakeInputPeer(chat_id)

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    args = _args(
        title="Ops",
        emoticon="🗂",
        include_chat=[123],
        exclude_chat=[456],
        contacts=True,
        groups=True,
        exclude_muted=True,
        idempotency_key="folder-create-1",
    )

    first = asyncio.run(chats._folder_create_runner(args))
    second = asyncio.run(chats._folder_create_runner(args))

    assert first["folder_id"] == 3
    assert first["title"] == "Ops"
    assert first["include_peer_count"] == 1
    assert first["exclude_peer_count"] == 1
    assert second["folder_id"] == 3
    assert second["idempotent_replay"] is True
    assert [request.__class__.__name__ for request in fake.requests] == [
        "GetDialogFiltersRequest",
        "UpdateDialogFilterRequest",
    ]
    update = fake.requests[1]
    assert update.id == 3
    assert isinstance(update.filter.title, TextWithEntities)
    assert update.filter.title.text == "Ops"
    assert update.filter.emoticon == "🗂"
    assert update.filter.contacts is True
    assert update.filter.groups is True
    assert update.filter.exclude_muted is True
    assert fake.input_peer_calls == [123, 456]


def test_folder_create_dry_run_does_not_call_telethon(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    def fail_make_client(session_path):
        raise AssertionError("dry-run must not create Telethon client")

    monkeypatch.setattr(chats, "make_client", fail_make_client)
    data = asyncio.run(chats._folder_create_runner(_args(
        title="Ops",
        include_chat=[123],
        dry_run=True,
        idempotency_key="folder-create-dry-run",
    )))

    assert data["dry_run"] is True
    assert data["payload"]["title"] == "Ops"
    assert data["payload"]["include_chat_ids"] == [123]
```

Append to `tests/tgcli/test_cli_smoke.py`:

```python
def test_phase62_folder_create_dry_run_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "supergroup", "Alpha Forum", "alpha_forum"),
    )
    con.commit()
    con.close()

    env = {
        **_os.environ,
        "TG_API_ID": "1",
        "TG_API_HASH": "x",
        "TG_DB_PATH": str(db),
        "TG_AUDIT_PATH": str(tmp_path / "audit.log"),
    }
    result = _subprocess.run(
        [
            str(PYTHON),
            "-m",
            "tgcli",
            "folder-create",
            "Ops",
            "--include-chat",
            "123",
            "--allow-write",
            "--idempotency-key",
            "phase62-folder-create-dry-run",
            "--dry-run",
            "--json",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    payload = _json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["payload"]["include_chat_ids"] == [123]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase62_folders.py::test_folder_create_builds_dialog_filter_and_replays_idempotency tests/tgcli/test_phase62_folders.py::test_folder_create_dry_run_does_not_call_telethon tests/tgcli/test_cli_smoke.py::test_phase62_folder_create_dry_run_smoke -q
```

Expected: FAIL because `_folder_create_runner()` is not present and `run_folder_create()` still uses the Task 1 surface runner.

- [ ] **Step 3: Add create helpers and runner**

Add below the read runners:

```python
async def _input_peers_for_chat_ids(client, chat_ids: list[int]) -> list[Any]:
    peers = []
    for chat_id in chat_ids:
        peers.append(await client.get_input_peer(int(chat_id)))
    return peers


def _next_folder_id(filters: list[Any]) -> int:
    ids = [_folder_id(folder) for folder in filters if _folder_id(folder) > 0]
    return (max(ids) + 1) if ids else 1


def _dialog_filter(
    *,
    folder_id: int,
    title,
    pinned_peers: list[Any],
    include_peers: list[Any],
    exclude_peers: list[Any],
    emoticon: str | None,
    flags: dict[str, bool | None],
) -> DialogFilter:
    return DialogFilter(
        id=int(folder_id),
        title=title,
        pinned_peers=list(pinned_peers),
        include_peers=list(include_peers),
        exclude_peers=list(exclude_peers),
        contacts=flags.get("contacts"),
        non_contacts=flags.get("non_contacts"),
        groups=flags.get("groups"),
        broadcasts=flags.get("broadcasts"),
        bots=flags.get("bots"),
        exclude_muted=flags.get("exclude_muted"),
        exclude_read=flags.get("exclude_read"),
        exclude_archived=flags.get("exclude_archived"),
        emoticon=emoticon,
    )


def _folder_create_flags(args) -> dict[str, bool | None]:
    return {field: bool(getattr(args, field, False)) or None for field in _FOLDER_BOOL_FIELDS}


async def _folder_create_runner(args) -> dict[str, Any]:
    command = "folder-create"
    request_id = _request_id(args)
    require_write_allowed(args)
    _require_folder_write_key(args)
    title = _folder_title(args.title)
    include_chat_ids = [int(chat_id) for chat_id in (args.include_chat or [])]
    exclude_chat_ids = [int(chat_id) for chat_id in (args.exclude_chat or [])]

    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        payload = {
            "title": title.text,
            "emoticon": args.emoticon,
            "include_chat_ids": include_chat_ids,
            "exclude_chat_ids": exclude_chat_ids,
            "flags": _folder_create_flags(args),
            "telethon_method": "UpdateDialogFilterRequest",
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)

        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=0,
            resolved_chat_title="dialog folders",
            payload_preview=payload,
            telethon_method="UpdateDialogFilterRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            filters = _folders_from_result(await client(GetDialogFiltersRequest()))
            folder_id = _next_folder_id(filters)
            include_peers = await _input_peers_for_chat_ids(client, include_chat_ids)
            exclude_peers = await _input_peers_for_chat_ids(client, exclude_chat_ids)
            folder = _dialog_filter(
                folder_id=folder_id,
                title=title,
                pinned_peers=[],
                include_peers=include_peers,
                exclude_peers=exclude_peers,
                emoticon=args.emoticon,
                flags=_folder_create_flags(args),
            )
            await client(UpdateDialogFilterRequest(id=folder_id, filter=folder))
            data = {
                "folder_id": folder_id,
                "title": title.text,
                "emoticon": args.emoticon,
                "include_peer_count": len(include_peers),
                "exclude_peer_count": len(exclude_peers),
                "flags": _folder_flags(folder),
                "idempotent_replay": False,
            }
            record_idempotency(con, args.idempotency_key, command, request_id, _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_folder_create(args) -> int:
    return _run_write_command("folder-create", args, _folder_create_runner)
```

Remove the temporary `run_folder_create()` stub from Task 1.

- [ ] **Step 4: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase62_folders.py::test_folder_create_builds_dialog_filter_and_replays_idempotency tests/tgcli/test_phase62_folders.py::test_folder_create_dry_run_does_not_call_telethon tests/tgcli/test_cli_smoke.py::test_phase62_folder_create_dry_run_smoke -q
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: PASS with about `132 tests collected`.

- [ ] **Step 6: Commit**

```bash
git add tgcli/commands/chats.py tests/tgcli/test_phase62_folders.py tests/tgcli/test_cli_smoke.py
git commit -m "feat(tgcli): create dialog folders safely"
```

---

## Task 4: `tg folder-edit` and `tg folder-delete`

**Goal:** Implement full custom folder edits and folder deletion with idempotency replay and reserved id protection.

**Files:**
- Modify: `tgcli/commands/chats.py`
- Modify: `tests/tgcli/test_phase62_folders.py`

- [ ] **Step 1: Add failing unit tests for edit and delete**

Append to `tests/tgcli/test_phase62_folders.py`:

```python
def test_folder_edit_preserves_existing_peers_and_updates_flags(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.requests = []

        async def start(self):
            pass

        async def __call__(self, request):
            self.requests.append(request)
            if request.__class__.__name__ == "GetDialogFiltersRequest":
                return [_filter(folder_id=2, title="Ops", include=[FakeInputPeer(123)], exclude=[FakeInputPeer(456)])]
            return True

        async def get_input_peer(self, chat_id):
            return FakeInputPeer(chat_id)

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    data = asyncio.run(chats._folder_edit_runner(_args(
        folder_id=2,
        title="Ops 2",
        emoticon="✅",
        include_chat=[789],
        groups=False,
        bots=True,
        idempotency_key="folder-edit-1",
    )))

    assert data["folder_id"] == 2
    assert data["edited"] is True
    update = [request for request in fake.requests if request.__class__.__name__ == "UpdateDialogFilterRequest"][0]
    assert update.id == 2
    assert update.filter.title.text == "Ops 2"
    assert update.filter.emoticon == "✅"
    assert [peer.peer_id for peer in update.filter.include_peers] == [123, 789]
    assert [peer.peer_id for peer in update.filter.exclude_peers] == [456]
    assert update.filter.groups is False
    assert update.filter.bots is True


def test_folder_edit_requires_mutation():
    with pytest.raises(BadArgs, match="nothing to edit"):
        chats._folder_edit_mutations(_args(folder_id=2))


def test_folder_delete_rejects_default_folder():
    with pytest.raises(BadArgs, match="folder id 0 is reserved"):
        asyncio.run(chats._folder_delete_runner(_args(folder_id=0)))


def test_folder_delete_uses_none_filter_and_replays_idempotency(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.requests = []

        async def start(self):
            pass

        async def __call__(self, request):
            self.requests.append(request)
            return True

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    args = _args(folder_id=2, idempotency_key="folder-delete-1")

    first = asyncio.run(chats._folder_delete_runner(args))
    second = asyncio.run(chats._folder_delete_runner(args))

    assert first["deleted"] is True
    assert second["idempotent_replay"] is True
    assert len(fake.requests) == 1
    request = fake.requests[0]
    assert request.__class__.__name__ == "UpdateDialogFilterRequest"
    assert request.id == 2
    assert request.filter is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase62_folders.py::test_folder_edit_preserves_existing_peers_and_updates_flags tests/tgcli/test_phase62_folders.py::test_folder_edit_requires_mutation tests/tgcli/test_phase62_folders.py::test_folder_delete_rejects_default_folder tests/tgcli/test_phase62_folders.py::test_folder_delete_uses_none_filter_and_replays_idempotency -q
```

Expected: FAIL because `_folder_edit_runner()` and `_folder_delete_runner()` do not exist.

- [ ] **Step 3: Add edit/delete implementation**

Add below `_folder_create_runner()`:

```python
def _dedupe_peers(peers: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for peer in peers:
        key = _peer_id_value(peer)
        if key is None:
            key = id(peer)
        if key in seen:
            continue
        seen.add(key)
        out.append(peer)
    return out


def _flags_from_existing(existing: DialogFilter, updates: dict[str, Any]) -> dict[str, bool | None]:
    flags: dict[str, bool | None] = {}
    for field in _FOLDER_BOOL_FIELDS:
        if field in updates:
            flags[field] = bool(updates[field])
        else:
            flags[field] = getattr(existing, field, None)
    return flags


async def _updated_dialog_filter(client, existing: DialogFilter, args, updates: dict[str, Any]) -> DialogFilter:
    include_peers = [] if updates.get("clear_include") else list(getattr(existing, "include_peers", None) or [])
    exclude_peers = [] if updates.get("clear_exclude") else list(getattr(existing, "exclude_peers", None) or [])
    include_peers.extend(await _input_peers_for_chat_ids(client, [int(chat_id) for chat_id in (args.include_chat or [])]))
    exclude_peers.extend(await _input_peers_for_chat_ids(client, [int(chat_id) for chat_id in (args.exclude_chat or [])]))
    title = updates.get("title", getattr(existing, "title", _folder_title("Folder")))
    emoticon = updates.get("emoticon", getattr(existing, "emoticon", None))
    return _dialog_filter(
        folder_id=int(existing.id),
        title=title,
        pinned_peers=list(getattr(existing, "pinned_peers", None) or []),
        include_peers=_dedupe_peers(include_peers),
        exclude_peers=_dedupe_peers(exclude_peers),
        emoticon=emoticon,
        flags=_flags_from_existing(existing, updates),
    )


async def _folder_edit_runner(args) -> dict[str, Any]:
    command = "folder-edit"
    request_id = _request_id(args)
    require_write_allowed(args)
    _require_folder_write_key(args)
    updates = _folder_edit_mutations(args)
    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        payload = {
            "folder_id": int(args.folder_id),
            "title": getattr(args, "title", None),
            "emoticon": getattr(args, "emoticon", None),
            "clear_include": bool(getattr(args, "clear_include", False)),
            "clear_exclude": bool(getattr(args, "clear_exclude", False)),
            "include_chat_ids": list(getattr(args, "include_chat", []) or []),
            "exclude_chat_ids": list(getattr(args, "exclude_chat", []) or []),
            "boolean_updates": {field: getattr(args, field) for field in _FOLDER_BOOL_FIELDS if getattr(args, field, None) is not None},
            "telethon_method": "UpdateDialogFilterRequest",
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)
        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=0,
            resolved_chat_title=f"folder {int(args.folder_id)}",
            payload_preview=payload,
            telethon_method="UpdateDialogFilterRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            filters = _folders_from_result(await client(GetDialogFiltersRequest()))
            existing = _ensure_mutable_folder(_matching_folder(filters, int(args.folder_id)), int(args.folder_id))
            folder = await _updated_dialog_filter(client, existing, args, updates)
            await client(UpdateDialogFilterRequest(id=int(args.folder_id), filter=folder))
            data = {
                "folder_id": int(args.folder_id),
                "title": _folder_title_text(folder.title),
                "edited": True,
                "include_peer_count": len(folder.include_peers),
                "exclude_peer_count": len(folder.exclude_peers),
                "flags": _folder_flags(folder),
                "idempotent_replay": False,
            }
            record_idempotency(con, args.idempotency_key, command, request_id, _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


async def _folder_delete_runner(args) -> dict[str, Any]:
    command = "folder-delete"
    request_id = _request_id(args)
    require_write_allowed(args)
    _require_folder_write_key(args)
    folder_id = int(args.folder_id)
    if folder_id == 0:
        raise BadArgs("folder id 0 is reserved and cannot be deleted")
    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        payload = {"folder_id": folder_id, "telethon_method": "UpdateDialogFilterRequest", "filter": None}
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)
        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=0,
            resolved_chat_title=f"folder {folder_id}",
            payload_preview=payload,
            telethon_method="UpdateDialogFilterRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            await client(UpdateDialogFilterRequest(id=folder_id, filter=None))
            data = {"folder_id": folder_id, "deleted": True, "idempotent_replay": False}
            record_idempotency(con, args.idempotency_key, command, request_id, _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_folder_edit(args) -> int:
    return _run_write_command("folder-edit", args, _folder_edit_runner)


def run_folder_delete(args) -> int:
    return _run_write_command("folder-delete", args, _folder_delete_runner)
```

Remove the temporary `run_folder_edit()` and `run_folder_delete()` stubs from Task 1.

- [ ] **Step 4: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase62_folders.py::test_folder_edit_preserves_existing_peers_and_updates_flags tests/tgcli/test_phase62_folders.py::test_folder_edit_requires_mutation tests/tgcli/test_phase62_folders.py::test_folder_delete_rejects_default_folder tests/tgcli/test_phase62_folders.py::test_folder_delete_uses_none_filter_and_replays_idempotency -q
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: PASS with about `136 tests collected`.

- [ ] **Step 6: Commit**

```bash
git add tgcli/commands/chats.py tests/tgcli/test_phase62_folders.py
git commit -m "feat(tgcli): edit and delete dialog folders"
```

---

## Task 5: `tg folder-add-chat`, `tg folder-remove-chat`, and `tg folders-reorder`

**Goal:** Implement chat membership mutation and folder ordering with fuzzy-gated chat resolution, idempotency replay, warnings, and request-shape tests.

**Files:**
- Modify: `tgcli/commands/chats.py`
- Modify: `tests/tgcli/test_phase62_folders.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Add failing unit and smoke tests**

Append to `tests/tgcli/test_phase62_folders.py`:

```python
def test_folder_add_chat_resolves_chat_and_replays_idempotency(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.requests = []

        async def start(self):
            pass

        async def __call__(self, request):
            self.requests.append(request)
            if request.__class__.__name__ == "GetDialogFiltersRequest":
                return [_filter(folder_id=2, title="Ops", include=[])]
            return True

        async def get_input_peer(self, chat_id):
            return FakeInputPeer(chat_id)

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    args = _args(folder_id=2, chat="@alpha_forum", idempotency_key="folder-add-1")

    first = asyncio.run(chats._folder_add_chat_runner(args))
    second = asyncio.run(chats._folder_add_chat_runner(args))

    assert first["chat"] == {"chat_id": 123, "title": "Alpha Forum"}
    assert first["added"] is True
    assert second["idempotent_replay"] is True
    updates = [request for request in fake.requests if request.__class__.__name__ == "UpdateDialogFilterRequest"]
    assert len(updates) == 1
    assert [peer.peer_id for peer in updates[0].filter.include_peers] == [123]


def test_folder_remove_chat_warns_when_chat_is_excluded(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.requests = []

        async def start(self):
            pass

        async def __call__(self, request):
            self.requests.append(request)
            if request.__class__.__name__ == "GetDialogFiltersRequest":
                return [_filter(folder_id=2, title="Ops", include=[], exclude=[FakeInputPeer(123)])]
            return True

        async def get_input_peer(self, chat_id):
            return FakeInputPeer(chat_id)

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    data = asyncio.run(chats._folder_remove_chat_runner(_args(
        folder_id=2,
        chat="@alpha_forum",
        idempotency_key="folder-remove-1",
    )))

    assert data["removed"] is False
    assert data["warnings"] == ["chat was present in exclude_peers, not include_peers"]
    update = [request for request in fake.requests if request.__class__.__name__ == "UpdateDialogFilterRequest"][0]
    assert update.filter.include_peers == []
    assert [peer.peer_id for peer in update.filter.exclude_peers] == [123]


def test_folders_reorder_uses_order_request_and_replays(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.requests = []

        async def start(self):
            pass

        async def __call__(self, request):
            self.requests.append(request)
            return True

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    args = _args(folder_ids=[2, 3, 4], idempotency_key="folders-reorder-1")

    first = asyncio.run(chats._folders_reorder_runner(args))
    second = asyncio.run(chats._folders_reorder_runner(args))

    assert first["order"] == [2, 3, 4]
    assert second["idempotent_replay"] is True
    assert len(fake.requests) == 1
    assert fake.requests[0].__class__.__name__ == "UpdateDialogFiltersOrderRequest"
    assert fake.requests[0].order == [2, 3, 4]
```

Append to `tests/tgcli/test_cli_smoke.py`:

```python
def test_phase62_folder_other_write_dry_run_smoke(tmp_path):
    from tgcli.db import connect

    db = tmp_path / "telegram.sqlite"
    con = connect(db)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "supergroup", "Alpha Forum", "alpha_forum"),
    )
    con.commit()
    con.close()

    env = {
        **_os.environ,
        "TG_API_ID": "1",
        "TG_API_HASH": "x",
        "TG_DB_PATH": str(db),
        "TG_AUDIT_PATH": str(tmp_path / "audit.log"),
    }
    commands = [
        [str(PYTHON), "-m", "tgcli", "folder-edit", "2", "--title", "Ops 2", "--allow-write", "--idempotency-key", "phase62-edit-dry", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "folder-delete", "2", "--allow-write", "--idempotency-key", "phase62-delete-dry", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "folder-add-chat", "2", "@alpha_forum", "--allow-write", "--idempotency-key", "phase62-add-dry", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "folder-remove-chat", "2", "@alpha_forum", "--allow-write", "--idempotency-key", "phase62-remove-dry", "--dry-run", "--json"],
        [str(PYTHON), "-m", "tgcli", "folders-reorder", "2", "3", "--allow-write", "--idempotency-key", "phase62-reorder-dry", "--dry-run", "--json"],
    ]
    for command in commands:
        result = _subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, f"command: {command} stderr: {result.stderr}"
        payload = _json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["dry_run"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase62_folders.py::test_folder_add_chat_resolves_chat_and_replays_idempotency tests/tgcli/test_phase62_folders.py::test_folder_remove_chat_warns_when_chat_is_excluded tests/tgcli/test_phase62_folders.py::test_folders_reorder_uses_order_request_and_replays tests/tgcli/test_cli_smoke.py::test_phase62_folder_other_write_dry_run_smoke -q
```

Expected: FAIL because membership and reorder runners do not exist.

- [ ] **Step 3: Add add/remove/reorder implementation**

Add below the delete runner:

```python
def _remove_peer_by_id(peers: list[Any], peer_id: int) -> tuple[list[Any], bool]:
    out = []
    removed = False
    for peer in peers:
        if _peer_id_value(peer) == int(peer_id):
            removed = True
            continue
        out.append(peer)
    return out, removed


async def _folder_membership_runner(args, *, command: str, add: bool) -> dict[str, Any]:
    request_id = _request_id(args)
    require_write_allowed(args)
    _require_folder_write_key(args)
    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        chat = _resolve_write_chat(con, args, args.chat)
        payload = {
            "folder_id": int(args.folder_id),
            "chat": chat,
            "action": "add" if add else "remove",
            "telethon_method": "UpdateDialogFilterRequest",
        }
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)
        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=chat["chat_id"],
            resolved_chat_title=chat["title"],
            payload_preview=payload,
            telethon_method="UpdateDialogFilterRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            filters = _folders_from_result(await client(GetDialogFiltersRequest()))
            existing = _ensure_mutable_folder(_matching_folder(filters, int(args.folder_id)), int(args.folder_id))
            target_peer = await client.get_input_peer(chat["chat_id"])
            include_peers = list(getattr(existing, "include_peers", None) or [])
            exclude_peers = list(getattr(existing, "exclude_peers", None) or [])
            warnings: list[str] = []
            if add:
                include_peers = _dedupe_peers([*include_peers, target_peer])
                changed = True
            else:
                include_peers, removed = _remove_peer_by_id(include_peers, chat["chat_id"])
                in_exclude = any(_peer_id_value(peer) == chat["chat_id"] for peer in exclude_peers)
                if in_exclude and not removed:
                    warnings.append("chat was present in exclude_peers, not include_peers")
                changed = removed
            folder = _dialog_filter(
                folder_id=int(existing.id),
                title=getattr(existing, "title", _folder_title("Folder")),
                pinned_peers=list(getattr(existing, "pinned_peers", None) or []),
                include_peers=_dedupe_peers(include_peers),
                exclude_peers=_dedupe_peers(exclude_peers),
                emoticon=getattr(existing, "emoticon", None),
                flags={field: getattr(existing, field, None) for field in _FOLDER_BOOL_FIELDS},
            )
            await client(UpdateDialogFilterRequest(id=int(args.folder_id), filter=folder))
            data = {
                "folder_id": int(args.folder_id),
                "chat": chat,
                "added": bool(add and changed),
                "removed": bool((not add) and changed),
                "include_peer_count": len(folder.include_peers),
                "exclude_peer_count": len(folder.exclude_peers),
                "warnings": warnings,
                "idempotent_replay": False,
            }
            record_idempotency(con, args.idempotency_key, command, request_id, _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


async def _folder_add_chat_runner(args) -> dict[str, Any]:
    return await _folder_membership_runner(args, command="folder-add-chat", add=True)


async def _folder_remove_chat_runner(args) -> dict[str, Any]:
    return await _folder_membership_runner(args, command="folder-remove-chat", add=False)


async def _folders_reorder_runner(args) -> dict[str, Any]:
    command = "folders-reorder"
    request_id = _request_id(args)
    require_write_allowed(args)
    _require_folder_write_key(args)
    order = [int(folder_id) for folder_id in args.folder_ids]
    if not order:
        raise BadArgs("at least one folder id is required")
    if len(order) != len(set(order)):
        raise BadArgs("folder ids in reorder list must be unique")
    con = connect(DB_PATH)
    try:
        replay = lookup_idempotency(con, args.idempotency_key, command)
        if replay is not None:
            data = dict(replay["data"])
            data["idempotent_replay"] = True
            return data
        payload = {"order": order, "telethon_method": "UpdateDialogFiltersOrderRequest"}
        if args.dry_run:
            return _dry_run_envelope(command, request_id, payload)
        _check_write_rate_limit()
        audit_pre(
            AUDIT_PATH,
            cmd=command,
            request_id=request_id,
            resolved_chat_id=0,
            resolved_chat_title="dialog folders",
            payload_preview=payload,
            telethon_method="UpdateDialogFiltersOrderRequest",
            dry_run=False,
        )
        client = make_client(SESSION_PATH)
        await client.start()
        try:
            await client(UpdateDialogFiltersOrderRequest(order=order))
            data = {"order": order, "reordered": True, "idempotent_replay": False}
            record_idempotency(con, args.idempotency_key, command, request_id, _write_result(command, request_id, data))
            return data
        finally:
            await client.disconnect()
    finally:
        con.close()


def run_folder_add_chat(args) -> int:
    return _run_write_command("folder-add-chat", args, _folder_add_chat_runner)


def run_folder_remove_chat(args) -> int:
    return _run_write_command("folder-remove-chat", args, _folder_remove_chat_runner)


def run_folders_reorder(args) -> int:
    return _run_write_command("folders-reorder", args, _folders_reorder_runner)
```

Remove the temporary `run_folder_add_chat()`, `run_folder_remove_chat()`, and `run_folders_reorder()` stubs from Task 1.

- [ ] **Step 4: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase62_folders.py::test_folder_add_chat_resolves_chat_and_replays_idempotency tests/tgcli/test_phase62_folders.py::test_folder_remove_chat_warns_when_chat_is_excluded tests/tgcli/test_phase62_folders.py::test_folders_reorder_uses_order_request_and_replays tests/tgcli/test_cli_smoke.py::test_phase62_folder_other_write_dry_run_smoke -q
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: PASS with about `140 tests collected`.

- [ ] **Step 6: Commit**

```bash
git add tgcli/commands/chats.py tests/tgcli/test_phase62_folders.py tests/tgcli/test_cli_smoke.py
git commit -m "feat(tgcli): update dialog folder membership"
```

---

## Task 6: Test count stabilization and final cleanup

**Goal:** Keep the final Phase 6.2 test count inside the agreed `140-145` band and verify no out-of-scope files changed.

**Files:**
- Modify: `tests/tgcli/test_phase62_folders.py`
- Modify: `tests/tgcli/test_cli_smoke.py`

- [ ] **Step 1: Normalize final test count to the target**

Run:

```bash
.venv/bin/pytest --collect-only -q | tail -1
```

Expected target: `140-145 tests collected`.

If the count is above `145`, merge overlapping parser-only tests while preserving behavior. The intended merged smoke test is:

```python
def test_phase62_folder_help_surfaces():
    read_commands = ["folders-list", "folder-show"]
    write_commands = [
        "folder-create",
        "folder-edit",
        "folder-delete",
        "folder-add-chat",
        "folder-remove-chat",
        "folders-reorder",
    ]
    for command in [*read_commands, *write_commands]:
        result = _subprocess.run(
            [str(PYTHON), "-m", "tgcli", command, "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"command: {command} stderr: {result.stderr}"
        assert "usage:" in result.stdout.lower()
        if command in write_commands:
            assert "--allow-write" in result.stdout
            assert "--dry-run" in result.stdout
            assert "--idempotency-key" in result.stdout
            assert "--fuzzy" in result.stdout
```

- [ ] **Step 2: Run folder-focused tests**

Run:

```bash
.venv/bin/pytest tests/tgcli/test_phase62_folders.py tests/tgcli/test_cli_smoke.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: PASS with `140-145 tests collected`.

- [ ] **Step 4: Confirm only in-scope files changed**

Run:

```bash
git diff --name-only
```

Expected output includes only:

```text
tgcli/commands/chats.py
tests/tgcli/test_phase62_folders.py
tests/tgcli/test_cli_smoke.py
```

It must not include:

```text
tgcli/__main__.py
tgcli/commands/events.py
tgcli/sedex.py
tgcli/commands/sedex_agent.py
tests/tgcli/test_sedex.py
tgcli/commands/messages.py
```

- [ ] **Step 5: Commit**

```bash
git add tgcli/commands/chats.py tests/tgcli/test_phase62_folders.py tests/tgcli/test_cli_smoke.py
git commit -m "test(tgcli): stabilize phase 6.2 folder coverage"
```

---

## Final Verification

Run the full automated verification:

```bash
.venv/bin/pytest -q
```

Expected: PASS with `140-145 tests collected`, from the Phase 6.1 baseline of `122`.

Run parser smoke checks manually:

```bash
.venv/bin/python -m tgcli folders-list --help
.venv/bin/python -m tgcli folder-show --help
.venv/bin/python -m tgcli folder-create --help
.venv/bin/python -m tgcli folder-edit --help
.venv/bin/python -m tgcli folder-delete --help
.venv/bin/python -m tgcli folder-add-chat --help
.venv/bin/python -m tgcli folder-remove-chat --help
.venv/bin/python -m tgcli folders-reorder --help
```

Expected: each command exits 0; write commands show `--allow-write`, `--dry-run`, `--idempotency-key`, and `--fuzzy`; read commands do not require write flags.

Run dry-run checks against a seeded test DB:

```bash
.venv/bin/pytest tests/tgcli/test_cli_smoke.py::test_phase62_folder_create_dry_run_smoke tests/tgcli/test_cli_smoke.py::test_phase62_folder_other_write_dry_run_smoke -q
```

Expected: PASS; no live Telegram connection is attempted.

Manual live checks after merge, run by the user against a known account:

```bash
tg folders-list --json
tg folder-show 0 --json
tg folder-create "tg-cli smoke folder" --include-chat 123456789 --allow-write --idempotency-key phase62-smoke-folder-create --json
tg folder-edit 7 --title "tg-cli smoke folder renamed" --allow-write --idempotency-key phase62-smoke-folder-edit --json
tg folder-add-chat 7 @alpha_forum --allow-write --idempotency-key phase62-smoke-folder-add --json
tg folder-remove-chat 7 @alpha_forum --allow-write --idempotency-key phase62-smoke-folder-remove --json
tg folders-reorder 7 2 3 --allow-write --idempotency-key phase62-smoke-folders-reorder --json
tg folder-delete 7 --allow-write --idempotency-key phase62-smoke-folder-delete --json
```

Expected: live calls succeed for valid folder ids and cached chat selectors. Running `tg folder-delete 0 --allow-write --idempotency-key phase62-delete-default --json` returns `BAD_ARGS` with message `folder id 0 is reserved and cannot be deleted`.

---

## Exact Commit Sequence

```bash
git commit -m "feat(tgcli): add folder parser surfaces"
git commit -m "feat(tgcli): list and show dialog folders"
git commit -m "feat(tgcli): create dialog folders safely"
git commit -m "feat(tgcli): edit and delete dialog folders"
git commit -m "feat(tgcli): update dialog folder membership"
git commit -m "test(tgcli): stabilize phase 6.2 folder coverage"
```

---

## Self-Review Checklist

- [ ] `folders-list` uses live `GetDialogFiltersRequest()` and has no write gate.
- [ ] `folder-show` uses live `GetDialogFiltersRequest()` and enriches peers from `tg_chats.title` and `tg_chats.type`.
- [ ] `folders-list` includes folder id `0` with `is_default: true` when Telethon returns `DialogFilterDefault`.
- [ ] `folder-create`, `folder-edit`, `folder-delete`, `folder-add-chat`, `folder-remove-chat`, and `folders-reorder` require `--allow-write` or `TG_ALLOW_WRITE=1`.
- [ ] Folder write runners require a non-empty `--idempotency-key`.
- [ ] Folder write runners support `--dry-run` before any Telethon call.
- [ ] `folder-create` records and replays an idempotency envelope including the new `folder_id`.
- [ ] `folder-edit`, `folder-delete`, `folder-add-chat`, `folder-remove-chat`, and `folders-reorder` skip API calls on idempotency replay.
- [ ] `DialogFilter.title` is always `TextWithEntities(text=..., entities=[])`, not `str`.
- [ ] `--include-chat` and `--exclude-chat` values are integer ids for create/edit.
- [ ] Include/exclude ids are wrapped with `client.get_input_peer(chat_id)` before constructing `DialogFilter`.
- [ ] `folder-add-chat` and `folder-remove-chat` use `_resolve_write_chat()` so fuzzy title selectors require `--fuzzy`.
- [ ] `folder-delete 0` raises `BadArgs`.
- [ ] `folder-remove-chat` warns when the peer is in `exclude_peers` but not `include_peers`.
- [ ] No source files outside `tgcli/commands/chats.py` are modified.
- [ ] No test files outside `tests/tgcli/test_phase62_folders.py` and `tests/tgcli/test_cli_smoke.py` are modified.
- [ ] `tgcli/__main__.py`, `tgcli/commands/events.py`, `tgcli/sedex.py`, `tgcli/commands/sedex_agent.py`, and `tests/tgcli/test_sedex.py` are untouched or absent.
- [ ] Full pytest ends inside the `140-145` count band.

---

## Out of Scope

- No Sedex, LLM hooks, autonomous folder management, or agent automation.
- No changes to `tgcli/__main__.py` or `tgcli/commands/events.py`.
- No new modules such as `tgcli/sedex.py` or `tgcli/commands/sedex_agent.py`.
- No `tests/tgcli/test_sedex.py`.
- No nested argparse command groups such as `tg folder create`; Phase 6.2 uses flat hyphenated command names only.
- No fuzzy resolution for `folder-create/edit --include-chat/--exclude-chat`; those options accept integer ids only in v1.
- No live Telethon tests.
