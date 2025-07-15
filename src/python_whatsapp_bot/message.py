import mimetypes
import os
from pathlib import Path
import re
from typing import Optional, Union
import json
import requests
from .markup import (
    Reply_markup,
    Inline_button,
    Inline_keyboard,
    Inline_list,
    List_item,
    List_section,
    InlineLocationRequest,
)

TIMEOUT: int = 30
KNOWN_EXTENSIONS = {
    "text/plain": ".txt",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "audio/mp3": ".mp3",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/aac": ".aac",
    "audio/ogg": ".opus",
    "audio/webm": ".webm",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}


def headers(WA_TOKEN):
    return {"Content-Type": "application/json", "Authorization": f"Bearer {WA_TOKEN}"}


def mark_as_read(update, url: str, token: str):
    payload = json.dumps(
        {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": update["id"],
            "typing_indicator": {"type": "text"},
        }
    )
    response = requests.post(url, headers=headers(token), data=payload, timeout=TIMEOUT)
    return response


def message_text(
    url: str,
    token: str,
    phone_num: str,
    text: str,
    msg_id: str = "",
    web_page_preview=True,
    tag_message: bool = True,
):
    message_frame = {
        "messaging_product": "whatsapp",
        "to": str(phone_num),
        "recipient_type": "individual",
        "type": "text",
        "text": {"body": text, "preview_url": web_page_preview},
    }
    if msg_id and tag_message:
        message_frame["context"] = {"message_id": msg_id}
    payload = json.dumps(message_frame)
    response = requests.post(url, headers=headers(token), data=payload, timeout=TIMEOUT)
    return response


def message_interactive(
    url: str,
    token: str,
    phone_num: str,
    text: str,
    reply_markup: Reply_markup,
    msg_id: str = "",
    header: str = None,
    header_type: str = "text",
    footer: str = None,
    web_page_preview=True,
):
    if not isinstance(reply_markup, Reply_markup):
        raise ValueError("Reply markup must be a Reply_markup object")
    message_frame = {
        "messaging_product": "whatsapp",
        "to": str(phone_num),
        "recipient_type": "individual",
        "type": "interactive",
        "interactive": {
            "type": reply_markup.type,  # [button, list, location_request_message]
            "body": {"text": text},
            "action": reply_markup.markup,
        },
    }
    if msg_id:
        message_frame["context"] = {"message_id": msg_id}
    if header:
        if header_type == "text":
            message_frame["interactive"]["header"] = {
                "type": "text",  # [text,video,image,document]
                "text": header,
            }
        elif header_type in ["image", "video", "document"]:
            if re.match(r"^((http[s]?://)|(www.))", header):
                header_type_object = {"link": header}
            else:
                header_type_object = {"id": header}
            message_frame["interactive"]["header"] = {
                "type": header_type,  # [text,video,image,document]
                header_type: header_type_object,
            }

    if footer:
        message_frame["interactive"]["footer"] = {"text": footer}
    payload = json.dumps(message_frame)
    response = requests.post(url, headers=headers(token), data=payload, timeout=TIMEOUT)
    return response


def message_template(
    url: str,
    token: str,
    phone_num: str,
    template_name: str,
    components: list = None,
    language_code: str = "en_US",
):
    payload = json.dumps(
        {
            "messaging_product": "whatsapp",
            "to": str(phone_num),
            "recipient_type": "individual",
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": list(components) if components is not None else [],
            },
        }
    )
    response = requests.post(url, headers=headers(token), data=payload, timeout=TIMEOUT)
    return response


def upload_media(url: str, token: str):
    payload = json.dumps(
        {
            "messaging_product": "whatsapp",
        }
    )
    response = requests.post(url, headers=headers(token), data=payload, timeout=TIMEOUT)
    return response


def get_media_url(base_url: str, media_id: str, token: str):
    url = f"{base_url}/{media_id}"
    response = requests.get(url, headers=headers(token), timeout=TIMEOUT)
    return response


def download_media(
    base_url: str, media_id: str, token: str, relative_file_path: str = "/media"
):
    if not media_id:
        return None
    # Generate the absolute file path from the relative path
    file_path = Path("tmp/" + relative_file_path).resolve() / media_id

    # Ensure the file has the correct extension
    media_data = get_media_url(base_url, media_id, token).json()
    media_url = media_data["url"]
    mime_type = media_data["mime_type"]
    extension = (
        KNOWN_EXTENSIONS.get(mime_type)
        or mimetypes.guess_extension(mime_type, strict=True)
        or ".bin"
    )

    file_path = file_path.with_suffix(extension)

    # Create the directory if it does not exist
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Download the media file
    with requests.get(
        media_url, headers=headers(token), stream=True, timeout=TIMEOUT
    ) as response, open(file_path, "wb") as file:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                file.write(chunk)

    return file_path


def download_media_data(
    base_url: str, media_id: str, token: str, relative_file_path: str = "/media"
):
    if not media_id:
        return None
    media_data = get_media_url(base_url, media_id, token).json()
    media_url = media_data["url"]

    # Download the media file
    return requests.get(media_url, headers=headers(token), stream=True, timeout=TIMEOUT)


def message_media(
    url: str,
    token: str,
    phone_num: str,
    image_path: str,
    caption: str = None,
    media_provider_token: str = None,
):
    payload = json.dumps(
        {
            "messaging_product": "whatsapp",
            "to": str(phone_num),
            "recipient_type": "individual",
            "type": "image",
            "image": {
                # "id" : "MEDIA-OBJECT-ID"
                "link": image_path,
                "caption": caption,
            },
        }
    )
    response = requests.post(url, headers=headers(token), data=payload, timeout=TIMEOUT)
    return response


def message_location(
    url: str,
    token: str,
    phone_num: str,
    location_latitude: str,
    location_longitude: str,
    location_name: Optional[str] = None,
    location_address: Optional[str] = None,
):
    location_data: dict = {
        "latitude": location_latitude,
        "longitude": location_longitude,
    }
    if location_name:
        location_data["name"] = location_name
    if location_address:
        location_data["address"] = location_address
    payload = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": str(phone_num),
            "type": "location",
            "location": location_data,
        }
    )
    response = requests.post(url, headers=headers(token), data=payload, timeout=TIMEOUT)
    return response


def message_location_request(
    url: str,
    token: str,
    phone_num: str,
    location_latitude: str,
    location_longitude: str,
    location_name: Optional[str] = None,
    location_address: Optional[str] = None,
):

    payload = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": str(phone_num),
            "type": "interactive",
            "interactive": {
                "type": "location_request_message",
                "body": {"text": "<BODY_TEXT>"},
                "action": {"name": "send_location"},
            },
        }
    )
    response = requests.post(url, headers=headers(token), data=payload, timeout=TIMEOUT)
    return response
