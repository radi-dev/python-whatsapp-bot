---
sidebar_position: 4
---

# Interactive Messages

Interactive messages let the user answer by tapping instead of typing. They are sent with
`send_message` / `asend_message` (or `update.reply_message`) by passing a `reply_markup`:

| Markup | What the user sees | Limits |
|---|---|---|
| `Inline_keyboard([...])` | up to 3 reply buttons under the text | 1-3 buttons, titles ≤ 20 chars, unique ids |
| `Inline_list(button_text, [...])` | a button that opens a list of options | up to 10 rows in total, optionally grouped in sections |
| `InlineLocationRequest(text)` | a "Send location" button | - |

The user's tap arrives as an *interactive* update whose `message_text` is the **id** of the
chosen button or row - handle it with `@wa_bot.on_interactive_message()`.

## Reply buttons

```python
from python_whatsapp_bot import Inline_keyboard, Inline_button

# Quick form: the button text is also its id
wa_bot.send_message('2348145xxxxx', 'Confirm your order?', reply_markup=Inline_keyboard(['Yes', 'No']))

# Explicit ids, so the handler does not depend on the visible text
buttons = Inline_keyboard([
    Inline_button('Yes, confirm', button_id='order_confirm'),
    Inline_button('Cancel', button_id='order_cancel'),
])
wa_bot.send_message('2348145xxxxx', 'Confirm your order?', reply_markup=buttons)
```

`Inline_keyboard` raises `ValueError` for fewer than 1 or more than 3 buttons, or for
duplicate ids/titles.

## Lists

```python
from python_whatsapp_bot import Inline_list, List_item

menu = Inline_list('Choose a dish', [
    List_item('Pizza'),                                   # id defaults to the title
    List_item('Burger', _id='dish_burger', description='With fries'),
    List_item('Salad', _id='dish_salad'),
])
wa_bot.send_message('2348145xxxxx', 'What would you like?', reply_markup=menu)
```

### Sections

Group rows under headings by passing `List_section` objects instead of items:

```python
from python_whatsapp_bot.markup import List_section

menu = Inline_list('Menu', [
    List_section('Starters', [List_item('Spring rolls'), List_item('Garlic bread')]),
    List_section('Mains', [List_item('Pasta'), List_item('Steak', description='300g')]),
])
```

## Location request

```python
from python_whatsapp_bot import InlineLocationRequest

wa_bot.send_message(
    '2348145xxxxx',
    'Where should we deliver?',
    reply_markup=InlineLocationRequest('Send location'),
)
```

The user's answer is a *location* update - handle it with `@wa_bot.on_location_message()`
(see [Media handling](./media-handling#location-messages)).

## Header and footer

Any interactive message can carry a header and a footer:

```python
wa_bot.send_message(
    '2348145xxxxx',
    'Pick a plan:',
    reply_markup=Inline_keyboard(['Basic', 'Pro']),
    header='Pricing',                    # text header
    footer='Prices include VAT',
)

wa_bot.send_message(
    '2348145xxxxx',
    'Like it?',
    reply_markup=Inline_keyboard(['Love it', 'Meh']),
    header='https://example.com/product.jpg',   # media header: a public URL...
    header_type='image',                        # ...or an uploaded media id; 'image' | 'video' | 'document'
)
```

## Handling the answer

```python
@wa_bot.on_interactive_message(regex=r'^order_')
def on_order_decision(update, context):
    if update.message_text == 'order_confirm':
        update.reply_message('Great, your order is on its way.')
    else:
        update.reply_message('Order cancelled.')

@wa_bot.on_interactive_message(regex=r'^dish_')
def on_dish(update, context):
    context.user_data['dish'] = update.message_text
    update.reply_message(f'{update.message_text} it is!')
```

`on_interactive_message` handles both button and list replies by default; use
`handle_button=False` or `handle_list=False` to restrict it. As with every handler, the first
matching one wins and `regex` / `func` filter on `message_text`, i.e. on the id.

Buttons and lists are often the second step of a conversation; combine them with
`set_next_step(update, fn, handler_type=InteractiveQueryHandler)` - see
[Multi-step conversations](./message-handlers#multi-step-conversations).
