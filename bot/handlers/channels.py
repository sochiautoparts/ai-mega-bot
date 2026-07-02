"""
Channel handler — ONLY sets emoji reactions on channel posts.

Per requirement: when the bot is added to a channel, it should ONLY put emoji
reactions (likes) on posts, NOT write comments in the channel. This keeps
channels clean — the bot is a silent engaged subscriber that reacts but never
floods with comments.

Reactions use Telegram setMessageReaction (👍❤️🔥😄😮🙏 etc.).
The bot must be added as a channel admin for reactions to work on posts.
"""

import logging
import random

from aiogram import Router, F
from aiogram.types import Message, Chat

from bot.config import config
from bot import database as db
from bot.reactions import maybe_react

logger = logging.getLogger("mega.channels")

channel_router = Router()


def _is_politics_or_war(text: str) -> bool:
    t = (text or "").lower()
    triggers = ["путин", "кремль", "госдума", "санкци", "сво", "мобилиз", "война",
                "зеленск", "байден", "трамп", "выборы", "парламент", "ракетн", "обстрел"]
    return any(w in t for w in triggers)


@channel_router.channel_post(F.text | F.photo | F.video | F.animation)
async def handle_channel_post(message: Message):
    """React to channel posts with emoji — NO comments, NO replies.

    The bot is a silent engaged subscriber in channels: only puts likes
    (reactions), never writes comments. This keeps the channel clean.
    """
    chat: Chat = message.chat
    await db.upsert_channel(chat.id, username=chat.username or "", title=chat.title or "")

    if not await db.is_channel_enabled(chat.id):
        return

    # Probability per config — feels natural, not every single post.
    if random.random() > config.CHANNEL_REACTION_PROB:
        return

    post_text = (message.caption or message.text or "").strip()
    if _is_politics_or_war(post_text):
        return  # skip politics/war posts

    try:
        await maybe_react(
            message.bot, chat.id, message.message_id, post_text,
            prob=1.0, force=True,  # already checked probability
        )
    except Exception as e:
        logger.debug(f"channel reaction failed: {e}")

    # NO comment reply — channels are reaction-only by design.
