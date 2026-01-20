import re
import inspect
from typing import Any, Callable, Dict, Optional

from .markup import Reply_markup
from .error_handlers import keys_exists


class Update:

    def __init__(self, bot, update):
        # type: (Any, Dict[str, Any]) -> None
        self.bot = bot
        self.value = update  # type: Dict[str, Any]
        self.message = self.value.get("messages", [{}])[0]  # type: Dict[str, Any]
        self.user = self.value.get("contacts", [{}])[0]  # type: Dict[str, Any]
        self.user_display_name = self.user.get("profile", {}).get("name", "")  # type: str
        self.user_phone_number = self.user.get("wa_id", "")  # type: str
        self.message_id = self.message.get("id")  # type: Optional[str]
        self.message_text = None  # type: Optional[str]
        self.interactive_text = None  # type: Optional[str]
        self.media_url = None  # type: Optional[str]
        self.media_mime_type = None  # type: Optional[str]
        self.media_file_id = None  # type: Optional[str]
        self.media_hash = None  # type: Optional[str]
        self.media_voice = False  # type: bool
        self.loc_address = None  # type: Optional[str]
        self.loc_name = None  # type: Optional[str]
        self.loc_latitude = None  # type: Optional[str]
        self.loc_longitude = None  # type: Optional[str]

    #     self._initialize_message_text()

    # def _initialize_message_text(self):
    #     if keys_exists(self.message, "text", "body"):
    #         self.message_text = self.message["text"]["body"]
    #     if keys_exists(self.message, "interactive", "list_reply"):
    #         self.interactive_text = self.message["interactive"]["list_reply"]
    #         self.message_text = self.message["interactive"]["list_reply"]["id"]
    #     if keys_exists(self.message, "interactive", "button_reply"):
    #         self.interactive_text = self.message["interactive"]["button_reply"]
    #         self.message_text = self.message["interactive"]["button_reply"]["id"]

    def set_message_text(self, text):
        # type: (str) -> None
        self.message_text = text

    def reply_message(
        self,
        text,  # type: str
        reply_markup=None,  # type: Optional[Reply_markup]
        header=None,  # type: Optional[str]
        header_type="text",  # type: str
        footer=None,  # type: Optional[str]
        web_page_preview=True,  # type: bool
        tag_message=True,  # type: bool
        *args,
        **kwargs
    ):
        # type: (...) -> Any
        return self.bot.reply_message(
            self.user_phone_number,
            text,
            msg_id=self.message_id,
            reply_markup=reply_markup,
            header=header,
            header_type=header_type,
            footer=footer,
            web_page_preview=web_page_preview,
            tag_message=tag_message,
            *args,
            **kwargs,
        )

    def reply_media(
        self,
        media_path,  # type: str
        caption=None,  # type: Optional[str]
        media_provider_token=None,  # type: Optional[str]
        *args,
        **kwargs
    ):
        # type: (...) -> Any
        return self.bot.reply_media(
            self.user_phone_number,
            media_path,
            caption,
            media_provider_token,
            *args,
            **kwargs,
        )


class UpdateData:
    def __init__(self):
        # type: () -> None
        self.message_txt = ""  # type: str
        self.list_reply = None  # type: Optional[Any]

        # Media
        self.media_mime_type = None  # type: Optional[str]
        self.media_file_id = None  # type: Optional[str]
        self.media_hash = None  # type: Optional[str]
        self.media_voice = False  # type: bool

        # Location
        self.loc_address = None  # type: Optional[str]
        self.loc_name = None  # type: Optional[str]
        self.loc_latitude = None  # type: Optional[str]
        self.loc_longitude = None  # type: Optional[str]


class UpdateHandler:
    def __init__(self, context=True, *args, **kwargs):
        # type: (bool, *Any, **Any) -> None
        self.name = None  # type: Optional[str]
        self.regex = None  # type: Optional[str]
        self.func = None  # type: Optional[Callable]
        self.action = None  # type: Optional[Callable]
        self.context = context  # type: bool
        self.list = None  # type: Optional[bool]
        self.button = None  # type: Optional[bool]
        self.persistent = False  # type: bool

    def extract_data(self, msg):
        # type: (Dict[str, dict]) -> UpdateData
        data = UpdateData()
        data.message_txt = ""
        return data

    def filter_check(self, msg):
        # type: (str) -> bool
        if self.regex:
            return bool(re.match(self.regex, msg))
        if self.func:
            return bool(self.func(msg))
        return True

    def run(self, *args, **kwargs):
        # type: (*Any, **Any) -> Any
        new_kwargs = {
            key: val
            for key, val in kwargs.items()
            if key in inspect.getfullargspec(self.action).args
        }
        return self.action(*args, **new_kwargs)

    async def arun(self, *args, **kwargs):
        # type: (*Any, **Any) -> Any
        new_kwargs = {
            key: val
            for key, val in kwargs.items()
            if key in inspect.getfullargspec(self.action).args
        }
        if not inspect.iscoroutinefunction(self.action):
            raise TypeError(
                f"function {self.action.__name__} must be an async function (coroutine), but it is not."
            )
        return await self.action(*args, **new_kwargs)


class MessageHandler(UpdateHandler):
    def __init__(
        self,
        regex: str = None,
        func: Callable = None,
        action: Callable = None,
        context: bool = True,
        persistent: bool = False,
    ) -> None:
        super().__init__(context)
        self.name = "text"
        self.regex = regex
        self.func = func
        self.action = action
        self.persistent = persistent

    def extract_data(self, msg) -> UpdateData:
        data = UpdateData()
        data.message_txt = msg.get("text", {}).get("body", "")
        return data


class InteractiveQueryHandler(UpdateHandler):
    """For button_reply and list_reply"""

    def __init__(
        self,
        regex=None,  # type: Optional[str]
        func=None,  # type: Optional[Callable]
        handle_button=True,  # type: bool
        handle_list=True,  # type: bool
        action=None,  # type: Optional[Callable]
        context=True,  # type: bool
        persistent=False,  # type: bool
    ):
        # type: (...) -> None
        super().__init__(context)
        self.name = "interactive"
        self.regex = regex
        self.func = func
        self.action = action
        self.list = handle_list
        self.button = handle_button
        self.persistent = persistent

    def extract_data(self, msg) -> UpdateData:
        message_txt = ""
        if msg["interactive"]["type"] == "button_reply" and self.button:
            message_txt = msg.get("interactive", {}).get("button_reply", {}).get("id")
        elif msg["interactive"]["type"] == "list_reply" and self.list:
            message_txt = msg.get("interactive", {}).get("list_reply", {}).get("id")
        data = UpdateData()
        data.message_txt = message_txt
        return data


class MediaHandler(UpdateHandler):
    def __init__(
        self,
        regex: str = None,
        func: Callable = None,
        action: Callable = None,
        context: bool = True,
        persistent: bool = False,
    ) -> None:
        super().__init__(context)
        self.regex = regex
        self.func = func
        self.action = action
        self.persistent = persistent


class ImageHandler(MediaHandler):
    def __init__(self, *args, **kwargs):
        # type: (*Any, **Any) -> None
        super(ImageHandler, self).__init__(*args, **kwargs)
        self.name = "image"

    def extract_data(self, msg):
        # type: (Dict[str, Any]) -> UpdateData
        data = UpdateData()
        img_data = msg.get("image", {})
        data.message_txt = img_data.get("caption", "")
        data.media_mime_type = img_data.get("mime_type", "")
        data.media_file_id = img_data.get("id", "")
        data.media_hash = img_data.get("sha256", "")
        return data


class AudioHandler(MediaHandler):
    def __init__(self, *args, **kwargs):
        # type: (*Any, **Any) -> None
        super(AudioHandler, self).__init__(*args, **kwargs)
        self.name = "audio"

    def extract_data(self, msg):
        # type: (Dict[str, Any]) -> UpdateData
        data = UpdateData()
        audio_data = msg.get("audio", {})
        data.media_mime_type = audio_data.get("mime_type", "")
        data.media_file_id = audio_data.get("id", "")
        data.media_hash = audio_data.get("sha256", "")
        data.media_voice = audio_data.get("voice", "")
        return data


class VideoHandler(MediaHandler):
    def __init__(self, *args, **kwargs):
        # type: (*Any, **Any) -> None
        super(VideoHandler, self).__init__(*args, **kwargs)
        self.name = "video"

    def extract_data(self, msg):
        # type: (Dict[str, Any]) -> UpdateData
        data = UpdateData()
        vid_data = msg.get("video", {})
        data.message_txt = vid_data.get("caption", "")
        data.media_mime_type = vid_data.get("mime_type", "")
        data.media_file_id = vid_data.get("id", "")
        data.media_hash = vid_data.get("sha256", "")
        return data


class StickerHandler(MediaHandler):
    def __init__(self, *args, **kwargs):
        # type: (*Any, **Any) -> None
        super(StickerHandler, self).__init__(*args, **kwargs)
        self.name = "sticker"

    def extract_data(self, msg):
        # type: (Dict[str, Any]) -> UpdateData
        data = UpdateData()
        stckr_data = msg.get("sticker", {})
        data.media_mime_type = stckr_data.get("mime_type", "")
        data.media_file_id = stckr_data.get("id", "")
        data.media_hash = stckr_data.get("sha256", "")
        return data


class LocationHandler(UpdateHandler):
    def __init__(
        self,
        regex=None,  # type: Optional[str]
        func=None,  # type: Optional[Callable]
        action=None,  # type: Optional[Callable]
        context=True,  # type: bool
        persistent=False,  # type: bool
    ):
        # type: (...) -> None
        super(LocationHandler, self).__init__(context)
        self.name = "location"
        self.regex = regex
        self.func = func
        self.action = action
        self.persistent = persistent

    def extract_data(self, msg):
        # type: (Dict[str, Any]) -> UpdateData
        data = UpdateData()
        loc_data = msg.get("location", {})
        loc_name = loc_data.get("name", "")
        data.loc_address = loc_data.get("address", "")
        data.loc_name = loc_data.get("name", "")
        data.loc_latitude = loc_data.get("latitude", "")
        data.loc_longitude = loc_data.get("longitude", "")
        data.message_txt = (
            loc_name + "\n" + data.loc_address
            if data.loc_address
            else f"long - _{data.loc_longitude}_\nlat - _{data.loc_longitude}_"
        )

        return data


class UnknownHandler(UpdateHandler):
    def __init__(
        self,
        regex=None,  # type: Optional[str]
        func=None,  # type: Optional[Callable]
        action=None,  # type: Optional[Callable]
        context=True,  # type: bool
        persistent=False,  # type: bool
    ):
        # type: (...) -> None
        super(UnknownHandler, self).__init__(context)
        self.name = "unknown"
        self.regex = regex
        self.func = func
        self.action = action
        self.persistent = persistent


class UnsupportedHandler(UpdateHandler):
    def __init__(
        self,
        regex=None,  # type: Optional[str]
        func=None,  # type: Optional[Callable]
        action=None,  # type: Optional[Callable]
        context=True,  # type: bool
        persistent=False,  # type: bool
    ):
        # type: (...) -> None
        super(UnsupportedHandler, self).__init__(context)
        self.name = "unsupported"
        self.regex = regex
        self.func = func
        self.action = action
        self.persistent = persistent
