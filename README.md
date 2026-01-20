# python-whatsapp-bot

A modern, feature-rich Python library for building WhatsApp bots using the [WhatsApp Business Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api).

[![Made in Nigeria](https://img.shields.io/badge/made%20in-nigeria-008751.svg?style=flat-square)](https://github.com/acekyd/made-in-nigeria)
[![Downloads](https://pepy.tech/badge/python-whatsapp-bot)](https://pepy.tech/project/python-whatsapp-bot)
[![Downloads](https://pepy.tech/badge/python-whatsapp-bot/month)](https://pepy.tech/project/python-whatsapp-bot)
[![Downloads](https://pepy.tech/badge/python-whatsapp-bot/week)](https://pepy.tech/project/python-whatsapp-bot)

## ✨ Key Features

- 🔄 **Sync & Async Support**: Mirror async versions of all functions (e.g., `send_message` and `asend_message`)
- 📝 **Full Type Annotations**: Python 3.6+ compatible type hints throughout the codebase
- 💬 **Text Messages**: Send and receive text messages with preview support
- 🎯 **Interactive Messages**: Buttons, lists, and location requests
- 📄 **Template Messages**: Send pre-approved template messages
- 📎 **Media Support**: Send and receive images, videos, audio, documents, and stickers
- 📍 **Location Sharing**: Send and receive location data
- 🤖 **Handler System**: Decorator-based message handlers with regex and custom filters
- 🔁 **Context Management**: Maintain conversation state across messages
- 🚀 **Easy Setup**: Simple initialization and intuitive API

## 📦 Installation

Install the library using pip:

```bash
pip install --upgrade python-whatsapp-bot
```

## 🚀 Quick Start

### Setting Up

To use this library, you need:
1. **Phone Number ID**: From your WhatsApp Business account
2. **Access Token**: From the Facebook Developer Portal

Follow the [official WhatsApp setup tutorial](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started) to obtain these credentials.

### Basic Initialization

```python
from python_whatsapp_bot import Whatsapp

# Initialize the bot
wa_bot = Whatsapp(number_id='YOUR_PHONE_NUMBER_ID', token='YOUR_ACCESS_TOKEN')
```

## 📖 Usage Guide

### Sending Text Messages

**Synchronous:**
```python
# Simple text message
wa_bot.send_message('2348145xxxxx', 'Hello, World!')

# With web preview disabled
wa_bot.send_message('2348145xxxxx', 'Check this link: https://example.com', web_page_preview=False)
```

**Asynchronous:**
```python
import asyncio

async def main():
    # Async version
    await wa_bot.asend_message('2348145xxxxx', 'Hello from async!')

asyncio.run(main())
```

### Interactive Messages

#### Buttons

```python
from python_whatsapp_bot import Inline_keyboard

# Simple buttons
buttons = Inline_keyboard(['Option 1', 'Option 2', 'Option 3'])
wa_bot.send_message(
    '2348145xxxxx',
    'Choose an option:',
    reply_markup=buttons
)

# Custom button IDs
from python_whatsapp_bot import Inline_button

buttons = Inline_keyboard([
    Inline_button('Yes', button_id='btn_yes'),
    Inline_button('No', button_id='btn_no')
])
wa_bot.send_message('2348145xxxxx', 'Confirm?', reply_markup=buttons)
```

#### Lists

```python
from python_whatsapp_bot import Inline_list, List_item

# Simple list
list_items = [
    List_item('Pizza'),
    List_item('Burger'),
    List_item('Salad')
]
list_markup = Inline_list('Select Food', list_items)
wa_bot.send_message('2348145xxxxx', 'What would you like?', reply_markup=list_markup)

# List with descriptions
list_items = [
    List_item('Premium Plan', _id='plan_premium', description='$99/month - All features'),
    List_item('Basic Plan', _id='plan_basic', description='$29/month - Essential features')
]
list_markup = Inline_list('Choose Plan', list_items)
wa_bot.send_message('2348145xxxxx', 'Select a plan:', reply_markup=list_markup)

# Sectioned lists
from python_whatsapp_bot import List_section

sections = [
    List_section('Appetizers', [
        List_item('Spring Rolls'),
        List_item('Garlic Bread')
    ]),
    List_section('Main Course', [
        List_item('Pasta'),
        List_item('Steak')
    ])
]
list_markup = Inline_list('Menu', sections)
wa_bot.send_message('2348145xxxxx', 'Our menu:', reply_markup=list_markup)
```

### Template Messages

```python
# Simple template
wa_bot.send_template_message('2348145xxxxx', 'hello_world')

# Template with components
components = [
    {
        "type": "body",
        "parameters": [
            {"type": "text", "text": "John Doe"},
            {"type": "text", "text": "Order #12345"}
        ]
    }
]
wa_bot.send_template_message(
    '2348145xxxxx',
    'order_confirmation',
    components=components,
    language_code='en_US'
)

# Async version
await wa_bot.asend_template_message('2348145xxxxx', 'hello_world')
```

### Media Messages

```python
# Send image from URL
wa_bot.send_media_message(
    '2348145xxxxx',
    'https://example.com/image.jpg',
    caption='Check this out!'
)

# Async version
await wa_bot.asend_media_message(
    '2348145xxxxx',
    'https://example.com/image.jpg',
    caption='Amazing photo!'
)

# Download received media
media_id = 'MEDIA_ID_FROM_WEBHOOK'
file_path = wa_bot.download_media(media_id, '/downloads')
print(f'Media saved to: {file_path}')

# Async download
file_path = await wa_bot.adownload_media(media_id, '/downloads')
```

### Location Messages

```python
from python_whatsapp_bot.message import message_location

message_location(
    wa_bot.msg_url,
    wa_bot.token,
    '2348145xxxxx',
    latitude='37.7749',
    longitude='-122.4194',
    location_name='San Francisco',
    location_address='Golden Gate Bridge'
)
```

## 🎯 Handling Incoming Messages

### Setting Up Webhooks

WhatsApp sends incoming messages to your webhook URL. You need to:
1. Register your webhook URL in the Facebook Developer Portal
2. Verify the webhook with a GET request handler
3. Process POST requests containing message updates

### Message Handlers

```python
from flask import Flask, request

app = Flask(__name__)

# Simple message handler
@wa_bot.on_message()
def handle_message(update, context):
    # Echo the message
    update.reply_message(f"You said: {update.message_text}")

# Regex-based handler
@wa_bot.on_message(regex=r'^/start')
def handle_start(update, context):
    update.reply_message('Welcome! How can I help you?')

# Interactive message handler
@wa_bot.on_interactive_message()
def handle_button(update, context):
    button_id = update.message_text
    if button_id == 'btn_yes':
        update.reply_message('Great! Proceeding...')
    elif button_id == 'btn_no':
        update.reply_message('Okay, cancelled.')

# Image handler
@wa_bot.on_image_message()
def handle_image(update, context):
    media_id = update.media_file_id
    update.reply_message(f'Thanks for the image! ID: {media_id}')

# Location handler
@wa_bot.on_location_message()
def handle_location(update, context):
    lat = update.loc_latitude
    lon = update.loc_longitude
    update.reply_message(f'Received location: {lat}, {lon}')

# Webhook endpoint
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    wa_bot.process_update(data)
    return 'OK', 200

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    if mode == 'subscribe' and token == 'YOUR_VERIFY_TOKEN':
        return challenge, 200
    return 'Forbidden', 403

if __name__ == '__main__':
    app.run(port=5000)
```

### Async Message Handlers

```python
import asyncio
from aiohttp import web

# Async handler
@wa_bot.on_message()
async def handle_message_async(update, context):
    # Perform async operations
    await asyncio.sleep(1)  # Simulate async work
    await update.reply_message('Processed asynchronously!')

# Async webhook
async def webhook_handler(request):
    data = await request.json()
    await wa_bot.dispatcher.aprocess_update(data)
    return web.Response(text='OK')

app = web.Application()
app.router.add_post('/webhook', webhook_handler)

if __name__ == '__main__':
    web.run_app(app, port=5000)
```

### Context and Conversation Management

```python
# Store user data in context
@wa_bot.on_message(regex=r'^/setname (.+)')
def set_name(update, context):
    name = update.message_text.split(' ', 1)[1]
    context.user_data['name'] = name
    update.reply_message(f'Name set to: {name}')

@wa_bot.on_message(regex=r'^/getname')
def get_name(update, context):
    name = context.user_data.get('name', 'Not set')
    update.reply_message(f'Your name is: {name}')

# Multi-step conversations
@wa_bot.on_message(regex=r'^/register')
def start_registration(update, context):
    update.reply_message('Please enter your name:')
    wa_bot.set_next_step(update, get_user_name)

def get_user_name(update, context):
    context.user_data['name'] = update.message_text
    update.reply_message('Please enter your email:')
    wa_bot.set_next_step(update, get_user_email)

def get_user_email(update, context):
    context.user_data['email'] = update.message_text
    name = context.user_data['name']
    email = context.user_data['email']
    update.reply_message(f'Registration complete!\nName: {name}\nEmail: {email}')
```

## 🔧 Advanced Features

### Custom Filters

```python
# Custom filter function
def is_premium_user(message_text):
    # Your logic here
    return message_text.startswith('!')

@wa_bot.on_message(func=is_premium_user)
def handle_premium(update, context):
    update.reply_message('Premium command received!')
```

### Persistent Handlers

```python
# Handler that runs for every message
@wa_bot.on_message(persistent=True)
def log_all_messages(update, context):
    print(f'Message from {update.user_phone_number}: {update.message_text}')
```

### Mark Messages as Read

```python
# Sync
wa_bot.mark_as_read(message_update)

# Async
await wa_bot.amark_as_read(message_update)

# Auto-mark on initialization
wa_bot = Whatsapp(number_id='...', token='...', mark_as_read=True)  # Default
```

## 🧪 Testing

The library includes comprehensive test suites for both sync and async functions.

```bash
# Install dev dependencies
pip install pytest pytest-asyncio pytest-httpx

# Run all tests
pytest

# Run specific test file
pytest tests/test_message.py

# Run async tests only
pytest tests/test_message_async.py

# With coverage
pytest --cov=python_whatsapp_bot
```

## 📚 API Reference

### Main Classes

#### `Whatsapp(number_id, token, mark_as_read=True)`
Main bot class for interacting with WhatsApp Cloud API.

**Methods:**
- `send_message()` / `asend_message()` - Send text messages
- `send_template_message()` / `asend_template_message()` - Send template messages
- `send_media_message()` / `asend_media_message()` - Send media files
- `mark_as_read()` / `amark_as_read()` - Mark messages as read
- `download_media()` / `adownload_media()` - Download media files
- `get_media_url()` / `aget_media_url()` - Get media URLs
- `process_update()` - Process incoming webhook updates

#### `Update`
Represents an incoming message update.

**Attributes:**
- `user_phone_number` - Sender's phone number
- `user_display_name` - Sender's display name
- `message_text` - Text content of message
- `message_id` - Unique message identifier
- `media_file_id` - Media file ID (for media messages)
- `loc_latitude`, `loc_longitude` - Location coordinates

**Methods:**
- `reply_message()` - Reply to the message
- `reply_media()` - Reply with media

#### Markup Classes

- `Inline_keyboard(buttons)` - Create button markup
- `Inline_button(text, button_id)` - Single button
- `Inline_list(button_text, list_items)` - List markup
- `List_item(title, _id, description)` - List item
- `List_section(title, items_list)` - List section
- `InlineLocationRequest(text)` - Location request button

## 🐛 Troubleshooting

### Common Issues

**Import Errors:**
```bash
pip install --upgrade python-whatsapp-bot httpx
```

**Webhook Not Receiving Messages:**
1. Verify webhook URL is registered in Facebook Developer Portal
2. Ensure URL is publicly accessible (use ngrok for local testing)
3. Check webhook verification token matches

**Message Not Sending:**
1. Verify phone number format (include country code without '+' or '00')
2. Check access token is valid
3. Ensure phone number is registered with WhatsApp Business

## 🔗 Links

- **Documentation**: [Full documentation site](https://radi-dev.github.io/python-whatsapp-cloud-bot/)
- **GitHub**: [Repository](https://github.com/Radi-dev/python-whatsapp-cloud-bot)
- **PyPI**: [Package](https://pypi.org/project/python-whatsapp-bot/)
- **WhatsApp API Docs**: [Official documentation](https://developers.facebook.com/docs/whatsapp/cloud-api/)

## 🤝 Contributing

Contributions are welcome! This is an open-source project under the MIT License.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Credits

- All contributors to this project
- WhatsApp Business Cloud API team
- The Python community

## 📮 Support

If you encounter any issues or have questions:
- Open an [issue on GitHub](https://github.com/Radi-dev/python-whatsapp-cloud-bot/issues)
- Check the [documentation](https://radi-dev.github.io/python-whatsapp-cloud-bot/)
- Review [WhatsApp API documentation](https://developers.facebook.com/docs/whatsapp/cloud-api/)

---

Made with ❤️ by [Radi](https://github.com/Radi-dev)
