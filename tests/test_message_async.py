"""Tests for async message functions"""
import pytest
import json
from unittest.mock import AsyncMock, Mock, patch
from python_whatsapp_bot.message import (
    amark_as_read,
    amessage_text,
    amessage_interactive,
    amessage_template,
    aget_media_url,
    amessage_media,
    amessage_location,
)
from python_whatsapp_bot.markup import Inline_keyboard


@pytest.mark.asyncio
class TestAsyncMarkAsRead:
    async def test_amark_as_read_success(self):
        with patch('python_whatsapp_bot.message.httpx.AsyncClient') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200

            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_context

            update = {"id": "msg_123"}
            url = "https://graph.facebook.com/v21.0/123456/messages"
            token = "test_token"

            result = await amark_as_read(update, url, token)

            assert result.status_code == 200


@pytest.mark.asyncio
class TestAsyncMessageText:
    async def test_amessage_text_basic(self):
        with patch('python_whatsapp_bot.message.httpx.AsyncClient') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200

            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_context

            url = "https://graph.facebook.com/v21.0/123456/messages"
            token = "test_token"
            phone_num = "1234567890"
            text = "Hello, Async World!"

            result = await amessage_text(url, token, phone_num, text)

            assert result.status_code == 200

    async def test_amessage_text_with_reply(self):
        with patch('python_whatsapp_bot.message.httpx.AsyncClient') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200

            mock_context = AsyncMock()
            mock_post = AsyncMock(return_value=mock_response)
            mock_context.__aenter__.return_value.post = mock_post
            mock_client.return_value = mock_context

            url = "https://graph.facebook.com/v21.0/123456/messages"
            token = "test_token"
            phone_num = "1234567890"
            text = "Reply message"
            msg_id = "original_msg_123"

            result = await amessage_text(url, token, phone_num, text, msg_id=msg_id, tag_message=True)

            assert mock_post.called


@pytest.mark.asyncio
class TestAsyncMessageInteractive:
    async def test_amessage_interactive_with_buttons(self):
        with patch('python_whatsapp_bot.message.httpx.AsyncClient') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200

            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_context

            url = "https://graph.facebook.com/v21.0/123456/messages"
            token = "test_token"
            phone_num = "1234567890"
            text = "Choose an option"
            reply_markup = Inline_keyboard(["Option 1", "Option 2"])

            result = await amessage_interactive(url, token, phone_num, text, reply_markup)

            assert result.status_code == 200


@pytest.mark.asyncio
class TestAsyncMessageTemplate:
    async def test_amessage_template_basic(self):
        with patch('python_whatsapp_bot.message.httpx.AsyncClient') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200

            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_context

            url = "https://graph.facebook.com/v21.0/123456/messages"
            token = "test_token"
            phone_num = "1234567890"
            template_name = "hello_world"

            result = await amessage_template(url, token, phone_num, template_name)

            assert result.status_code == 200


@pytest.mark.asyncio
class TestAsyncGetMediaUrl:
    async def test_aget_media_url(self):
        with patch('python_whatsapp_bot.message.httpx.AsyncClient') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "url": "https://example.com/media/123",
                "mime_type": "image/jpeg"
            }

            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_context

            base_url = "https://graph.facebook.com/v21.0"
            media_id = "media_123"
            token = "test_token"

            result = await aget_media_url(base_url, media_id, token)

            assert result.status_code == 200


@pytest.mark.asyncio
class TestAsyncMessageMedia:
    async def test_amessage_media_basic(self):
        with patch('python_whatsapp_bot.message.httpx.AsyncClient') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200

            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_context

            url = "https://graph.facebook.com/v21.0/123456/messages"
            token = "test_token"
            phone_num = "1234567890"
            image_path = "https://example.com/image.jpg"

            result = await amessage_media(url, token, phone_num, image_path)

            assert result.status_code == 200


@pytest.mark.asyncio
class TestAsyncMessageLocation:
    async def test_amessage_location(self):
        with patch('python_whatsapp_bot.message.httpx.AsyncClient') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200

            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_context

            url = "https://graph.facebook.com/v21.0/123456/messages"
            token = "test_token"
            phone_num = "1234567890"
            latitude = "37.7749"
            longitude = "-122.4194"

            result = await amessage_location(url, token, phone_num, latitude, longitude)

            assert result.status_code == 200
