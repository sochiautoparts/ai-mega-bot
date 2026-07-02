"""
Admin handler — owner/operator commands.

  /stats                 — AI request statistics
  /channel_on <id>       — enable reactions for a channel
  /channel_off <id>      — disable reactions for a channel
  /broadcast <chat_id> <text>  — send a message to a chat
  /providers             — list active AI providers
"""

import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

from bot.config import config
from bot import database as db
from ai import client as ai_client

logger = logging.getLogger("mega.admin")

admin_router = Router()


def _is_admin(message: Message) -> bool:
    uid = message.from_user.id if message.from_user else 0
    return uid == config.OWNER_ID or uid in config.ADMIN_IDS


@admin_router.message(Command("stats"))
async def cmd_stats(message: Message):
    if not _is_admin(message):
        return
    s = ai_client.stats()
    await message.reply(
        f"📊 Статистика AI (через OpenClaw):\n"
        f"Запросов: {s.get('requests', 0)}\n"
        f"Успешно: {s.get('success', 0)}\n"
        f"Ошибок: {s.get('fail', 0)}\n"
        f"Последняя ошибка: {s.get('last_error', '—')[:120]}"
    )


@admin_router.message(Command("providers"))
async def cmd_providers(message: Message):
    if not _is_admin(message):
        return
    await message.reply(f"🔌 Провайдеры OpenClaw:\n{config.providers_status()}")


@admin_router.message(Command("channel_on"))
async def cmd_channel_on(message: Message):
    if not _is_admin(message):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.reply("Использование: /channel_on <chat_id>")
        return
    try:
        chat_id = int(parts[1])
    except ValueError:
        await message.reply("chat_id должен быть числом")
        return
    await db.set_channel_enabled(chat_id, True)
    await message.reply(f"✅ Реакции для канала {chat_id} включены")


@admin_router.message(Command("channel_off"))
async def cmd_channel_off(message: Message):
    if not _is_admin(message):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.reply("Использование: /channel_off <chat_id>")
        return
    try:
        chat_id = int(parts[1])
    except ValueError:
        await message.reply("chat_id должен быть числом")
        return
    await db.set_channel_enabled(chat_id, False)
    await message.reply(f"🚫 Реакции для канала {chat_id} выключены")


@admin_router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if not _is_admin(message):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.reply("Использование: /broadcast <chat_id> <текст>")
        return
    try:
        chat_id = int(parts[1])
    except ValueError:
        await message.reply("chat_id должен быть числом")
        return
    text = parts[2]
    try:
        await message.bot.send_message(chat_id, text)
        await message.reply("✅ Отправлено")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")
