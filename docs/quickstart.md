# Quickstart

Five commands to feel out the surface.

## 1. Sync a fast view of your dialogs

```bash
tg discover
```

Pulls every chat you have access to (DMs, groups, channels) into the local SQLite cache. Just metadata — names, types, ids — not messages. Fast.

## 2. Pull recent messages

```bash
tg backfill --max-chats 10 --per-chat 100
```

Pulls the most recent 100 messages from each of your top 10 dialogs into local SQLite. Caps on `--max-messages` and `--max-db-size-mb` keep this safe to leave running.

For media:

```bash
tg backfill --max-chats 5 --per-chat 50 --download-media
```

Adds photos / voice notes / video / document files into `accounts/default/media/<chat_id>/`.

## 3. Search what you've cached

```bash
tg search "shipping" --json
```

Substring search across all cached message text. Returns a JSON envelope with hits, chat ids, dates. Restrict to one chat with `--chat <selector>`.

## 4. Send a message

```bash
tg send @username "hello from tg-cli" --allow-write
```

The `--allow-write` flag is required for any message that hits Telegram. Without it the command exits with a clear error — this is the [write gate](safety.md).

For multi-line text:

```bash
echo "line one\nline two" | tg send @username - --allow-write
```

## 5. Listen live

```bash
tg listen
```

Streams new incoming messages to stdout in JSON envelope form, also writing them to the local cache. Ctrl-C to stop. Useful as the input source for an LLM-drafted reply pipeline.

## What now?

- Browse the [full command reference](commands.md)
- Use it from Python via the [SDK](sdk.md)
- Read the [safety model](safety.md) before sending or deleting at scale
- Set up [multi-account](multi-account.md) if you have a personal + business split
