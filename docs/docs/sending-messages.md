---
sidebar_position: 3
---

# Sending Messages

Every sending method exists in a synchronous form and an asynchronous form prefixed with `a`
(`send_message` / `asend_message`). Both return the HTTP response of the Cloud API call - a
`requests.Response` for sync calls, an `httpx.Response` for async calls - so you can inspect
`response.status_code` and `response.json()`.

Phone numbers are always given in international format without `+`, spaces or leading zeros:
`'2348145xxxxx'`, not `'+234 814 5xxxxx'`.

## Text messages

```python
wa_bot.send_message('2348145xxxxx', 'Hello, World!')

# async
await wa_bot.asend_message('2348145xxxxx', 'Hello, World!')

# disable the link preview
wa_bot.send_message('2348145xxxxx', 'Read https://example.com', web_page_preview=False)

# quote (reply to) a specific message
wa_bot.send_message('2348145xxxxx', 'Replying to that', msg_id='wamid.HBgL...')
```

Inside a handler, `update.reply_message(text, ...)` does the same and quotes the incoming
message automatically - see [Message handlers](./message-handlers).

## Interactive messages

Buttons, lists and location requests are text messages with a `reply_markup`:

```python
from python_whatsapp_bot import Inline_keyboard

wa_bot.send_message(
    '2348145xxxxx',
    'Choose an option:',
    reply_markup=Inline_keyboard(['Option 1', 'Option 2', 'Option 3']),
    header='Main menu',         # optional; header_type='text' | 'image' | 'video' | 'document'
    footer='Reply within 24h',  # optional
)
```

All markup types are described in [Interactive messages](./interactive-messages).

## Template messages

Templates are pre-approved messages you create in the WhatsApp Manager; they are the only
messages you can send outside the 24-hour customer service window.

```python
wa_bot.send_template_message('2348145xxxxx', 'hello_world')

components = [
    {
        "type": "body",
        "parameters": [
            {"type": "text", "text": "John"},
            {"type": "text", "text": "Order #12345"},
        ],
    }
]
wa_bot.send_template_message(
    '2348145xxxxx', 'order_confirmation', components=components, language_code='en_US'
)

await wa_bot.asend_template_message('2348145xxxxx', 'hello_world')
```

`components` follows the
[Cloud API template format](https://developers.facebook.com/docs/whatsapp/cloud-api/messages/template-messages)
verbatim; `language_code` defaults to `en_US`.

## Image messages

```python
wa_bot.send_media_message(
    '2348145xxxxx',
    'https://example.com/image.jpg',
    caption='Check this out!',
)

await wa_bot.asend_media_message('2348145xxxxx', 'https://example.com/image.jpg')
```

:::note
`send_media_message` currently sends **images by public URL** only (the Cloud API `image` +
`link` form). Sending other media types or uploading local files is not implemented yet; for
those, call the Cloud API directly with the `wa_bot.msg_url` / `wa_bot.token` attributes.
:::

Receiving and downloading media is covered in [Media handling](./media-handling).

## Location messages

There is no wrapper on the bot object yet; use the underlying function with the bot's URL and
token:

```python
from python_whatsapp_bot.message import message_location, amessage_location

message_location(
    wa_bot.msg_url, wa_bot.token, '2348145xxxxx',
    latitude='37.7749', longitude='-122.4194',
    location_name='San Francisco', location_address='California, USA',
)

await amessage_location(wa_bot.msg_url, wa_bot.token, '2348145xxxxx',
                        latitude='37.7749', longitude='-122.4194')
```

To *ask* the user for their location, send an `InlineLocationRequest` markup - see
[Interactive messages](./interactive-messages#location-request).

## Marking messages as read

Incoming messages are marked as read automatically (`Whatsapp(..., mark_as_read=True)`, the
default). To do it yourself, pass the raw message dict from the webhook payload:

```python
wa_bot = Whatsapp(number_id, token, mark_as_read=False)
wa_bot.mark_as_read(update.message)          # sync
await wa_bot.amark_as_read(update.message)   # async
```

## Checking the result

```python
response = wa_bot.send_message('2348145xxxxx', 'Hello')
body = response.json()
if response.ok:
    print('sent, id:', body['messages'][0]['id'])
else:
    print('error:', body['error']['message'])
```

The library does not retry or raise on API errors; network failures raise the usual
`requests` / `httpx` exceptions after a 30 second timeout.

## Sending many messages

Async calls can run concurrently:

```python
import asyncio

async def notify(numbers):
    await asyncio.gather(*(wa_bot.asend_message(n, 'Maintenance tonight at 23:00') for n in numbers))
```

Respect the Cloud API's rate limits and the 24-hour window - messages outside it must be
templates.
