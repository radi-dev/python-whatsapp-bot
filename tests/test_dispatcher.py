"""Tests for the Dispatcher class."""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
from queue import Queue

from python_whatsapp_bot.dispatcher import Dispatcher
from python_whatsapp_bot.handler_classes import (
    Update,
    MessageHandler,
    InteractiveQueryHandler,
    ImageHandler,
    VideoHandler,
    AudioHandler,
    StickerHandler,
    LocationHandler,
)


class TestDispatcherInitialization(unittest.TestCase):
    """Test Dispatcher initialization."""

    def setUp(self):
        self.mock_bot = Mock()
        self.mock_bot.id = "123456789"
        self.mock_bot.queue = Queue()
        self.mock_bot.threaded = False

    def test_init_with_defaults(self):
        """Test dispatcher initializes with default values."""
        dispatcher = Dispatcher(self.mock_bot)
        
        self.assertEqual(dispatcher.bot, self.mock_bot)
        self.assertEqual(dispatcher.mark_as_read, True)
        self.assertEqual(dispatcher.registered_handlers, [])
        self.assertEqual(dispatcher.next_step_handler, {})
        self.assertIsNone(dispatcher.fallback_function)

    def test_init_with_mark_as_read_false(self):
        """Test dispatcher initializes with mark_as_read=False."""
        dispatcher = Dispatcher(self.mock_bot, mark_as_read=False)
        
        self.assertEqual(dispatcher.mark_as_read, False)


class TestHandlerRegistration(unittest.TestCase):
    """Test handler registration methods."""

    def setUp(self):
        self.mock_bot = Mock()
        self.mock_bot.id = "123456789"
        self.mock_bot.queue = Queue()
        self.mock_bot.threaded = False
        self.dispatcher = Dispatcher(self.mock_bot)

    def test_register_handler(self):
        """Test internal handler registration."""
        handler = MessageHandler(action=lambda u: None)
        index = self.dispatcher._register_handler(handler)
        
        self.assertEqual(index, 0)
        self.assertEqual(len(self.dispatcher.registered_handlers), 1)
        self.assertEqual(self.dispatcher.registered_handlers[0], handler)

    def test_register_multiple_handlers(self):
        """Test registering multiple handlers."""
        handler1 = MessageHandler(action=lambda u: None)
        handler2 = MessageHandler(action=lambda u: None)
        
        index1 = self.dispatcher._register_handler(handler1)
        index2 = self.dispatcher._register_handler(handler2)
        
        self.assertEqual(index1, 0)
        self.assertEqual(index2, 1)
        self.assertEqual(len(self.dispatcher.registered_handlers), 2)

    def test_add_message_handler_decorator(self):
        """Test add_message_handler decorator."""
        @self.dispatcher.add_message_handler(regex=r"^/start")
        def start_handler(update, context):
            pass
        
        self.assertEqual(len(self.dispatcher.registered_handlers), 1)
        handler = self.dispatcher.registered_handlers[0]
        self.assertIsInstance(handler, MessageHandler)
        self.assertEqual(handler.regex, r"^/start")
        self.assertEqual(handler.action, start_handler)

    def test_add_interactive_handler_decorator(self):
        """Test add_interactive_handler decorator."""
        @self.dispatcher.add_interactive_handler(regex=r"^button_")
        def button_handler(update, context):
            pass
        
        self.assertEqual(len(self.dispatcher.registered_handlers), 1)
        handler = self.dispatcher.registered_handlers[0]
        self.assertIsInstance(handler, InteractiveQueryHandler)
        self.assertEqual(handler.regex, r"^button_")

    def test_add_image_handler_decorator(self):
        """Test add_image_handler decorator."""
        @self.dispatcher.add_image_handler()
        def image_handler(update, context):
            pass
        
        self.assertEqual(len(self.dispatcher.registered_handlers), 1)
        handler = self.dispatcher.registered_handlers[0]
        self.assertIsInstance(handler, ImageHandler)

    def test_add_video_handler_decorator(self):
        """Test add_video_handler decorator."""
        @self.dispatcher.add_video_handler()
        def video_handler(update, context):
            pass
        
        handler = self.dispatcher.registered_handlers[0]
        self.assertIsInstance(handler, VideoHandler)

    def test_add_audio_handler_decorator(self):
        """Test add_audio_handler decorator."""
        @self.dispatcher.add_audio_handler()
        def audio_handler(update, context):
            pass
        
        handler = self.dispatcher.registered_handlers[0]
        self.assertIsInstance(handler, AudioHandler)

    def test_add_sticker_handler_decorator(self):
        """Test add_sticker_handler decorator."""
        @self.dispatcher.add_sticker_handler()
        def sticker_handler(update, context):
            pass
        
        handler = self.dispatcher.registered_handlers[0]
        self.assertIsInstance(handler, StickerHandler)

    def test_add_location_handler_decorator(self):
        """Test add_location_handler decorator."""
        @self.dispatcher.add_location_handler()
        def location_handler(update, context):
            pass
        
        handler = self.dispatcher.registered_handlers[0]
        self.assertIsInstance(handler, LocationHandler)

    def test_handler_with_persistent_flag(self):
        """Test handler with persistent=True."""
        @self.dispatcher.add_message_handler(persistent=True)
        def persistent_handler(update, context):
            pass
        
        handler = self.dispatcher.registered_handlers[0]
        self.assertTrue(handler.persistent)

    def test_handler_without_context(self):
        """Test handler with context=False."""
        @self.dispatcher.add_message_handler(context=False)
        def no_context_handler(update):
            pass
        
        handler = self.dispatcher.registered_handlers[0]
        self.assertFalse(handler.context)


class TestUpdateProcessing(unittest.TestCase):
    """Test update processing logic."""

    def setUp(self):
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

    def test_process_empty_update(self):
        """Test processing empty update."""
        with patch('python_whatsapp_bot.dispatcher.logger') as mock_logger:
            self.dispatcher.process_update(None)
            mock_logger.warning.assert_called_with("Received empty update")

    def test_process_invalid_structure(self):
        """Test processing update with invalid structure."""
        invalid_update = {"invalid": "structure"}
        self.dispatcher.process_update(invalid_update)
        # Should not raise an error, just log and return

    def test_process_update_wrong_bot_id(self):
        """Test processing update for different bot."""
        update = self.create_text_update()
        update["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = "987654321"
        
        handler_called = False
        
        @self.dispatcher.add_message_handler()
        def test_handler(update, context):
            nonlocal handler_called
            handler_called = True
        
        self.dispatcher.process_update(update)
        self.assertFalse(handler_called)

    def test_process_text_message(self):
        """Test processing a text message."""
        update = self.create_text_update("Hello World")
        handler_called = False
        received_update = None
        
        @self.dispatcher.add_message_handler()
        def test_handler(update, context):
            nonlocal handler_called, received_update
            handler_called = True
            received_update = update
        
        self.dispatcher.process_update(update)
        
        self.assertTrue(handler_called)
        self.assertIsInstance(received_update, Update)
        self.assertEqual(received_update.message_text, "Hello World")

    def test_process_message_with_regex_match(self):
        """Test message processing with regex filter."""
        update = self.create_text_update("/start")
        handler_called = False
        
        @self.dispatcher.add_message_handler(regex=r"^/start")
        def start_handler(update, context):
            nonlocal handler_called
            handler_called = True
        
        self.dispatcher.process_update(update)
        self.assertTrue(handler_called)

    def test_process_message_regex_no_match(self):
        """Test message processing when regex doesn't match."""
        update = self.create_text_update("hello")
        handler_called = False
        
        @self.dispatcher.add_message_handler(regex=r"^/start")
        def start_handler(update, context):
            nonlocal handler_called
            handler_called = True
        
        self.dispatcher.process_update(update)
        self.assertFalse(handler_called)

    def test_mark_as_read_called(self):
        """Test that mark_as_read is called when enabled."""
        update = self.create_text_update()
        
        @self.dispatcher.add_message_handler()
        def test_handler(update, context):
            pass
        
        self.dispatcher.process_update(update)
        self.mock_bot.mark_as_read.assert_called_once()

    def test_mark_as_read_not_called_when_disabled(self):
        """Test that mark_as_read is not called when disabled."""
        dispatcher = Dispatcher(self.mock_bot, mark_as_read=False)
        update = self.create_text_update()
        
        @dispatcher.add_message_handler()
        def test_handler(update, context):
            pass
        
        dispatcher.process_update(update)
        self.mock_bot.mark_as_read.assert_not_called()

    def test_multiple_handlers_first_match_wins(self):
        """Test that only the first matching handler is executed."""
        update = self.create_text_update("/start")
        handler1_called = False
        handler2_called = False
        
        @self.dispatcher.add_message_handler(regex=r"^/")
        def handler1(update, context):
            nonlocal handler1_called
            handler1_called = True
        
        @self.dispatcher.add_message_handler(regex=r"^/start")
        def handler2(update, context):
            nonlocal handler2_called
            handler2_called = True
        
        self.dispatcher.process_update(update)
        self.assertTrue(handler1_called)
        self.assertFalse(handler2_called)  # Should not be called

    def test_handler_without_context_parameter(self):
        """Test handler that doesn't use context."""
        update = self.create_text_update("test")
        handler_called = False
        
        @self.dispatcher.add_message_handler(context=False)
        def test_handler(update):
            nonlocal handler_called
            handler_called = True
        
        self.dispatcher.process_update(update)
        self.assertTrue(handler_called)


class TestNextStepHandler(unittest.TestCase):
    """Test next step handler functionality."""

    def setUp(self):
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

    def test_set_next_handler(self):
        """Test setting a next step handler."""
        update_obj = Update(self.mock_bot, self.create_text_update()["entry"][0]["changes"][0]["value"])
        
        def next_step(update, context):
            pass
        
        result = self.dispatcher.set_next_handler(
            update_obj, next_step, handler_type=MessageHandler
        )
        
        self.assertIsNone(result)
        self.assertIn(update_obj.user_phone_number, self.dispatcher.next_step_handler)

    def test_next_step_handler_overrides_regular(self):
        """Test that next step handler takes precedence."""
        regular_called = False
        next_step_called = False
        
        # Register regular handler
        @self.dispatcher.add_message_handler()
        def regular_handler(update, context):
            nonlocal regular_called
            regular_called = True
        
        # Process first update and set next step
        update1 = self.create_text_update("first")
        self.dispatcher.process_update(update1)
        self.assertTrue(regular_called)
        
        # Set next step handler
        update_obj = Update(self.mock_bot, update1["entry"][0]["changes"][0]["value"])
        
        def next_step(update, context):
            nonlocal next_step_called
            next_step_called = True
        
        self.dispatcher.set_next_handler(update_obj, next_step, handler_type=MessageHandler)
        
        # Process second update - should call next step, not regular
        regular_called = False
        update2 = self.create_text_update("second")
        self.dispatcher.process_update(update2)
        
        self.assertTrue(next_step_called)
        self.assertFalse(regular_called)

    def test_next_step_handler_cleared_after_execution(self):
        """Test that next step handler is removed after execution."""
        # Set next step handler
        update1 = self.create_text_update("first")
        self.dispatcher.process_update(update1)
        
        update_obj = Update(self.mock_bot, update1["entry"][0]["changes"][0]["value"])
        phone_number = update_obj.user_phone_number
        
        def next_step(update, context):
            pass
        
        self.dispatcher.set_next_handler(update_obj, next_step, handler_type=MessageHandler)
        self.assertIn(phone_number, self.dispatcher.next_step_handler)
        
        # Process next update
        update2 = self.create_text_update("second")
        self.dispatcher.process_update(update2)
        
        # Next step handler should be cleared
        self.assertNotIn(phone_number, self.dispatcher.next_step_handler)

    def test_end_conversation_keyword(self):
        """Test conversation end with keyword."""
        end_action_called = False
        next_step_called = False
        
        def end_action(update, context):
            nonlocal end_action_called
            end_action_called = True
        
        def next_step(update, context):
            nonlocal next_step_called
            next_step_called = True
        
        # Set next step
        update1 = self.create_text_update("start")
        self.dispatcher.process_update(update1)
        
        update_obj = Update(self.mock_bot, update1["entry"][0]["changes"][0]["value"])
        self.dispatcher.set_next_handler(
            update_obj, 
            next_step, 
            handler_type=MessageHandler,
            end_conversation_action=end_action
        )
        
        # Send "end" to trigger fallback
        update2 = self.create_text_update("end")
        self.dispatcher.process_update(update2)
        
        self.assertTrue(end_action_called)
        self.assertFalse(next_step_called)


class TestPersistentHandlers(unittest.TestCase):
    """Test persistent handler functionality."""

    def setUp(self):
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

    def test_persistent_handler_with_next_step(self):
        """Test that persistent handlers run even when next step is set."""
        persistent_called = False
        next_step_called = False
        
        # Register persistent handler
        @self.dispatcher.add_message_handler(regex=r"^/help", persistent=True)
        def help_handler(update, context):
            nonlocal persistent_called
            persistent_called = True
        
        # Set next step handler
        update1 = self.create_text_update("start")
        self.dispatcher.process_update(update1)
        
        update_obj = Update(self.mock_bot, update1["entry"][0]["changes"][0]["value"])
        
        def next_step(update, context):
            nonlocal next_step_called
            next_step_called = True
        
        self.dispatcher.set_next_handler(update_obj, next_step, handler_type=MessageHandler)
        
        # Send /help - should trigger persistent handler
        persistent_called = False
        update2 = self.create_text_update("/help")
        self.dispatcher.process_update(update2)
        
        self.assertTrue(persistent_called)
        self.assertFalse(next_step_called)


class TestInteractiveHandlers(unittest.TestCase):
    """Test interactive message handlers."""

    def setUp(self):
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

    def create_list_update(self, list_id="list_1"):
        """Helper to create a list reply update."""
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
                                            "type": "list_reply",
                                            "list_reply": {"id": list_id},
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

    def test_button_reply_handler(self):
        """Test handling button reply."""
        handler_called = False
        received_text = None
        
        @self.dispatcher.add_interactive_handler()
        def button_handler(update, context):
            nonlocal handler_called, received_text
            handler_called = True
            received_text = update.message_text
        
        update = self.create_button_update("confirm")
        self.dispatcher.process_update(update)
        
        self.assertTrue(handler_called)
        self.assertEqual(received_text, "confirm")

    def test_list_reply_handler(self):
        """Test handling list reply."""
        handler_called = False
        received_text = None
        
        @self.dispatcher.add_interactive_handler()
        def list_handler(update, context):
            nonlocal handler_called, received_text
            handler_called = True
            received_text = update.message_text
        
        update = self.create_list_update("option_1")
        self.dispatcher.process_update(update)
        
        self.assertTrue(handler_called)
        self.assertEqual(received_text, "option_1")


class TestMediaHandlers(unittest.TestCase):
    """Test media message handlers."""

    def setUp(self):
        self.mock_bot = Mock()
        self.mock_bot.id = "123456789"
        self.mock_bot.queue = Queue()
        self.mock_bot.threaded = False
        self.mock_bot.mark_as_read = Mock()
        self.dispatcher = Dispatcher(self.mock_bot)

    def create_image_update(self, caption="Test image"):
        """Helper to create an image message update."""
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
                                        "type": "image",
                                        "image": {
                                            "caption": caption,
                                            "mime_type": "image/jpeg",
                                            "id": "image_123",
                                            "sha256": "hash123",
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

    def test_image_handler(self):
        """Test handling image message."""
        handler_called = False
        
        @self.dispatcher.add_image_handler()
        def image_handler(update, context):
            nonlocal handler_called
            handler_called = True
            self.assertEqual(update.media_mime_type, "image/jpeg")
            self.assertEqual(update.media_file_id, "image_123")
        
        update = self.create_image_update()
        self.dispatcher.process_update(update)
        
        self.assertTrue(handler_called)


if __name__ == "__main__":
    unittest.main()
