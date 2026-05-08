# Safety model

`tg-cli` runs against your real Telegram account. A misconfigured
agent that sends, forwards, or deletes the wrong thing has real
consequences — friends DM'd in error, messages permanently gone,
chats abandoned. The safety model is designed for that threat:
*the operator is a script that may be wrong*.

## The pipeline

Every write command passes through these gates in order:

```
parse args
   ↓
write gate: --allow-write or TG_READONLY rejection
   ↓
destructive gate (if applicable): typed --confirm <id>
   ↓
fuzzy gate: --fuzzy required for non-int / non-@username selectors
   ↓
dry-run short-circuit: print would-do envelope, exit 0
   ↓
local rate limiter (token bucket: 20 outbound / 60s default)
   ↓
audit_pre: NDJSON entry with shared request_id
   ↓
Telethon call
   ↓
audit_post: NDJSON entry with same request_id + result
   ↓
emit success / fail envelope
```

## Write gate (`--allow-write`)

Any command that hits Telegram requires `--allow-write` per
invocation. There is **no env var bypass** by design — a leaked shell
env on a script that runs occasionally would silently grant write
permission forever.

```bash
tg send @username "hi"                  # → exit 6: WRITE_DISALLOWED
tg send @username "hi" --allow-write    # → sends
```

To globally lock down a session against any write:

```bash
export TG_READONLY=1
```

This rejects writes even with `--allow-write` flagged. Use this in
scripts that are supposed to be pure-read.

## Destructive gate (typed `--confirm <id>`)

Destructive commands (`delete-msg`, `leave-chat`, `block-user`,
`promote`, `demote`, `ban-from-chat`, `kick`, `terminate-session`)
require `--confirm <id>` matching the **resolved** id, not just a flag.

```bash
tg delete-msg @hamid 99 --allow-write                    # → exit 7: NEEDS_CONFIRM
tg delete-msg @hamid 99 --allow-write --confirm @hamid    # ← rejected, must be the resolved chat_id
tg delete-msg @hamid 99 --allow-write --confirm 12345    # ← passes if resolver returned 12345
```

This catches the "agent meant to delete in Hamid's chat but resolver
matched Hamburg supergroup" failure mode that bare-flag confirms
allow.

## Fuzzy gate (`--fuzzy`)

Chat selectors resolve via three strategies in order:

1. **Integer chat_id** — exact match, always allowed
2. **`@username`** — exact match, always allowed
3. **Fuzzy substring on cached chat title** — allowed for reads,
   **rejected for writes unless `--fuzzy` is passed**

```bash
tg show Hambu                    # ← reads OK with fuzzy match
tg send Hambu "..." --allow-write    # ← exit 2 BAD_ARGS without --fuzzy
tg send Hambu "..." --allow-write --fuzzy    # ← OK
```

The point is to make agents commit to fuzzy resolution at call site
rather than silently accepting whatever the title-match returned.
For reads it doesn't matter (you can recover); for writes you can't.

## Idempotency keys

Every write command accepts `--idempotency-key <name>`. If the same
key + same command was previously committed, the cached result
envelope is returned **without** re-calling Telegram.

```bash
tg send @hamid "ack" --allow-write --idempotency-key reply-99-2026-05-08
```

Use case: an LLM-drafted reply pipeline that retries after
`FloodWaitError` (`exit 5`). The first attempt sends; the retry sees
the cached envelope and returns the prior `message_id` — no double-send.

The cache is per-account, in `accounts/<name>/telegram.sqlite`'s
`tg_idempotency` table. Same key reused for a *different* command
raises `BadArgs`.

## Audit log

Every write generates **two NDJSON entries** in `audit.log`:

```json
{"ts": "2026-05-08T11:18:21Z", "phase": "before", "request_id": "req-abc",
 "cmd": "messages.send", "actor": "agent", "resolved_chat_id": 12345,
 "resolved_chat_title": "Hamïd Ijadi", "args": {...}, "dry_run": false}
{"ts": "2026-05-08T11:18:22Z", "phase": "after", "request_id": "req-abc",
 "cmd": "messages.send", "result": "ok", "message_id": 99}
```

The pre-call entry is written *before* the Telethon call, so even if
the call hangs / crashes / times out, you know what was attempted.
The post-call entry shares the same `request_id` so retries are
linkable.

`audit.log` lives at `accounts/<name>/audit.log` and is append-only.
File permissions are 0600 (owner-only read/write).

## Local rate limiter

A token bucket caps outbound Telegram writes at 20 per 60 seconds
by default. Hitting it raises `LocalRateLimited` with a
`retry_after_seconds` field. This is your guard against an agent
loop that goes haywire.

The Telegram-side rate limit (`FloodWait`) is separate and stricter
when triggered. The local limit is more conservative — it gives you
time to notice and stop.

## Session lock

Only one process at a time can hold the Telethon session. The lock
is an `fcntl.flock` on `accounts/<name>/tg.session.lock`. Pass
`--lock-wait <secs>` to wait up to N seconds for the lock instead
of failing immediately.

## File permissions

Sensitive files in `accounts/<name>/` are chmod'd to owner-only:

| File | Mode |
|---|---|
| `tg.session` | 0600 |
| `telegram.sqlite` | 0600 |
| `audit.log` | 0600 |
| `tg.session.lock` | 0600 |
| Account directories | 0700 |

This is best-effort and never blocks the operation if it fails.

## Exit codes

| Code | Name | Meaning |
|---|---|---|
| 0 | OK | Command succeeded |
| 1 | GENERIC | Unclassified error |
| 2 | BAD_ARGS | Invalid args (or fuzzy-write without `--fuzzy`) |
| 3 | NOT_AUTHED | `TG_API_ID/HASH` not set or session expired |
| 4 | NOT_FOUND | Chat / message / folder not in DB or server |
| 5 | FLOOD_WAIT | Telegram rate-limited; check `retry_after_seconds` in envelope |
| 6 | WRITE_DISALLOWED | Write attempted without `--allow-write` (or `--read-only` mode) |
| 7 | NEEDS_CONFIRM | Destructive op without `--confirm <id>` |
| 8 | LOCAL_RATE_LIMIT | In-process rate limiter tripped |
| 9 | PREMIUM_REQUIRED | Telegram requires Premium for this action |
