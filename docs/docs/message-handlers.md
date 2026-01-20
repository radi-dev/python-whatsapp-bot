---
sidebar_position: 6
---

# Message Handlers

Message handlers allow you to define custom logic for processing incoming messages from users. They form the core of your bot's response mechanism.

## Creating Message Handlers

You can create message handlers to process different types of incoming messages:

```python
from python_whatsapp_bot.handler_classes import BaseMessageHandler

class CustomMessageHandler(BaseMessageHandler):
    def __init__(self):
        super().__init__()
    
    async def handle_message(self, message_data):
        # Process the incoming message
        message_type = message_data.get('type')
        
        if message_type == 'text':
            return await self.handle_text_message(message_data)
        elif message_type == 'image':
            return await self.handle_image_message(message_data)
        # Add more message type handlers as needed
    
    async def handle_text_message(self, message_data):
        # Handle text messages specifically
        text = message_data.get('text', {}).get('body', '')
        
        if 'hello' in text.lower():
            return {'response': 'Hello! How can I help you?'}
        
        return {'response': 'Thanks for your message!'}
    
    async def handle_image_message(self, message_data):
        # Handle image messages specifically
        image_url = message_data.get('image', {}).get('url', '')
        # Process the image as needed
        
        return {'response': 'Received your image!'}
```

## Registering Handlers

To register your custom message handler with the dispatcher:

```python
from python_whatsapp_bot.dispatcher import MessageDispatcher

dispatcher = MessageDispatcher()
handler = CustomMessageHandler()
dispatcher.register_handler(handler)
```

## Handler Priority

Handlers are processed in the order they are registered. You can control the priority by registering more specific handlers first.