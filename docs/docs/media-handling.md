---
sidebar_position: 7
---

# Media Handling

## Receiving media

Images, videos, audio (including voice notes) and stickers arrive through their own handlers.
WhatsApp does not send the file itself - only a **media id** that you can resolve and download
within about 30 days:

```python
@wa_bot.on_image_message()
def on_image(update, context):
    print(update.media_file_id)     # e.g. '1234567890'
    print(update.media_mime_type)   # e.g. 'image/jpeg'
    print(update.media_hash)        # sha256 of the file
    print(update.message_text)      # the caption, '' if none
    path = wa_bot.download_media(update.media_file_id, 'incoming/images')
    update.reply_message(f'Saved to {path}')

@wa_bot.on_video_message(regex=r'(?i)^invoice')   # filters on the caption
def on_invoice_video(update, context): ...

@wa_bot.on_audio_message()
def on_audio(update, context):
    if update.media_voice:          # True for voice notes
        ...

@wa_bot.on_sticker_message()
def on_sticker(update, context): ...
```

Documents are not routed to a handler yet; their payload is still available if you inspect the
raw webhook JSON before calling `process_update`.

## Downloading

```python
# Resolve the id to a (short-lived) URL and metadata
info = wa_bot.get_media_url(media_id)
# {'url': 'https://lookaside.fbsbx.com/...', 'mime_type': 'image/jpeg', 'sha256': '...', 'file_size': 12345, 'id': ...}

# Download to disk. Files go to ./tmp/<relative_dir>/<media_id>.<ext>, the extension is
# derived from the MIME type. Returns the pathlib.Path of the saved file.
path = wa_bot.download_media(media_id, 'incoming/images')

# Keep it in memory instead: returns the HTTP response of the download
response = wa_bot.download_media_data(media_id, 'unused')
data = response.content

# Async variants
info = await wa_bot.aget_media_url(media_id)
path = await wa_bot.adownload_media(media_id, 'incoming/images')
response = await wa_bot.adownload_media_data(media_id, 'unused')
```

Media URLs returned by `get_media_url` expire after a few minutes and require the access
token as a bearer header - `download_media` / `download_media_data` handle both for you.

## Sending images

```python
wa_bot.send_media_message('2348145xxxxx', 'https://example.com/image.jpg', caption='Hello')
await wa_bot.asend_media_message('2348145xxxxx', 'https://example.com/image.jpg')

# from a handler
update.reply_media('https://example.com/image.jpg', caption='Here you go')
```

The URL must be publicly reachable by WhatsApp's servers.

:::note
Only **images by URL** are supported for sending at the moment; videos, audio, documents,
stickers and uploads of local files are not implemented. To send those, build the payload per
the [Cloud API media docs](https://developers.facebook.com/docs/whatsapp/cloud-api/messages/media-messages)
and POST it to `wa_bot.msg_url` with `Authorization: Bearer <token>`.
:::

## Location messages

Incoming locations (sent by the user, or in answer to an `InlineLocationRequest`):

```python
@wa_bot.on_location_message()
def on_location(update, context):
    context.user_data['delivery'] = {
        'lat': update.loc_latitude, 'lng': update.loc_longitude,
        'name': update.loc_name, 'address': update.loc_address,
    }
    update.reply_message('Got it, delivering to ' + (update.loc_address or 'your pin'))
```

Sending a location is described in [Sending messages](./sending-messages#location-messages).
