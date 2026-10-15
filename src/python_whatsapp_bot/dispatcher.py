"""Message dispatcher for routing WhatsApp webhook updates to handlers."""

from typing import Any, Callable, Dict, List, Optional, Tuple
from threading import Thread
import logging

from .error_handlers import keys_exists
from .context_storage import (
    ContextLock,
    ContextStorage,
    ContextStorageError,
    ContextStorageNotConfiguredError,
    ContextLockTimeoutError,
    DEFAULT_LOCK_TIMEOUT,
    DEFAULT_LOCK_WAIT,
)
from .user_context import User_context, get_context_storage, resolve_context_storage
from .next_step import (
    NextStepResolutionError,
    StepRegistry,
    build_next_step,
    build_next_step_handlers,
    end_conversation,
)
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

    Conversation state (the ``context`` passed to handlers and the "next step"
    set with :meth:`set_next_handler`) lives in an external
    :class:`~python_whatsapp_bot.ContextStorage`, never in process memory, so
    any number of worker processes can share it. For every message update the
    user's record is loaded once (under a per-user lock), the matching handler
    runs, and the record is written back if it changed.
    
    Args:
        bot: The WhatsApp bot instance
        mark_as_read: Whether to automatically mark messages as read (default: True)
        context_storage: Storage backend for the per-user ``context`` passed to
            handlers and for next-step state. Falls back to the global default set
            with :func:`~python_whatsapp_bot.set_context_storage`. Required if at
            least one handler takes a ``context`` argument or ``set_next_handler``
            is used; otherwise processing raises
            :class:`~python_whatsapp_bot.ContextStorageNotConfiguredError`.
        context_lock: Hold a per-user lock (provided by the storage) while an
            update is processed, so that updates of the same user are never
            processed concurrently by different threads/workers (default: True).
        lock_timeout: Seconds after which a held lock expires on its own. Must
            exceed the run time of your slowest handler (default: 60).
        lock_wait: Max seconds to wait for a busy lock. On expiry
            :class:`~python_whatsapp_bot.ContextLockTimeoutError` is raised
            *before* anything was processed, so a non-2xx webhook response lets
            WhatsApp re-deliver the message (default: 10).
    """
    
    def __init__(
        self,
        bot,  # type: Any
        mark_as_read=True,  # type: bool
        context_storage=None,  # type: Optional[ContextStorage]
        context_lock=True,  # type: bool
        lock_timeout=DEFAULT_LOCK_TIMEOUT,  # type: float
        lock_wait=DEFAULT_LOCK_WAIT,  # type: float
    ):
        # type: (...) -> None
        self.bot = bot
        self.registered_handlers = []  # type: List[UpdateHandler]
        self.mark_as_read = mark_as_read  # type: bool
        self.fallback_function = None  # type: Optional[Callable]
        self.steps = StepRegistry()  # type: StepRegistry
        self._context_storage = None  # type: Optional[ContextStorage]
        self._context_required = False  # type: bool
        self._context_storage_verified = None  # type: Optional[ContextStorage]
        self.context_storage = context_storage
        self.context_lock = bool(context_lock)  # type: bool
        self.lock_timeout = float(lock_timeout)  # type: float
        self.lock_wait = float(lock_wait)  # type: float

    # ------------------------------------------------------------------ #
    # Context storage
    # ------------------------------------------------------------------ #

    @property
    def context_storage(self):
        # type: () -> Optional[ContextStorage]
        """Storage explicitly configured for this dispatcher (may be None)."""
        return self._context_storage

    @context_storage.setter
    def context_storage(self, storage):
        # type: (Optional[ContextStorage]) -> None
        if storage is not None and not isinstance(storage, ContextStorage):
            raise TypeError(
                "context_storage must be a ContextStorage instance "
                "(MemoryStorage, SQLiteStorage, RedisStorage, SQLAlchemyStorage or a "
                "custom subclass), got {!r}".format(type(storage).__name__)
            )
        self._context_storage = storage
        self._context_storage_verified = None

    @property
    def context_required(self):
        # type: () -> bool
        """True once any registered handler declares a ``context`` parameter."""
        return self._context_required

    def get_context_storage(self):
        # type: () -> ContextStorage
        """Return the effective storage (own or global). Hard-fails if none."""
        return resolve_context_storage(self._context_storage)

    def _storage_or_none(self):
        # type: () -> Optional[ContextStorage]
        """Effective storage (own or global) without failing."""
        return self._context_storage if self._context_storage is not None else get_context_storage()

    def _storage_for_processing(self):
        # type: () -> Optional[ContextStorage]
        """Storage to use for an update: required if handlers use the context.

        Returns None only when no storage is configured *and* nothing needs one.
        Verifies a newly seen storage once (ping) so misconfiguration fails early.
        """
        storage = self._storage_or_none()
        if storage is None:
            if self._context_required:
                raise ContextStorageNotConfiguredError()
            return None
        if self._context_storage_verified is not storage:
            storage.ping()
            self._context_storage_verified = storage
            logger.info("User context storage verified: %r", storage)
        return storage

    async def _astorage_for_processing(self):
        # type: () -> Optional[ContextStorage]
        storage = self._storage_or_none()
        if storage is None:
            if self._context_required:
                raise ContextStorageNotConfiguredError()
            return None
        if self._context_storage_verified is not storage:
            await storage.aping()
            self._context_storage_verified = storage
            logger.info("User context storage verified: %r", storage)
        return storage

    def _note_handler(self, handler):
        # type: (UpdateHandler) -> None
        if handler.wants_context():
            self._context_required = True

    def user_context(self, phone_num):
        # type: (str) -> User_context
        """Return a :class:`User_context` for ``phone_num`` using this bot's storage.

        Handy for reading/writing a user's data outside of a handler::

            with bot.dispatcher.user_context("2348145xxxxx") as ctx:
                ctx.user_data["vip"] = True
        """
        return User_context(phone_num, storage=self.get_context_storage())

    # ------------------------------------------------------------------ #
    # Per-user locking
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_user_phone(update):
        # type: (Dict[str, Any]) -> Optional[str]
        """The sender's wa_id of a message update, or None for other payloads."""
        if not keys_exists(update, "entry", 0, "changes", 0, "value", "contacts", 0, "wa_id"):
            return None
        value = update["entry"][0]["changes"][0]["value"]
        if not keys_exists(value, "messages", 0):
            return None
        return str(value["contacts"][0]["wa_id"])

    def _needs_user_lock(self, update, storage):
        # type: (Dict[str, Any], Optional[ContextStorage]) -> Optional[str]
        """Return the user id to lock for this update, or None if no lock is needed."""
        if storage is None or not self.context_lock:
            return None
        phone = self._extract_user_phone(update)
        if phone is None:
            return None
        value = update["entry"][0]["changes"][0]["value"]
        if not self._is_for_this_bot(value):
            return None
        return phone

    def _acquire_user_lock(self, update, storage):
        # type: (Dict[str, Any], Optional[ContextStorage]) -> Optional[ContextLock]
        """Take the per-user lock for this update (sync). Raises on timeout."""
        phone = self._needs_user_lock(update, storage)
        if phone is None:
            return None
        lock = storage.lock(phone, timeout=self.lock_timeout, blocking_timeout=self.lock_wait)  # type: ignore[union-attr]
        if not lock.acquire():
            raise ContextLockTimeoutError(phone, self.lock_wait)
        logger.debug("Acquired context lock for user %s", phone)
        return lock

    async def _aacquire_user_lock(self, update, storage):
        # type: (Dict[str, Any], Optional[ContextStorage]) -> Optional[ContextLock]
        phone = self._needs_user_lock(update, storage)
        if phone is None:
            return None
        lock = storage.lock(phone, timeout=self.lock_timeout, blocking_timeout=self.lock_wait)  # type: ignore[union-attr]
        if not await lock.aacquire():
            raise ContextLockTimeoutError(phone, self.lock_wait)
        logger.debug("Acquired context lock for user %s", phone)
        return lock

    def _warn_if_expired(self, lock):
        # type: (ContextLock) -> None
        if lock.expired:
            logger.warning(
                "Processing for user %s took %.1fs, longer than lock_timeout=%.0fs: the context "
                "lock expired and another worker may have run concurrently. Raise "
                "context_lock_timeout or speed up the handler.",
                lock.key, lock.held_for, lock.timeout,
            )

    def _release_user_lock(self, lock):
        # type: (Optional[ContextLock]) -> None
        if lock is None:
            return
        self._warn_if_expired(lock)
        try:
            lock.release()
        except Exception as e:
            logger.error(f"Failed to release context lock for user {lock.key}: {e}", exc_info=True)

    async def _arelease_user_lock(self, lock):
        # type: (Optional[ContextLock]) -> None
        if lock is None:
            return
        self._warn_if_expired(lock)
        try:
            await lock.arelease()
        except Exception as e:
            logger.error(f"Failed to release context lock for user {lock.key}: {e}", exc_info=True)

    def _process_update_locked(self, update, storage, lock):
        # type: (Dict[str, Any], Optional[ContextStorage], Optional[ContextLock]) -> None
        try:
            self._process_single_update(update, storage)
        finally:
            self._release_user_lock(lock)

    # ------------------------------------------------------------------ #
    # Entry points
    # ------------------------------------------------------------------ #

    def process_update(self, update):
        # type: (Dict[str, Any]) -> None
        """Process one incoming webhook update (synchronous).

        Each call handles exactly the update it was given, so that an error
        (e.g. :class:`ContextLockTimeoutError`) is always reported to the webhook
        request that delivered the message, and that request alone. Ordering of
        a user's messages is guaranteed by the per-user context lock, not by
        this method; updates of different users may be processed concurrently.

        Args:
            update: The webhook update payload from WhatsApp
        """
        if not update:
            logger.warning("Received empty update")
            return

        # Hard fail early: handlers use the context, so storage must exist.
        storage = self._storage_for_processing()

        # The per-user lock is taken here, in the caller's (webhook) thread and
        # before any processing: a ContextLockTimeoutError therefore surfaces to
        # the webhook while nothing has happened yet, and updates of one user are
        # processed in arrival order even in threaded mode.
        lock = self._acquire_user_lock(update, storage)
        try:
            if not self.bot.threaded:
                self._process_update_locked(update, storage, lock)
            else:
                try:
                    Thread(target=self._process_update_locked, args=(update, storage, lock)).start()
                except BaseException:
                    self._release_user_lock(lock)
                    raise
        except ContextStorageError:
            raise
        except Exception as e:
            logger.error(f"Error processing update: {e}", exc_info=True)

    async def aprocess_update(self, update):
        # type: (Dict[str, Any]) -> None
        """Process one incoming webhook update (asynchronous).

        See :meth:`process_update`; the same guarantees apply.

        Args:
            update: The webhook update payload from WhatsApp
        """
        if not update:
            logger.warning("Received empty update")
            return

        # Hard fail early: handlers use the context, so storage must exist.
        storage = await self._astorage_for_processing()

        lock = await self._aacquire_user_lock(update, storage)
        try:
            if self.bot.threaded:
                # Note: Thread cannot run async functions directly
                logger.warning("Threaded mode with async processing is not fully supported")
            await self._aprocess_single_update(update, storage)
        except ContextStorageError:
            raise
        except Exception as e:
            logger.error(f"Error processing async update: {e}", exc_info=True)
        finally:
            await self._arelease_user_lock(lock)

    # ------------------------------------------------------------------ #
    # Processing one update
    # ------------------------------------------------------------------ #

    def _prepare_update(self, update):
        # type: (Dict[str, Any]) -> Optional[Dict[str, Any]]
        """Validate the payload and return its ``value`` if it is a message for this bot."""
        if not self._validate_update_structure(update):
            return None
        value = update["entry"][0]["changes"][0]["value"]
        if not self._is_for_this_bot(value):
            return None
        if not keys_exists(value, "messages"):
            logger.debug("Update has no messages, skipping")
            return None
        return value

    def _mark_as_read(self, message):
        # type: (Dict[str, Any]) -> None
        if self.mark_as_read:
            try:
                self.bot.mark_as_read(message)
            except Exception as e:
                logger.error(f"Failed to mark message as read: {e}")

    def _process_single_update(self, update, storage):
        # type: (Dict[str, Any], Optional[ContextStorage]) -> None
        """Internal method to process a single update."""
        value = self._prepare_update(update)
        if value is None:
            return
        _message = value["messages"][0]
        update_obj = Update(self.bot, value)

        # Load the user's record (user_data + next step) once, before anything
        # else: a storage failure here propagates, so the webhook can fail and
        # WhatsApp re-delivers the message.
        user_context = None  # type: Optional[User_context]
        if storage is not None:
            user_context = User_context(update_obj.user_phone_number, storage=storage)
            user_context.load()
            update_obj._user_context = user_context

        self._mark_as_read(_message)

        try:
            matched_handlers = self._get_matched_handlers(update_obj, user_context)
            for handler in matched_handlers:
                if not isinstance(handler, UpdateHandler):
                    continue
                if handler.name != _message.get("type"):
                    continue
                try:
                    message_txt = handler.extract_data(_message).message_txt
                except Exception as e:
                    logger.error(f"Failed to extract data from message: {e}")
                    continue
                if self._check_and_run_handler(handler, update_obj, _message, message_txt, user_context):
                    self._finish_next_step(handler, user_context)
                    return
        finally:
            # Persist user_data / next-step changes even if the handler raised,
            # mirroring the old in-memory behaviour where every write was
            # immediately visible.
            if user_context is not None:
                self._save_context(user_context)

    async def _aprocess_single_update(self, update, storage):
        # type: (Dict[str, Any], Optional[ContextStorage]) -> None
        """Internal async method to process a single update."""
        value = self._prepare_update(update)
        if value is None:
            return
        _message = value["messages"][0]
        update_obj = Update(self.bot, value)

        user_context = None  # type: Optional[User_context]
        if storage is not None:
            user_context = User_context(update_obj.user_phone_number, storage=storage)
            await user_context.aload()
            update_obj._user_context = user_context

        self._mark_as_read(_message)

        try:
            matched_handlers = self._get_matched_handlers(update_obj, user_context)
            for handler in matched_handlers:
                if not isinstance(handler, UpdateHandler):
                    continue
                if handler.name != _message.get("type"):
                    continue
                try:
                    message_txt = handler.extract_data(_message).message_txt
                except Exception as e:
                    logger.error(f"Failed to extract data from message: {e}")
                    continue
                if await self._acheck_and_run_handler(handler, update_obj, _message, message_txt, user_context):
                    self._finish_next_step(handler, user_context)
                    return
        finally:
            if user_context is not None:
                await self._asave_context(user_context)

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
    
    def _get_matched_handlers(self, update, user_context):
        # type: (Update, Optional[User_context]) -> List[UpdateHandler]
        """Get the list of handlers to process for this update.
        
        Returns persistent handlers plus either the user's next-step handlers
        (from the stored record) or all registered handlers.
        """
        persistent_handlers = [h for h in self.registered_handlers if h.persistent]

        spec = user_context.next_step if user_context is not None else None
        if spec is not None:
            try:
                fallback, next_handler = build_next_step_handlers(spec, self.steps)
            except NextStepResolutionError as e:
                logger.error(
                    "Dropping stored next step for user %s, it cannot be resolved in this "
                    "process (%s). Falling back to the regular handlers.",
                    update.user_phone_number, e,
                )
                user_context.next_step = None  # type: ignore[union-attr]
                spec = None
            else:
                matched_handlers = []  # type: List[UpdateHandler]
                if fallback is not None:
                    fallback._next_step_spec = spec  # type: ignore[attr-defined]
                    matched_handlers.append(fallback)
                next_handler._next_step_spec = spec  # type: ignore[attr-defined]
                matched_handlers.append(next_handler)
                return persistent_handlers + matched_handlers

        return persistent_handlers + list(self.registered_handlers)

    @staticmethod
    def _finish_next_step(handler, user_context):
        # type: (UpdateHandler, Optional[User_context]) -> None
        """Clear the stored next step once its handler (or the end fallback) ran,
        unless the handler set a new next step meanwhile."""
        spec = getattr(handler, "_next_step_spec", None)
        if spec is None or user_context is None:
            return
        if user_context.next_step is spec:
            user_context.next_step = None

    def _check_and_run_handler(self, handler, update, _message, message, user_context):
        # type: (UpdateHandler, Update, Dict[str, Any], str, Optional[User_context]) -> bool
        """Check handler filter and run if matched.
        
        Returns True if handler was executed, False otherwise.
        """
        if not hasattr(handler, "filter_check"):
            return False
            
        # Check if message passes handler's filter
        if not handler.filter_check(message):
            return False

        if handler.wants_context() and user_context is None:
            # Cannot happen when storage checks ran, but never fall back to memory.
            raise ContextStorageNotConfiguredError()

        try:
            extracted_data = handler.extract_data(_message)
            
            # Set message text and other extracted data
            update.message_text = extracted_data.message_txt
            for key, val in extracted_data.__dict__.items():
                setattr(update, key, val)
            
            # Run handler with or without context
            if handler.wants_context():
                handler.run(update, context=user_context)
            else:
                handler.run(update)
            
            return True
        except ContextStorageError:
            raise  # configuration problems must surface, not be logged away
        except Exception as e:
            logger.error(f"Error running handler: {e}", exc_info=True)
            return False

    async def _acheck_and_run_handler(self, handler, update, _message, message, user_context):
        # type: (UpdateHandler, Update, Dict[str, Any], str, Optional[User_context]) -> bool
        """Async version: Check handler filter and run if matched.
        
        Returns True if handler was executed, False otherwise.
        """
        if not hasattr(handler, "filter_check"):
            return False
            
        # Check if message passes handler's filter
        if not handler.filter_check(message):
            return False

        if handler.wants_context() and user_context is None:
            raise ContextStorageNotConfiguredError()

        try:
            extracted_data = handler.extract_data(_message)
            
            # Set message text and other extracted data
            update.message_text = extracted_data.message_txt
            for key, val in extracted_data.__dict__.items():
                setattr(update, key, val)
            
            # Run async handler with or without context
            if handler.wants_context():
                await handler.arun(update, context=user_context)
            else:
                await handler.arun(update)
            
            return True
        except ContextStorageError:
            raise
        except Exception as e:
            logger.error(f"Error running async handler: {e}", exc_info=True)
            return False

    @staticmethod
    def _save_context(user_context):
        # type: (User_context) -> None
        """Write the record if it changed; otherwise refresh its TTL (activity)."""
        try:
            if user_context.save():
                logger.debug("Saved context for user %s", user_context.phone_num)
            else:
                user_context.touch()
        except Exception as e:
            logger.error(
                f"Failed to save context for user {user_context.phone_num}: {e}", exc_info=True
            )

    @staticmethod
    async def _asave_context(user_context):
        # type: (User_context) -> None
        try:
            if await user_context.asave():
                logger.debug("Saved context for user %s", user_context.phone_num)
            else:
                await user_context.atouch()
        except Exception as e:
            logger.error(
                f"Failed to save context for user {user_context.phone_num}: {e}", exc_info=True
            )

    # ------------------------------------------------------------------ #
    # Handler registration
    # ------------------------------------------------------------------ #

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
        self._note_handler(handler_instance)
        handler_index = len(self.registered_handlers) - 1
        logger.debug(f"Registered handler: {handler_instance.__class__.__name__} at index {handler_index}")
        return handler_index

    # ------------------------------------------------------------------ #
    # Next step (multi-step conversations)
    # ------------------------------------------------------------------ #

    def register_step(self, name=None):
        # type: (Any) -> Callable
        """Register a function under a stable name so it can be a next step.

        Next-step functions are stored by *reference* in the user's context
        record, so every worker process can resolve them. Module-level functions
        are referenced by import path automatically and need no registration.
        Use this for functions that are not importable by name - closures (e.g.
        inside an app factory), methods or partials::

            @wa_bot.register_step("get_email")
            def get_email(update, context): ...

            @wa_bot.register_step            # name defaults to the function name
            def get_name(update, context): ...

            wa_bot.register_step("finish")(some_obj.method)

        Registration must happen in every worker (i.e. at import/app-creation
        time), and the name must stay stable across deploys while conversations
        are in flight.
        """
        if callable(name):
            func = name
            self.steps.register(getattr(func, "__name__", None) or repr(func), func)
            return func

        def decorator(func):
            # type: (Callable) -> Callable
            self.steps.register(name, func)
            return func

        return decorator

    def _context_for_next_step(self, update_or_phone):
        # type: (Any) -> Tuple[User_context, bool]
        """(context, in_flight): the in-flight context of an update being processed,
        or a freshly loaded one that must be saved by the caller."""
        ctx = getattr(update_or_phone, "_user_context", None)
        if isinstance(ctx, User_context):
            return ctx, True
        storage = self._storage_or_none()
        if storage is None:
            raise ContextStorageNotConfiguredError(
                "set_next_step / clear_next_step need a context storage: the next-step state is "
                "persisted in the user's context record so every worker process sees it. "
                + ContextStorageNotConfiguredError.DEFAULT_MESSAGE
            )
        phone = getattr(update_or_phone, "user_phone_number", update_or_phone)
        ctx = User_context(phone, storage=storage)
        ctx.load()
        return ctx, False

    def set_next_handler(
        self,
        update,  # type: Update
        function,  # type: Callable
        handler_type=UpdateHandler,  # type: type
        regex=None,  # type: Optional[str]
        func=None,  # type: Optional[Callable]
        end_conversation_action=end_conversation,  # type: Callable
        end_conversation_keyword_regex=r"(?i)^(end|stop|cancel)$",  # type: str
    ):
        # type: (...) -> None
        """Set the function that handles this user's next update.

        Overrides the regular handlers for the user's next message. The state is
        persisted in the user's context record (next to ``user_data``), so it is
        shared by all worker processes and survives restarts.

        ``function``, ``func`` and ``end_conversation_action`` are stored by
        reference: they must be module-level functions (importable by name) or
        registered with :meth:`register_step`. Anything else raises
        :class:`~python_whatsapp_bot.NextStepNotSerializableError` immediately.

        Args:
            update: The current update object (the one passed to your handler)
            function: The function to call on the next update
            handler_type: Type of handler to create (MessageHandler, InteractiveQueryHandler, ...)
            regex: Optional regex pattern the next message must match
            func: Optional custom filter function
            end_conversation_action: Called instead if the user sends an end keyword
            end_conversation_keyword_regex: Pattern that ends the conversation
        """
        spec = build_next_step(
            function,
            self.steps,
            handler_type=handler_type,
            regex=regex,
            func=func,
            end_conversation_action=end_conversation_action,
            end_conversation_keyword_regex=end_conversation_keyword_regex,
        )
        self._note_handler(MessageHandler(action=function))
        ctx, in_flight = self._context_for_next_step(update)
        ctx.next_step = spec
        if not in_flight:
            ctx.save()
        logger.debug("Set next step %s for user %s", spec["handler"], ctx.phone_num)
        return None

    def clear_next_step(self, update_or_phone):
        # type: (Any) -> bool
        """Cancel the pending next step of a user. Returns True if there was one.

        Accepts the update being processed or a phone number.
        """
        ctx, in_flight = self._context_for_next_step(update_or_phone)
        had = ctx.next_step is not None
        ctx.next_step = None
        if not in_flight:
            ctx.save()
        return had

    def get_next_step(self, update_or_phone):
        # type: (Any) -> Optional[Dict[str, Any]]
        """The stored next-step record of a user (a plain dict), or None."""
        ctx, _ = self._context_for_next_step(update_or_phone)
        return ctx.next_step

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
