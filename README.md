# telegram_test

Read-only Telegram scraper. Logs in as your account, captures incoming
messages, backfills history, syncs contacts. Stores everything in local
SQLite. The only outbound action is an optional one-line echo to your own
Saved Messages — never to anyone else.

## Setup (one time)

1. **Register a personal app** at https://my.telegram.org/apps
   - Sign in with your phone number
   - Click "Create new application"
   - Title and short name can be anything (e.g. "personal-archiver")
   - URL/platform/description are optional
   - Copy the `App api_id` and `App api_hash` values

2. **Set the credentials in your shell**:

   ```bash
   export TG_API_ID=12345678
   export TG_API_HASH=abcdef0123456789abcdef0123456789
   ```

   (or copy `.env.example` → `.env` and `source` it before running)

3. **First-time auth** (interactive — Telegram will SMS you a 5-digit code):

   ```bash
   cd /Users/christiannikolov/Projects/scrapling-test/telegram_test
   ../.venv/bin/python tg_scrape.py login
   ```

   This creates `tg.session` next to the script. Subsequent runs read
   from it silently. **Treat that file like a password.**

## Use

```bash
# All commands run from this directory with the project venv:
cd /Users/christiannikolov/Projects/scrapling-test/telegram_test
PY=../.venv/bin/python

# Pull last 200 messages from your top 50 chats (1s pause between chats).
# Throttled — first run on a heavy account may FloodWait briefly.
$PY tg_scrape.py backfill --per-chat 200 --max-chats 50

# Pull your phone-book contacts (only contacts already on your phone)
$PY tg_scrape.py sync-contacts

# Live listener — every incoming message gets stored in SQLite.
# Stays running until Ctrl+C.
$PY tg_scrape.py listen

# Same, but ALSO echo a one-line summary of each message to your own
# Saved Messages (so your phone notifies you with a clean unified feed):
$PY tg_scrape.py listen --notify

# DB summary (chat counts, top 10 chats by message volume, latest msg)
$PY tg_scrape.py stats
```

## What gets stored

`telegram.sqlite` (next to this file):

| Table         | Rows                                                  |
|---------------|-------------------------------------------------------|
| `tg_chats`    | every chat the user has ever seen (DMs, groups, channels) |
| `tg_messages` | text + metadata for every captured message            |
| `tg_contacts` | name, phone, username for everyone in your phone-book |

Plus `tg.session` — Telethon's encrypted auth token.

## What it does NOT do

- Never sends a message to anyone except optionally a summary to your own Saved Messages
- Never replies, never forwards, never reacts, never joins/leaves anything
- Never downloads media files (just records that media exists + its type)
- Never imports phone numbers to discover new Telegram users

## Ban risk

Effectively zero for read-only userbots. The API calls are the same ones
the official Telegram clients use. Telethon handles FloodWait throttles
transparently. If you blast `backfill` against 500 chats with `--throttle
0`, you'll get rate-limited (a temporary throttle), not banned.

The default throttle of 1s/chat is conservative.

## Inspect the DB

```bash
sqlite3 telegram.sqlite

-- Most recent 20 incoming messages
SELECT date, c.title, m.text
FROM tg_messages m JOIN tg_chats c ON c.chat_id = m.chat_id
WHERE m.is_outgoing = 0
ORDER BY date DESC
LIMIT 20;

-- Messages per day (last 30 days)
SELECT substr(date, 1, 10) AS day, COUNT(*)
FROM tg_messages
WHERE date >= date('now', '-30 days')
GROUP BY day
ORDER BY day DESC;
```
