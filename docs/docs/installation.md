---
sidebar_position: 2
---

# Installation

## Requirements

- Python 3.7 or higher
- A WhatsApp Business account on the Meta for Developers portal (see below)
- For production: an external store for conversation state - SQLite needs nothing extra; Redis,
  Postgres and MySQL need an optional package (see below)

## Install

```bash
pip install --upgrade python-whatsapp-bot
```

This installs the library with its two runtime dependencies, `requests` (sync HTTP) and `httpx`
(async HTTP).

### Optional: context storage backends

Conversation state (`context.user_data`, multi-step conversations) is kept in a storage backend
you choose. `SQLiteStorage` works out of the box; the others need a driver:

```bash
pip install "python-whatsapp-bot[redis]"        # RedisStorage
pip install "python-whatsapp-bot[postgres]"     # SQLAlchemyStorage with psycopg
pip install "python-whatsapp-bot[mysql]"        # SQLAlchemyStorage with PyMySQL
pip install "python-whatsapp-bot[sqlalchemy]"   # SQLAlchemyStorage, bring your own driver
```

See [Context storage](./context-storage) for how to configure them.

### From source

```bash
git clone https://github.com/Radi-dev/python-whatsapp-cloud-bot.git
cd python-whatsapp-cloud-bot
pip install -e ".[dev]"    # editable install with everything needed to run the tests
pytest
```

## WhatsApp Business setup

You need two credentials from the [Meta for Developers](https://developers.facebook.com/) portal.

1. **Create an app** - "Create App", choose the *Business* type, then add the **WhatsApp**
   product to it.
2. **Phone Number ID** - under *WhatsApp → API Setup*, copy the *Phone number ID* (not the phone
   number itself), e.g. `109123456789012`.
3. **Access token** - the same page offers a *temporary* token that expires after 24 hours. For
   production create a *System User* under *Business Settings* and generate a permanent token
   with the `whatsapp_business_messaging` permission.
4. **Webhook** - configured later, once your server is reachable. See [Webhooks](./webhooks).

:::warning
Never commit tokens. Keep them in environment variables or a secrets manager.
:::

```python
import os
from python_whatsapp_bot import Whatsapp, SQLiteStorage

wa_bot = Whatsapp(
    number_id=os.environ['WHATSAPP_PHONE_NUMBER_ID'],
    token=os.environ['WHATSAPP_ACCESS_TOKEN'],
    context_storage=SQLiteStorage('bot_context.db'),
)
```

## Verify

```python
from python_whatsapp_bot import Whatsapp
print(Whatsapp)   # no ImportError: the library is installed
```

To verify the credentials, send yourself a message (the recipient must have messaged your
business number first, or you must use an approved template):

```python
wa_bot.send_message('2348145xxxxx', 'Hello from python-whatsapp-bot!')
```

`send_message` returns the `requests.Response` of the API call; `response.json()` contains the
message id on success or an `error` object otherwise.

## Graph API version

The library targets Graph API **v21.0** by default. To pin another version:

```python
wa_bot.set_version(22)
```
