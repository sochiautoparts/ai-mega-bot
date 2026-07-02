"""Media helpers — extract captions + download photos for vision understanding."""

import base64
import logging

from aiogram import Bot
from aiogram.types import Message

logger = logging.getLogger("mega.media")


def extract_caption(message: Message) -> str:
    """Return the caption of a media message, or '' if none."""
    return (message.caption or "").strip()


async def download_photo_as_base64(bot: Bot, message: Message, max_size: int = 5_000_000) -> str:
    """Download the largest photo from a message and return as base64 data URI.

    Returns '' if download fails or no photo. The data URI is suitable for
    OpenAI-compatible vision API (image_url with data URI).
    """
    try:
        if not message.photo:
            return ""
        # Take the largest photo size (last in the list)
        photo = message.photo[-1]
        # Check file size if available (avoid downloading huge files)
        if photo.file_size and photo.file_size > max_size:
            logger.debug(f"photo too large ({photo.file_size} bytes), skipping")
            return ""
        file = await bot.get_file(photo.file_id)
        if not file.file_path:
            return ""
        # Download the file bytes
        import httpx
        # aiogram 3.x: bot.download_file returns bytes-like or stream
        data = await bot.download_file(file.file_path)
        # data is a BytesIO-like object
        raw = data.read() if hasattr(data, "read") else data
        if not raw or len(raw) > max_size:
            return ""
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        logger.debug(f"photo download error: {e}")
        return ""
