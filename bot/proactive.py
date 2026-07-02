"""
Proactive Topic Starter — Василий periodically initiates conversations in groups
where there's been silence, and occasionally injects thoughts into active chats.

Two modes:
  1. SILENT group (no messages for 2h+): start a fresh topic (max 1 per 3h/group)
  2. ACTIVE group: 8% chance per check to inject a related thought (max 1 per 45min)

This makes Василий an ACTIVE community member who doesn't just respond but
also STARTS conversations — exactly as a real engaged group member would.
"""

import asyncio
import logging
import random
import time
from typing import Optional

from aiogram import Bot

from bot import database as db
from bot.config import config
from bot.mood import current_mood_descriptor
from bot.context import recent_messages_to_text
from bot.persona import TOPIC_PROMPT
from bot.safe_send import safe_send
from ai import client as ai_client

logger = logging.getLogger("mega.proactive")

# How long of silence before Василий initiates a topic
SILENCE_THRESHOLD = 2 * 3600  # 2 hours
# How often to check groups
CHECK_INTERVAL = 10 * 60  # 10 minutes
# Min time between Василий's proactive topics in the same group (silent mode)
MIN_TOPIC_INTERVAL = 3 * 3600  # 3 hours
# Chance to inject a topic EVEN in active groups
ACTIVE_GROUP_INJECTION_PROB = 0.08  # 8% per check
# Min time between injections in active groups
ACTIVE_MIN_INTERVAL = 45 * 60  # 45 min

_bot_ref: Optional[Bot] = None


def set_bot(bot: Bot) -> None:
    global _bot_ref
    _bot_ref = bot


# Topic starter openers (Василий is male, casual)
TOPIC_STARTERS = [
    "народ, что думаете про",
    "кто-нибудь следил за",
    "а вы как считаете насчёт",
    "кстати, слышали что",
    "интересно ваше мнение —",
    "недавно думал про",
    "народ, а кто-нибудь",
    "блин, только что вспомнил —",
    "кстати о чём говорили,",
    "а что нового у всех? давно не виделись",
]

# General non-political topics Василий can bring up
GENERAL_TOPICS = [
    "новые гаджеты и технологии",
    "какие фильмы/сериалы сейчас стоит глянуть",
    "путешествия и куда бы хотелось поехать",
    "любимая еда и рецепты",
    "как проходит неделя",
    "что нового в мире авто",
    "интересные факты о которых мало кто знает",
    "хобби и увлечения",
    "какой кофе/чай любите",
    "что читаете сейчас",
    "планы на выходные",
    "любимые места в городе",
    "новости AI и нейросетей",
    "спорт — кто за кем следит",
]


async def _check_and_start_topic(chat_id: int) -> None:
    """Check if a group needs a proactive topic, and send one if so."""
    if _bot_ref is None:
        return
    try:
        recent = await db.get_recent_group_messages(chat_id, limit=6)
        if not recent:
            return

        now = time.time()
        last_msg_ts = await db.last_message_time(chat_id)
        silence = now - last_msg_ts if last_msg_ts else now
        last_bot_ts = await db.last_bot_message_time(chat_id)
        since_bot = now - last_bot_ts if last_bot_ts else 999999

        is_silent = silence >= SILENCE_THRESHOLD
        is_active_inject = (
            not is_silent
            and random.random() < ACTIVE_GROUP_INJECTION_PROB
            and since_bot >= ACTIVE_MIN_INTERVAL
        )

        if is_silent:
            if since_bot < MIN_TOPIC_INTERVAL:
                return
        elif is_active_inject:
            pass
        else:
            return

        # Build context from recent messages
        recent_text = recent_messages_to_text(recent, limit=4)
        mood = await current_mood_descriptor()
        dialog_history = []
        for m in recent:
            who = m.get("first_name") or m.get("username") or "кто-то"
            if m.get("user_id") == config.BOT_ID:
                role, content = "assistant", m.get("content", "")
            else:
                role, content = "user", f"{who}: {m.get('content', '')}"
            if content.strip():
                dialog_history.append({"role": role, "content": content})

        topic = random.choice(GENERAL_TOPICS)
        starter = random.choice(TOPIC_STARTERS)

        if is_silent:
            prompt = (
                f"В группе давно тишина ({silence/3600:.0f}ч). "
                f"Начни беседу — поделись мыслью/новостью/вопросом чтобы оживить чат. "
                f"Тема для старта: {topic}. Используй оборот вроде «{starter}». "
                f"Коротко, живо, 1-2 предложения. Задай вопрос группе."
            )
        else:
            prompt = (
                f"В группе активная беседа. Вступи со СВОЕЙ мыслью/вопросом/фактом — "
                f"не просто комментируй, а подними новую грань темы или смежную тему. "
                f"Можно: {topic}. Используй оборот вроде «{starter}». "
                f"Коротко, живо, 1-2 предложения. Задай вопрос группе. "
                f"Не повторяй то, что уже сказали другие."
            )

        extra_ctx = (
            f"Ты в группе. {'Иницируешь беседу после тишины' if is_silent else 'Вступаешь со своей мыслью в активную беседу'}. "
            f"Настроение: {mood}. "
            f"Недавний контекст:\n{recent_text}\n"
            f"Будь естественным, не формальным. Цель — вовлечь людей в разговор."
        )

        system = TOPIC_PROMPT + f"\n\nТвоё текущее настроение: {mood}."
        try:
            text = await asyncio.wait_for(
                ai_client.chat(
                    prompt, system=system, extra_context=extra_ctx,
                    dialog_history=dialog_history, max_tokens=300, temperature=0.95,
                    allow_static_fallback=False,
                ),
                timeout=40.0,
            )
        except asyncio.TimeoutError:
            return

        if not text:
            return
        text = text.strip()[:config.GROUP_MAX_CHARS]
        if not text:
            return

        sent = await safe_send(_bot_ref, chat_id, text, priority=False)
        if sent:
            mode = "silent" if is_silent else "active-inject"
            logger.info(f"Proactive topic ({mode}) in {chat_id} | silence={silence/60:.0f}min | {text[:50]!r}")
            await db.add_group_message(
                chat_id=chat_id, user_id=config.BOT_ID,
                username=config.BOT_USERNAME.lstrip("@"),
                first_name="Василий", content=text, is_media=False, is_bot=True,
            )
    except Exception as e:
        logger.debug(f"start_topic error for {chat_id}: {e}")


async def proactive_loop() -> None:
    """Background task: periodically check groups for silence and start topics."""
    logger.info("Proactive topic starter loop started")
    while True:
        try:
            await asyncio.sleep(CHECK_INTERVAL)
            groups = await db.get_active_group_chats(within_hours=24, limit=20)
            logger.debug(f"Checking {len(groups)} groups for proactive topics")
            for chat_id in groups:
                await _check_and_start_topic(chat_id)
                await asyncio.sleep(2)  # small delay between groups
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"proactive_loop error: {e}")
            await asyncio.sleep(60)
