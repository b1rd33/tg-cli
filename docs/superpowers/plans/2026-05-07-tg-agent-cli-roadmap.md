# tg-cli Roadmap — Phases 5+

**Last updated:** 2026-05-07

This is the priority-ordered list of remaining work after Phase 4. Each item below either points at an existing per-phase plan or signals "needs writing-plans skill before executing." Phase 1–4 are complete and merged to `main`.

## Status

| Phase | Status | Branch / commit |
|---|---|---|
| 1 — Package refactor | ✅ done | `main` (`dcfc298`) |
| 2 — Output framework + safety | ✅ done | `main` (`85cb0c9`) |
| 3 — Resolver + `--min-msgs` | ✅ done | `main` (`2ca4bea`) |
| 4 — Read API expansion | ✅ done | `main` (`1931ebe`) |
| **Sedex agent (in-progress)** | 🟡 prototype, uncommitted | working tree |

**Tests on main:** 80 passing.

## Active priority

**Sedex agent is the immediate priority** — the actual business application using the platform. Before any new platform phase:

1. Commit the in-progress Sedex code (`tgcli/sedex.py`, `tgcli/commands/sedex_agent.py`, modified `events.py` + `__main__.py`).
2. Add tests for `is_likely_shipping_inquiry` and `ShippingContextGate.should_forward` (English-positive, English-negative, Persian-positive, Persian-negative, follow-up-window — 5 cases minimum).
3. Add retry logic on `post_intake` failures (HTTP 5xx, network timeouts).
4. Hook Sedex events into `audit.log` for after-the-fact debugging.
5. Real-customer dry-run for one day before going live.

Phase 5+ resumes once Sedex is in production.

## Remaining platform phases (priority order)

### 🔴 Must-have for agent-ready CLI

#### Phase 5 — SDK extraction *(~1 day)*

**Goal:** Make `tgcli/commands/*.py` runners importable as Python functions, so Sedex / MCP / future LLM-drafted-reply code can call them directly without subprocess.

**Scope:**
- Refactor each command's runner to accept kwargs (or a typed `Request` object) instead of `argparse.Namespace`.
- Add `tgcli/__init__.py` exports: `from tgcli import Client`.
- `Client` class: holds Telethon client + DB connection, exposes `.me()`, `.chats.list()`, `.messages.search()`, `.listen()`, etc.
- CLI commands become 5-line wrappers that build kwargs from argparse and call the SDK.
- Sedex moved out of `tgcli/` into a sibling package `~/Projects/sedex-agent/` that depends on `tgcli`.

**Why first:** Unblocks Sedex from coupling to tgcli internals. Unblocks every later phase that wants in-process calls.

**Status:** ❌ no plan written yet. Use `superpowers:writing-plans` skill before executing.

---

#### Phase 6 — Write text commands *(~3 days)*

**Goal:** Ship `messages send`, `edit`, `forward`, `pin`, `unpin`, `react`, `mark-read` with the full safety pipeline.

**Scope (from master plan):**
- Write gate (`--allow-write` flag-only — no env-var bypass).
- Typed `--confirm <chat-id>` for destructive paths (e.g. `forward` to a bulk audience).
- Idempotency keys (`--idempotency-key`) so retries after FloodWait don't double-send.
- Opt-in `--fuzzy` for write-side resolver — fuzzy-matched chats reject writes without `--fuzzy` flag.
- Pre-call + post-call audit log entries with shared `request_id`.
- Local rate limiter (already in `tgcli/safety.py`) wired into outbound message paths.

**Why next:** Unlocks LLM-drafted replies for Sedex inquiries. The whole "50 messages a day → triage + auto-respond" pitch needs this.

**Status:** Outlined in master plan (`docs/superpowers/plans/2026-05-06-tg-agent-cli.md`), not yet detailed per-task. Use `superpowers:writing-plans` skill.

---

#### Phase 7 — MCP servers (read-only first) *(~2 days)*

**Goal:** Expose tgcli as MCP tools to Claude Code via three separate servers.

**Scope:**
- `tgcli_mcp/read_server.py` — exposes ~12 read-only tools: `tg_chats_list`, `tg_chats_info`, `tg_messages_list`, `tg_messages_search`, `tg_messages_get`, `tg_contacts_list`, `tg_me`, `tg_unread`, `tg_stats`, `tg_account_info`, `tg_account_sessions_list`, `tg_chats_discover`.
- Each tool's params schema derived from the SDK method signature (Phase 5 prerequisite).
- Wire to Claude Code: `claude mcp add tg-read /path/to/run.sh read`.
- Defer `write_server` and `destructive_server` until read-only is proven.

**Why third:** Read-only MCP is low-risk and immediately useful for inquiry analysis from Claude Code ("what shipping inquiries did I get today?"). Write/destructive servers can wait.

**Status:** Outlined in master plan, no per-phase detail yet. Steal the tool catalog shape from `chigwell/telegram-mcp` (~80-tool reference). Use `superpowers:writing-plans` skill.

---

#### Phase 8 — wacli polish bundle *(~2 days)*

**Goal:** Adopt the cheap, high-value ergonomics from openclaw/wacli.

**Scope:** 12 individual changes, each ≤30 minutes.
- `--read-only` / `TG_READONLY=1` global flag (binary kill-switch on writes)
- `--lock-wait DURATION` to wait for transient store locks before failing
- `--full` flag to disable table truncation
- Owner-only file perms (0700 dirs / 0600 files) on `tg.session`, `telegram.sqlite`, `audit.log`, `tg.session.lock`
- Reject `?` and `#` in user-supplied paths (SQLite URI injection prevention)
- `tg doctor` subcommand — diagnose session, DB, schema, FTS, live API connectivity
- `AGENTS.md` (copy from CLAUDE.md or alongside; works for any agent)
- `--max-messages` / `--max-db-size` caps on `backfill`
- Multi-account from one binary: `accounts add/use/list/show/remove` with isolated stores
- Send rate-limit warning on rapid succession
- PR full-gate: `format:check && lint && test && git diff --check`
- Conventional Commits enforcement

**Why fourth:** Quality-of-life and safety hardening once the surface is feature-complete.

**Status:** Itemized above; each is small enough to implement directly without a full per-phase plan.

---

### 🟡 Nice-to-have (real Telegram coverage, lower agent value)

#### Phase 9 — Media upload *(~1 day)*
- `media upload <chat> <file> [--caption T] [--reply-to ID] [--as voice|video|document|photo]`
- File-path allowlist with deny-by-default (steal from chigwell/telegram-mcp)
- 100 MB cap (steal from wacli)
- Already have `media download` from Phase 1.

#### Phase 10 — Destructive *(~1 day)*
- `messages delete`, `chats leave`, `contacts remove`, `contacts block/unblock`, `account sessions terminate`
- All gated behind `--allow-write` + typed `--confirm <id>`
- `tg-destructive-*` MCP tool prefix (extend Phase 7 to add destructive server)

#### Phase 11 — Chat lifecycle *(~1 day)*
- `chats join/leave/mute/unmute/archive/unarchive/title`, `contacts add`
- Mostly thin Telethon wrappers behind the existing safety pipeline

#### Phase 12 — Account *(~0.5 day)*
- `account info`, `account sessions list`, `account sessions terminate`, `account export-data`

#### Phase 13 — `events tail` NDJSON *(~0.5 day)*
- Live event stream as line-delimited JSON for non-Python consumers
- Different from `listen` — produces stdout, not DB writes
- Skip if all consumers stay Python (use the SDK instead)

---

### ⚪ Skip / out of scope

These were considered and explicitly dropped:
- `tg api <method>` raw MTProto escape hatch — bypasses safety, dropped post-Codex review
- Voice/video calls — beyond user-bot scope
- Stories
- Secret/encrypted chats — Telethon support is poor
- Custom-emoji reactions — Premium-only, niche
- Poll creation — niche
- Webhook fan-out — wacli has it, our use case doesn't need it (Sedex calls HTTP directly)

---

## Realistic timeline (platform only, excluding Sedex work)

| Track | Days | Calendar at 4hr/day |
|---|---|---|
| **Must-haves** (Phases 5–8) | ~8 working days | ~2 weeks |
| **Plus nice-to-haves** (Phases 9–13) | +~4 working days | ~3 weeks total |

Practical-minimal (skip Phase 11 lifecycle + Phase 13 NDJSON): **~6 working days** to feature-complete agent-ready CLI.

---

## How to pick up the next phase

1. **Sedex work pending?** Finish that first (commit, test, harden, deploy).
2. **Otherwise:** start Phase 5 (SDK extraction).
3. Use `superpowers:writing-plans` to draft a per-phase plan in `docs/superpowers/plans/2026-MM-DD-tg-agent-cli-phase-N.md`.
4. Codex-review the plan with `codex:rescue` agent before executing.
5. Use `superpowers:executing-plans` (or `subagent-driven-development`) to ship the phase.
6. Squash-merge to `main` when phase done.
7. Update this roadmap (move the phase to "Status" table).

## Things to remember from earlier reviews

These came up in Codex review of the master plan and the wacli/competitor analysis. Don't lose them:

- **Idempotency keys** (`--idempotency-key`) on every write op — Phase 6 must include this.
- **Typed `--confirm <id>`** not bare flag — Phase 6 + Phase 10.
- **Opt-in `--fuzzy` for writes** — fuzzy-resolved chat IDs reject writes without the flag. Phase 6.
- **Three-tier MCP topology** — separate servers for read / write / destructive. Phase 7 + Phase 10.
- **Pre-call + post-call audit entries** with shared `request_id`. Phase 6.
- **Sanitize tool output** in MCP servers (control-char + invisible-char strip; prompt-injection mitigation). Phase 7. Steal from chigwell/telegram-mcp.
- **`ToolAnnotations(readOnlyHint=True, destructiveHint=True)`** on each MCP tool. Phase 7 + Phase 10.
- **Owner-only file perms** on session/DB/audit. Phase 8.
- **Multi-account isolated stores from day one.** Phase 8 — easier to design now than retrofit.

## Reference plans to read before each phase

- Master plan: `docs/superpowers/plans/2026-05-06-tg-agent-cli.md`
- Phase 2 plan: `docs/superpowers/plans/2026-05-06-tg-agent-cli-phase-2.md`
- Phase 3 plan: `docs/superpowers/plans/2026-05-07-tg-agent-cli-phase-3.md`
- (Phase 4 plan does not exist — was executed inline)

External references worth reading once before MCP work:
- `chigwell/telegram-mcp` — ~80 MCP tool catalog. Treat as Phase 7 spec source.
- `openclaw/wacli` — `AGENTS.md`, doctor command, multi-account, audit patterns.
