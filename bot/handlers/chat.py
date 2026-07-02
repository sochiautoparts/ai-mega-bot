"""
Private chat handler — normal AI conversation through OpenClaw.

Василий remembers the user across restarts:
  - Persistent dialog history (private_messages table) — survives restarts
  - Global user profile (name, acquaintance level, known facts)
  - Fact extraction from messages (lives in / works as / loves …)

Commands:
  /start — greeting
  /help  — commands list
  /clear — forget this user's private chat history
  /mood  — current mood
  /stats — AI stats (owner)
  /whoami — show what the bot remembers about you
"""

import logging
import random

from aiogram import Router, F
from aiogram.types import Message
from aiogram.enums import ChatAction
from aiogram.filters import Command

from bot.config import config
from bot.mood import update_mood_from_message, current_mood_descriptor
from bot.persona import SYSTEM_PROMPT
from bot import database as db
from bot.context import build_private_context, build_user_profile, extract_and_store_facts
from ai import client as ai_client

logger = logging.getLogger("mega.chat")

chat_router = Router()

_MAX_HISTORY = 16  # turns loaded from DB for context


@chat_router.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: Message):
    # Register the user even on /start
    u = message.from_user
    if u:
        await db.upsert_user(u.id, username=u.username or "", first_name=u.first_name or "",
                             last_name=u.last_name or "", is_bot=u.is_bot, in_private=True)
    await message.reply(
        "Привет! Я Василий 🤖\n\n"
        "Общаюсь в личке и активно в группах/чатах, ставлю реакции, "
        "комментирую новости и дополняю их информацией из интернета.\n\n"
        "В каналах — только реакции (лайки), без комментариев.\n\n"
        "Я запоминаю что ты рассказывал о себе — так что можем общаться как знакомые. "
        "Пиши что угодно 🙂"
    )


@chat_router.message(Command("help"))
async def cmd_help(message: Message):
    await message.reply(
        "Команды:\n"
        "/start — приветствие\n"
        "/clear — забыть историю нашего разговора\n"
        "/mood — показать настроение\n"
        "/whoami — что я о тебе помню\n"
        "/stats — статистика (владелец)\n\n"
        "В группе упомяни меня (@) или ответь на сообщение — отвечу. "
        "Иначе комментирую по настроению."
    )


@chat_router.message(Command("clear"), F.chat.type == "private")
async def cmd_clear(message: Message):
    uid = message.from_user.id
    n = await db.clear_private_history(uid)
    await message.reply(f"Готово — забыл историю нашего разговора ({n} сообщений) 🧹")


@chat_router.message(Command("mood"), F.chat.type == "private")
async def cmd_mood(message: Message):
    mood = await current_mood_descriptor()
    await message.reply(f"Сейчас я {mood} 😎")


@chat_router.message(Command("whoami"), F.chat.type == "private")
async def cmd_whoami(message: Message):
    uid = message.from_user.id
    profile = await build_user_profile(uid)
    if not profile:
        await message.reply("Пока ничего о тебе не знаю. Расскажи что-нибудь о себе 🙂")
        return
    await message.reply(f"Вот что я о тебе помню:\n\n{profile}")


@chat_router.message(F.text, F.chat.type == "private")
async def handle_private_text(message: Message):
    """Private chat text handler.

    CRITICAL: the F.chat.type == 'private' filter ensures this handler does NOT
    match group messages. In aiogram 3.x, when a handler matches (even if it
    just returns), the event is consumed and NOT propagated to subsequent
    routers. Without this filter, chat_router (included before group_router)
    would eat all group text messages and group_router would never see them —
    making the bot silent in groups even with Privacy Mode OFF.
    """
    u = message.from_user
    if not u:
        return
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return

    # 1. Register / update the user profile (global)
    await db.upsert_user(u.id, username=u.username or "", first_name=u.first_name or "",
                         last_name=u.last_name or "", is_bot=u.is_bot, in_private=True)

    # 2. Update mood from sentiment
    update_mood_from_message(text)
    mood = await current_mood_descriptor()

    # 3. Extract & store personal facts ("я живу в Москве" → "Павел живёт в Москве")
    name = u.first_name or u.username or ""
    try:
        new_facts = await extract_and_store_facts(u.id, name, text, source_chat=message.chat.id)
        for f in new_facts:
            logger.info(f"FACT STORED (private): {f}")
    except Exception as e:
        logger.debug(f"fact extraction error: {e}")

    # 4. Load persistent dialog history from DB (survives restarts!)
    history = await db.get_private_history(u.id, limit=_MAX_HISTORY)

    # 5. Save the user's message to DB BEFORE calling AI (so it's remembered)
    await db.add_private_message(u.id, "user", text)

    # 6. Build context: time + what we know about this person
    user_profile = await build_user_profile(u.id)
    ctx = build_private_context(user_profile)
    system = SYSTEM_PROMPT + f"\n\nТвоё текущее настроение: {mood}."
    if ctx:
        system += f"\n\n{ctx}"

    # 7. Call AI through OpenClaw (3-layer resilience: OpenClaw → Pollinations → static)
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        reply = await ai_client.chat(
            text, system=system, dialog_history=history,
            max_tokens=800, temperature=0.9, allow_static_fallback=True,
        )
    except Exception as e:
        logger.error(f"private chat AI error: {e}")
        reply = ""

    if not reply:
        fallbacks = [
            "Слушай, чет я завис 🙈 Повтори-ка ещё раз?",
            "Не уловил мысль, бро. Сформулируй иначе?",
            "Секунду, туплю немного. Давай ещё раз?",
            "Чёт связь барахлит. Накатай ещё разок 🙂",
            "Я тут, просто задумался. Повтори?",
        ]
        await message.reply(random.choice(fallbacks))
        return

    # 8. Save assistant reply to DB (so it's in the remembered history too)
    await db.add_private_message(u.id, "assistant", reply)
    await message.reply(reply[:4000])
