---
sidebar_position: 1
---

# Getting Started

Welcome to **python-whatsapp-bot** - a modern, feature-rich Python library for building WhatsApp bots using the WhatsApp Business Cloud API.

## What You'll Learn

This documentation will guide you through:

- ✅ Setting up your WhatsApp Business account
- ✅ Installing and configuring the library
- ✅ Sending various types of messages (text, media, templates)
- ✅ Creating interactive messages with buttons and lists
- ✅ Handling incoming messages with decorators
- ✅ Using both sync and async versions of functions
- ✅ Managing conversation state and context
- ✅ Testing your bot

## Key Features

### 🔄 Sync & Async Support

Every function has both synchronous and asynchronous versions:

```python
# Synchronous
wa_bot.send_message('1234567890', 'Hello!')

# Asynchronous
await wa_bot.asend_message('1234567890', 'Hello!')
```

### 📝 Type Annotations

Full type hints compatible with Python 3.6+:

```python
def send_message(
    phone_num,  # type: str
    text,  # type: str
    msg_id="",  # type: str
):
    # type: (...) -> Any
```

### 🎯 Interactive Messages

Easily create buttons, lists, and location requests:

```python
from python_whatsapp_bot import Inline_keyboard

buttons = Inline_keyboard(['Option 1', 'Option 2'])
wa_bot.send_message('1234567890', 'Choose:', reply_markup=buttons)
```

### 🤖 Decorator-Based Handlers

Simple and intuitive message handling:

```python
@wa_bot.on_message(regex=r'^/start')
def handle_start(update, context):
    update.reply_message('Welcome!')
```

## Quick Installation

```bash
pip install --upgrade python-whatsapp-bot
```

## Prerequisites

Before you begin, you'll need:

1. **WhatsApp Business Account** - Sign up at [Facebook Developer Portal](https://developers.facebook.com/)
2. **Phone Number ID** - Get this from your WhatsApp Business account
3. **Access Token** - Generate from Facebook Developer Portal
4. **Python 3.6+** - The library supports Python 3.6 and above

## Next Steps

Ready to build your first bot? Continue to the Installation Guide to get started!
