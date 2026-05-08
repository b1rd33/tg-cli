# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.1] - 2026-05-08

Polish release. No code or behavior changes.

### Added
- MkDocs Material documentation site at <https://b1rd33.github.io/tg-cli/>
  with 8 pages (home, install, quickstart, commands, SDK, safety,
  multi-account, contributing).
- Telethon attribution: linked in the README lede, in a new Credits
  section, and as `[project.urls]` "Built on Telethon" upstream link.
- `telegram-client` keyword in `pyproject.toml` for PyPI search hits.
- `[docs]` optional dep group: `pip install -e .[docs]`.

### Changed
- README structure: CLI examples moved up after Quick start; Python
  SDK section moved to the bottom (before Contributing).
- `tg` shell wrapper comment cleaned up (dropped the stale
  "or tg_scrape.py during transition" reference).
- Test fixtures sanitized: replaced real-contact names + usernames
  in `test_resolve.py` and `test_messages.py` with synthetic fixtures
  preserving the diacritic / case-fold / fuzzy-disambiguation invariants.

## [1.0.0] - 2026-05-08

Symbolic feature-complete release. The full surface — read, write,
destructive, media, admin, plus the Python SDK — is now stable.

### Naming
- PyPI distribution name: `tgctl` (`pip install tgctl`). The
  shorter `tgcli` and `tg-cli` names are taken / collide on
  PyPI's similarity check. The binary remains `tg`, the Python
  import remains `from tgcli import Client`, and the GitHub repo
  remains `b1rd33/tg-cli`.

### Surface
- 62 CLI commands (up from 46 at v0.1.0)
- Python SDK: `from tgcli import Client` with on-demand method coverage
- 246 tests covering CLI runners, dispatch, safety gates, idempotency,
  multi-account, and the SDK

### Capabilities by phase
- Phase 1–4: package refactor, JSON envelope output, exit-code catalog,
  resolver with int / @username / fuzzy fallbacks, basic read API
- Phase 6–6.2: text writes (send, edit-msg, forward, pin, react,
  mark-read), forum topics, chat folders
- Phase 8: read-only mode, lock-wait, owner-only file perms, path
  injection guard, doctor command, multi-account
- Phase 9: destructive commands with typed `--confirm <id>`
- Phase 10: open-source readiness (LICENSE, pyproject.toml, CI,
  CHANGELOG, README, ruff baseline)
- Phase 12: media upload (photo, voice, video, document)
- Phase 13: channel/group admin (12 commands incl. promote, demote,
  ban, kick, set-permissions, chat-invite-link, chat-members)
- Phase 11: Python SDK — `from tgcli import Client`, write-gate
  enforcement, single-account-per-process

### No code changes from v0.4.0
This release is the symbolic 1.0 bump only. The bits on PyPI and the
v0.4.0 wheel are functionally identical.

## [0.4.0] - 2026-05-08

### Added - Phase 11: SDK extraction
- `from tgcli import Client` — Python SDK for embedding tg-cli in
  external Python apps; namespace surface (`messages`, `chats`,
  `topics`, `folders`, `contacts`, `media`, `accounts`, `admin`) plus
  `c.me()` and `c.stats()` at the top level
- Wired methods (v0.4.0): `c.me()`, `c.stats()`, `c.messages.show()`,
  `c.messages.send()`, `c.admin.chat_title()`. Remaining runners stay
  CLI-only and can be added on demand
- Same safety gates as the CLI: `allow_write=True` required on writes,
  typed `confirm=<id>` on destructive ops, `WriteDisallowed` raised on
  bypass attempts
- Single-account-per-process: `Client(account=X)` validates against the
  account frozen at import time and raises `RuntimeError` on mismatch
- Wrapper-not-rewrite: existing 62 CLI runners untouched, all 235
  prior tests still pass + 11 new SDK tests

## [0.3.0] - 2026-05-08

### Added - Phase 13: Channel/group admin commands
- `chat-title`, `chat-photo`, `chat-description`
- `promote`, `demote`, `ban-from-chat`, `kick`, `unban-from-chat`
- `set-permissions` with multi-flag permissions and `--review`
- `chat-invite-link` for invite generation and revocation
- `chat-pinned-list` and `chat-members` read commands
- Typed `--confirm <chat-id>` for destructive admin operations, plus affected-user
  pre-call audit payloads

## [0.2.0] - 2026-05-08

Phase 11 SDK extraction is deferred. Phase 12 media upload commands take the
`0.2.0` version slot.

### Added - Phase 12: Media upload commands
- `upload-photo`, `upload-voice`, `upload-video`, `upload-document`
- Shared write safety pipeline: `--allow-write`, `--dry-run`,
  `--idempotency-key`, write-side `--fuzzy`, and audit logging
- Magic-byte MIME validation for photos, OGG/Opus voice notes, and videos
- Upload path safety checks and file size caps via `--max-size-mb`

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

[Unreleased]: https://github.com/b1rd33/tg-cli/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/b1rd33/tg-cli/compare/v0.4.0...v1.0.0
[0.4.0]: https://github.com/b1rd33/tg-cli/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/b1rd33/tg-cli/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/b1rd33/tg-cli/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/b1rd33/tg-cli/releases/tag/v0.1.0
