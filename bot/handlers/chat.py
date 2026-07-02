"""
Private chat handler — normal AI conversation through OpenClaw.

The bot remembers the recent dialog per user and answers naturally. /clear
resets the in-memory dialog. /help lists commands.
"""

import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.enums import ChatAction
from aiogram.filters import Command

from bot.config import config
from bot.mood import update_mood_from_message, current_mood_descriptor
from bot.persona import SYSTEM_PROMPT
from ai import client as ai_client

logger = logging.getLogger("mega.chat")

chat_router = Router()

# In-memory dialog history per user (kept short). Lost on restart — acceptable
# for a GitHub Actions bot (state that matters lives in the group DB).
_dialogs: dict[int, list[dict]] = {}
_MAX_HISTORY = 8


def _history(user_id: int) -> list[dict]:
    return _dialogs.setdefault(user_id, [])


@chat_router.message(Command("start"))
async def cmd_start(message: Message):
    await message.reply(
        "Привет! Я Василий 🤖\n\n"
        "Общаюсь в личке и активно в группах/чатах, ставлю реакции, "
        "комментирую новости и дополняю их информацией из интернета.\n\n"
        "В каналах — только реакции (лайки), без комментариев.\n\n"
        "Пиши что угодно — отвечу 🙂"
    )


@chat_router.message(Command("help"))
async def cmd_help(message: Message):
    await message.reply(
        "Команды:\n"
        "/start — приветствие\n"
        "/clear — забыть историю чата\n"
        "/mood — показать настроение\n"
        "/stats — статистика (владелец)\n\n"
        "В группе упомяни меня (@) или ответь на сообщение — отвечу. "
        "Иначе комментирую по настроению."
    )


@chat_router.message(Command("clear"))
async def cmd_clear(message: Message):
    _dialogs.pop(message.from_user.id, None)
    await message.reply("Готово — забыл историю нашего разговора 🧹")


@chat_router.message(Command("mood"))
async def cmd_mood(message: Message):
    mood = await current_mood_descriptor()
    await message.reply(f"Сейчас я {mood} 😊")


@chat_router.message(F.text)
async def handle_private_text(message: Message):
    if message.chat.type != "private":
        return  # groups handled elsewhere
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return

    update_mood_from_message(text)
    mood = await current_mood_descriptor()

    history = _history(message.from_user.id)
    history.append({"role": "user", "content": text})
    # keep only recent turns
    if len(history) > _MAX_HISTORY:
        history[:] = history[-_MAX_HISTORY:]

    system = SYSTEM_PROMPT + f"\n\nТвоё текущее настроение: {mood}."

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        reply = await ai_client.chat(
            text, system=system, dialog_history=history[:-1],
            max_tokens=800, temperature=0.9,
        )
    except Exception as e:
        logger.error(f"private chat AI error: {e}")
        reply = ""

    if not reply:
        await message.reply("Что-то я зависла 🙈 Попробуй ещё раз через секунду.")
        return

    history.append({"role": "assistant", "content": reply})
    await message.reply(reply[:4000])
