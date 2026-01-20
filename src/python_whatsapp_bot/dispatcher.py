"""Message dispatcher for routing WhatsApp webhook updates to handlers."""

from typing import Any, Callable, Dict, List, Optional
from threading import Thread
import logging

from .error_handlers import keys_exists
from .user_context import User_context
from .handler_classes import (
    Update,
    UpdateHandler,
    MessageHandler,
    InteractiveQueryHandler,
    ImageHandler,
    LocationHandler,
    StickerHandler,
    AudioHandler,
    VideoHandler,
    UnknownHandler,
    UnsupportedHandler,
)

# Legacy aliases for backward compatibility
Message_handler = MessageHandler
Interactive_query_handler = InteractiveQueryHandler
Update_handler = UpdateHandler

logger = logging.getLogger(__name__)


class Dispatcher:
    """Dispatcher for routing incoming WhatsApp updates to registered handlers.
    
    The Dispatcher manages handler registration, message routing, and conversation
    state for multi-step interactions.
    
    Args:
        bot: The WhatsApp bot instance
        mark_as_read: Whether to automatically mark messages as read (default: True)
    """
    
    def __init__(self, bot, mark_as_read=True):
        # type: (Any, bool) -> None
        self.bot = bot
        self.queue = bot.queue
        self.registered_handlers = []  # type: List[UpdateHandler]
        self.mark_as_read = mark_as_read  # type: bool
        self.next_step_handler = {}  # type: Dict[str, Dict[str, Any]]
        self.fallback_function = None  # type: Optional[Callable]

    def process_update(self, update):
        # type: (Dict[str, Any]) -> None
        """Process incoming webhook update (synchronous).
        
        Args:
            update: The webhook update payload from WhatsApp
        """
        if not update:
            logger.warning("Received empty update")
            return
            
        self.queue.put(update)
        while not self.queue.empty():
            _update = self.queue.get()
            try:
                if not self.bot.threaded:
                    self._process_queue(_update)
                else:
                    Thread(target=self._process_queue, args=(_update,)).start()
            except Exception as e:
                logger.error(f"Error processing update: {e}", exc_info=True)

    async def aprocess_update(self, update):
        # type: (Dict[str, Any]) -> None
        """Process incoming webhook update (asynchronous).
        
        Args:
            update: The webhook update payload from WhatsApp
        """
        if not update:
            logger.warning("Received empty update")
            return
            
        self.queue.put(update)
        while not self.queue.empty():
            _update = self.queue.get()
            try:
                if not self.bot.threaded:
                    await self._aprocess_queue(_update)
                else:
                    # Note: Thread cannot run async functions directly
                    logger.warning("Threaded mode with async processing is not fully supported")
                    await self._aprocess_queue(_update)
            except Exception as e:
                logger.error(f"Error processing async update: {e}", exc_info=True)

    def _process_queue(self, update):
        # type: (Dict[str, Any]) -> None
        """Internal method to process a single update from the queue."""
        # Validate update structure
        if not self._validate_update_structure(update):
            return
            
        value = update["entry"][0]["changes"][0]["value"]
        
        # Verify the update is for this bot
        if not self._is_for_this_bot(value):
            return
            
        if not keys_exists(value, "messages"):
            logger.debug("Update has no messages, skipping")
            return
            
        _message = value["messages"][0]
        
        # Mark message as read if configured
        if self.mark_as_read:
            try:
                self.bot.mark_as_read(_message)
            except Exception as e:
                logger.error(f"Failed to mark message as read: {e}")
                
        update_obj = Update(self.bot, value)
        
        # Get handlers to process
        matched_handlers = self._get_matched_handlers(update_obj)
        
        # Process handlers
        for handler in matched_handlers:
            if not isinstance(handler, UpdateHandler):
                continue
                
            # Check if handler matches message type
            if handler.name != _message.get("type"):
                continue

            # Extract message text for filtering
            try:
                message_txt = handler.extract_data(_message).message_txt
            except Exception as e:
                logger.error(f"Failed to extract data from message: {e}")
                continue

            # Check filter and run handler
            if self._check_and_run_handler(handler, value, message_txt):
                # Clean up next step handler if this was it
                self._cleanup_next_step_handler(update_obj.user_phone_number, handler)
                return

    async def _aprocess_queue(self, update):
        # type: (Dict[str, Any]) -> None
        """Internal async method to process a single update from the queue."""
        # Validate update structure
        if not self._validate_update_structure(update):
            return
            
        value = update["entry"][0]["changes"][0]["value"]
        
        # Verify the update is for this bot
        if not self._is_for_this_bot(value):
            return
            
        if not keys_exists(value, "messages"):
            logger.debug("Update has no messages, skipping")
            return
            
        _message = value["messages"][0]
        
        # Mark message as read if configured
        if self.mark_as_read:
            try:
                self.bot.mark_as_read(_message)
            except Exception as e:
                logger.error(f"Failed to mark message as read: {e}")
                
        update_obj = Update(self.bot, value)
        
        # Get handlers to process
        matched_handlers = self._get_matched_handlers(update_obj)
        
        # Process handlers
        for handler in matched_handlers:
            if not isinstance(handler, UpdateHandler):
                continue
                
            # Check if handler matches message type
            if handler.name != _message.get("type"):
                continue

            # Extract message text for filtering
            try:
                message_txt = handler.extract_data(_message).message_txt
            except Exception as e:
                logger.error(f"Failed to extract data from message: {e}")
                continue

            # Check filter and run handler
            if await self._acheck_and_run_handler(handler, value, message_txt):
                # Clean up next step handler if this was it
                self._cleanup_next_step_handler(update_obj.user_phone_number, handler)
                return

    def _validate_update_structure(self, update):
        # type: (Dict[str, Any]) -> bool
        """Validate that the update has the expected structure."""
        if not keys_exists(update, "entry", 0, "changes", 0, "value"):
            logger.warning("Update missing required structure")
            return False
        return True
    
    def _is_for_this_bot(self, value):
        # type: (Dict[str, Any]) -> bool
        """Check if the update is for this bot instance."""
        if not keys_exists(value, "metadata", "phone_number_id"):
            logger.warning("Update missing phone_number_id")
            return False
        return str(value["metadata"]["phone_number_id"]) == str(self.bot.id)
    
    def _get_matched_handlers(self, update):
        # type: (Update) -> List[UpdateHandler]
        """Get the list of handlers to process for this update.
        
        Returns persistent handlers plus either next-step handlers or all registered handlers.
        """
        persistent_handlers = [h for h in self.registered_handlers if h.persistent]
        
        # Check for next step handler for this user
        user_phone = update.user_phone_number
        if user_phone in self.next_step_handler:
            users_next_step = self.next_step_handler[user_phone]
            matched_handlers = []
            
            # Add fallback handler if exists
            if "fallback_function" in users_next_step:
                matched_handlers.append(users_next_step["fallback_function"])
            
            # Add next step handler
            matched_handlers.append(users_next_step["next_step_handler"])
        else:
            # Use all registered handlers
            matched_handlers = list(self.registered_handlers)
        
        return persistent_handlers + matched_handlers
    
    def _cleanup_next_step_handler(self, user_phone, handler):
        # type: (str, UpdateHandler) -> None
        """Remove next step handler if this handler was the next step or fallback."""
        try:
            user_next = self.next_step_handler.get(user_phone, {})
            if (user_next.get("next_step_handler") == handler or 
                user_next.get("fallback_function") == handler):
                del self.next_step_handler[user_phone]
        except KeyError:
            pass
    
    def _check_and_run_handler(self, handler, value, message):
        # type: (UpdateHandler, Dict[str, Any], str) -> bool
        """Check handler filter and run if matched.
        
        Returns True if handler was executed, False otherwise.
        """
        _message = value.get("messages", [{}])[0]
        
        if not hasattr(handler, "filter_check"):
            return False
            
        # Check if message passes handler's filter
        if not handler.filter_check(message):
            return False
        
        try:
            update = Update(self.bot, value)
            extracted_data = handler.extract_data(_message)
            
            # Set message text and other extracted data
            update.message_text = extracted_data.message_txt
            for key, val in extracted_data.__dict__.items():
                setattr(update, key, val)
            
            # Run handler with or without context
            if handler.context:
                handler.run(update, context=User_context(update.user_phone_number))
            else:
                handler.run(update)
            
            return True
        except Exception as e:
            logger.error(f"Error running handler: {e}", exc_info=True)
            return False

    async def _acheck_and_run_handler(self, handler, value, message):
        # type: (UpdateHandler, Dict[str, Any], str) -> bool
        """Async version: Check handler filter and run if matched.
        
        Returns True if handler was executed, False otherwise.
        """
        _message = value.get("messages", [{}])[0]
        
        if not hasattr(handler, "filter_check"):
            return False
            
        # Check if message passes handler's filter
        if not handler.filter_check(message):
            return False
        
        try:
            update = Update(self.bot, value)
            extracted_data = handler.extract_data(_message)
            
            # Set message text and other extracted data
            update.message_text = extracted_data.message_txt
            for key, val in extracted_data.__dict__.items():
                setattr(update, key, val)
            
            # Run async handler with or without context
            if handler.context:
                await handler.arun(update, context=User_context(update.user_phone_number))
            else:
                await handler.arun(update)
            
            return True
        except Exception as e:
            logger.error(f"Error running async handler: {e}", exc_info=True)
            return False

    def _register_handler(self, handler_instance):
        # type: (UpdateHandler) -> int
        """Register a handler and return its index.
        
        Args:
            handler_instance: The handler to register
            
        Returns:
            Index of the registered handler
        """
        if not isinstance(handler_instance, UpdateHandler):
            raise TypeError(f"Handler must be an UpdateHandler, got {type(handler_instance)}")
        
        self.registered_handlers.append(handler_instance)
        handler_index = len(self.registered_handlers) - 1
        logger.debug(f"Registered handler: {handler_instance.__class__.__name__} at index {handler_index}")
        return handler_index

    def set_next_handler(
        self,
        update,  # type: Update
        function,  # type: Callable
        handler_type=UpdateHandler,  # type: type
        regex=None,  # type: Optional[str]
        func=None,  # type: Optional[Callable]
        end_conversation_action=lambda x: x,  # type: Callable
        end_conversation_keyword_regex=r"(?i)^(end|stop|cancel)$",  # type: str
    ):
        # type: (...) -> Optional[str]
        """Set a function to handle the next update from this user.
        
        This overrides other handlers until the next update is processed.
        Useful for multi-step conversations.
        
        Args:
            update: The current update object
            function: The function to call on the next update
            handler_type: Type of handler to create (MessageHandler, InteractiveQueryHandler, etc.)
            regex: Optional regex pattern to match
            func: Optional custom filter function
            end_conversation_action: Action to call if user ends conversation
            end_conversation_keyword_regex: Pattern to detect conversation end
            
        Returns:
            None on success, error message string on failure
        """
        if not issubclass(handler_type, UpdateHandler):
            error_msg = "handler_type must be an UpdateHandler subclass"
            logger.error(error_msg)
            return error_msg
        
        user_phone = update.user_phone_number
        self.next_step_handler[user_phone] = {}
        users_next = self.next_step_handler[user_phone]
        
        # Set fallback handler for conversation end keywords
        users_next["fallback_function"] = MessageHandler(
            regex=end_conversation_keyword_regex, 
            action=end_conversation_action
        )
        
        # Create appropriate handler type
        if handler_type == MessageHandler:
            users_next["next_step_handler"] = MessageHandler(
                regex=regex, func=func, action=function  # type: ignore[arg-type]
            )
        elif handler_type == InteractiveQueryHandler:
            users_next["next_step_handler"] = InteractiveQueryHandler(
                regex=regex, func=func, action=function  # type: ignore[arg-type]
            )
        else:
            # Generic handler for other types
            try:
                new_handler = UpdateHandler()
                new_handler.regex = regex
                new_handler.func = func
                new_handler.action = function
                users_next["next_step_handler"] = new_handler
            except Exception as e:
                logger.error(f"Error creating next step handler: {e}")
                return None
        
        logger.debug(f"Set next step handler for user {user_phone}")
        return None

    def add_message_handler(
        self,
        regex=None,  # type: Optional[str]
        func=None,  # type: Optional[Callable]
        context=True,  # type: bool
        persistent=False,  # type: bool
    ):
        # type: (...) -> Callable
        """Decorator to register a text message handler.
        
        Args:
            regex: Optional regex pattern to match message text
            func: Optional custom filter function
            context: Whether to pass user context (default: True)
            persistent: Whether handler persists after next-step handlers (default: False)
            
        Returns:
            Decorator function
            
        Example:
            @dispatcher.add_message_handler(regex=r'^/start')
            def start_handler(update, context):
                update.reply_message("Welcome!")
        """
        def inner(function):
            _handler = MessageHandler(
                regex=regex,
                func=func,
                action=function,
                context=context,
                persistent=persistent,
            )
            self._register_handler(_handler)
            return function
        return inner

    def add_interactive_handler(
        self,
        regex=None,  # type: Optional[str]
        func=None,  # type: Optional[Callable]
        handle_button=True,  # type: bool
        handle_list=True,  # type: bool
        context=True,  # type: bool
        persistent=False,  # type: bool
    ):
        # type: (...) -> Callable
        """Decorator to register an interactive (button/list) message handler.
        
        Args:
            regex: Optional regex pattern to match button/list ID
            func: Optional custom filter function
            handle_button: Whether to handle button replies (default: True)
            handle_list: Whether to handle list replies (default: True)
            context: Whether to pass user context (default: True)
            persistent: Whether handler persists after next-step handlers (default: False)
            
        Returns:
            Decorator function
        """
        def inner(function):
            _handler = InteractiveQueryHandler(
                regex=regex,
                func=func,
                action=function,
                handle_button=handle_button,
                handle_list=handle_list,
                context=context,
                persistent=persistent,
            )
            self._register_handler(_handler)
            return function
        return inner

    def add_image_handler(
        self,
        regex=None,  # type: Optional[str]
        func=None,  # type: Optional[Callable]
        context=True,  # type: bool
        persistent=False,  # type: bool
    ):
        # type: (...) -> Callable
        """Decorator to register an image message handler.
        
        Args:
            regex: Optional regex pattern to match image caption
            func: Optional custom filter function
            context: Whether to pass user context (default: True)
            persistent: Whether handler persists after next-step handlers (default: False)
            
        Returns:
            Decorator function
        """
        def inner(function):
            _handler = ImageHandler(
                regex=regex,
                func=func,
                action=function,
                context=context,
                persistent=persistent,
            )
            self._register_handler(_handler)
            return function
        return inner

    def add_audio_handler(
        self,
        regex=None,  # type: Optional[str]
        func=None,  # type: Optional[Callable]
        context=True,  # type: bool
        persistent=False,  # type: bool
    ):
        # type: (...) -> Callable
        """Decorator to register an audio message handler.
        
        Args:
            regex: Optional regex pattern (for future use)
            func: Optional custom filter function
            context: Whether to pass user context (default: True)
            persistent: Whether handler persists after next-step handlers (default: False)
            
        Returns:
            Decorator function
        """
        def inner(function):
            _handler = AudioHandler(
                regex=regex,
                func=func,
                action=function,
                context=context,
                persistent=persistent,
            )
            self._register_handler(_handler)
            return function
        return inner

    def add_video_handler(
        self,
        regex=None,  # type: Optional[str]
        func=None,  # type: Optional[Callable]
        context=True,  # type: bool
        persistent=False,  # type: bool
    ):
        # type: (...) -> Callable
        """Decorator to register a video message handler.
        
        Args:
            regex: Optional regex pattern to match video caption
            func: Optional custom filter function
            context: Whether to pass user context (default: True)
            persistent: Whether handler persists after next-step handlers (default: False)
            
        Returns:
            Decorator function
        """
        def inner(function):
            _handler = VideoHandler(
                regex=regex,
                func=func,
                action=function,
                context=context,
                persistent=persistent,
            )
            self._register_handler(_handler)
            return function
        return inner

    def add_sticker_handler(
        self,
        context=True,  # type: bool
        persistent=False,  # type: bool
    ):
        # type: (...) -> Callable
        """Decorator to register a sticker message handler.
        
        Args:
            context: Whether to pass user context (default: True)
            persistent: Whether handler persists after next-step handlers (default: False)
            
        Returns:
            Decorator function
        """
        def inner(function):
            _handler = StickerHandler(
                action=function,
                context=context,
                persistent=persistent,
            )
            self._register_handler(_handler)
            return function
        return inner

    def add_location_handler(
        self,
        context=True,  # type: bool
        persistent=False,  # type: bool
    ):
        # type: (...) -> Callable
        """Decorator to register a location message handler.
        
        Args:
            context: Whether to pass user context (default: True)
            persistent: Whether handler persists after next-step handlers (default: False)
            
        Returns:
            Decorator function
        """
        def inner(function):
            _handler = LocationHandler(
                action=function,
                context=context,
                persistent=persistent,
            )
            self._register_handler(_handler)
            return function
        return inner
