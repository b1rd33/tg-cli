# Contributing

`tg-cli` is a small project but contributions are welcome — bug reports,
PRs, doc fixes, new commands.

## Quick links

- **Report a bug** — <https://github.com/b1rd33/tg-cli/issues>
- **Read AGENTS.md** — top-level project conventions, exit codes, gotchas
- **Read the safety model** — [Safety](safety.md) before adding any write command
- **CHANGELOG.md** — version history

## Local setup

```bash
git clone https://github.com/b1rd33/tg-cli
cd tg-cli
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/tgcli
```

The `[dev]` extra pulls `pytest` + `ruff`.

## Running the gate locally

```bash
make gate    # ruff format check + ruff lint + pytest + git diff check
```

Or step by step:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest tests/tgcli -q
```

## Running the docs site locally

```bash
.venv/bin/pip install mkdocs-material
.venv/bin/mkdocs serve     # http://127.0.0.1:8000
```

## Conventions

- **Conventional Commits** — `feat|fix|docs|refactor|test|chore|perf|security|ci(scope): subject`
- **Optional commit-msg hook** — install via `make install-hooks`
- **One commit per task** on a `feat/phase-N-...` feature branch, squash-merge to main when done
- **Audit log is append-only NDJSON** — pre + post entries share `request_id`

## Adding a new write command

Read `tgcli/commands/messages.py`'s `_send_runner` end-to-end first.
The pipeline is fixed:

```
write gate → read text → idempotency lookup → resolver + fuzzy gate
  → dry-run short-circuit → rate limit → audit_pre → Telethon
  → record_idempotency → audit_post
```

Don't bypass any of these. The pattern is verbose but it's the
whole point of the project — every write hits the same gates,
auditable.

## Adding a new read command

Much simpler — just resolve the chat, query SQLite, return data dict.
The dispatch layer handles envelope + exit codes for you.

## Tests

Every new command should ship with a test. Smoke tests at minimum;
unit tests for any non-trivial transformation. Telethon is **not
mocked** — write tests that stop just before the Telethon call and
assert the constructed payload.

## Telethon API surface

Read the actual installed Telethon at
`.venv/lib/python3.12/site-packages/telethon/tl/functions/`.
Don't trust outdated docs.

## Releasing

The release flow is automated. Push a `v*` tag → `release.yml` builds
+ publishes to PyPI via Trusted Publisher → GitHub release auto-generated.

## License

By contributing you agree your contributions will be MIT licensed.
