# AGENTS.md — tg-cli

Agent-friendly Telegram CLI built on [Telethon](https://github.com/LonamiWebs/Telethon). All commands emit a uniform JSON envelope or human output; writes are gated behind `--allow-write`; every invocation logs to `audit.log`.

## Status

- **PyPI:** [`tgctl`](https://pypi.org/project/tgctl/) — `pip install tgctl`
- **GitHub:** <https://github.com/b1rd33/tg-cli>
- **Docs:** <https://b1rd33.github.io/tg-cli/>
- **Latest:** v1.0.1 (2026-05-08) — feature-complete, MIT licensed
- **CI:** Ubuntu + macOS × Python 3.12, 3.13 — green on `main`

## Quick reference (62 commands)

- **Read:** `stats`, `me`, `show`, `search`, `list-msgs`, `get-msg`, `contacts`, `unread`, `chats-info`, `topics-list`, `folders-list`, `folder-show`, `chat-pinned-list`, `chat-members`, `account-sessions`
- **Write — text:** `send`, `edit-msg`, `forward`, `pin-msg`, `unpin-msg`, `react`, `mark-read`
- **Write — media:** `upload-photo`, `upload-voice`, `upload-video`, `upload-document`
- **Write — topics:** `topic-create`, `topic-edit`, `topic-pin`, `topic-unpin`
- **Write — folders:** `folder-create`, `folder-edit`, `folder-delete`, `folder-add-chat`, `folder-remove-chat`, `folders-reorder`
- **Write — admin:** `chat-title`, `chat-photo`, `chat-description`, `set-permissions`, `chat-invite-link`, `unban-from-chat`
- **Destructive (typed `--confirm <id>`):** `delete-msg`, `leave-chat`, `block-user`, `promote`, `demote`, `ban-from-chat`, `kick`, `terminate-session`
- **Recoverable un-destructive:** `unblock-user`
- **Local-DB writers:** `sync-contacts`, `discover`, `backfill` (write only to `telegram.sqlite`, not to Telegram)
- **Live event stream:** `listen`
- **Auth:** `login`
- **Health:** `doctor`
- **Multi-account:** `accounts-add`, `accounts-use`, `accounts-list`, `accounts-show`, `accounts-remove`

### Python SDK (v0.4.0+)

```python
from tgcli import Client
c = Client(account="default")
me = await c.me()
data = c.stats()
result = await c.messages.send(chat=12345, text="...", allow_write=True)
```

Curated subset wired in v1.0; remaining commands available via CLI shell-out.

## Architectural facts

- Paths are env-overridable: `TG_DB_PATH`, `TG_SESSION_PATH`, `TG_AUDIT_PATH`, `TG_MEDIA_DIR`, `TG_API_ID`, `TG_API_HASH`, `TG_ACCOUNT`, `TG_READONLY`, `TG_ALLOW_WRITE`.
- Single-process Telethon session lock at `tg.session.lock` via `fcntl.flock`. `--lock-wait DURATION` lets you wait instead of fail-fast.
- All chat selectors resolve through `resolve_chat_db()` in three strategies: integer chat_id, `@username`, fuzzy title match. Fuzzy matches require `--fuzzy` for any write.
- Idempotency: every write command accepts `--idempotency-key NAME`. Same key + same command returns the cached envelope without re-calling Telegram.
- Read-only mode: `--read-only` or `TG_READONLY=1` rejects writes (Telegram-side AND local DB writes).
- Multi-account: `--account NAME` switches the active account directory at `accounts/<NAME>/`. Default is `default`.

## Exit codes (public contract)

```
0  OK                  command succeeded
1  GENERIC             unclassified error
2  BAD_ARGS            invalid args (or fuzzy-write without --fuzzy)
3  NOT_AUTHED          TG_API_ID/HASH not set or session expired
4  NOT_FOUND           chat / message / folder not in DB or server
5  FLOOD_WAIT          Telegram rate-limited; retry after `retry_after_seconds`
6  WRITE_DISALLOWED    write attempted without --allow-write (or --read-only mode)
7  NEEDS_CONFIRM       destructive op without --confirm (Phase 10+)
8  LOCAL_RATE_LIMIT    in-process write limiter tripped
9  PREMIUM_REQUIRED    Telegram requires Premium for this action
```

## Build / test

```
.venv/bin/pytest tests/tgcli -q     # unit tests
make gate                            # test + diff-check
./tg doctor --json                   # diagnose env + cache + (with --live) network
```

## Conventions

- Conventional Commits: `feat|fix|docs|refactor|test|chore|perf|security|ci(scope): subject`. Optional commit-msg hook at `.githooks/commit-msg`; install via `make install-hooks`.
- One commit per task on a `feat/phase-N-...` branch; squash-merge to main when phase complete.
- Audit log is append-only NDJSON at `audit.log`. Pre + post entries share `request_id`.

## Release process

- Tag `vX.Y.Z` on `main` after `make gate` is green.
- `git push origin vX.Y.Z` triggers `.github/workflows/release.yml` which builds with hatchling, publishes to PyPI via Trusted Publisher (no API token), and creates a GitHub release with auto-generated notes.
- Pages deploy of the docs site (`docs/` + `mkdocs.yml`) runs automatically on any push to `main` that touches them.

## Read me first if working on...

- **Adding a write command:** read `tgcli/commands/messages.py`'s `_send_runner` end-to-end. The pipeline is fixed: write gate → read text → idempotency lookup → resolver + fuzzy gate → dry-run short-circuit → rate limit → audit_pre → Telethon → record_idempotency → audit_post.
- **Adding a read command:** much simpler — just resolve the chat, query SQLite, return data dict.
- **Telethon API surface:** read the actual installed Telethon at `.venv/lib/python3.12/site-packages/telethon/tl/functions/`. Don't trust outdated docs.

## Gotchas

- Folder emoticons: Telegram has a curated allowlist; non-allowed emojis are silently dropped. `folder-create` round-trips and warns when this happens.
- Topic edits combining title + close/reopen: Telegram returns TOPIC_CLOSE_SEPARATELY. Runner auto-splits into two requests.
- Reactions: free accounts can't react in Saved Messages or many groups; `react` returns exit 9 PREMIUM_REQUIRED.
- Filter ids 0 and 1 are reserved server-side (`All chats`, `Archive`); user-created folders start at id 2.
- Backfill respects `--max-messages` (default 100k) and `--max-db-size-mb` (default 500); refuses to start if exceeded.
