"""
Channel handler — reactions + comments on channel posts.

Bot puts 3 positive reactions on every post, plus occasionally
writes a short comment (reply) to simulate engaged subscriber.
"""

import asyncio
import logging
import random

from aiogram import Router, F
from aiogram.types import Message, Chat

from bot.config import config
from bot import database as db
from bot.reactions import maybe_react

logger = logging.getLogger("vasya.channels" if "vasya" == "luba" else "mega.channels")

channel_router = Router()

# Ready-made short comments (no AI needed — instant, 20% of posts)
_QUICK_COMMENTS = [
    "Огонь! 🔥", "Согласен полностью 💯", "Вот это новость!", "Интересно 🤔",
    "Жду больше деталей", "Топ контент 👍", "Спасибо за новость!", "Вот это да!",
    "Поддерживаю!", "Качественный пост 🔥", "Беру на заметку", "Супер!",
    "Вот это поворот...", "Не ожидал такого", "Отличный разбор 👏",
    "Согласен с редакцией", "Точно подмечено!", "Интересная мысль 💭",
    "Вот это тема!", "Качественно 🔥", "Респект автору 👍", "Полезно, спасибо!",
    "Вот это инфа!", "Держите марку 💪", "Читаю с удовольствием",
    "Это надо обсудить!", "Хороший пост 🙌", "Одобряю!",
]

def _is_politics_or_war(text: str) -> bool:
    t = (text or "").lower()
    triggers = ["путин", "кремл", "госдума", "санкци", "мобилиз",
                "зеленск", "байден", "трамп", "выборы", "парламент", "ракетн", "обстрел",
                "спецопераци", "вооружен", "боевые действия"]
    return any(w in t for w in triggers)


async def _post_comment(message: Message, post_text: str):
    """Post a short comment on channel post (reply creates comment in discussion group).
    20% — ready-made quick comment
    10% — AI-generated contextual comment
    70% — no comment (just reactions)
    """
    roll = random.random()
    
    if roll < 0.20:
        # Quick ready-made comment
        comment = random.choice(_QUICK_COMMENTS)
        try:
            await asyncio.sleep(random.uniform(5, 15))  # natural delay
            await message.reply(comment, disable_web_page_preview=True)
            logger.info(f"  Comment posted (quick): {comment}")
        except Exception as e:
            logger.debug(f"  Quick comment failed: {e}")
    
    elif roll < 0.30:
        # AI-generated contextual comment (1-2 sentences)
        try:
            from ai import client as ai_client
            from bot.persona import COMMENT_PROMPT
            prompt = f"Коротко прокомментируй этот пост канала (1-2 предложения, живо, с эмодзи). Текст поста: {post_text[:300]}"
            comment = await ai_client.chat(
                prompt, system=COMMENT_PROMPT,
                max_tokens=100, temperature=0.9, allow_static_fallback=False, fast=True
            )
            if comment and len(comment.strip()) > 5:
                comment = comment.strip()[:300]
                await asyncio.sleep(random.uniform(5, 15))  # natural delay
                await message.reply(comment, disable_web_page_preview=True)
                logger.info(f"  Comment posted (AI): {comment[:50]}")
        except Exception as e:
            logger.debug(f"  AI comment failed: {e}")


@channel_router.channel_post(F.text | F.photo | F.video | F.animation | F.sticker | F.voice | F.document | F.video_note)
async def handle_channel_post(message: Message):
    """React to channel posts with 3 reactions + occasional comments."""
    chat: Chat = message.chat
    await db.upsert_channel(chat.id, username=chat.username or "", title=chat.title or "")
    logger.info(f"CHANNEL POST received: chat={chat.id} (@{chat.username or ''}) msg={message.message_id}")

    if not await db.is_channel_enabled(chat.id):
        return

    post_text = (message.caption or message.text or "").strip()
    if _is_politics_or_war(post_text):
        return

    already = await db.already_reacted(chat.id, message.message_id)
    if already:
        return

    # 1. Reactions (always)
    try:
        ok = await maybe_react(
            message.bot, chat.id, message.message_id, post_text,
            prob=1.0, force=True, count=3,
        )
        logger.info(f"  maybe_react: {'OK' if ok else 'FAILED'}")
    except Exception as e:
        logger.warning(f"  reaction failed: {e}")

    # 2. Comments (30% chance — 20% quick + 10% AI)
    await _post_comment(message, post_text)


@channel_router.channel_post()
async def handle_channel_post_catchall(message: Message):
    """Catch-all for other channel post types."""
    chat: Chat = message.chat
    await db.upsert_channel(chat.id, username=chat.username or "", title=chat.title or "")

    if not await db.is_channel_enabled(chat.id):
        return

    already = await db.already_reacted(chat.id, message.message_id)
    if already:
        return

    try:
        ok = await maybe_react(
            message.bot, chat.id, message.message_id, "",
            prob=1.0, force=True, count=3,
        )
        logger.info(f"  maybe_react (catch-all): {'OK' if ok else 'FAILED'}")
    except Exception as e:
        logger.warning(f"  catch-all reaction failed: {e}")
