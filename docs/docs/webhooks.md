---
sidebar_position: 5
---

# Webhooks

WhatsApp delivers incoming messages by calling an HTTPS endpoint of yours. The library does not
run a web server: you expose the endpoint with any framework and hand each payload to the bot.

```
WhatsApp  --POST /webhook-->  your app  --> wa_bot.process_update(payload) --> your handlers
```

## 1. Verification (GET)

When you register the URL in the Meta developer portal (*WhatsApp → Configuration → Webhook*),
WhatsApp sends a `GET` with `hub.mode`, `hub.verify_token` and `hub.challenge`. Echo the
challenge if the token matches the one you typed into the portal:

```python
@app.route('/webhook', methods=['GET'])
def verify_webhook():
    if (request.args.get('hub.mode') == 'subscribe'
            and request.args.get('hub.verify_token') == VERIFY_TOKEN):
        return request.args.get('hub.challenge'), 200
    return 'Forbidden', 403
```

Subscribe to the **messages** field of the WhatsApp Business Account object.

## 2. Updates (POST)

### Flask (sync handlers)

```python
from flask import Flask, request
from python_whatsapp_bot import Whatsapp, SQLiteStorage, ContextLockTimeoutError

wa_bot = Whatsapp(number_id, token, context_storage=SQLiteStorage('bot_context.db'))
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        wa_bot.process_update(request.get_json())
    except ContextLockTimeoutError:
        return 'Busy, retry later', 503     # WhatsApp re-delivers the message
    return 'OK', 200
```

### FastAPI (async handlers)

```python
from fastapi import FastAPI, Request, Response
from python_whatsapp_bot import Whatsapp, RedisStorage, ContextLockTimeoutError

wa_bot = Whatsapp(number_id, token, context_storage=RedisStorage('redis://localhost:6379/0'))
app = FastAPI()

@wa_bot.on_message()
async def echo(update, context):                       # async handlers with aprocess_update
    await update.bot.asend_message(update.user_phone_number, update.message_text)

@app.post('/webhook')
async def webhook(request: Request):
    try:
        await wa_bot.dispatcher.aprocess_update(await request.json())
    except ContextLockTimeoutError:
        return Response('Busy, retry later', status_code=503)
    return Response('OK')
```

`process_update` runs **sync** handlers; `aprocess_update` runs **async** handlers
(`async def`). Do not mix: an async handler given to `process_update` is never awaited, and a
sync handler under `aprocess_update` is rejected with a `TypeError` in the logs.

## What `process_update` does

1. Validates the payload and ignores anything that is not a message for this bot's phone number
   id (status/delivery receipts, other numbers).
2. If a [context storage](./context-storage) is configured, takes the **per-user lock** and
   loads the user's record (`user_data` + pending next step).
3. Marks the message as read (unless `mark_as_read=False`).
4. Runs the first matching [handler](./message-handlers).
5. Saves the record if it changed and releases the lock.

Each call processes exactly the update it was given; calls for different users may run
concurrently, calls for the same user are serialised by the lock.

### Threaded vs inline

By default (`wa_bot.threaded = True`) steps 3-5 run in a new thread and `process_update`
returns immediately, so the webhook answers fast even if a handler makes slow API calls.
Set `wa_bot.threaded = False` to run everything inline (useful in tests, or if your server
already runs requests in worker threads). `aprocess_update` always runs inline on the event loop.

In threaded mode the lock is still taken *before* the thread is spawned, in the webhook
request, so errors below are always raised to the request that delivered the message.

## Errors: when to answer non-2xx

WhatsApp treats any non-2xx response (or a timeout) as "not delivered" and **re-sends the
webhook with exponential backoff**. The library raises - instead of logging - exactly when
nothing has been processed yet and a retry is therefore safe:

| Exception | Meaning |
|---|---|
| `ContextLockTimeoutError` | another worker is still handling this user (waited `context_lock_wait` seconds) |
| `ContextStorageNotConfiguredError` | a handler needs the context but no storage was configured |
| other `ContextStorageError`s | the storage is unreachable or misconfigured |
| `NextStepNotSerializableError` | `set_next_step` was given a function other workers cannot resolve |

Return 5xx (or let the exception propagate) and the message comes back later. Exceptions
raised *inside your handler* are logged and swallowed, because the handler may already have
sent replies - retrying would duplicate them.

## Running several workers

Because all conversation state lives in the storage backend, you can run as many processes as
you like - `gunicorn -w 4`, `uvicorn --workers 4`, several containers - provided they share the
same backend:

- one machine → `SQLiteStorage` on a shared file is enough;
- several machines → `RedisStorage` or `SQLAlchemyStorage` (Postgres/MySQL).

Register handlers (and `register_step` names) at import time so every worker has the same
set. See [Context storage](./context-storage) for locking, expiry and next-step details.

## Local development

WhatsApp needs a public HTTPS URL. Expose your local server with a tunnel such as
[ngrok](https://ngrok.com/) (`ngrok http 5000`) and register the generated URL as the webhook.
Remember that the temporary access token from the portal expires after 24 hours.
