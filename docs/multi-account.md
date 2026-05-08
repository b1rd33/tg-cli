# Multi-account

`tg-cli` supports multiple Telegram accounts on the same machine
with isolated stores per account.

## Why isolate

Each account gets its own:

- Telethon `tg.session` (auth token)
- `telegram.sqlite` (cached messages)
- `audit.log` (write trail)
- `media/` (downloaded photos / voice / video / documents)
- `tg.session.lock` (concurrent-process guard)

This means a write you make as `work` cannot leak into `personal`'s
audit log, and a backfill on one account doesn't pollute the other's
SQLite. It also means losing or rotating one account's session
doesn't affect the other.

## Layout on disk

```
~/Projects/your-app/
├── accounts/
│   ├── default/
│   │   ├── tg.session
│   │   ├── telegram.sqlite
│   │   ├── audit.log
│   │   └── media/
│   ├── work/
│   │   ├── tg.session
│   │   ├── telegram.sqlite
│   │   ├── audit.log
│   │   └── media/
│   └── .current        ← which one is "default" right now
└── ...
```

If you don't use `accounts-add`, everything lives at
`accounts/default/`. The account name `default` is reserved
and auto-created on first run.

## Commands

### `tg accounts-add <name>`

Creates a new isolated account directory.

```bash
tg accounts-add work
```

Then log in as that account:

```bash
tg --account work login
```

### `tg accounts-list`

Lists all configured accounts, showing which is current.

```bash
tg accounts-list
```

### `tg accounts-show`

Show paths and current account.

```bash
tg accounts-show
# {"current": "default", "accounts": ["default", "work"], ...}
```

### `tg accounts-use <name>`

Set the default account selector. Every subsequent command without
an explicit `--account` uses this one.

```bash
tg accounts-use work
tg me                # uses work
tg --account default me   # explicit override, uses default
```

### `tg accounts-remove <name>`

Delete an account directory. Permanent — back up the files first
if you want them.

```bash
tg accounts-remove old-test-account
```

## Selecting an account at command time

Three precedence rules, highest first:

1. `--account <name>` flag on the command
2. `TG_ACCOUNT=<name>` environment variable
3. The current selector at `accounts/.current`
4. Falls back to `default`

```bash
tg --account work send @colleague "..." --allow-write    # explicit
TG_ACCOUNT=work tg send @colleague "..." --allow-write    # via env
tg accounts-use work && tg send @colleague "..." --allow-write    # via selector file
```

## In Python (SDK)

```python
from tgcli import Client

c = Client(account="work")    # explicit
me = await c.me()
```

## Recommended use cases

- **Personal + business split** — keep work DMs in `accounts/work/` and your
  personal account untouched
- **Test accounts for development** — develop reply flows against
  `accounts/test/` with a throwaway phone number, then promote to
  `accounts/default/` once stable
- **Temporary backup account** — register a second SIM as `accounts/backup/`
  in case your main account hits a SpamBot restriction. Won't help recover the
  main, but lets you keep operating while you appeal.
