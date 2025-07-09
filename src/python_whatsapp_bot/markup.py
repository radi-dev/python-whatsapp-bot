from typing import Any, Dict, Union


class Reply_markup:
    type: str

    def __init__(self, markup: Dict[str, Any]) -> None:
        self.markup = markup

    # if item is for keyboard, initialize with button settings
    # if item is for list actions, initialize with list settings


class InlineLocationRequest(Reply_markup):
    """This is used to request a location from the user.
    It is a button that when clicked, opens the user's location.
    Args:
        text: (str),required - Specifies the text of the button
        button_id: (str),optional - Specifies the id of the button. If not provided, it will be set to the text of the button
    """

    type: str = "location_request_message"

    def __init__(self, text: str):
        self.action = self.get_action()
        super().__init__(self.action)

    def get_action(self):
        return {"name": "send_location"}


class Inline_button:
    def __init__(self, text: str, button_id: str = None):

        self.button = {
            "type": "reply",
                    "reply": {
                        "id": button_id if button_id else text,
                        "title": text
                    }
        }
    __slots__ = ('button')


class Inline_keyboard(Reply_markup):
    """Accepts only three(3) text (or buttons) in a flat list.
    Minimum of one(1)"""
    type: str = "button"

    def __init__(self, inline_buttons: Union[list[str], list[Inline_button]]):
        self.inline_buttons = self.set_buttons(inline_buttons)
        self.error_check()
        self.keyboard = self.set_keys()
        super().__init__(self.keyboard)

    def set_buttons(self, _buttons: Union[list[str], list[Inline_button]]):
        if not isinstance(_buttons, list):
            raise ValueError("List argument expected")
        res = []
        for i in _buttons:
            if isinstance(i, str):
                res.append(Inline_button(i))
            elif isinstance(i, Inline_button):
                res.append(i)
            else:
                raise ValueError(
                    "str or Inline_button expected as button elements")
        return res

    def error_check(self):
        if len(self.inline_buttons) > 3 or len(self.inline_buttons) < 1:
            raise ValueError(
                f"Inline_keyboard can only accept minimum of 1 Inline_button item and maximum of 3, you added {len(self.inline_buttons)}"
            )
        button_id_check = []
        button_text_check = []
        for i, button in enumerate(self.inline_buttons):
            if not isinstance(button, Inline_button):
                raise ValueError(
                    f"Item at position {i} of list argument expected to be string or an instance of Inline_button")
            butt = button.button['reply']['id']
            buttt = button.button['reply']['title']
            if butt in button_id_check or buttt in button_text_check:
                raise ValueError("Use unique id and text for the buttons")
            button_id_check.append(butt)
            button_text_check.append(buttt)

    def set_keys(self):
        action = {"buttons": [i.button for i in self.inline_buttons]}
        return action


class List_item():
    def __init__(self, title: str, _id: str = None, description: str = None) -> None:
        self.title = title
        self._id = _id if _id else self.title
        self.item = {
            "id": self._id,
            "title": self.title
        }
        if description:
            self.item["description"] = description
    __slots__ = ('title', 'item', '_id')


class List_section():
    def __init__(self, title: str, items_list: Union[list[str], list[List_item]]) -> None:
        self.title = title
        self.items_list = self.set_list(items_list)
        self.error_check()
        self.section = self.set_section()

    def set_list(self, _items_list: Union[list[str], list[List_item]]):
        if not isinstance(_items_list, list):
            raise ValueError("List argument expected")
        res = []
        for i in _items_list:
            if isinstance(i, str):
                res.append(List_item(i))
            elif isinstance(i, List_item):
                res.append(i)
            else:
                raise ValueError(
                    "str or List_item object expected as items_list elements")
        return res

    def error_check(self):
        for i, item in enumerate(self.items_list):
            if not isinstance(item, List_item):
                raise ValueError(
                    f"Item at position {i} of list argument expected to be an instance of Inline_button")

    def set_section(self):
        sections = {"title": self.title,
                    "rows": [i.item for i in self.items_list]}
        return sections


class Inline_list(Reply_markup):
    """Accepts up to ten(10) list items. Minimum of one(1)
    Accepts one level of nesting, e.g [[],[],[]].
    Args:
        button_text: (str),required - Specifies the button that displays the list items when clicked
        list_items:(list) required - Specifies the list items to be listed. Maximum of ten items.
            These Items are defined with the List_item class.
            To use sections, pass a list of List_section instances instead"""
    type: str = "list"

    def __init__(self, button_text: str, list_items: Union[list[List_item], list[List_section]]):
        self.button_text = button_text
        self.list_items = list_items
        self.error_check()
        self.inline_list = self.set_list()
        super().__init__(self.inline_list)

    def error_check(self):
        if not isinstance(self.list_items, list):
            raise ValueError(
                "The argument for list_items should be of type 'list'")

        for i, item in enumerate(self.list_items):
            if not (isinstance(item, List_item) or isinstance(item, List_section)):
                # Check that non-nested list is List_item
                raise ValueError(
                    f"Item at position {i} of list argument expected to be an instance of List_item or list of List_section")

    def set_list(self):
        action = {
            "button": self.button_text,
            "sections": [i.section for i in self.list_items] if isinstance(self.list_items, List_section) else [{"rows": [i.item for i in self.list_items]}]}
        return action
