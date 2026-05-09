# Commands

`tg --help` shows all 62 commands. They group as follows.

## Auth

| Command | What |
|---|---|
| `tg login` | Interactive sign-in (phone + code). Run once per account. |
| `tg me` | Show authenticated user info. `--offline` reads cached self. |

## Local cache

| Command | What |
|---|---|
| `tg discover` | Sync chat metadata (no messages) — fast |
| `tg backfill` | Pull historical messages into local SQLite |
| `tg sync-contacts` | Pull phone-book contacts |
| `tg stats` | Local cache summary |

## Read

| Command | What |
|---|---|
| `tg show <chat>` | Print messages from one chat |
| `tg search "<query>"` | Substring search across cached messages |
| `tg list-msgs <chat>` | Filtered listing (date range, sender, etc.) |
| `tg get-msg <chat> <id>` | One specific message by id |
| `tg unread` | Chats with unread messages |
| `tg chats-info` | Chat metadata listing |
| `tg contacts` | Saved contacts (with `--chatted` filter) |

## Write — text

| Command | What | Destructive? |
|---|---|---|
| `tg send <chat> "<text>"` | Send a text message | no |
| `tg edit-msg <chat> <id> "<new>"` | Edit your own message | no |
| `tg forward <from-chat> <id> --to <chat>` | Forward a message | no |
| `tg pin-msg <chat> <id>` / `tg unpin-msg` | Pin / unpin | no |
| `tg react <chat> <id> --emoji 👍` | Add reaction | no |
| `tg mark-read <chat>` | Mark all read | no |
| `tg delete-msg <chat> <id>...` | Delete one or more | **yes** — needs `--confirm <chat-id>` |

## Write — media

| Command | What |
|---|---|
| `tg upload-photo <chat> <file>` | Image (jpg/png/webp/gif) |
| `tg upload-voice <chat> <file>` | OGG/Opus voice note |
| `tg upload-video <chat> <file>` | Video (mp4/webm/mov) |
| `tg upload-document <chat> <file>` | Any file as document |

All take `--caption`, `--reply-to`, `--silent`, `--max-size-mb` (default 100).

## Forum topics

| Command | What |
|---|---|
| `tg topics-list <chat>` | List topics in a forum supergroup |
| `tg topic-create <chat> "<title>"` | Create a topic |
| `tg topic-edit <chat> <topic-id>` | Rename / change icon |
| `tg topic-pin <chat> <id>` / `tg topic-unpin` | Pin / unpin |

`tg send` and `tg forward` accept `--topic <id>` to target a forum topic.

## Folders

| Command | What |
|---|---|
| `tg folders-list` | List your dialog folders |
| `tg folder-show <id>` | One folder's contents |
| `tg folder-create "<name>"` | New folder |
| `tg folder-edit <id>` | Rename / change emoticon |
| `tg folder-delete <id>` | Delete (recoverable on Telegram) |
| `tg folder-add-chat <folder> <chat>` | Add chat to folder |
| `tg folder-remove-chat <folder> <chat>` | Remove from folder |
| `tg folders-reorder <id1> <id2>...` | Reorder |

## Chat administration

For groups / channels you administer.

| Command | What | Destructive? |
|---|---|---|
| `tg chat-title <chat> "<new>"` | Rename | no |
| `tg chat-photo <chat> <file>` | Set chat photo | no |
| `tg chat-description <chat> "<text>"` | Set description | no |
| `tg chat-invite-link <chat>` | Generate / revoke invite link | no |
| `tg chat-pinned-list <chat>` | List pinned messages (read) | no |
| `tg chat-members <chat>` | Paged member list (read) | no |
| `tg promote <chat> <user>` | Promote to admin | **yes** |
| `tg demote <chat> <user>` | Demote admin | **yes** |
| `tg ban-from-chat <chat> <user>` | Ban | **yes** |
| `tg kick <chat> <user>` | Remove without ban | **yes** |
| `tg unban-from-chat <chat> <user>` | Lift ban | no |
| `tg set-permissions <chat>` | Default member permissions (`--review` for preview) | no |

## Live / interactive

| Command | What |
|---|---|
| `tg listen` | Stream new incoming messages, write to cache. `--notify` echoes a one-liner to your Saved Messages. `--download-media` saves attachments. |

## Account & sessions

| Command | What | Destructive? |
|---|---|---|
| `tg account-sessions` | List active Telegram sessions across all your devices | no |
| `tg terminate-session <hash>` | Revoke one session (logs out that device) | **yes** |
| `tg block-user <user>` | Block | **yes** |
| `tg unblock-user <user>` | Unblock | no |
| `tg leave-chat <chat>` | Leave a group/channel | **yes** |

## Multi-account

| Command | What |
|---|---|
| `tg accounts-add <name>` | Create a new isolated account dir |
| `tg accounts-list` | Show all configured accounts |
| `tg accounts-show` | Show current default + paths |
| `tg accounts-use <name>` | Switch the default account |
| `tg accounts-remove <name>` | Delete an account dir |

Pass `--account <name>` to any command to use that account's session/db.

## Health

| Command | What |
|---|---|
| `tg doctor` | Diagnose env, session, DB, schema. Add `--live` to ping Telegram. |

## Global flags

Available on any command:

| Flag | Effect |
|---|---|
| `--json` | Force JSON envelope output |
| `--human` | Force human output (default on TTY) |
| `--read-only` | Reject any write — Telegram-side AND local DB. Also `TG_READONLY=1`. |
| `--lock-wait <secs>` | Wait for Telethon session lock instead of fail-fast. Default 0. |
| `--full` | Disable column truncation in human output |
| `--account <name>` | Use this account's isolated dir. Default: `default` |

For write commands:

| Flag | Effect |
|---|---|
| `--allow-write` | **Required** for any Telegram-side write |
| `--dry-run` | Print the resolved payload, exit before calling Telegram |
| `--idempotency-key <key>` | Replay-safe: same key + same command returns the cached envelope without re-calling |
| `--fuzzy` | Allow title-substring chat selectors on a write (otherwise rejected to prevent agent fat-fingering) |
| `--confirm <id>` | Required on destructive commands; must equal the resolved chat/user/session id |
| `--parse-mode {plain,html,md}` | Available on `send`, `edit-msg`, and the four `upload-*` (caption). Default `plain` — text is sent literally. `html` allows `<b>`, `<i>`, `<a href>`, `<code>`, `<pre>`, `<spoiler>`. `md` allows `**bold**`, `__italic__`, `` `code` ``, `[text](url)`, `\|\|spoiler\|\|`. v1.1.0+ |
