"""Tests for sync message functions"""
import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from python_whatsapp_bot.message import (
    headers,
    mark_as_read,
    message_text,
    message_interactive,
    message_template,
    get_media_url,
    message_media,
    message_location,
)
from python_whatsapp_bot.markup import Inline_keyboard


class TestHeaders:
    def test_headers_format(self):
        token = "test_token_123"
        result = headers(token)
        assert result == {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }


class TestMarkAsRead:
    @patch('python_whatsapp_bot.message.requests.post')
    def test_mark_as_read_success(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        update = {"id": "msg_123"}
        url = "https://graph.facebook.com/v21.0/123456/messages"
        token = "test_token"

        result = mark_as_read(update, url, token)

        assert result.status_code == 200
        mock_post.assert_called_once()

        # Verify payload
        call_args = mock_post.call_args
        payload_data = json.loads(call_args[1]['data'])
        assert payload_data['message_id'] == "msg_123"
        assert payload_data['status'] == "read"


class TestMessageText:
    @patch('python_whatsapp_bot.message.requests.post')
    def test_message_text_basic(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        url = "https://graph.facebook.com/v21.0/123456/messages"
        token = "test_token"
        phone_num = "1234567890"
        text = "Hello, World!"

        result = message_text(url, token, phone_num, text)

        assert result.status_code == 200
        mock_post.assert_called_once()

        # Verify payload
        call_args = mock_post.call_args
        payload_data = json.loads(call_args[1]['data'])
        assert payload_data['to'] == phone_num
        assert payload_data['text']['body'] == text
        assert payload_data['type'] == "text"

    @patch('python_whatsapp_bot.message.requests.post')
    def test_message_text_with_reply(self, mock_post):
        mock_response = Mock()
        mock_post.return_value = mock_response

        url = "https://graph.facebook.com/v21.0/123456/messages"
        token = "test_token"
        phone_num = "1234567890"
        text = "Reply message"
        msg_id = "original_msg_123"

        result = message_text(url, token, phone_num, text, msg_id=msg_id, tag_message=True)

        # Verify context was added
        call_args = mock_post.call_args
        payload_data = json.loads(call_args[1]['data'])
        assert 'context' in payload_data
        assert payload_data['context']['message_id'] == msg_id


class TestMessageInteractive:
    @patch('python_whatsapp_bot.message.requests.post')
    def test_message_interactive_with_buttons(self, mock_post):
        mock_response = Mock()
        mock_post.return_value = mock_response

        url = "https://graph.facebook.com/v21.0/123456/messages"
        token = "test_token"
        phone_num = "1234567890"
        text = "Choose an option"
        reply_markup = Inline_keyboard(["Option 1", "Option 2"])

        result = message_interactive(url, token, phone_num, text, reply_markup)

        # Verify payload
        call_args = mock_post.call_args
        payload_data = json.loads(call_args[1]['data'])
        assert payload_data['type'] == "interactive"
        assert payload_data['interactive']['type'] == "button"
        assert payload_data['interactive']['body']['text'] == text


class TestMessageTemplate:
    @patch('python_whatsapp_bot.message.requests.post')
    def test_message_template_basic(self, mock_post):
        mock_response = Mock()
        mock_post.return_value = mock_response

        url = "https://graph.facebook.com/v21.0/123456/messages"
        token = "test_token"
        phone_num = "1234567890"
        template_name = "hello_world"

        result = message_template(url, token, phone_num, template_name)

        # Verify payload
        call_args = mock_post.call_args
        payload_data = json.loads(call_args[1]['data'])
        assert payload_data['type'] == "template"
        assert payload_data['template']['name'] == template_name
        assert payload_data['template']['language']['code'] == "en_US"

    @patch('python_whatsapp_bot.message.requests.post')
    def test_message_template_with_components(self, mock_post):
        mock_response = Mock()
        mock_post.return_value = mock_response

        url = "https://graph.facebook.com/v21.0/123456/messages"
        token = "test_token"
        phone_num = "1234567890"
        template_name = "custom_template"
        components = [{"type": "body", "parameters": [{"type": "text", "text": "John"}]}]

        result = message_template(url, token, phone_num, template_name, components=components)

        # Verify payload
        call_args = mock_post.call_args
        payload_data = json.loads(call_args[1]['data'])
        assert len(payload_data['template']['components']) == 1


class TestGetMediaUrl:
    @patch('python_whatsapp_bot.message.requests.get')
    def test_get_media_url(self, mock_get):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "url": "https://example.com/media/123",
            "mime_type": "image/jpeg"
        }
        mock_get.return_value = mock_response

        base_url = "https://graph.facebook.com/v21.0"
        media_id = "media_123"
        token = "test_token"

        result = get_media_url(base_url, media_id, token)

        assert result.status_code == 200
        mock_get.assert_called_once()


class TestMessageMedia:
    @patch('python_whatsapp_bot.message.requests.post')
    def test_message_media_basic(self, mock_post):
        mock_response = Mock()
        mock_post.return_value = mock_response

        url = "https://graph.facebook.com/v21.0/123456/messages"
        token = "test_token"
        phone_num = "1234567890"
        image_path = "https://example.com/image.jpg"

        result = message_media(url, token, phone_num, image_path)

        # Verify payload
        call_args = mock_post.call_args
        payload_data = json.loads(call_args[1]['data'])
        assert payload_data['type'] == "image"
        assert payload_data['image']['link'] == image_path


class TestMessageLocation:
    @patch('python_whatsapp_bot.message.requests.post')
    def test_message_location(self, mock_post):
        mock_response = Mock()
        mock_post.return_value = mock_response

        url = "https://graph.facebook.com/v21.0/123456/messages"
        token = "test_token"
        phone_num = "1234567890"
        latitude = "37.7749"
        longitude = "-122.4194"

        result = message_location(url, token, phone_num, latitude, longitude)

        # Verify payload
        call_args = mock_post.call_args
        payload_data = json.loads(call_args[1]['data'])
        assert payload_data['type'] == "location"
        assert payload_data['location']['latitude'] == latitude
        assert payload_data['location']['longitude'] == longitude
