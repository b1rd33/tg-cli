# Final OSS Release Plan — `tg-cli`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Date:** 2026-05-08
**Author:** Claude (in main session, after spawning blocked codex-rescue agent)
**Status:** Phase 10 ✅ done locally (`8bb4a43`, tagged `v0.1.0`); awaiting GitHub push + PyPI publish + Phase 11

**Strategy:** Quiet release. Goal is "make it correctly public so Sedex (separate repo) can `pip install tg-cli`, and people can find it via search". **No marketing, no Show HN, no Reddit announcements.** If the project finds users organically, great. If not, no harm done — it's still useful for personal use and as a Sedex dependency.

## Status board (live)

| Item | Status | Notes |
|---|---|---|
| **Phase 10 — local artifacts** | ✅ done | commit `8bb4a43`, tag `v0.1.0` |
| LICENSE (MIT) | ✅ | 21 lines |
| pyproject.toml (hatchling) | ✅ | 101 lines |
| CHANGELOG.md | ✅ | 67 lines, retroactive Phases 1–9 |
| README.md | ✅ rewrite | 164 lines |
| .github/workflows/ci.yml | ✅ | 30 lines |
| .github/workflows/release.yml | ✅ | 29 lines |
| ruff baseline + RUF043 fix | ✅ | 48 files reformatted |
| `python -m build` | ✅ | wheel + sdist in dist/ |
| `twine check dist/*` | ✅ | both PASSED |
| Smoke install in fresh venv | ✅ | `tg --help` works |
| 202 tests | ✅ | all passing (1 known-flaky session-lock test) |
| **Git author email** | ✅ kept as `christian@tabulara.de` | Owner's decision: real email is fine for public OSS |
| **Create GitHub repo** | ❌ pending | `b1rd33/tg-cli` not yet created |
| **`git push origin main`** | ❌ pending | once repo exists |
| **PyPI Trusted Publisher** | ❌ pending | manual one-time setup |
| **`git push origin v0.1.0`** | ❌ pending | triggers PyPI publish + GitHub release |
| **Phase 11 — SDK** | ⏳ deferred | trigger when Sedex starts |
| **Phase 12 — media** | ⏳ optional | only if wanted |
| **Phase 13 — admin** | ⏳ optional | only if wanted |
| **Phase 14 — v1.0.0** | ⏳ optional | symbolic bump |

## Lessons from Phase 10 execution

The codex agent deviated mid-execution: when its sandbox couldn't fetch `hatchling`, it built a custom 150-line `_tg_build_backend.py` instead of failing or asking. The user reverted to the planned hatchling backend, deleted the custom file, and rebuilt cleanly.

Takeaway for future agent dispatches:
- Plans should explicitly say "if a sandbox/network issue blocks a planned dependency, STOP and report — do not invent alternatives".
- Codex agents may run silently and exit without committing; `git status` after dispatch is mandatory before assuming work landed.

## Executive summary

- **Name:** `tg-cli` on PyPI + GitHub. `tgcli` Python import name preserved (already in codebase). PyPI confirmed available.
- **License:** MIT, matching Telethon (the core dependency) and openclaw/wacli (the closest-shape competitor).
- **Packaging:** `hatchling` build backend, single `pyproject.toml`, version read from `tgcli/__init__.py:__version__` (already there as `0.1.0`).
- **Release sequence:** Phase 10 ships v0.1.0 to PyPI + GitHub immediately with current 46 commands → Phase 11 SDK ships v0.2.0 (needed for Sedex) → Phases 12/13 (media + admin) are optional, ship if/when needed.
- **Total effort to public:** ~3–4 hours (Phase 10 only). Phase 11 (~1 day) follows when Sedex needs it.

## Differentiation reality check

The safety architecture is genuinely novel — no existing Telegram CLI has these:

1. Typed `--confirm <id>` matched against resolved chat/user/session id
2. Idempotency keys with envelope replay
3. Pre-call + post-call audit log with shared `request_id`
4. Opt-in `--fuzzy` required for write commands
5. fcntl session lock preventing concurrent corruption
6. `--read-only` global gate cascading to local DB writes
7. `doctor` health check with optional `--live` ping

Outside of those, we overlap with two competitors:

- **kabi-tg-cli** (jackwener/tg-cli, 230 stars, 60 days stale) — covers ~70% of our CLI surface with simpler code. Wins on: time-window analytics (`today / recent / top / timeline`) and YAML output as agent default. Loses on: no media, no destructive ops, no folders/topics, no safety architecture.
- **chigwell/telegram-mcp** (1,067 stars, actively developed) — has 80+ MCP tools and broader Telegram primitive coverage. Wins on: media upload, output sanitization, Docker. **Loses on: MCP-only (no standalone CLI), no local SQLite cache (every read hits Telegram online), no live event listener, none of the safety architecture.**
- **iyear/tdl** — different category (Go bulk download/forward).

What we should consider stealing (cheap, would close gaps):
- kabi's `today / recent / top / timeline` analytics commands (~2 hrs to add)
- chigwell's `sanitize.py` for prompt-injection mitigation in JSON output (~30 min to copy)

Honest README pitch: *"Standalone Telegram CLI with safety architecture for unattended agent use — the typed confirm + idempotency + audit log + opt-in fuzzy that no other tool has. Local-first SQLite cache. MIT, `pip install tg-cli`."*

Don't oversell as "the only" or "the best" — kabi and chigwell exist and are honest competition.

---

## Decisions

### Name: `tg-cli` (PyPI + GitHub) / `tgcli` (Python import)

**PyPI availability** (confirmed via direct API check at planning time):

| Candidate | PyPI status |
|---|---|
| `tgcli` | ❌ TAKEN (Eray Erdin's 2019 dormant project, last release 2019-09, never reached 1.0) |
| **`tg-cli`** | **✅ AVAILABLE** |
| `telegram-cli` | ❌ taken |
| `tgkit`, `tg-pro`, `tgctl`, `tgshell`, `tg-archiver`, `tgmate`, `kris-tg`, `telegram-agent` | ✅ available |

`tg-cli` is the obvious pick:
- Matches the directory name (`~/Projects/tg-cli/`)
- Matches the binary name (`./tg`)
- The hyphen is the PyPI convention; `pip install tg-cli` reads naturally
- Maps to Python module `tgcli` automatically (no underscore wrangling)
- Avoids the squatter on `tgcli`

GitHub repo name: `tg-cli` under the existing user account (commit author `b1rd33`). Recommend `b1rd33/tg-cli`. Consider creating an `openclaw`-style org if multiple related projects emerge later (Sedex, etc.) — defer.

### License: MIT

**Why MIT:**
- Telethon (core dep) is MIT — license compatibility is automatic
- openclaw/wacli (closest reference project) is MIT — community familiarity
- Maximally permissive — any contributor or downstream user understands it without legal review
- Single-paragraph license file, no patent grant complexity
- Matches typical Python CLI tool norm (e.g. httpie, click, rich)

**What we're not picking and why:**
- Apache 2.0: stronger but adds a patent grant clause that's overkill for a personal CLI; rare for Python tools
- AGPL-3.0 (iyear/tdl chose this): viral, deters commercial use; wrong fit for an SDK others should embed
- BSD-3-Clause: functionally similar to MIT but less common in Python world

Copyright line: `Copyright (c) 2026 Kris (b1rd33)`.

### Packaging: hatchling, pyproject.toml only, no setup.py

**Why hatchling:**
- Modern, PEP 621 compliant
- Zero-config for simple packages
- Reads version dynamically from `tgcli/__init__.py:__version__` (DRY)
- No need for setup.py, MANIFEST.in, or setup.cfg
- Maintained by PyPA, won't disappear like poetry's churn

Build backend: `hatchling`. Frontend: `pip` (we don't need poetry, hatch, uv for the user — they can use any).

### Python version: 3.12+

Current dev environment is 3.12.2. f-strings with `=`, `match`/`case`, `from __future__ import annotations` everywhere — we use modern syntax. Supporting older Pythons requires backport pain that nobody asked for.

Declare: `requires-python = ">=3.12"`.

### Versioning: SemVer

Standard MAJOR.MINOR.PATCH. Already at 0.1.0 in the codebase. Releases below 1.0.0 signal "API may change without bump". After channel/group admin lands and the surface stabilizes, bump to 1.0.0.

### Linting / formatting: ruff (added in Phase 10)

Single tool replaces black + flake8 + isort. Fast, zero-config out of the box, increasingly the default for new Python projects in 2026.

Add a minimal `pyproject.toml [tool.ruff]` block. CI runs `ruff check && ruff format --check`. **Don't** enforce in pre-commit hooks initially — let the user opt into the friction later.

### Author email: switch to GitHub noreply

**Current commits:** `b1rd33 <christian@tabulara.de>`. Personal email visible in git log forever once pushed.

**Recommendation:** before first push, run:
```bash
git config user.email "b1rd33@users.noreply.github.com"
```
This applies only to NEW commits (existing history retains real email). Trade-off:
- Keeping real email: most OSS authors do this; it's the norm
- Switching to noreply: privacy, no spam scraping, but less identifiable

For a personal project that may attract attention, **switch to noreply going forward**. Don't rewrite history — the volume of past commits with real email is small (11 commits, all this week) and rewrite invalidates plan-doc cross-references.

---

## Phase 10 — Open-source readiness pass (~3-4 hrs)

Goal: ship `v0.1.0` to PyPI + GitHub with what's already built. No new features. Just professional packaging.

### Files to create

**`LICENSE`** (MIT, exact text):

```
MIT License

Copyright (c) 2026 Kris (b1rd33)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**`pyproject.toml`** (full content, ready to copy):

```toml
[build-system]
requires = ["hatchling>=1.18"]
build-backend = "hatchling.build"

[project]
name = "tg-cli"
description = "Agent-friendly Telegram CLI built on Telethon — read, write, archive your Telegram from the terminal."
readme = "README.md"
license = "MIT"
license-files = ["LICENSE"]
requires-python = ">=3.12"
authors = [
  { name = "Kris", email = "b1rd33@users.noreply.github.com" },
]
keywords = ["telegram", "cli", "mtproto", "telethon", "automation", "agent"]
classifiers = [
  "Development Status :: 4 - Beta",
  "Environment :: Console",
  "Intended Audience :: Developers",
  "License :: OSI Approved :: MIT License",
  "Operating System :: MacOS",
  "Operating System :: POSIX :: Linux",
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Topic :: Communications :: Chat",
  "Topic :: Utilities",
]
dependencies = [
  "telethon>=1.43,<2",
]
dynamic = ["version"]

[project.optional-dependencies]
dev = [
  "pytest>=9.0",
  "ruff>=0.6",
]

[project.scripts]
tg = "tgcli.__main__:main"

[project.urls]
Homepage = "https://github.com/b1rd33/tg-cli"
Repository = "https://github.com/b1rd33/tg-cli"
Issues = "https://github.com/b1rd33/tg-cli/issues"
Changelog = "https://github.com/b1rd33/tg-cli/blob/main/CHANGELOG.md"

[tool.hatch.version]
path = "tgcli/__init__.py"

[tool.hatch.build.targets.wheel]
packages = ["tgcli"]

[tool.hatch.build.targets.sdist]
include = [
  "tgcli/",
  "AGENTS.md",
  "CHANGELOG.md",
  "LICENSE",
  "README.md",
  "pyproject.toml",
]
exclude = [
  "accounts/",
  "media/",
  ".venv/",
  "tests/",
  "docs/",
  ".env*",
  "*.session*",
  "audit.log",
  "telegram.sqlite*",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "RUF"]
ignore = ["E501"]  # let formatter handle line length

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
```

**`CHANGELOG.md`** (starter — covers all 9 phases retroactively):

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-05-08

First public release. 46 commands, 202 tests, full read + write + destructive
Telegram operations.

### Added — Phase 1: Package refactor
- `tgcli/` package with separated env, db, client, commands modules
- Initial command set: login, stats, contacts, sync-contacts, show, backfill, discover, listen
- 9 unit tests covering env loading, credential guard, smoke

### Added — Phase 2: Output framework + safety gates
- JSON envelope output with `request_id`, `command`, `data`, `warnings` fields
- Exit code catalog (0–8)
- `--allow-write` write gate, `--dry-run`, `--idempotency-key`
- `audit.log` NDJSON append-only log
- `RateLimiter` token-bucket helper

### Added — Phase 3: Resolver + filters
- `resolve_chat_db()` with int / @username / fuzzy fallbacks
- `Ambiguous` and `NotFound` typed exceptions
- `--min-msgs` filter on `stats` and `contacts`

### Added — Phase 4: Read API expansion
- `me`, `search`, `list-msgs`, `get-msg`, `unread`, `chats-info`

### Added — Phase 6: Text write commands with safety pipeline
- `send`, `edit-msg`, `forward`, `pin-msg`, `unpin-msg`, `react`, `mark-read`
- Opt-in `--fuzzy` for write-side resolver
- Pre-call + post-call audit entries with shared request_id
- Idempotency replay via `tg_idempotency` table

### Added — Phase 6.1: Forum topics
- `topics-list`, `topic-create`, `topic-edit`, `topic-pin`, `topic-unpin`
- `--topic` flag on `send` and `forward`

### Added — Phase 6.2: Chat folders
- `folders-list`, `folder-show`, `folder-create`, `folder-edit`, `folder-delete`
- `folder-add-chat`, `folder-remove-chat`, `folders-reorder`

### Added — Phase 8: Wacli polish bundle
- `--read-only` / `TG_READONLY=1` global gate
- `--lock-wait DURATION` for transient session lock
- `--full` (disable column truncation)
- `--max-messages` / `--max-db-size-mb` caps on backfill
- Owner-only file perms (0600/0700) on session, DB, audit, lockfile
- Path injection guard (rejects `?` and `#` in user paths)
- `doctor` command with optional `--live`
- Multi-account support: `accounts-add`, `accounts-use`, `accounts-list`,
  `accounts-show`, `accounts-remove`; isolated stores under `accounts/<NAME>/`
- AGENTS.md (top-level agent guide)

### Added — Phase 9: Destructive commands with typed --confirm
- `delete-msg`, `leave-chat`, `block-user`, `unblock-user`,
  `account-sessions`, `terminate-session`
- Typed `--confirm <id>` matched against resolved chat/user/session id

[Unreleased]: https://github.com/b1rd33/tg-cli/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/b1rd33/tg-cli/releases/tag/v0.1.0
```

**`.github/workflows/ci.yml`** (full content):

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e ".[dev]"
      - name: Lint with ruff
        run: |
          ruff check .
          ruff format --check .
      - name: Run pytest
        run: pytest tests/tgcli -v
```

**`.github/workflows/release.yml`** (publishes to PyPI on tag):

```yaml
name: Release

on:
  push:
    tags:
      - "v*"

jobs:
  release:
    runs-on: ubuntu-latest
    permissions:
      id-token: write  # for PyPI Trusted Publisher
      contents: write  # for GitHub release
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Build distributions
        run: |
          python -m pip install --upgrade pip build
          python -m build
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          generate_release_notes: true
          files: dist/*
```

(Trusted Publisher setup: register `tg-cli` on PyPI under the user's account, then in PyPI project settings add a "Trusted Publisher" pointing at `b1rd33/tg-cli` GitHub repo, workflow `release.yml`, environment unset. No API token needed.)

**`README.md`** (full rewrite — outline):

- Title + 1-line tagline + badges (PyPI version, CI status, Python version, license)
- 1-paragraph description: what it is, what it's for, who it's for
- Animated demo (asciinema or screenshot) — optional, can ship later
- Quick start (3 commands: install, login, stats)
- Feature list (collapsed: read / write / live / multi-account / safety / observability)
- Full commands table (alphabetical, 1-line per command)
- "Why this exists" / comparison vs `kabi-tg-cli`, `chigwell/telegram-mcp`, `iyear/tdl`, `nchat`
- Configuration (env vars, .env, multi-account)
- Architecture (1-paragraph + diagram)
- Safety model (write gate, typed confirm, idempotency, audit log)
- Contributing (links to AGENTS.md, plan structure)
- License

**Skeleton ready to fill in:**

```markdown
# tg-cli

[![PyPI](https://img.shields.io/pypi/v/tg-cli.svg)](https://pypi.org/project/tg-cli/)
[![CI](https://github.com/b1rd33/tg-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/b1rd33/tg-cli/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/tg-cli.svg)](https://pypi.org/project/tg-cli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Agent-friendly Telegram CLI** built on Telethon. Read, write, archive,
and listen to your own Telegram account from the terminal — with JSON
output, idempotency, audit log, multi-account, and explicit safety gates
for autonomous-agent use.

## Quick start

\`\`\`bash
pip install tg-cli
echo "TG_API_ID=12345678" > .env  # from https://my.telegram.org/apps
echo "TG_API_HASH=abcdef..." >> .env
tg login
tg stats
\`\`\`

## Features

- **46 commands** covering read, write, and destructive Telegram operations
- **Multi-account** with isolated session/db/audit per account
- **JSON envelope output** for clean agent integration
- **Typed `--confirm <id>`** on destructive ops; idempotency keys; audit log
- **Local SQLite cache** for offline queries

## Commands at a glance

[generated table here]

## Why tg-cli?

[comparison vs kabi-tg-cli / chigwell-telegram-mcp / iyear-tdl / nchat]

## Configuration

[env vars table]

## Multi-account

[accounts-add example]

## Safety

[--allow-write, --confirm, --dry-run, --read-only, audit.log]

## Architecture

[1-para + simple diagram]

## Contributing

See [AGENTS.md](AGENTS.md) for the project's working conventions and
[docs/superpowers/plans/](docs/superpowers/plans/) for the design history.

## License

MIT — see [LICENSE](LICENSE).
```

(Real prose generated during execution — outline is intentionally a skeleton so the executing agent fills it with current accurate facts.)

**`.gitignore`** (additions):

```
# Build artifacts
dist/
build/
*.egg-info/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
```

### Other Phase 10 housekeeping

- Update `tgcli/__init__.py:__version__` from `"0.1.0"` to … `"0.1.0"` (already correct; but verify after the release flow runs once)
- Add a `MANIFEST.in`? **No** — hatchling reads from `pyproject.toml [tool.hatch.build]`, MANIFEST.in is a setuptools artifact
- Switch git author email: `git config user.email "b1rd33@users.noreply.github.com"` (only future commits affected)
- Run `ruff check .` and `ruff format --check .` once; fix anything that comes up (likely a few minor style fixes — they're not blocking)

### Verification before tag

```bash
make gate                         # existing — runs tests + diff-check
ruff check .                      # new
ruff format --check .             # new
python -m build                   # produces dist/tg_cli-0.1.0-*.whl + .tar.gz
twine check dist/*                # validates package metadata
pip install dist/tg_cli-0.1.0-*.whl --force-reinstall --target /tmp/tg-test
PYTHONPATH=/tmp/tg-test /tmp/tg-test/bin/tg --help  # verify entry point works
```

### Tagging + push

```bash
git add LICENSE pyproject.toml CHANGELOG.md README.md .github/workflows/ .gitignore
git commit -m "feat(tg-cli): v0.1.0 — open-source readiness pass

LICENSE (MIT), pyproject.toml (hatchling), CI + release workflows,
CHANGELOG retroactively covering Phases 1–9, full README rewrite.

Ready for PyPI publication and public GitHub repo.

[v0.1.0]"
git tag -a v0.1.0 -m "v0.1.0 — first public release"
git remote add origin https://github.com/b1rd33/tg-cli.git
git push -u origin main
git push origin v0.1.0  # triggers release.yml → PyPI publish + GitHub release
```

### Done when

- [ ] LICENSE + pyproject.toml + CHANGELOG.md + README.md committed
- [ ] CI workflow passes on a test branch
- [ ] `python -m build` produces valid sdist + wheel
- [ ] PyPI Trusted Publisher configured for `tg-cli` ↔ `b1rd33/tg-cli`
- [ ] `git push` succeeds
- [ ] `pip install tg-cli` works in a fresh venv
- [ ] GitHub release `v0.1.0` visible at https://github.com/b1rd33/tg-cli/releases

---

## Phase 11 — SDK extraction (~1 day)

Goal: expose `from tgcli import Client` so external Python apps (Sedex, future LLM-drafted-reply systems, custom agents) can call tgcli without subprocess. Tag `v0.2.0`.

### API shape

```python
from tgcli import Client

# Default: reads .env, uses default account
c = Client()

# Or explicit
c = Client(account="work", api_id=123, api_hash="...", session_path=Path("..."))

# Read methods (sync where DB-only, async where Telegram-side)
me = await c.me()                            # User dict
chats = c.chats.list(min_msgs=5)             # sync — DB only
chat = await c.chats.info(chat="@hamid")     # async — fetches latest
msgs = c.messages.list(chat=12345, limit=50) # sync
msg = c.messages.get(chat=12345, msg_id=99)  # sync
hits = c.messages.search("shipping", chat="@hamid")  # sync

# Write methods (all async)
result = await c.messages.send(
    chat=12345,
    text="hello",
    allow_write=True,           # required (Pythonic equivalent of --allow-write)
    idempotency_key="abc123",   # optional
    fuzzy=False,                # default; enable to allow fuzzy chat selectors
)
# result is the same envelope shape: {"ok": True, "data": {...}, "request_id": ...}

await c.messages.edit(chat=..., msg_id=..., text="...", allow_write=True)
await c.messages.forward(...)
await c.messages.delete(..., allow_write=True, confirm=12345)  # typed confirm
await c.messages.react(...)
await c.messages.mark_read(...)

# Topics
await c.topics.create(...)
topics = c.topics.list(chat=12345)

# Folders
folders = c.folders.list()
await c.folders.create(...)

# Live listener
async for event in c.listen():
    print(event.message_id, event.text)

# Multi-account explicit
work = Client(account="work")
me = await work.me()
```

### Refactor strategy

The existing command runners already return data dicts (see Phase 2 dispatch architecture). The SDK extraction is mechanical:

1. **For each `tgcli/commands/X.py`**, identify the `_runner()` functions (e.g. `_send_runner`, `_show_runner`).
2. **Promote runner signatures** from `(args: argparse.Namespace)` to typed kwargs:
   ```python
   # Before
   async def _send_runner(args):
       chat = await resolve_chat_db(...)
       ...
   # After
   async def send(*, chat, text, allow_write=False, idempotency_key=None,
                  fuzzy=False, dry_run=False, reply_to=None, silent=False,
                  no_webpage=False) -> dict:
       ...
   ```
3. **CLI runners become 5-line shims** that build kwargs from `args` and call the SDK function:
   ```python
   async def _send_runner(args):
       return await send(
           chat=args.chat, text=args.text, allow_write=args.allow_write,
           idempotency_key=args.idempotency_key, fuzzy=args.fuzzy,
           dry_run=args.dry_run, reply_to=args.reply_to, silent=args.silent,
           no_webpage=args.no_webpage,
       )
   ```
4. **Wire `Client` class** in `tgcli/__init__.py` (or new `tgcli/client_sdk.py` to avoid name collision with existing `tgcli/client.py`):
   ```python
   class Client:
       def __init__(self, account="default", **kwargs): ...
       
       @cached_property
       def messages(self): return _MessagesNamespace(self)
       @cached_property
       def chats(self): return _ChatsNamespace(self)
       # ... topics, folders, contacts, accounts
   
   class _MessagesNamespace:
       def __init__(self, client): self._c = client
       async def send(self, **kwargs):
           from tgcli.commands.messages import send as _send
           return await _send(_client=self._c, **kwargs)
       # ... etc
   ```
5. **Dispatch still wraps the SDK call** for the CLI path. The SDK call returns a data dict; CLI dispatch wraps it in the envelope. SDK callers get the envelope shape directly (consistent surface). This means SDK does NOT bypass safety gates — they live inside the runner functions themselves, not in dispatch.

### What needs to change in safety / dispatch

- `require_write_allowed(args)` currently reads `args.allow_write` — refactor to take a plain bool: `require_write_allowed(allow_write: bool)`. CLI runners pass `args.allow_write`, SDK callers pass the kwarg directly.
- Same for `require_explicit_or_fuzzy(args, raw_selector)` → `require_explicit_or_fuzzy(fuzzy: bool, raw_selector: str)`.
- `audit_pre()` and `audit_write()` already take kwargs — no change.
- Dispatch layer remains for the CLI path; SDK path is dispatch-free.

### Tests

Add `tests/tgcli/test_sdk.py`:
- Import `from tgcli import Client` succeeds
- `Client().chats.list()` returns list of dicts
- `await Client().me()` returns a User dict with `id`, `first_name`
- `await Client().messages.send(chat=X, text="...", allow_write=True, dry_run=True)` returns a `would-do` envelope without calling Telegram
- `await Client().messages.send(...)` without `allow_write=True` raises `WriteDisallowed`
- ~10 tests covering the major methods

### Tag and bump

- Update `tgcli/__init__.py:__version__` to `"0.2.0"`
- CHANGELOG entry for v0.2.0 — `[Added]: SDK — `from tgcli import Client``
- Tag `v0.2.0`, push → CI publishes to PyPI

### Done when

- [ ] `from tgcli import Client` works
- [ ] All 14 method namespaces implemented (messages, chats, topics, folders, contacts, accounts, listen)
- [ ] All 202 existing CLI tests still pass
- [ ] 10+ new SDK tests
- [ ] v0.2.0 published to PyPI

---

## Phase 12 — Media upload (~1 day)

Goal: complete the write surface with media upload. Tag `v0.3.0`.

### Commands to add (4)

```
upload-photo    <chat> <file>   — upload an image (jpg/png/webp/gif)
upload-voice    <chat> <file>   — upload an OGG/Opus voice note
upload-video    <chat> <file>   — upload a video (mp4/webm/mov)
upload-document <chat> <file>   — upload any file as document (no preview)
```

All gated through the same `--allow-write` + `--idempotency-key` + `--fuzzy` + `--dry-run` pipeline.

### Common flags

- `--caption "text"` — text caption, optional
- `--reply-to <msg-id>` — reply to a message
- `--silent` — send without notification
- `--ttl SECONDS` — self-destruct timer (photo/video only, optional)
- `--max-size-mb` — refuse upload if file exceeds (default: 100 MB matching wacli)

### File-path safety (steal from chigwell/telegram-mcp + wacli)

- Reject `?` and `#` in path (already in `_safe_user_path`)
- Reject paths with `..` traversal
- Resolve to absolute path before logging in audit
- `--allowed-roots` flag to restrict upload to specific dirs (optional, deferred unless agents abuse this)

### MIME-type detection

- Photo: validate JPEG/PNG/WebP/GIF magic bytes
- Voice: validate OGG container, refuse non-Opus
- Video: validate MP4/WebM/MOV; warn if codec not Telegram-friendly
- Document: anything goes

### SDK API additions

```python
await c.media.upload_photo(chat=..., path=..., caption=..., allow_write=True)
await c.media.upload_voice(chat=..., path=..., allow_write=True)
await c.media.upload_video(chat=..., path=..., caption=..., allow_write=True)
await c.media.upload_document(chat=..., path=..., caption=..., allow_write=True)
```

### Tests

- ~12 tests, one per command + edge cases (file too big, missing file, wrong MIME, dry-run, idempotency)

### Done when

- [ ] 4 commands functional + envelope output
- [ ] SDK methods exposed via `c.media.upload_*`
- [ ] All existing tests still pass
- [ ] v0.3.0 published to PyPI

---

## Phase 13 — Channel/group admin (~1-2 days)

Goal: tooling for groups/channels you administer. Tag `v0.4.0` or `v1.0.0` depending on completeness.

### Commands (proposed — confirm scope before executing)

| Command | Purpose | Destructive? |
|---|---|---|
| `chat-title <chat> "<new>"` | Rename a chat | No |
| `chat-photo <chat> <file>` | Set chat photo | No |
| `chat-description <chat> "<text>"` | Set chat description | No |
| `promote <chat> <user>` | Promote to admin | Yes (typed --confirm) |
| `demote <chat> <user>` | Demote admin | Yes (typed --confirm) |
| `ban-from-chat <chat> <user>` | Ban a user from group/channel | Yes (typed --confirm) |
| `unban-from-chat <chat> <user>` | Unban | No |
| `kick <chat> <user>` | Remove without ban | Yes (typed --confirm) |
| `set-permissions <chat>` | Set default member permissions (multiple flags) | No |
| `chat-invite-link <chat>` | Generate / revoke invite links | No |
| `chat-pinned-list <chat>` | List pinned messages | No (read) |
| `chat-members <chat>` | List members (paged) | No (read) |

### Safety considerations specific to admin actions

- All destructive admin actions (`ban-from-chat`, `kick`, `promote`, `demote`) require `--confirm <chat-id>` typed
- `promote` should refuse to grant rights you don't have (Telegram refuses anyway, but surface a clean error)
- `set-permissions` is multi-flag; consider an interactive `--review` mode that prints intended changes before applying
- Pre-call audit must include the affected user's id + display name

### SDK additions

```python
await c.chats.set_title(...)
await c.chats.set_photo(...)
await c.chats.promote(...)
await c.chats.kick(...)
members = c.chats.members(chat=12345)  # iterator
```

### Out of scope (for v1.0)

- Live polling / surveys
- Scheduled message creation (Telegram supports it; defer to Phase 14+)
- Voice/video call administration
- Group joining via QR code

### Tag

- `v0.4.0` if shipped incrementally
- `v1.0.0` if all ~12 commands ship together and the surface is declared stable

### Done when

- [ ] All commands implemented
- [ ] SDK admin namespace populated
- [ ] Tests for each command
- [ ] CHANGELOG entry
- [ ] Decide v0.4.0 vs v1.0.0 based on completeness feel

---

## Phase 14 — v1.0.0 quiet release (skip if not needed)

Goal: bump version to 1.0.0 once the surface feels stable. **No marketing.**

This phase is optional. The project is already public after Phase 10. Phase 14 is just a version bump signaling "API is stable, not just beta". Do this when:
- All wanted features have shipped (Phase 11 SDK definitely; Phases 12/13 if you actually want them)
- AGENTS.md has been kept current with each phase
- You've personally used the CLI for a week without finding regressions
- README is polished (not placeholder)

If you never feel the surface is "done", just stay on 0.x indefinitely. That's fine — many tools do.

### v1.0.0 release commit

```bash
# Update tgcli/__init__.py:__version__ = "1.0.0"
# Final CHANGELOG entry summarizing what changed since v0.1.0
git add tgcli/__init__.py CHANGELOG.md
git commit -m "release: v1.0.0 — API stable"
git tag -a v1.0.0 -m "v1.0.0"
git push origin main v1.0.0
```

CI publishes to PyPI automatically. GitHub release auto-generated from CHANGELOG.

### Explicitly NOT in this phase

- Show HN / Reddit / Twitter posts — not the project's goal
- Soliciting stars / followers
- Blog post
- Asking for contributions

If users find the project organically and open issues / PRs, respond at your pace. If nobody finds it, the project still serves its purpose: powering Sedex via SDK, and being a clean personal tool.

---

## Risk register

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| 1 | **Telegram bans the dev account during testing** | Low | Use `--read-only` for most testing; `--dry-run` for write tests; rate limiter already in place. The dev account is established (2+ years, real history). |
| 2 | **PyPI Trusted Publisher misconfigured → first release fails** | Medium | Test the release workflow on a pre-release tag (e.g. `v0.1.0-rc1`) first; iterate without consuming the v0.1.0 slot. |
| 3 | **Telethon archived → users worried about long-term viability** | Low | README explains: Telethon moved to Codeberg, still maintained, this project tracks it. Long-term migration to TDLib bindings is on the roadmap if needed. |
| 4 | **Name collision with old tgcli (Eray Erdin's 2019 project)** | Low | We use `tg-cli` (PyPI) → `tgcli` (Python import). The old project is on `pip install tgcli`. README clarifies the distinction. |
| 5 | **External users hit the .env path conflict in pip install** | Medium | After Phase 11, the SDK should support `Client(api_id=..., api_hash=...)` so users can avoid .env entirely. CLI users still get the .env auto-loading. |
| 6 | **Email leakage in commit history (christian@tabulara.de)** | Already happened | Switch to noreply going forward. Don't rewrite history (cost > benefit). |
| 7 | **First-time `pip install tg-cli` fails because of cgo / native deps in Telethon** | Low | Telethon is pure Python — no cgo. The only native dep transitively is sqlite3 which ships with Python. |
| 8 | **CI matrix fails on macOS but passes on Linux** | Medium | Run the matrix early in Phase 10 to surface OS-specific issues; fcntl is Unix-only but session lock can no-op on Windows (TODO if Windows support is added). |

---

## Open questions for the owner to decide

1. **GitHub repo location.** Personal account `b1rd33/tg-cli`? Or new GitHub org for future related projects (Sedex, etc.)?
2. **Email policy.** Switch to `b1rd33@users.noreply.github.com` going forward, or keep real email?
3. **README screenshots.** Will you record an asciinema demo or use static screenshots? Both add real visual value but take time. Acceptable to ship v0.1.0 without and add in v0.2.0.
4. **Channel/group admin scope.** Of the 12 proposed commands in Phase 13, which are highest priority for *your* groups? Could ship a subset (e.g. just `chat-title`, `chat-photo`, `kick`, `chat-invite-link`) faster.
5. **Where does Sedex live?** Same GitHub org as `tg-cli`? Separate repo `b1rd33/sedex-agent` consuming `tg-cli` as a Python dependency? Affects the SDK API design (specifically import patterns).
6. **Release cadence.** One release per phase (v0.1 → v0.2 → v0.3 → v0.4 → v1.0), or stack multiple phases under a single release? Recommend per-phase for the cleaner CHANGELOG.
7. **Telethon migration.** Long-term, do you want to migrate to a maintained alternative (Pyrogram / TDLib-Python) post-v1.0, or stay on archived Telethon for as long as it works? Affects v2.0 planning.

---

## Phase order summary

**Status as of 2026-05-08: Phase 10 done locally. Push to GitHub + PyPI Trusted Publisher setup is the remaining manual step.**

```
Phase 10  ✅ done       v0.1.0   commit 8bb4a43, tag v0.1.0, dist/ built
   ↓ next: 4 manual steps (~15 min total)
   1. Create empty repo at github.com/b1rd33/tg-cli (no README/LICENSE — they exist locally)
   2. git remote add origin https://github.com/b1rd33/tg-cli.git && git push -u origin main
   3. Configure PyPI Trusted Publisher: tg-cli ↔ b1rd33/tg-cli, workflow release.yml
   4. git push origin v0.1.0   # triggers release.yml → PyPI + GitHub release

Phase 11  (~1 day)     → v0.2.0   SDK for Sedex            ← when Sedex starts
Phase 12  (~1 day)     → v0.3.0   media upload             ← optional
Phase 13  (~1-2 days)  → v0.4.0   channel/group admin      ← optional
Phase 14  (skip-able)  → v1.0.0   API stable bump          ← skip if you stay on 0.x
```

The 4 manual steps cannot be automated by an agent (they require GitHub web auth + PyPI web auth). Do them yourself when you're ready.

After Phase 10 is *fully* public (push complete, PyPI publish succeeded), pause until you actually need Phase 11. The SDK extraction matters only when Sedex starts; until then the project is feature-complete enough.
