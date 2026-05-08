# Install

## Requirements

- Python 3.12 or newer
- A real Telegram account (not a bot account)
- `TG_API_ID` and `TG_API_HASH` from <https://my.telegram.org/apps>

## Install from PyPI

```bash
pip install tgctl
```

This installs the package and puts a `tg` binary on your PATH.

## Set up API credentials

Telegram requires you to register a personal app once. It's free and takes ~2 minutes:

1. Visit <https://my.telegram.org/apps> and sign in with your phone number
2. Click "Create new application"
3. Give it any title (e.g. "Personal Archiver"); platform = "Desktop"
4. Copy the resulting `api_id` (an integer) and `api_hash` (32-char hex)

Put them in a `.env` file in the directory where you'll run `tg`:

```bash
TG_API_ID=12345678
TG_API_HASH=abcdef0123456789abcdef0123456789
```

Or set them as shell env vars:

```bash
export TG_API_ID=12345678
export TG_API_HASH=abcdef0123456789abcdef0123456789
```

## First login

```bash
tg login
```

You'll be prompted for your phone number, then a code Telegram will send you (via the Telegram app, not SMS). After that, `tg.session` is created locally and you stay logged in.

## Verify

```bash
tg me
tg stats
```

`tg me` shows your authenticated account info. `tg stats` shows your local cache state (will be empty until you run `backfill` or `discover`).

## Troubleshooting

**`tg: command not found`** — pip didn't put the script on PATH. Run with `python -m tgcli` instead, or check your shell's PATH includes pip's bin directory.

**Auth errors** — run `tg doctor --json` to see exactly which check fails (credentials / session / DB / live API). The `--live` flag also pings Telegram to confirm network connectivity.

**Account flagged or limited** — message `@SpamBot` from your Telegram client. New accounts and accounts running automation against many strangers are at higher risk; established personal accounts running tg-cli for personal use are at very low risk.
