# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-08

First public release. 46 commands, 202 tests, full read + write + destructive
Telegram operations.

### Added - Phase 1: Package refactor
- `tgcli/` package with separated env, db, client, commands modules
- Initial command set: login, stats, contacts, sync-contacts, show, backfill, discover, listen
- 9 unit tests covering env loading, credential guard, smoke

### Added - Phase 2: Output framework + safety gates
- JSON envelope output with `request_id`, `command`, `data`, `warnings` fields
- Exit code catalog (0-8)
- `--allow-write` write gate, `--dry-run`, `--idempotency-key`
- `audit.log` NDJSON append-only log
- `RateLimiter` token-bucket helper

### Added - Phase 3: Resolver + filters
- `resolve_chat_db()` with int / @username / fuzzy fallbacks
- `Ambiguous` and `NotFound` typed exceptions
- `--min-msgs` filter on `stats` and `contacts`

### Added - Phase 4: Read API expansion
- `me`, `search`, `list-msgs`, `get-msg`, `unread`, `chats-info`

### Added - Phase 6: Text write commands with safety pipeline
- `send`, `edit-msg`, `forward`, `pin-msg`, `unpin-msg`, `react`, `mark-read`
- Opt-in `--fuzzy` for write-side resolver
- Pre-call + post-call audit entries with shared request_id
- Idempotency replay via `tg_idempotency` table

### Added - Phase 6.1: Forum topics
- `topics-list`, `topic-create`, `topic-edit`, `topic-pin`, `topic-unpin`
- `--topic` flag on `send` and `forward`

### Added - Phase 6.2: Chat folders
- `folders-list`, `folder-show`, `folder-create`, `folder-edit`, `folder-delete`
- `folder-add-chat`, `folder-remove-chat`, `folders-reorder`

### Added - Phase 8: Wacli polish bundle
- `--read-only` / `TG_READONLY=1` global gate
- `--lock-wait DURATION` for transient session lock
- `--full` to disable column truncation
- `--max-messages` / `--max-db-size-mb` caps on backfill
- Owner-only file perms (0600/0700) on session, DB, audit, lockfile
- Path injection guard rejecting `?` and `#` in user paths
- `doctor` command with optional `--live`
- Multi-account support: `accounts-add`, `accounts-use`, `accounts-list`,
  `accounts-show`, `accounts-remove`; isolated stores under `accounts/<NAME>/`
- AGENTS.md top-level agent guide

### Added - Phase 9: Destructive commands with typed --confirm
- `delete-msg`, `leave-chat`, `block-user`, `unblock-user`,
  `account-sessions`, `terminate-session`
- Typed `--confirm <id>` matched against resolved chat/user/session id

[Unreleased]: https://github.com/b1rd33/tg-cli/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/b1rd33/tg-cli/releases/tag/v0.1.0
