# Python SDK

`tg-cli` exposes a Python SDK for in-process usage. The CLI itself
is a thin shell around the same runners; calling the SDK skips
subprocess overhead and lets you handle results as Python objects
instead of parsing JSON envelopes.

## Import

```python
from tgcli import Client
```

## Construct

```python
c = Client(account="default")    # default
c = Client(account="work")        # alternate account dir at accounts/work/
```

!!! warning "Single-account-per-process in v1.0"

    The SDK is single-account-per-process in v1.0. If you set
    `TG_ACCOUNT=work` before importing `tgcli`, you must construct
    `Client(account="work")` — mismatched constructions raise
    `RuntimeError` to prevent silent wrong-account writes.

## Read methods (sync — query the local SQLite cache)

```python
me = await c.me()
data = c.stats()
```

For the full surface, every CLI runner has an equivalent. v1.0
exposes a curated subset directly on the SDK; the remainder are
reachable by shelling out via `subprocess.run(["tg", "...", "--json"])`
and parsing the envelope. More SDK methods land in v1.1+ on demand.

## Write methods (async — call Telegram)

```python
result = await c.messages.send(
    chat=12345,
    text="hello",
    allow_write=True,                     # equivalent to --allow-write
    idempotency_key="reply-to-12345-msg-99",
    fuzzy=False,                          # leave False unless using fuzzy selectors
    dry_run=False,                        # True returns the would-do envelope
)
```

The result is the same envelope shape as the CLI's `--json` output:

```python
{
    "ok": True,
    "command": "messages.send",
    "request_id": "req-abc123",
    "data": {"chat_id": 12345, "message_id": 99, "date": "..."},
    "warnings": [],
}
```

## Errors

The SDK raises typed exceptions instead of returning fail envelopes
(unlike the CLI which converts exceptions to envelopes for shell-friendliness):

```python
from tgcli.safety import WriteDisallowed, NeedsConfirm, LocalRateLimited
from tgcli.resolve import NotFound, Ambiguous

try:
    await c.messages.send(chat="@hamid", text="...")    # missing allow_write=True
except WriteDisallowed:
    ...

try:
    chat_id, title = c.chats.resolve("Hambu")
except Ambiguous as e:
    print(e.candidates)    # list of (id, title) for disambiguation
```

## Live event stream

```python
async for event in c.listen():
    print(event.message_id, event.text)
```

Use this as the input source for an LLM-drafted reply pipeline,
custom notifier, archiver, etc. Events are written to the local
cache automatically.

## Example: triage incoming messages with an LLM

```python
from tgcli import Client
from anthropic import Anthropic

c = Client()
ai = Anthropic()

async def main():
    async for event in c.listen():
        # Skip outgoing, group spam, and channel posts
        if event.is_outgoing or event.chat_type != "user":
            continue

        # Generate a draft via Claude
        draft = ai.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=200,
            messages=[{"role": "user", "content": f"Reply to: {event.text}"}],
        ).content[0].text

        # Send the draft to your own Saved Messages for review
        await c.messages.send(
            chat="me",
            text=f"Draft reply to {event.sender_name}:\n\n{draft}",
            allow_write=True,
        )
```

## Versioning

The SDK API is **stable** as of v1.0.0. New methods are additive.
Breaking changes will bump the major version (v2.0.0+).
