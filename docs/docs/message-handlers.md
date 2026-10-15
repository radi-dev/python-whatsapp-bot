---
sidebar_position: 6
---

# Message Handlers

Handlers are plain functions registered with a decorator. For each incoming message the
dispatcher runs **the first registered handler whose type and filter match**, passing it the
`update` and - if the function declares the parameter - the user's `context`.

```python
@wa_bot.on_message(regex=r'^/start')
def start(update, context):
    update.reply_message(f'Hi {update.user_display_name}!')
```

## Handler types

| Decorator | Runs for | `update.message_text` |
|---|---|---|
| `on_message(regex, func, context, persistent)` | text messages | the text |
| `on_interactive_message(regex, func, handle_button, handle_list, context, persistent)` | button and list replies | the **id** of the chosen button / row |
| `on_image_message(regex, func, context, persistent)` | images | the caption (may be empty) |
| `on_video_message(regex, func, context, persistent)` | videos | the caption |
| `on_audio_message(regex, func, context, persistent)` | audio and voice notes | `''` |
| `on_sticker_message(context, persistent)` | stickers | `''` |
| `on_location_message(context, persistent)` | locations | name + address, or coordinates |

All decorators accept `()` with no arguments.

## Filters

- `regex=r'...'` - the handler matches if `re.match(regex, message_text)` succeeds (anchored at
  the start; use `(?i)` for case-insensitive).
- `func=callable` - a function receiving `message_text` and returning a truthy value. Ignored if
  `regex` is given.
- Neither - matches every message of that type. Register such catch-alls **last**: handlers are
  tried in registration order and the first match wins.

```python
@wa_bot.on_message(regex=r'(?i)^(hi|hello)\b')
def greet(update, context): ...

@wa_bot.on_message(func=lambda text: text.isdigit())
def number(update, context): ...

@wa_bot.on_message()                          # fallback
def anything_else(update, context): ...
```

## The `update` object

| Attribute | Description |
|---|---|
| `user_phone_number` | sender's WhatsApp id (phone number), also the key of their context |
| `user_display_name` | sender's profile name |
| `message_id` | id of the incoming message |
| `message_text` | text / caption / button id, as per the table above |
| `message` | the raw message dict from the payload |
| `media_file_id`, `media_mime_type`, `media_hash`, `media_voice` | media messages - see [Media handling](./media-handling) |
| `loc_latitude`, `loc_longitude`, `loc_name`, `loc_address` | location messages |
| `bot` | the `Whatsapp` instance |

Reply helpers:

```python
update.reply_message('text', reply_markup=None, header=None, header_type='text', footer=None,
                     web_page_preview=True)                 # quotes the incoming message
update.reply_media('https://example.com/pic.jpg', caption='...')
```

For anything else use the bot directly, e.g.
`update.bot.send_template_message(update.user_phone_number, 'order_shipped')`.

## The `context` object

`context.user_data` is a dict that belongs to this user and persists between messages - in the
[context storage](./context-storage) you configured, not in memory:

```python
@wa_bot.on_message(regex=r'^/lang (\w+)')
def set_language(update, context):
    context.user_data['lang'] = update.message_text.split()[1]

@wa_bot.on_message()
def reply(update, context):
    lang = context.user_data.get('lang', 'en')
    ...
```

The dict is loaded before the handler runs and written back afterwards if it changed (nested
changes included). Values must be JSON-serializable.

Handlers that do not need state can simply omit the parameter - `def h(update):` - or be
registered with `context=False`. Such handlers never require a storage.

:::caution
If *any* handler takes `context` (or you call `set_next_step`) and no storage is configured,
the first `process_update` raises `ContextStorageNotConfiguredError`. The library never falls
back to process memory.
:::

## Persistent handlers

A `persistent=True` handler is checked **before** everything else on every message, even while
the user is in the middle of a multi-step conversation. Use it for global commands:

```python
@wa_bot.on_message(regex=r'(?i)^/help$', persistent=True)
def help_command(update):
    update.reply_message('Commands: /start, /order, /cancel')
```

## Async handlers

Declare handlers with `async def` and feed the webhook to `aprocess_update`:

```python
@wa_bot.on_message()
async def handler(update, context):
    data = await fetch_something()
    await update.bot.asend_message(update.user_phone_number, data)

# in your async web framework
await wa_bot.dispatcher.aprocess_update(payload)
```

Storage access is non-blocking (native async clients for Redis and SQLAlchemy `AsyncEngine`,
a thread pool otherwise). Do not mix sync handlers with `aprocess_update` or vice versa.

## Multi-step conversations

`set_next_step(update, function)` makes `function` handle the user's **next** message instead
of the regular handlers:

```python
@wa_bot.on_message(regex=r'^/register')
def start_registration(update, context):
    update.reply_message('What is your name?')
    wa_bot.set_next_step(update, get_name)

def get_name(update, context):
    context.user_data['name'] = update.message_text
    update.reply_message('And your email?')
    wa_bot.set_next_step(update, get_email, regex=r'^[^@\s]+@[^@\s]+$')

def get_email(update, context):
    context.user_data['email'] = update.message_text
    update.reply_message(f"Thanks {context.user_data['name']}, you're registered.")
```

Parameters:

| Parameter | Default | Meaning |
|---|---|---|
| `handler_type` | `UpdateHandler` | `MessageHandler` to accept text, `InteractiveQueryHandler` for a button/list reply, etc. |
| `regex`, `func` | `None` | filter; if the next message does not match, nothing runs and the step stays pending |
| `end_conversation_keyword_regex` | `(?i)^(end\|stop\|cancel)$` | a message matching this ends the conversation instead |
| `end_conversation_action` | no-op | function called for the end keyword |

Rules:

- Persistent handlers still run first; everything else is bypassed until the step has run.
- The step is cleared once its function ran (or the end keyword was received). If the function
  raises, the step is kept and the user's next message is offered to it again.
- `wa_bot.clear_next_step(update)` (or a phone number) cancels a pending step;
  `wa_bot.get_next_step(phone)` shows it.

The pending step is **persisted in the user's context record** so it works across workers and
restarts. Functions are therefore stored by reference: module-level functions just work;
closures, methods or partials must be registered with `@wa_bot.register_step('name')`; lambdas
are rejected. Details in [Context storage → Multi-step conversations](./context-storage#multi-step-conversations-set_next_step).

## Error handling

An exception inside a handler is logged (`python_whatsapp_bot.dispatcher` logger) and does not
propagate to the webhook - the message counts as handled. Changes made to `context.user_data`
before the exception are still saved. Configure logging to see these errors:

```python
import logging
logging.basicConfig(level=logging.INFO)
```
