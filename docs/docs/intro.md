---
sidebar_position: 1
---

# Getting Started

**python-whatsapp-bot** is a Python library for building WhatsApp bots on the
[WhatsApp Business Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api). It
handles the HTTP calls for sending messages, parses incoming webhook payloads, routes them to
your handler functions, and keeps per-user conversation state in a storage backend of your
choice.

## What you get

- **Sending** text, interactive (buttons, lists, location requests), template and image messages,
  each with a sync (`send_message`) and an async (`asend_message`) variant.
- **Receiving** text, button/list replies, images, audio, video, stickers and locations through
  decorator-based handlers with regex or custom filters.
- **Conversation state** - a per-user `context.user_data` dict and multi-step conversations
  (`set_next_step`), stored in SQLite, Redis, Postgres, MySQL or your own backend, so the bot
  works unchanged behind several worker processes.
- **Safety for scaled deployments** - per-user locking, a retry contract with WhatsApp's webhook
  re-delivery, and optional expiry of idle users' data.

## Prerequisites

1. A **WhatsApp Business account** on the [Meta for Developers](https://developers.facebook.com/)
   portal, with the WhatsApp product added to an app.
2. The **Phone Number ID** and an **access token** from that app - see
   [Installation](./installation#whatsapp-business-setup).
3. **Python 3.7+**.

## Install

```bash
pip install --upgrade python-whatsapp-bot
```

## A minimal bot

```python
from flask import Flask, request
from python_whatsapp_bot import Whatsapp, SQLiteStorage

wa_bot = Whatsapp(
    number_id='YOUR_PHONE_NUMBER_ID',
    token='YOUR_ACCESS_TOKEN',
    context_storage=SQLiteStorage('bot_context.db'),   # where conversation state lives
)

@wa_bot.on_message(regex=r'^/start')
def start(update, context):
    context.user_data['greeted'] = True
    update.reply_message('Welcome! Send me anything.')

@wa_bot.on_message()
def echo(update, context):
    prefix = 'Again? ' if context.user_data.get('greeted') else ''
    update.reply_message(f'{prefix}You said: {update.message_text}')

app = Flask(__name__)

@app.route('/webhook', methods=['GET'])
def verify():
    if request.args.get('hub.verify_token') == 'YOUR_VERIFY_TOKEN':
        return request.args.get('hub.challenge'), 200
    return 'Forbidden', 403

@app.route('/webhook', methods=['POST'])
def webhook():
    wa_bot.process_update(request.get_json())
    return 'OK', 200
```

Three things are happening here:

1. `Whatsapp(...)` is your bot. It needs the phone number id and token, plus a
   **context storage** - required as soon as any handler takes a `context` argument or uses
   `set_next_step`. The library never keeps conversation state in process memory, because that
   breaks the moment you run more than one worker. See [Context storage](./context-storage).
2. `@wa_bot.on_message(...)` registers handlers. The first matching handler runs; `update` holds
   the incoming message and `context.user_data` is this user's persistent dict. See
   [Message handlers](./message-handlers).
3. Your web framework receives WhatsApp's webhook calls and passes the JSON to
   `wa_bot.process_update` (or `await wa_bot.dispatcher.aprocess_update` for async handlers).
   See [Webhooks](./webhooks).

## Sending a message outside a handler

```python
wa_bot.send_message('2348145xxxxx', 'Hello from Python!')
```

Phone numbers are international format without `+`, spaces or leading zeros.

## Where to next

- [Installation](./installation) - credentials, optional backend packages, dev setup
- [Sending messages](./sending-messages) and [Interactive messages](./interactive-messages)
- [Webhooks](./webhooks) - Flask / FastAPI examples and deployment with multiple workers
- [Message handlers](./message-handlers) - filters, the `update` object, multi-step conversations
- [Media handling](./media-handling) - receiving and downloading media
- [Context storage](./context-storage) - backends, locking, expiry, next-step persistence
