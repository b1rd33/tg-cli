# tgctl

[![PyPI](https://img.shields.io/pypi/v/tgctl.svg)](https://pypi.org/project/tgctl/)
[![CI](https://github.com/b1rd33/tg-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/b1rd33/tg-cli/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/tgctl.svg)](https://pypi.org/project/tgctl/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Agent-friendly Telegram CLI** built on [Telethon](https://github.com/LonamiWebs/Telethon). Read, write, archive,
and listen to your own Telegram account from the terminal with JSON output,
idempotency, audit logging, multi-account stores, and explicit safety gates
for autonomous-agent use.

`tgctl` is for developers and local agents that need a predictable Telegram
surface without running a bot account or handing control to a GUI client. It
uses your normal Telegram account through Telethon and stores a local SQLite
cache for fast offline queries.

> **Names:** the PyPI distribution is `tgctl` (in the `kubectl`/`flyctl`
> family — Telegram control). The binary on `PATH` is `tg`. The Python
> import is `from tgcli import Client`. The GitHub repo is `tg-cli`.

## Quick start

```bash
pip install tgctl
echo "TG_API_ID=12345678" > .env
echo "TG_API_HASH=abcdef0123456789abcdef0123456789" >> .env
tg login
tg stats
```

Get `TG_API_ID` and `TG_API_HASH` from https://my.telegram.org/apps.

## Features

- 62 commands covering read, write, media, folder, topic, account, admin, and destructive operations
- Multi-account mode with isolated session, database, and audit paths per account
- JSON envelope output for clean agent integration
- Local SQLite cache for fast reads and archival workflows
- Write safety through `--allow-write`, `--dry-run`, idempotency keys, and append-only audit logs
- Destructive safety through typed `--confirm <id>` checks
- Read-only mode for trusted inspection with `--read-only` or `TG_READONLY=1`

## Commands at a glance

| Command | Purpose |
| --- | --- |
| `account-sessions` | List authenticated Telegram sessions |
| `accounts-add` | Create a local account store |
| `accounts-list` | List local account stores |
| `accounts-remove` | Delete a local account store |
| `accounts-show` | Show current account paths |
| `accounts-use` | Switch the default local account |
| `backfill` | Pull historical messages into SQLite |
| `block-user` | Block a user or bot |
| `chats-info` | Show cached chat metadata |
| `contacts` | List synced contacts |
| `delete-msg` | Delete one or more messages |
| `discover` | Scan dialogs without fetching messages |
| `doctor` | Diagnose env, session, DB, schema, and optional live API |
| `edit-msg` | Edit one of your own text messages |
| `folder-add-chat` | Add a chat to a Telegram folder |
| `folder-create` | Create a Telegram folder |
| `folder-delete` | Delete a Telegram folder |
| `folder-edit` | Edit a Telegram folder |
| `folder-remove-chat` | Remove a chat from a Telegram folder |
| `folder-show` | Show one Telegram folder |
| `folders-list` | List Telegram folders |
| `folders-reorder` | Reorder Telegram folders |
| `forward` | Forward one cached message |
| `get-msg` | Get one cached message by id |
| `leave-chat` | Leave a group, supergroup, or channel |
| `list-msgs` | List cached messages from one chat |
| `listen` | Capture new incoming messages forever |
| `login` | Run one-time interactive auth |
| `mark-read` | Mark all messages in a chat as read |
| `me` | Print authenticated user info |
| `pin-msg` | Pin a message |
| `react` | Add a reaction to a message |
| `search` | Search cached messages in one chat |
| `send` | Send a text message |
| `show` | Print messages from one chat |
| `stats` | Show a database summary |
| `sync-contacts` | Pull phone-book contacts from Telegram |
| `terminate-session` | Terminate a Telegram session |
| `topic-create` | Create a forum topic |
| `topic-edit` | Edit a forum topic |
| `topic-pin` | Pin a forum topic |
| `topic-unpin` | Unpin a forum topic |
| `topics-list` | List forum topics in a supergroup |
| `unblock-user` | Unblock a user or bot |
| `unpin-msg` | Unpin a message |
| `unread` | List chats with unread messages |

## Why tg-cli?

Telegram tooling usually optimizes for one of four shapes: interactive TUIs,
file-transfer utilities, bot APIs, or MCP servers. `tg-cli` is narrower and
more scriptable: a local user-account CLI with stable exit codes, JSON output,
SQLite-backed reads, an audit trail, and explicit write gates. It is designed
for shell scripts and coding agents that need to inspect or operate on the
user's own Telegram account while keeping every write intentional.

## Python SDK

Use tg-cli inside your own Python apps without subprocess:

```python
from tgcli import Client

c = Client()                                  # default account

# Read paths
me = c.me()
summary = c.stats(min_msgs=10)
history = c.messages.show(chat_id=12345, limit=50)

# Write paths reuse the CLI's safety gates
result = c.messages.send(
    chat=12345,
    text="hello",
    allow_write=True,                         # required, mirrors --allow-write
    idempotency_key="abc123",                 # optional replay protection
)

# Dry-run any write to preview without calling Telegram
preview = c.messages.send(
    chat=12345, text="hi", allow_write=True, dry_run=True
)
assert preview["dry_run"] is True
```

The SDK reuses the CLI's safety gates — calling a write method without
`allow_write=True` raises `tgcli.safety.WriteDisallowed`. Destructive
admin methods accept `confirm=<resolved-id>` matching the CLI
`--confirm` flag.

**Multi-account:** v0.4.0 SDK is single-account-per-process. Set
`TG_ACCOUNT=<name>` BEFORE importing tgcli, then construct
`Client(account="<name>")`. Mismatched constructions raise
`RuntimeError`. For concurrent multi-account work, run one process
per account.

The SDK exposes a curated subset of runners (`me`, `stats`,
`messages.send`, `messages.show`, `admin.chat_title`) for v1.0. All
62 commands remain available through the CLI surface; open an issue
if you need a specific runner exposed in the SDK.

## Configuration

Paths and credentials can be provided through environment variables or a local
`.env` file.

| Variable | Purpose |
| --- | --- |
| `TG_API_ID` | Telegram API id from my.telegram.org |
| `TG_API_HASH` | Telegram API hash from my.telegram.org |
| `TG_SESSION_PATH` | Telethon session file path |
| `TG_DB_PATH` | SQLite cache path |
| `TG_AUDIT_PATH` | Append-only audit log path |
| `TG_MEDIA_DIR` | Media output directory |
| `TG_ACCOUNT` | Active local account name |
| `TG_READONLY` | Reject Telegram-side and local DB writes when set to `1` |
| `TG_ALLOW_WRITE` | Allow writes without passing `--allow-write` each time |

## Multi-account

```bash
tg accounts-add work
tg --account work login
tg accounts-use work
tg accounts-show
```

Each account stores its own session, database, and audit log under
`accounts/<NAME>/`. The default account remains `default`.

## Safety

Writes are blocked unless you pass `--allow-write` or set `TG_ALLOW_WRITE=1`.
Destructive commands also require a typed `--confirm <id>` value matched against
the resolved chat, user, message, folder, or session id. `--dry-run` reports
what would happen without calling Telegram. `--read-only` and `TG_READONLY=1`
reject both Telegram-side writes and local DB writers.

Every invocation appends audit entries to `audit.log`. Write commands record
pre-call and post-call entries with the same `request_id`; idempotency keys can
replay a cached successful envelope instead of calling Telegram again.

## Architecture

`tgcli.__main__` builds the argparse surface and dispatches into command modules
under `tgcli/commands/`. Commands share the same output envelope, resolver,
safety, idempotency, and audit helpers. Telethon handles Telegram API access;
SQLite stores chats, messages, contacts, folders, topics, and idempotency state.

```text
tg command
  -> argparse
  -> command runner
  -> safety gates + resolver + audit
  -> Telethon and/or SQLite
  -> JSON envelope or human output
```

## Contributing

See [AGENTS.md](AGENTS.md) for the project's working conventions and the
[git commit history](https://github.com/b1rd33/tg-cli/commits/main) for the
design progression.

## License

MIT - see [LICENSE](LICENSE).

## Credits

Built on [Telethon](https://github.com/LonamiWebs/Telethon), the pure-Python
MTProto client by Lonami, distributed under the MIT License.
