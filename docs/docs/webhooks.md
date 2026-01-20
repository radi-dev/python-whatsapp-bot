---
sidebar_position: 4
---

# Webhooks

Webhook functionality allows your application to receive real-time notifications from the WhatsApp Cloud API when events occur. This includes incoming messages, delivery receipts, and other important updates.

## Setting Up Webhooks

To set up webhooks for your Python WhatsApp Bot:

1. Configure your webhook endpoint URL in the WhatsApp Cloud API settings
2. Ensure your server can handle POST requests to the webhook endpoint
3. Verify the webhook using the token provided during setup

## Handling Webhook Events

The bot framework provides handlers for different webhook event types:

- Message received
- Message delivered
- Message read
- Media uploaded

For detailed implementation, see the [Message Handlers](./message-handlers) section.