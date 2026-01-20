---
sidebar_position: 5
---

# Interactive Messages

Interactive messages allow you to send rich message templates that enable users to interact with your bot through buttons, lists, and other UI elements.

## Types of Interactive Messages

The Python WhatsApp Bot supports several types of interactive messages:

### Reply Buttons
Simple buttons that users can tap to send a predefined message back to your bot.

### Action Lists
Dropdown-style lists that allow users to select from multiple options.

### Product Catalogs
Showcase products from your catalog with images and descriptions.

## Implementation

To send an interactive message:

```python
from python_whatsapp_bot import InteractiveMessage

# Create an interactive message with reply buttons
interactive_msg = InteractiveMessage(
    recipient_id="whatsapp_phone_number",
    header="Choose an option:",
    body="Please select one of the following options",
    footer="Powered by Python WhatsApp Bot",
    buttons=[
        {"type": "reply", "reply": {"id": "opt1", "title": "Option 1"}},
        {"type": "reply", "reply": {"id": "opt2", "title": "Option 2"}}
    ]
)

# Send the message
await client.send_interactive_message(interactive_msg)
```

For handling user interactions with these messages, see the [Message Handlers](./message-handlers) section.