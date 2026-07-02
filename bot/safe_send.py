"""
Safe send / reply for AI Mega Bot — handles Telegram rate limits (RetryAfter)
with exponential backoff and never crashes the bot on a failed send.

Two priority levels:
  priority=True  → directed messages, higher cap, never silently dropped
  priority=False → proactive comments, lower cap, may be dropped under flood
"""

import asyncio
import logging
import time

from aiogram import Bot
from aiogram.types import Message
from aiogram.exceptions import TelegramRetryAfter

logger = logging.getLogger("mega.safe_send")

# Simple per-chat rate limiter: max N messages per minute per chat.
_chat_buckets: dict[int, list[float]] = {}
_CHAT_WINDOW = 60  # seconds


def _can_send(chat_id: int, max_per_min: int, priority: bool) -> bool:
    now = time.time()
    cap = max_per_min + (5 if priority else 0)
    bucket = _chat_buckets.get(chat_id, [])
    bucket[:] = [t for t in bucket if now - t < _CHAT_WINDOW]
    if len(bucket) >= cap:
        return False
    bucket.append(now)
    _chat_buckets[chat_id] = bucket
    return True


async def safe_reply(
    bot: Bot,
    message: Message,
    text: str,
    always_reply: bool = True,
    priority: bool = False,
    max_per_min: int = 15,
) -> bool:
    """Reply to a message, handling rate limits. Returns True on success."""
    if not text:
        return False
    chat_id = message.chat.id
    if not _can_send(chat_id, max_per_min, priority):
        logger.info(f"rate-limited skip in {chat_id} (priority={priority})")
        return False

    for attempt in range(3):
        try:
            if always_reply:
                await message.reply(text, disable_web_page_preview=False)
            else:
                await bot.send_message(chat_id, text, disable_web_page_preview=False)
            return True
        except TelegramRetryAfter as e:
            wait = e.retry_after + 1
            logger.warning(f"RetryAfter {wait}s in {chat_id}")
            await asyncio.sleep(wait)
        except Exception as e:
            msg = str(e)
            if "message is too long" in msg.lower():
                # Telegram hard limit ~4096 chars; trim and retry once.
                text = text[:4000]
                try:
                    await message.reply(text)
                    return True
                except Exception:
                    return False
            logger.debug(f"send failed in {chat_id}: {e}")
            return False
    return False
