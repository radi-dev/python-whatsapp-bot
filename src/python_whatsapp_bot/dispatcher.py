from typing import Callable

# from queue import Queue
from threading import Thread

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

Message_handler, Interactive_query_handler, Update_handler = (
    MessageHandler,
    InteractiveQueryHandler,
    UpdateHandler,
)


class Dispatcher:
    def __init__(self, bot, mark_as_read: bool = True) -> None:
        self.bot = bot
        self.queue = bot.queue
        self.registered_handlers = []  # list of handler instances
        self.mark_as_read = mark_as_read
        self.next_step_handler = {}
        self.fallback_function = None

    def process_update(self, update) -> None:
        self.queue.put(update)
        while True:
            _update = self.queue.get()
            if not self.bot.threaded:
                self._process_queue(_update)
            else:
                Thread(target=self._process_queue(_update)).start()
            if self.queue.empty():
                break

    async def aprocess_update(self, update) -> None:
        self.queue.put(update)
        while True:
            _update = self.queue.get()
            if not self.bot.threaded:
                await self._aprocess_queue(_update)
            else:
                Thread(target=await self._aprocess_queue(_update)).start()
            if self.queue.empty():
                break

    def _process_queue(self, update) -> None:
        if not keys_exists(update, "entry", 0, "changes", 0, "value"):
            return
        value = update["entry"][0]["changes"][0]["value"]
        # self.value = value
        if not keys_exists(value, "metadata", "phone_number_id"):
            return
        if str(value["metadata"]["phone_number_id"]) == str(self.bot.id):
            if not keys_exists(value, "messages"):
                return
            _message = value["messages"][0]
            if self.mark_as_read:
                self.bot.mark_as_read(_message)
            update = Update(self.bot, value)
            print("\n\nupdate: ", update)

            # check if a next step handler has been registered
            persistent_handlers = [i for i in self.registered_handlers if i.persistent]
            try:
                users_next_step = self.next_step_handler[update.user_phone_number]
                users_next_step_handler = users_next_step["next_step_handler"]
                matched_handlers = []
                try:
                    users_next_step_fallback = users_next_step["fallback_function"]
                    matched_handlers.append(users_next_step_fallback)
                except KeyError:
                    pass
                matched_handlers.append(users_next_step_handler)
            # get registered handlers if no next step handler
            except KeyError:
                matched_handlers = list(self.registered_handlers)
            matched_handlers = persistent_handlers + matched_handlers

            for handler in matched_handlers:
                # if (
                #     isinstance(handler, UpdateHandler)
                #     and handler.name == _message["type"]
                # ) or isinstance(handler, UpdateHandler):
                if (
                    isinstance(handler, UpdateHandler)
                    and handler.name == _message["type"]
                ):

                    # Get message text
                    message_txt = handler.extract_data(_message).message_txt

                    res = self._check_and_run_handler(handler, value, message_txt)
                    if res:
                        try:
                            if (
                                self.next_step_handler[update.user_phone_number][
                                    "next_step_handler"
                                ]
                                == handler
                                or self.next_step_handler[update.user_phone_number][
                                    "fallback_function"
                                ]
                                == handler
                            ):
                                del self.next_step_handler[update.user_phone_number]
                            return
                        except KeyError:
                            return
                    else:
                        continue

    async def _aprocess_queue(self, update) -> None:
        if not keys_exists(update, "entry", 0, "changes", 0, "value"):
            return
        value = update["entry"][0]["changes"][0]["value"]
        # self.value = value
        if not keys_exists(value, "metadata", "phone_number_id"):
            return
        if str(value["metadata"]["phone_number_id"]) == str(self.bot.id):
            if not keys_exists(value, "messages"):
                return
            _message = value["messages"][0]
            if self.mark_as_read:
                self.bot.mark_as_read(_message)
            update = Update(self.bot, value)
            print("\n\nupdate: ", update)

            # check if a next step handler has been registered
            persistent_handlers = [i for i in self.registered_handlers if i.persistent]
            try:
                users_next_step = self.next_step_handler[update.user_phone_number]
                users_next_step_handler = users_next_step["next_step_handler"]
                matched_handlers = []
                try:
                    users_next_step_fallback = users_next_step["fallback_function"]
                    matched_handlers.append(users_next_step_fallback)
                except KeyError:
                    pass
                matched_handlers.append(users_next_step_handler)
            # get registered handlers if no next step handler
            except KeyError:
                matched_handlers = list(self.registered_handlers)
            matched_handlers = persistent_handlers + matched_handlers

            for handler in matched_handlers:
                # if (
                #     isinstance(handler, UpdateHandler)
                #     and handler.name == _message["type"]
                # ) or isinstance(handler, UpdateHandler):
                if (
                    isinstance(handler, UpdateHandler)
                    and handler.name == _message["type"]
                ):

                    # Get message text
                    message_txt = handler.extract_data(_message).message_txt

                    res = await self._acheck_and_run_handler(
                        handler, value, message_txt
                    )
                    if res:
                        try:
                            if (
                                self.next_step_handler[update.user_phone_number][
                                    "next_step_handler"
                                ]
                                == handler
                                or self.next_step_handler[update.user_phone_number][
                                    "fallback_function"
                                ]
                                == handler
                            ):
                                del self.next_step_handler[update.user_phone_number]
                            return
                        except KeyError:
                            return
                    else:
                        continue

    def _check_and_run_handler(self, handler: UpdateHandler, value, message):
        _message = value.get("messages", [{}])[0]
        if hasattr(handler, "filter_check"):
            if not handler.filter_check(message):
                return False
            if handler.context:
                update = Update(self.bot, value)
                extracted_data = handler.extract_data(_message)

                update.message_text = handler.extract_data(_message).message_txt
                for key, val in (extracted_data.__dict__).items():
                    setattr(update, key, val)
                # print("\n\nextracted_data: ", extracted_data.__dict__)

                handler.run(update, context=User_context(update.user_phone_number))
            else:
                handler.run(update)
            return True
        return False

    async def _acheck_and_run_handler(self, handler: UpdateHandler, value, message):
        _message = value.get("messages", [{}])[0]
        if hasattr(handler, "filter_check"):
            if not handler.filter_check(message):
                return False
            if handler.context:
                update = Update(self.bot, value)
                extracted_data = handler.extract_data(_message)

                update.message_text = handler.extract_data(_message).message_txt
                for key, val in (extracted_data.__dict__).items():
                    setattr(update, key, val)
                # print("\n\nextracted_data: ", extracted_data.__dict__)

                await handler.arun(
                    update, context=User_context(update.user_phone_number)
                )
            else:
                await handler.run(update)
            return True
        return False

    def _register_handler(self, handler_instance):
        self.registered_handlers.append(handler_instance)
        handler_index = len(self.registered_handlers) - 1
        return handler_index

    def set_next_handler(
        self,
        update: Update,
        function: Callable,
        handler_type: UpdateHandler = UpdateHandler,
        regex: str = None,
        func: Callable = None,
        end_conversation_action: Callable = lambda x: x,
        end_conversation_keyword_regex: str = r"(?i)^(end|stop|cancel)$",
    ):
        """Sets a function for handling of next update.
        The set_next_handler overrides other handlers till it handles an update itself
        """
        if not issubclass(handler_type, UpdateHandler):
            return "type should be an UpdateHandler class"
        self.next_step_handler[update.user_phone_number] = {}
        users_next = self.next_step_handler[update.user_phone_number]
        users_next["fallback_function"] = MessageHandler(
            regex=end_conversation_keyword_regex, action=end_conversation_action
        )
        if handler_type == MessageHandler:
            users_next["next_step_handler"] = MessageHandler(
                regex, func, action=function
            )
        elif handler_type == InteractiveQueryHandler:
            users_next["next_step_handler"] = InteractiveQueryHandler(
                regex, func, action=function
            )
        else:
            try:
                _type = update.value["messages"][0]["type"]
                new_handler = UpdateHandler()
                # new_handler.name = _type
                new_handler.regex = regex
                new_handler.func = func
                new_handler.action = function
                users_next["next_step_handler"] = new_handler
            except KeyError:
                return

    def add_message_handler(
        self,
        regex: str = None,
        func: Callable = None,
        context: bool = True,
        persistent: bool = False,
    ):
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
        regex: str = None,
        func: Callable = None,
        handle_button: bool = True,
        handle_list: bool = True,
        context: bool = True,
        persistent: bool = False,
    ):
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
        regex: str = None,
        func: Callable = None,
        context: bool = True,
        persistent: bool = False,
    ):
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
        regex: str = None,
        func: Callable = None,
        context: bool = True,
        persistent: bool = False,
    ):
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
        regex: str = None,
        func: Callable = None,
        context: bool = True,
        persistent: bool = False,
    ):
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
        context: bool = True,
        persistent: bool = False,
    ):
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
        context: bool = True,
        persistent: bool = False,
    ):
        def inner(function):
            _handler = LocationHandler(
                action=function,
                context=context,
                persistent=persistent,
            )
            self._register_handler(_handler)
            return function

        return inner

    # def add_location_handler(
    #     self,
    #     regex: str = None,
    #     func: Callable = None,
    #     context: bool = True,
    #     persistent: bool = False,
    # ):
    #     def inner(function):
    #         _handler = LocationHandler(
    #             regex=regex,
    #             func=func,
    #             action=function,
    #             context=context,
    #             persistent=persistent,
    #         )
    #         self._register_handler(_handler)
    #         return function

    #     return inner
