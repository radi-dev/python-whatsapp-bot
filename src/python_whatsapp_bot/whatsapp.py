from .dispatcher import Dispatcher, Update
from .message import (
    download_media,
    download_media_data,
    get_media_url,
    message_interactive,
    mark_as_read,
    message_text,
    message_template,
    upload_media,
    message_media,
    message_location,
    # Async versions
    adownload_media,
    adownload_media_data,
    aget_media_url,
    amessage_interactive,
    amark_as_read,
    amessage_text,
    amessage_template,
    aupload_media,
    amessage_media,
    amessage_location,
)
from .markup import Reply_markup
from .context_storage import ContextStorage, DEFAULT_LOCK_TIMEOUT, DEFAULT_LOCK_WAIT
from .user_context import User_context
from typing import Any, Dict, Optional, Union


class Whatsapp:

    def __init__(
        self,
        number_id,  # type: int
        token,  # type: str
        mark_as_read=True,  # type: bool
        context_storage=None,  # type: Optional[ContextStorage]
        context_lock=True,  # type: bool
        context_lock_timeout=DEFAULT_LOCK_TIMEOUT,  # type: float
        context_lock_wait=DEFAULT_LOCK_WAIT,  # type: float
    ):
        # type: (...) -> None
        """This is the main Whatsapp class. Use it to initialize your bot
        Args:
            id: Your phone number id provided by WhatsApp cloud
            token : Your token provided by WhatsApp cloud
            mark_as_read:(bool), Use to set whether incoming messages should be marked as read. Default is True
            context_storage: Where the per-user ``context`` given to handlers is stored
                (e.g. ``SQLiteStorage("bot.db")``, ``RedisStorage("redis://...")``,
                ``SQLAlchemyStorage("postgresql://...")``). Falls back to the global
                default set with :func:`python_whatsapp_bot.set_context_storage`.
                Required as soon as any handler takes a ``context`` argument; the bot
                raises :class:`ContextStorageNotConfiguredError` otherwise.
            context_lock:(bool) Hold a per-user lock while an update is processed so
                that two workers never process the same user concurrently. Default True.
            context_lock_timeout: Seconds before a held lock expires by itself (protects
                against crashed workers). Must exceed your slowest handler. Default 60.
            context_lock_wait: Max seconds to wait for a user's lock. When exceeded
                ``process_update`` raises :class:`ContextLockTimeoutError` before anything
                was processed - answer the webhook with a non-2xx status and WhatsApp
                re-delivers the message with exponential backoff. Default 10.
        """
        self.version_number = 21  # type: int
        self.threaded = True  # type: bool
        self.id = number_id  # type: int
        self.token = token  # type: str
        self.base_url = f"https://graph.facebook.com/v{str(float(self.version_number))}"  # type: str
        self.msg_url = self.base_url + f"/{str(self.id)}/messages"  # type: str
        self.media_url = self.base_url + f"/{str(self.id)}/media"  # type: str
        self.dispatcher = Dispatcher(
            self,
            mark_as_read,
            context_storage=context_storage,
            context_lock=context_lock,
            lock_timeout=context_lock_timeout,
            lock_wait=context_lock_wait,
        )  # type: Dispatcher
        self.on_message = self.dispatcher.add_message_handler
        self.on_interactive_message = self.dispatcher.add_interactive_handler
        self.on_image_message = self.dispatcher.add_image_handler
        self.on_audio_message = self.dispatcher.add_audio_handler
        self.on_video_message = self.dispatcher.add_video_handler
        self.on_sticker_message = self.dispatcher.add_sticker_handler
        self.on_location_message = self.dispatcher.add_location_handler
        self.set_next_step = self.dispatcher.set_next_handler
        self.clear_next_step = self.dispatcher.clear_next_step
        self.get_next_step = self.dispatcher.get_next_step
        self.register_step = self.dispatcher.register_step

    @property
    def context_storage(self):
        # type: () -> Optional[ContextStorage]
        """The storage backend configured for this bot's user context (or None)."""
        return self.dispatcher.context_storage

    @context_storage.setter
    def context_storage(self, storage):
        # type: (Optional[ContextStorage]) -> None
        self.dispatcher.context_storage = storage

    def set_context_storage(self, storage):
        # type: (Optional[ContextStorage]) -> None
        """Set (or replace) the storage backend used for the user context."""
        self.context_storage = storage

    def user_context(self, phone_num):
        # type: (str) -> User_context
        """Access a user's context outside of a handler, using this bot's storage.

        Example::

            with wa_bot.user_context("2348145xxxxx") as ctx:
                ctx.user_data["vip"] = True   # saved when the block exits
        """
        return self.dispatcher.user_context(phone_num)

    def _set_base_url(self):
        # type: () -> None
        self.base_url = f"https://graph.facebook.com/v{str(float(self.version_number))}"

    def set_version(self, version_number):
        # type: (int) -> None
        self.version_number = version_number
        self._set_base_url()

    def process_update(self, update):
        # type: (Dict[str, Any]) -> Any
        return self.dispatcher.process_update(update)

    def mark_as_read(self, update):
        # type: (Dict[str, Any]) -> Any
        """Mark any message as read"""
        return mark_as_read(update, self.msg_url, self.token)

    async def amark_as_read(self, update):
        # type: (Dict[str, Any]) -> Any
        """Async version: Mark any message as read"""
        return await amark_as_read(update, self.msg_url, self.token)

    def reply_message(
        self,
        phone_num,  # type: str
        text,  # type: str
        msg_id="",  # type: str
        reply_markup=None,  # type: Optional[Reply_markup]
        header=None,  # type: Optional[str]
        header_type="text",  # type: str
        footer=None,  # type: Optional[str]
        web_page_preview=True,  # type: bool
        tag_message=True,  # type: bool
    ):
        # type: (...) -> Any
        return self.send_message(
            phone_num,
            text,
            msg_id,
            reply_markup,
            header,
            header_type,
            footer,
            web_page_preview=web_page_preview,
            tag_message=tag_message,
        )

    @staticmethod
    def _phone_of(update_or_phone):
        # type: (Any) -> str
        """Accept either an Update or a plain phone number."""
        return str(getattr(update_or_phone, "user_phone_number", update_or_phone))

    def reply_template(self, update, template_name):
        # type: (Any, str) -> Any
        return self.send_template_message(self._phone_of(update), template_name)

    def reply_media(
        self,
        update,  # type: Any
        image_path,  # type: str
        caption=None,  # type: Optional[str]
        media_provider_token=None,  # type: Optional[str]
    ):
        # type: (...) -> Any
        """Reply with an image. ``update`` may be an Update or a phone number."""
        return self.send_media_message(
            self._phone_of(update), image_path, caption, media_provider_token
        )

    def send_message(
        self,
        phone_num,  # type: str
        text,  # type: str
        msg_id="",  # type: str
        reply_markup=None,  # type: Optional[Reply_markup]
        header=None,  # type: Optional[str]
        header_type="text",  # type: str
        footer=None,  # type: Optional[str]
        web_page_preview=True,  # type: bool
        tag_message=True,  # type: bool
    ):
        # type: (...) -> Any
        """Sends text message
        Args:
            phone_num:(int) Recipeint's phone number
            text:(str) The text to be sent
            web_page_preview:(bool),optional. Turn web page preview of links on/off
        """
        if reply_markup:
            return message_interactive(
                self.msg_url,
                self.token,
                phone_num,
                text,
                reply_markup,
                msg_id=msg_id,
                header=header,
                header_type=header_type,
                footer=footer,
                web_page_preview=web_page_preview,
            )
        else:
            return message_text(
                self.msg_url,
                self.token,
                phone_num,
                text,
                msg_id=msg_id,
                web_page_preview=web_page_preview,
                tag_message=tag_message,
            )

    async def asend_message(
        self,
        phone_num,  # type: str
        text,  # type: str
        msg_id="",  # type: str
        reply_markup=None,  # type: Optional[Reply_markup]
        header=None,  # type: Optional[str]
        header_type="text",  # type: str
        footer=None,  # type: Optional[str]
        web_page_preview=True,  # type: bool
        tag_message=True,  # type: bool
    ):
        # type: (...) -> Any
        """Async version: Sends text message
        Args:
            phone_num:(int) Recipeint's phone number
            text:(str) The text to be sent
            web_page_preview:(bool),optional. Turn web page preview of links on/off
        """
        if reply_markup:
            return await amessage_interactive(
                self.msg_url,
                self.token,
                phone_num,
                text,
                reply_markup,
                msg_id=msg_id,
                header=header,
                header_type=header_type,
                footer=footer,
                web_page_preview=web_page_preview,
            )
        else:
            return await amessage_text(
                self.msg_url,
                self.token,
                phone_num,
                text,
                msg_id=msg_id,
                web_page_preview=web_page_preview,
                tag_message=tag_message,
            )

    def send_template_message(
        self,
        phone_num,  # type: str
        template_name,  # type: str
        components=None,  # type: Optional[list]
        language_code=None,  # type: Optional[str]
    ):
        # type: (...) -> Any
        """Sends preregistered template message (``language_code`` defaults to ``en_US``)"""
        return message_template(
            self.msg_url,
            self.token,
            phone_num,
            template_name,
            components,
            language_code or "en_US",
        )

    async def asend_template_message(
        self,
        phone_num,  # type: str
        template_name,  # type: str
        components=None,  # type: Optional[list]
        language_code=None,  # type: Optional[str]
    ):
        # type: (...) -> Any
        """Async version: Sends preregistered template message (``language_code`` defaults to ``en_US``)"""
        return await amessage_template(
            self.msg_url,
            self.token,
            phone_num,
            template_name,
            components,
            language_code or "en_US",
        )

    def upload_media(self):
        # type: () -> Any
        return upload_media(self.media_url, self.token)

    async def aupload_media(self):
        # type: () -> Any
        """Async version: Upload media"""
        return await aupload_media(self.media_url, self.token)

    def get_media_url(self, media_id):
        # type: (str) -> Any
        return get_media_url(self.base_url, media_id, self.token).json()

    async def aget_media_url(self, media_id):
        # type: (str) -> Any
        """Async version: Get media URL"""
        return (await aget_media_url(self.base_url, media_id, self.token)).json()

    def download_media(self, media_id, file_path):
        # type: (str, str) -> Any
        return download_media(self.base_url, media_id, self.token, file_path)

    async def adownload_media(self, media_id, file_path):
        # type: (str, str) -> Any
        """Async version: Download media"""
        return await adownload_media(self.base_url, media_id, self.token, file_path)

    def download_media_data(self, media_id, file_path):
        # type: (str, str) -> Any
        return download_media_data(self.base_url, media_id, self.token, file_path)

    async def adownload_media_data(self, media_id, file_path):
        # type: (str, str) -> Any
        """Async version: Download media data"""
        return await adownload_media_data(self.base_url, media_id, self.token, file_path)

    def send_media_message(
        self,
        phone_num,  # type: str
        image_path,  # type: str
        caption=None,  # type: Optional[str]
        media_provider_token=None,  # type: Optional[str]
    ):
        # type: (...) -> Any
        """Sends media message which may include audio, document, image, sticker, or video
        Using media link or by uploading media from file.
        paths starting with http(s):// or www. will be treated as link, others will be treated as local files
        """
        return message_media(
            self.msg_url,
            self.token,
            phone_num,
            image_path,
            caption,
            media_provider_token,
        )

    async def asend_media_message(
        self,
        phone_num,  # type: str
        image_path,  # type: str
        caption=None,  # type: Optional[str]
        media_provider_token=None,  # type: Optional[str]
    ):
        # type: (...) -> Any
        """Async version: Sends media message which may include audio, document, image, sticker, or video
        Using media link or by uploading media from file.
        paths starting with http(s):// or www. will be treated as link, others will be treated as local files
        """
        return await amessage_media(
            self.msg_url,
            self.token,
            phone_num,
            image_path,
            caption,
            media_provider_token,
        )
