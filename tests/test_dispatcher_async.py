"""Async tests for the Dispatcher class."""

import pytest
from unittest.mock import Mock, AsyncMock
from queue import Queue

from python_whatsapp_bot.dispatcher import Dispatcher
from python_whatsapp_bot.handler_classes import (
    Update,
    MessageHandler,
    InteractiveQueryHandler,
)


class TestAsyncUpdateProcessing:
    """Test async update processing logic."""

    def setup_method(self):
        self.mock_bot = Mock()
        self.mock_bot.id = "123456789"
        self.mock_bot.queue = Queue()
        self.mock_bot.threaded = False
        self.mock_bot.mark_as_read = Mock()
        self.dispatcher = Dispatcher(self.mock_bot)

    def create_text_update(self, message_text="Hello", phone_number="1234567890"):
        """Helper to create a text message update."""
        return {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": self.mock_bot.id},
                                "messages": [
                                    {
                                        "id": "msg_123",
                                        "type": "text",
                                        "text": {"body": message_text},
                                    }
                                ],
                                "contacts": [
                                    {
                                        "wa_id": phone_number,
                                        "profile": {"name": "Test User"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }

    @pytest.mark.asyncio
    async def test_aprocess_empty_update(self):
        """Test async processing of empty update."""
        await self.dispatcher.aprocess_update(None)
        # Should not raise an error

    @pytest.mark.asyncio
    async def test_aprocess_text_message(self):
        """Test async processing of a text message."""
        update = self.create_text_update("Hello Async")
        handler_called = False
        received_update = None
        
        async def async_handler(update, context):
            nonlocal handler_called, received_update
            handler_called = True
            received_update = update
        
        # Manually create and register handler
        handler = MessageHandler(action=async_handler)
        self.dispatcher._register_handler(handler)
        
        await self.dispatcher.aprocess_update(update)
        
        assert handler_called
        assert isinstance(received_update, Update)
        assert received_update.message_text == "Hello Async"

    @pytest.mark.asyncio
    async def test_aprocess_message_with_regex_match(self):
        """Test async message processing with regex filter."""
        update = self.create_text_update("/start")
        handler_called = False
        
        async def start_handler(update, context):
            nonlocal handler_called
            handler_called = True
        
        handler = MessageHandler(regex=r"^/start", action=start_handler)
        self.dispatcher._register_handler(handler)
        
        await self.dispatcher.aprocess_update(update)
        assert handler_called

    @pytest.mark.asyncio
    async def test_aprocess_message_regex_no_match(self):
        """Test async message processing when regex doesn't match."""
        update = self.create_text_update("hello")
        handler_called = False
        
        async def start_handler(update, context):
            nonlocal handler_called
            handler_called = True
        
        handler = MessageHandler(regex=r"^/start", action=start_handler)
        self.dispatcher._register_handler(handler)
        
        await self.dispatcher.aprocess_update(update)
        assert not handler_called

    @pytest.mark.asyncio
    async def test_aprocess_mark_as_read_called(self):
        """Test that mark_as_read is called in async processing."""
        update = self.create_text_update()
        
        async def test_handler(update, context):
            pass
        
        handler = MessageHandler(action=test_handler)
        self.dispatcher._register_handler(handler)
        
        await self.dispatcher.aprocess_update(update)
        self.mock_bot.mark_as_read.assert_called_once()

    @pytest.mark.asyncio
    async def test_aprocess_handler_without_context(self):
        """Test async handler that doesn't use context."""
        update = self.create_text_update("test")
        handler_called = False
        
        async def test_handler(update):
            nonlocal handler_called
            handler_called = True
        
        handler = MessageHandler(action=test_handler, context=False)
        self.dispatcher._register_handler(handler)
        
        await self.dispatcher.aprocess_update(update)
        assert handler_called

    @pytest.mark.asyncio
    async def test_aprocess_multiple_updates_in_queue(self):
        """Test processing multiple updates in async mode."""
        handler_count = 0
        
        async def test_handler(update, context):
            nonlocal handler_count
            handler_count += 1
        
        handler = MessageHandler(action=test_handler)
        self.dispatcher._register_handler(handler)
        
        update1 = self.create_text_update("first")
        update2 = self.create_text_update("second")
        
        await self.dispatcher.aprocess_update(update1)
        await self.dispatcher.aprocess_update(update2)
        
        assert handler_count == 2

    @pytest.mark.asyncio
    async def test_aprocess_update_wrong_bot_id(self):
        """Test async processing of update for different bot."""
        update = self.create_text_update()
        update["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = "987654321"
        
        handler_called = False
        
        async def test_handler(update, context):
            nonlocal handler_called
            handler_called = True
        
        handler = MessageHandler(action=test_handler)
        self.dispatcher._register_handler(handler)
        
        await self.dispatcher.aprocess_update(update)
        assert not handler_called

    @pytest.mark.asyncio
    async def test_aprocess_with_async_context_operations(self):
        """Test async handler that performs async operations with context."""
        update = self.create_text_update("async test")
        handler_called = False
        context_accessed = False
        
        async def async_handler(update, context):
            nonlocal handler_called, context_accessed
            handler_called = True
            # Simulate async operation
            await asyncio.sleep(0.001)
            # Access context
            context.user_data["test"] = "value"
            context_accessed = True
        
        handler = MessageHandler(action=async_handler)
        self.dispatcher._register_handler(handler)
        
        await self.dispatcher.aprocess_update(update)
        
        assert handler_called
        assert context_accessed


class TestAsyncNextStepHandler:
    """Test async next step handler functionality."""

    def setup_method(self):
        self.mock_bot = Mock()
        self.mock_bot.id = "123456789"
        self.mock_bot.queue = Queue()
        self.mock_bot.threaded = False
        self.mock_bot.mark_as_read = Mock()
        self.dispatcher = Dispatcher(self.mock_bot)

    def create_text_update(self, message_text="Hello", phone_number="1234567890"):
        """Helper to create a text message update."""
        return {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": self.mock_bot.id},
                                "messages": [
                                    {
                                        "id": "msg_123",
                                        "type": "text",
                                        "text": {"body": message_text},
                                    }
                                ],
                                "contacts": [
                                    {
                                        "wa_id": phone_number,
                                        "profile": {"name": "Test User"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }

    @pytest.mark.asyncio
    async def test_async_next_step_handler_overrides_regular(self):
        """Test that async next step handler takes precedence."""
        regular_called = False
        next_step_called = False
        
        # Register regular async handler
        async def regular_handler(update, context):
            nonlocal regular_called
            regular_called = True
        
        handler = MessageHandler(action=regular_handler)
        self.dispatcher._register_handler(handler)
        
        # Process first update
        update1 = self.create_text_update("first")
        await self.dispatcher.aprocess_update(update1)
        assert regular_called
        
        # Set next step handler
        update_obj = Update(self.mock_bot, update1["entry"][0]["changes"][0]["value"])
        
        async def next_step(update, context):
            nonlocal next_step_called
            next_step_called = True
        
        self.dispatcher.set_next_handler(update_obj, next_step, handler_type=MessageHandler)
        
        # Process second update - should call next step, not regular
        regular_called = False
        update2 = self.create_text_update("second")
        await self.dispatcher.aprocess_update(update2)
        
        assert next_step_called
        assert not regular_called

    @pytest.mark.asyncio
    async def test_async_next_step_handler_cleared_after_execution(self):
        """Test that async next step handler is removed after execution."""
        # Process initial update
        update1 = self.create_text_update("first")
        
        async def initial_handler(update, context):
            pass
        
        handler = MessageHandler(action=initial_handler)
        self.dispatcher._register_handler(handler)
        
        await self.dispatcher.aprocess_update(update1)
        
        update_obj = Update(self.mock_bot, update1["entry"][0]["changes"][0]["value"])
        phone_number = update_obj.user_phone_number
        
        async def next_step(update, context):
            pass
        
        self.dispatcher.set_next_handler(update_obj, next_step, handler_type=MessageHandler)
        assert phone_number in self.dispatcher.next_step_handler
        
        # Process next update
        update2 = self.create_text_update("second")
        await self.dispatcher.aprocess_update(update2)
        
        # Next step handler should be cleared
        assert phone_number not in self.dispatcher.next_step_handler

    @pytest.mark.asyncio
    async def test_async_end_conversation_keyword(self):
        """Test async conversation end with keyword."""
        end_action_called = False
        next_step_called = False
        
        async def end_action(update, context):
            nonlocal end_action_called
            end_action_called = True
        
        async def next_step(update, context):
            nonlocal next_step_called
            next_step_called = True
        
        async def initial_handler(update, context):
            pass
        
        handler = MessageHandler(action=initial_handler)
        self.dispatcher._register_handler(handler)
        
        # Set next step
        update1 = self.create_text_update("start")
        await self.dispatcher.aprocess_update(update1)
        
        update_obj = Update(self.mock_bot, update1["entry"][0]["changes"][0]["value"])
        self.dispatcher.set_next_handler(
            update_obj, 
            next_step, 
            handler_type=MessageHandler,
            end_conversation_action=end_action
        )
        
        # Send "cancel" to trigger fallback
        update2 = self.create_text_update("cancel")
        await self.dispatcher.aprocess_update(update2)
        
        assert end_action_called
        assert not next_step_called


class TestAsyncPersistentHandlers:
    """Test async persistent handler functionality."""

    def setup_method(self):
        self.mock_bot = Mock()
        self.mock_bot.id = "123456789"
        self.mock_bot.queue = Queue()
        self.mock_bot.threaded = False
        self.mock_bot.mark_as_read = Mock()
        self.dispatcher = Dispatcher(self.mock_bot)

    def create_text_update(self, message_text="Hello", phone_number="1234567890"):
        """Helper to create a text message update."""
        return {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": self.mock_bot.id},
                                "messages": [
                                    {
                                        "id": "msg_123",
                                        "type": "text",
                                        "text": {"body": message_text},
                                    }
                                ],
                                "contacts": [
                                    {
                                        "wa_id": phone_number,
                                        "profile": {"name": "Test User"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }

    @pytest.mark.asyncio
    async def test_async_persistent_handler_with_next_step(self):
        """Test that async persistent handlers run even when next step is set."""
        persistent_called = False
        next_step_called = False
        
        # Register persistent async handler
        async def help_handler(update, context):
            nonlocal persistent_called
            persistent_called = True
        
        persistent_handler = MessageHandler(
            regex=r"^/help", action=help_handler, persistent=True
        )
        self.dispatcher._register_handler(persistent_handler)
        
        # Register initial handler
        async def initial_handler(update, context):
            pass
        
        handler = MessageHandler(action=initial_handler)
        self.dispatcher._register_handler(handler)
        
        # Set next step handler
        update1 = self.create_text_update("start")
        await self.dispatcher.aprocess_update(update1)
        
        update_obj = Update(self.mock_bot, update1["entry"][0]["changes"][0]["value"])
        
        async def next_step(update, context):
            nonlocal next_step_called
            next_step_called = True
        
        self.dispatcher.set_next_handler(update_obj, next_step, handler_type=MessageHandler)
        
        # Send /help - should trigger persistent handler
        update2 = self.create_text_update("/help")
        await self.dispatcher.aprocess_update(update2)
        
        assert persistent_called
        assert not next_step_called


class TestAsyncInteractiveHandlers:
    """Test async interactive message handlers."""

    def setup_method(self):
        self.mock_bot = Mock()
        self.mock_bot.id = "123456789"
        self.mock_bot.queue = Queue()
        self.mock_bot.threaded = False
        self.mock_bot.mark_as_read = Mock()
        self.dispatcher = Dispatcher(self.mock_bot)

    def create_button_update(self, button_id="button_1"):
        """Helper to create a button reply update."""
        return {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": self.mock_bot.id},
                                "messages": [
                                    {
                                        "id": "msg_123",
                                        "type": "interactive",
                                        "interactive": {
                                            "type": "button_reply",
                                            "button_reply": {"id": button_id},
                                        },
                                    }
                                ],
                                "contacts": [
                                    {
                                        "wa_id": "1234567890",
                                        "profile": {"name": "Test User"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }

    @pytest.mark.asyncio
    async def test_async_button_reply_handler(self):
        """Test async handling of button reply."""
        handler_called = False
        received_text = None
        
        async def button_handler(update, context):
            nonlocal handler_called, received_text
            handler_called = True
            received_text = update.message_text
        
        handler = InteractiveQueryHandler(action=button_handler)
        self.dispatcher._register_handler(handler)
        
        update = self.create_button_update("confirm")
        await self.dispatcher.aprocess_update(update)
        
        assert handler_called
        assert received_text == "confirm"


class TestAsyncErrorHandling:
    """Test async error handling."""

    def setup_method(self):
        self.mock_bot = Mock()
        self.mock_bot.id = "123456789"
        self.mock_bot.queue = Queue()
        self.mock_bot.threaded = False
        self.mock_bot.mark_as_read = Mock()
        self.dispatcher = Dispatcher(self.mock_bot)

    def create_text_update(self, message_text="Hello"):
        """Helper to create a text message update."""
        return {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": self.mock_bot.id},
                                "messages": [
                                    {
                                        "id": "msg_123",
                                        "type": "text",
                                        "text": {"body": message_text},
                                    }
                                ],
                                "contacts": [
                                    {
                                        "wa_id": "1234567890",
                                        "profile": {"name": "Test User"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }

    @pytest.mark.asyncio
    async def test_async_handler_exception_handled(self):
        """Test that exceptions in async handlers are caught and logged."""
        async def failing_handler(update, context):
            raise ValueError("Test error")
        
        handler = MessageHandler(action=failing_handler)
        self.dispatcher._register_handler(handler)
        
        update = self.create_text_update()
        
        # Should not raise, error should be logged
        await self.dispatcher.aprocess_update(update)

    @pytest.mark.asyncio
    async def test_sync_handler_in_async_mode_raises_error(self):
        """Test that using sync handler in async mode raises appropriate error."""
        def sync_handler(update, context):
            pass
        
        handler = MessageHandler(action=sync_handler)
        self.dispatcher._register_handler(handler)
        
        update = self.create_text_update()
        
        # Should handle the type error gracefully
        await self.dispatcher.aprocess_update(update)


# Import asyncio for sleep function in tests
import asyncio


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
