# tg-cli

**Agent-friendly Telegram CLI** built on [Telethon](https://github.com/LonamiWebs/Telethon).

Read, write, archive, and listen to your own Telegram account from the
terminal — with JSON envelope output, idempotency keys, audit logging,
multi-account stores, and explicit safety gates designed for autonomous
agent use.

```bash
pip install tgctl
tg login
tg --help    # 62 commands
```

## What is `tg-cli`?

`tg-cli` (PyPI: `tgctl`) is a Python CLI that drives your **personal
Telegram account** through Telethon's MTProto API. It exposes ~60
commands as JSON envelopes with stable exit codes, makes a local SQLite
mirror of your messages for offline queries, and ships an importable
Python SDK so other apps (LLM-drafted reply pipelines, custom
notifiers, dashboards) can consume the same surface.

It's **not a bot framework**. Bots run on Telegram's separate Bot API
and never see private chats. `tg-cli` is for *your own account* —
read your DMs, search archives, draft and send replies, manage
groups you administer, listen for incoming events.

## Why this exists

Telegram already has Pyrogram, Telethon, and the official Telegram
Desktop. This project sits in a specific gap:

| Need | Existing tool | Why `tg-cli` |
|---|---|---|
| Read/send from a script | Telethon | Lower-level — you write the CLI yourself |
| Interactive terminal client | nchat | TUI, not scriptable |
| Quick scriptable CLI | kabi-tg-cli | Smaller surface, no media, no admin |
| MCP for Claude | chigwell/telegram-mcp | Online-only, no offline cache, no safety gates |
| Bulk export | iyear/tdl | Different category — Go binary, no live listener |

`tg-cli` is the standalone CLI with the **safety architecture** that
the others don't have: typed `--confirm <chat-id>` on destructive ops,
idempotency keys for safe retries, pre/post audit logging with shared
request IDs, and opt-in `--fuzzy` so an agent can't fat-finger which
chat to address.

## Quick links

- [Install](install.md) — `pip install tgctl` + .env setup
- [Quickstart](quickstart.md) — first 5 commands
- [Commands](commands.md) — full 62-command reference
- [Python SDK](sdk.md) — `from tgcli import Client`
- [Safety model](safety.md) — write gate, typed confirm, idempotency, audit log
- [Multi-account](multi-account.md) — isolated stores per account
- [Contributing](contributing.md) — for code contributors

## Status

- **v1.1.0** on PyPI — `pip install tgctl`
- 62 CLI commands across read / write / destructive / media / admin
- 255 tests, CI matrix on Ubuntu + macOS × Python 3.12, 3.13
- MIT licensed
