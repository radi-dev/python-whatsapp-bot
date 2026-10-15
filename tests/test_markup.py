"""Tests for the reply-markup helpers."""

import pytest

from python_whatsapp_bot import Inline_button, Inline_keyboard, Inline_list, InlineLocationRequest, List_item
from python_whatsapp_bot.markup import List_section


class TestInlineKeyboard:
    def test_strings_become_buttons_with_text_as_id(self):
        kb = Inline_keyboard(["Yes", "No"])
        assert kb.type == "button"
        assert kb.markup == {
            "buttons": [
                {"type": "reply", "reply": {"id": "Yes", "title": "Yes"}},
                {"type": "reply", "reply": {"id": "No", "title": "No"}},
            ]
        }

    def test_explicit_ids(self):
        kb = Inline_keyboard([Inline_button("Yes", button_id="btn_yes")])
        assert kb.markup["buttons"][0]["reply"] == {"id": "btn_yes", "title": "Yes"}

    @pytest.mark.parametrize("buttons", [[], ["a", "b", "c", "d"], ["a", "a"], [1]])
    def test_invalid(self, buttons):
        with pytest.raises(ValueError):
            Inline_keyboard(buttons)


class TestInlineList:
    def test_flat_items(self):
        lst = Inline_list("Menu", [List_item("Pizza"), List_item("Burger", _id="b", description="Fries")])
        assert lst.type == "list"
        assert lst.markup == {
            "button": "Menu",
            "sections": [{"rows": [{"id": "Pizza", "title": "Pizza"},
                                    {"id": "b", "title": "Burger", "description": "Fries"}]}],
        }

    def test_sections(self):
        lst = Inline_list("Menu", [
            List_section("Starters", [List_item("Rolls"), "Bread"]),
            List_section("Mains", [List_item("Pasta", _id="m1")]),
        ])
        assert lst.markup == {
            "button": "Menu",
            "sections": [
                {"title": "Starters", "rows": [{"id": "Rolls", "title": "Rolls"}, {"id": "Bread", "title": "Bread"}]},
                {"title": "Mains", "rows": [{"id": "m1", "title": "Pasta"}]},
            ],
        }

    def test_mixed_items_and_sections_rejected(self):
        with pytest.raises(ValueError):
            Inline_list("Menu", [List_section("S", ["a"]), List_item("b")])

    def test_invalid_items(self):
        with pytest.raises(ValueError):
            Inline_list("Menu", "not a list")
        with pytest.raises(ValueError):
            Inline_list("Menu", ["plain strings are not allowed at top level"])


def test_location_request():
    m = InlineLocationRequest("Send location")
    assert m.type == "location_request_message"
    assert m.markup == {"name": "send_location"}
