"""Media helpers — extract captions from photos/videos/animations."""

from aiogram.types import Message


def extract_caption(message: Message) -> str:
    """Return the caption of a media message, or '' if none."""
    return (message.caption or "").strip()
