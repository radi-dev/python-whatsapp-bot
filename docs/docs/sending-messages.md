---
sidebar_position: 3
---

# Sending Messages

Learn how to send different types of messages with python-whatsapp-bot.

## Text Messages

### Basic Text Message

Send a simple text message:

```python
wa_bot.send_message('1234567890', 'Hello, World!')
```

### Async Version

```python
await wa_bot.asend_message('1234567890', 'Hello, World!')
```

### With Web Preview

Control link previews:

```python
# Disable preview
wa_bot.send_message(
    '1234567890',
    'Check out https://example.com',
    web_page_preview=False
)

# Enable preview (default)
wa_bot.send_message(
    '1234567890',
    'Check out https://example.com',
    web_page_preview=True
)
```

### Reply to a Message

Reply to a specific message:

```python
wa_bot.send_message(
    '1234567890',
    'This is a reply',
    msg_id='original_message_id',
    tag_message=True
)
```

## Template Messages

Send pre-approved template messages:

### Basic Template

```python
wa_bot.send_template_message('1234567890', 'hello_world')
```

### Template with Parameters

```python
components = [
    {
        "type": "body",
        "parameters": [
            {"type": "text", "text": "John"},
            {"type": "text", "text": "Order #12345"}
        ]
    }
]

wa_bot.send_template_message(
    '1234567890',
    'order_confirmation',
    components=components,
    language_code='en_US'
)
```

### Async Template

```python
await wa_bot.asend_template_message(
    '1234567890',
    'hello_world'
)
```

## Media Messages

### Send Image

From URL:

```python
wa_bot.send_media_message(
    '1234567890',
    'https://example.com/image.jpg',
    caption='Check this out!'
)
```

Async version:

```python
await wa_bot.asend_media_message(
    '1234567890',
    'https://example.com/image.jpg',
    caption='Amazing photo!'
)
```

### Supported Media Types

The library supports:
- **Images**: JPG, PNG, GIF
- **Videos**: MP4, 3GPP
- **Audio**: MP3, AAC, OGG
- **Documents**: PDF, DOC, DOCX, XLS, XLSX, PPT, PPTX
- **Stickers**: WEBP with transparency

## Location Messages

Send a location:

```python
from python_whatsapp_bot.message import message_location

message_location(
    wa_bot.msg_url,
    wa_bot.token,
    '1234567890',
    latitude='37.7749',
    longitude='-122.4194',
    location_name='San Francisco',
    location_address='California, USA'
)
```

Async version:

```python
from python_whatsapp_bot.message import amessage_location

await amessage_location(
    wa_bot.msg_url,
    wa_bot.token,
    '1234567890',
    latitude='37.7749',
    longitude='-122.4194',
    location_name='San Francisco',
    location_address='California, USA'
)
```

## Best Practices

### Phone Number Format

Always use the international format without `+` or spaces:

```python
# ✅ Correct
wa_bot.send_message('1234567890', 'Hello')

# ❌ Incorrect
wa_bot.send_message('+1 234 567 890', 'Hello')
wa_bot.send_message('+1234567890', 'Hello')
```

### Error Handling

Always handle potential errors:

```python
try:
    response = wa_bot.send_message('1234567890', 'Hello')
    if response.status_code == 200:
        print("Message sent successfully!")
    else:
        print(f"Error: {response.status_code}")
except Exception as e:
    print(f"Failed to send message: {e}")
```

### Rate Limiting

WhatsApp has rate limits. Implement proper throttling:

```python
import time

messages = ['Message 1', 'Message 2', 'Message 3']

for msg in messages:
    wa_bot.send_message('1234567890', msg)
    time.sleep(1)  # Wait 1 second between messages
```

### Async for Performance

Use async functions for better performance with multiple messages:

```python
import asyncio

async def send_bulk_messages():
    tasks = []
    for i in range(10):
        task = wa_bot.asend_message('1234567890', f'Message {i}')
        tasks.append(task)
    
    await asyncio.gather(*tasks)

asyncio.run(send_bulk_messages())
```

## Message Status

Check if a message was delivered:

```python
response = wa_bot.send_message('1234567890', 'Hello')
result = response.json()

if result.get('messages'):
    message_id = result['messages'][0]['id']
    print(f"Message ID: {message_id}")
```

## Next Steps

- Learn about [Interactive Messages](./interactive-messages)
- Set up [Message Handlers](./message-handlers)
- Explore [Media Handling](./media-handling)
