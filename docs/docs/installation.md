---
sidebar_position: 2
---

# Installation

This guide will help you install and set up python-whatsapp-bot for your project.

## Requirements

- Python 3.6 or higher
- pip (Python package manager)
- WhatsApp Business Account
- Access to Facebook Developer Portal

## Install via pip

The easiest way to install the library is using pip:

```bash
pip install --upgrade python-whatsapp-bot
```

## Install from source

If you want the latest development version:

```bash
git clone https://github.com/Radi-dev/python-whatsapp-cloud-bot.git
cd python-whatsapp-cloud-bot
pip install -e .
```

## Verify Installation

After installation, verify it works:

```python
from python_whatsapp_bot import Whatsapp

print("Installation successful!")
```

## Dependencies

The library automatically installs these dependencies:

- **requests** >= 2.0 - For synchronous HTTP requests
- **httpx** >= 0.23.0 - For asynchronous HTTP requests

### Development Dependencies

For development and testing:

```bash
pip install pytest pytest-asyncio pytest-httpx
```

## WhatsApp Business Setup

### Step 1: Create Facebook Developer Account

1. Go to [Facebook for Developers](https://developers.facebook.com/)
2. Click "Get Started" and create an account
3. Complete the registration process

### Step 2: Create an App

1. From the dashboard, click "Create App"
2. Select "Business" as the app type
3. Fill in the app details
4. Click "Create App"

### Step 3: Add WhatsApp Product

1. In your app dashboard, find "WhatsApp" in the products list
2. Click "Set Up"
3. Follow the configuration wizard

### Step 4: Get Credentials

You'll need two pieces of information:

#### Phone Number ID

1. Go to WhatsApp > Getting Started
2. Copy the "Phone number ID" (not the phone number itself)
3. Example: `109123456789012`

#### Access Token

1. In the same section, find "Temporary access token"
2. Copy this token for testing
3. For production, generate a permanent token:
   - Go to Business Settings
   - Create a System User
   - Generate a permanent token

:::warning Important
The temporary token expires after 24 hours. For production, always use a permanent token.
:::

### Step 5: Configure Webhook (Optional for now)

We'll cover webhook setup in detail in the [Webhooks Guide](./webhooks).

## Environment Variables

Store your credentials safely using environment variables:

```bash
# .env file
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
WHATSAPP_ACCESS_TOKEN=your_access_token
```

Load them in your Python code:

```python
import os
from dotenv import load_dotenv

load_dotenv()

phone_id = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
token = os.getenv('WHATSAPP_ACCESS_TOKEN')
```

## First Bot

Now you're ready to create your first bot:

```python
from python_whatsapp_bot import Whatsapp

# Initialize bot
wa_bot = Whatsapp(
    number_id='YOUR_PHONE_NUMBER_ID',
    token='YOUR_ACCESS_TOKEN'
)

# Send a message
wa_bot.send_message('1234567890', 'Hello from Python!')
```

## Troubleshooting

### Import Error

If you get an import error:

```bash
pip uninstall python-whatsapp-bot
pip install --upgrade python-whatsapp-bot
```

### Authentication Failed

- Verify your access token is valid
- Check if the token has expired
- Ensure you're using the correct phone number ID

### Module Not Found: httpx

Install httpx explicitly:

```bash
pip install httpx
```

## Next Steps

- Learn about [Sending Messages](./sending-messages)
- Explore [Interactive Messages](./interactive-messages)
- Set up [Message Handlers](./message-handlers)
