from typing import Any, Dict, Union


class Reply_markup:
    type: str

    def __init__(self, markup):
        # type: (Dict[str, Any]) -> None
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

    def __init__(self, text):
        # type: (str) -> None
        self.action = self.get_action()
        super(InlineLocationRequest, self).__init__(self.action)

    def get_action(self):
        # type: () -> Dict[str, str]
        return {"name": "send_location"}


class Inline_button:
    __slots__ = ('button',)

    def __init__(self, text, button_id=None):
        # type: (str, str) -> None

        self.button = {
            "type": "reply",
                    "reply": {
                        "id": button_id if button_id else text,
                        "title": text
                    }
        }


class Inline_keyboard(Reply_markup):
    """Accepts only three(3) text (or buttons) in a flat list.
    Minimum of one(1)"""
    type: str = "button"

    def __init__(self, inline_buttons):
        # type: (Union[list, list]) -> None
        self.inline_buttons = self.set_buttons(inline_buttons)
        self.error_check()
        self.keyboard = self.set_keys()
        super(Inline_keyboard, self).__init__(self.keyboard)

    def set_buttons(self, _buttons):
        # type: (Union[list, list]) -> list
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
        # type: () -> None
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
        # type: () -> Dict[str, list]
        action = {"buttons": [i.button for i in self.inline_buttons]}
        return action


class List_item():
    __slots__ = ('title', 'item', '_id')

    def __init__(self, title, _id=None, description=None):
        # type: (str, str, str) -> None
        self.title = title
        self._id = _id if _id else self.title
        self.item = {
            "id": self._id,
            "title": self.title
        }  # type: Dict[str, str]
        if description:
            self.item["description"] = description


class List_section():
    def __init__(self, title, items_list):
        # type: (str, Union[list, list]) -> None
        self.title = title
        self.items_list = self.set_list(items_list)
        self.error_check()
        self.section = self.set_section()

    def set_list(self, _items_list):
        # type: (Union[list, list]) -> list
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
        # type: () -> None
        for i, item in enumerate(self.items_list):
            if not isinstance(item, List_item):
                raise ValueError(
                    f"Item at position {i} of list argument expected to be an instance of Inline_button")

    def set_section(self):
        # type: () -> Dict[str, Any]
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

    def __init__(self, button_text, list_items):
        # type: (str, Union[list, list]) -> None
        self.button_text = button_text
        self.list_items = list_items
        self.error_check()
        self.inline_list = self.set_list()
        super(Inline_list, self).__init__(self.inline_list)

    def error_check(self):
        # type: () -> None
        if not isinstance(self.list_items, list):
            raise ValueError(
                "The argument for list_items should be of type 'list'")

        for i, item in enumerate(self.list_items):
            if not (isinstance(item, List_item) or isinstance(item, List_section)):
                # Check that non-nested list is List_item
                raise ValueError(
                    f"Item at position {i} of list argument expected to be an instance of List_item or list of List_section")

    def set_list(self):
        # type: () -> Dict[str, Any]
        action = {
            "button": self.button_text,
            "sections": [i.section for i in self.list_items] if isinstance(self.list_items, List_section) else [{"rows": [i.item for i in self.list_items]}]}
        return action
