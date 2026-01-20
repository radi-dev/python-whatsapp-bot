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
from typing import Any, Dict, Optional, Union
from queue import Queue


class Whatsapp:

    def __init__(self, number_id, token, mark_as_read=True):
        # type: (int, str, bool) -> None
        """This is the main Whatsapp class. Use it to initialize your bot
        Args:
            id: Your phone number id provided by WhatsApp cloud
            token : Your token provided by WhatsApp cloud
            mark_as_read:(bool), Use to set whether incoming messages should be marked as read. Default is True
        """
        self.version_number = 21  # type: int
        self.queue = Queue()  # type: Queue
        self.threaded = True  # type: bool
        self.id = number_id  # type: int
        self.token = token  # type: str
        self.base_url = f"https://graph.facebook.com/v{str(float(self.version_number))}"  # type: str
        self.msg_url = self.base_url + f"/{str(self.id)}/messages"  # type: str
        self.media_url = self.base_url + f"/{str(self.id)}/media"  # type: str
        self.dispatcher = Dispatcher(self, mark_as_read)  # type: Dispatcher
        self.on_message = self.dispatcher.add_message_handler
        self.on_interactive_message = self.dispatcher.add_interactive_handler
        self.on_image_message = self.dispatcher.add_image_handler
        self.on_audio_message = self.dispatcher.add_audio_handler
        self.on_video_message = self.dispatcher.add_video_handler
        self.on_sticker_message = self.dispatcher.add_sticker_handler
        self.on_location_message = self.dispatcher.add_location_handler
        self.set_next_step = self.dispatcher.set_next_handler

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

    def reply_template(self, update, template_name):
        # type: (Update, str) -> Any
        return self.send_template_message(update.user_phone_number, template_name)

    def reply_media(
        self,
        update,  # type: Update
        image_path,  # type: str
        caption=None,  # type: Optional[str]
        media_provider_token=None,  # type: Optional[str]
    ):
        # type: (...) -> Any
        return self.send_media_message(
            update.user_phone_number, image_path, caption, media_provider_token
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
        """Sends preregistered template message"""
        return message_template(
            self.msg_url,
            self.token,
            phone_num,
            template_name,
            components,
            language_code,
        )

    async def asend_template_message(
        self,
        phone_num,  # type: str
        template_name,  # type: str
        components=None,  # type: Optional[list]
        language_code=None,  # type: Optional[str]
    ):
        # type: (...) -> Any
        """Async version: Sends preregistered template message"""
        return await amessage_template(
            self.msg_url,
            self.token,
            phone_num,
            template_name,
            components,
            language_code,
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
