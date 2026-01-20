---
sidebar_position: 7
---

# Media Handling

The Python WhatsApp Bot provides comprehensive support for sending and receiving various types of media, including images, videos, documents, and audio files.

## Sending Media

To send media files to users:

### Images
```python
from python_whatsapp_bot import MediaMessage

# Send an image by URL
image_msg = MediaMessage(
    recipient_id="whatsapp_phone_number",
    media_type="image",
    media_url="https://example.com/image.jpg",
    caption="Check out this image!"
)

await client.send_media_message(image_msg)
```

### Documents
```python
# Send a document
document_msg = MediaMessage(
    recipient_id="whatsapp_phone_number",
    media_type="document",
    media_url="https://example.com/document.pdf",
    filename="important_document.pdf"
)

await client.send_media_message(document_msg)
```

## Receiving Media

When users send media to your bot, it's processed through the message handlers. The media is typically provided as URLs that expire after a certain period.

```python
async def handle_media_message(self, message_data):
    media_type = message_data.get('type')  # 'image', 'video', 'document', 'audio'
    media_url = message_data.get(media_type, {}).get('url', '')
    
    # Download and process the media as needed
    # Be sure to handle the expiration of temporary URLs
```

## Best Practices

- Always validate media URLs before processing
- Store media temporarily if you need to process it later
- Respect file size limits imposed by the WhatsApp Cloud API
- Provide appropriate fallbacks when media cannot be processed