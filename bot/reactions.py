"""
Emoji reactions for AI Mega Bot.

Picks a context-appropriate emoji for a message and sets it via Telegram's
setMessageReaction. Falls back gracefully when the bot lacks reaction rights
or Telegram rate-limits. De-duplicates so we never react twice to the same msg.
"""

import asyncio
import logging
import random
from typing import Optional

from aiogram import Bot
from aiogram.types import ReactionTypeEmoji

from bot.config import config
from bot import database as db

logger = logging.getLogger("mega.reactions")

# Emoji pool — chosen by light keyword matching on the message text.
_POSITIVE = ["👍", "❤️", "🔥", "😄", "👏", "🎉", "💪", "✨"]
_LOVE = ["❤️", "😍", "🥰", "💙", "💜"]
_FUN = ["😄", "😂", "🤣", "😆", "😎"]
_WOW = ["😮", "😱", "🤯", "👀", "🔥"]
_SAD = ["😢", "😔", "🙏", "💔"]
_THINK = ["🤔", "👀", "🧐", "💡"]
_NEUTRAL = ["👍", "👌", "🙌", "✨"]


def _pick_emoji(text: str) -> str:
    t = (text or "").lower()
    if any(w in t for w in ["люблю", "обожаю", "супер", "огонь", "класс", "топ", "🔥", "❤"]):
        return random.choice(_LOVE + ["🔥"])
    if any(w in t for w in ["смешн", "лол", "ха", "ржу", "😂", "🤣", "шутк"]):
        return random.choice(_FUN)
    if any(w in t for w in ["ого", "вау", "шок", "жесть", "😱", "невероятн", "удивил"]):
        return random.choice(_WOW)
    if any(w in t for w in ["грустн", "печаль", "жаль", "соболезн", " умер", "погиб"]):
        return random.choice(_SAD)
    if any(w in t for w in ["почему", "как так", "интересн", "думаю", "вопрос", "?"]):
        return random.choice(_THINK)
    if any(w in t for w in ["спасибо", "благодар", "спс"]):
        return random.choice(["🙏", "👍", "❤️"])
    return random.choice(_POSITIVE)


async def maybe_react(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str = "",
    prob: Optional[float] = None,
    force: bool = False,
) -> bool:
    """Set an emoji reaction on a message.

    prob: override reaction probability (default config.REACTION_PROB).
    force: if True, skip the probability check (caller already decided).
    Returns True if a reaction was actually set.
    """
    if not force:
        p = prob if prob is not None else config.REACTION_PROB
        if random.random() > p:
            return False

    # De-duplicate: never react twice to the same message.
    if await db.already_reacted(chat_id, message_id):
        return False

    emoji = _pick_emoji(text)
    try:
        await bot.set_message_reaction(
            chat_id, message_id, [ReactionTypeEmoji(type="emoji", emoji=emoji)]
        )
        await db.mark_reacted(chat_id, message_id)
        return True
    except Exception as e:
        msg = str(e)
        # Common benign failures: no reaction rights, chat forbidden, etc.
        if "REACTION_INVALID" in msg or "not enough rights" in msg.lower():
            logger.debug(f"no reaction rights in {chat_id}")
        elif "RetryAfter" in msg:
            logger.debug(f"reaction rate-limited in {chat_id}")
        else:
            logger.debug(f"reaction failed ({chat_id}/{message_id}): {e}")
        return False
