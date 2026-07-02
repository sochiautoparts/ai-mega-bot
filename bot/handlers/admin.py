"""
Admin handler — owner/operator commands.

  /stats                 — AI request statistics
  /diag                  — diagnostics: current chat info + what bot sees
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


@admin_router.message(Command("models"))
async def cmd_models(message: Message):
    """Live-test available Pollinations models + show AI stats breakdown."""
    if not _is_admin(message):
        return
    import httpx
    s = ai_client.stats()
    # Fetch Pollinations model list
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get("https://text.pollinations.ai/models")
        models = r.json() if r.status_code == 200 else []
    except Exception:
        models = []
    lines = [
        "🤖 Модели Pollinations:",
    ]
    for m in models:
        lines.append(f"  • {m.get('name','?')} — {m.get('description','')[:50]}")
        if m.get("aliases"):
            lines.append(f"    алиасы: {', '.join(m['aliases'])}")
    lines.append("")
    lines.append("📊 Статистика AI (по слоям):")
    lines.append(f"  Запросов: {s.get('requests',0)}")
    lines.append(f"  OpenClaw: {s.get('openclaw_ok',0)}")
    lines.append(f"  Pollinations direct: {s.get('pollinations_backup',0)}")
    lines.append(f"  Static fallback: {s.get('static_fallback',0)}")
    lines.append(f"  Ошибок: {s.get('fail',0)}")
    if s.get("last_error"):
        lines.append(f"  Посл. ошибка: {s['last_error'][:80]}")
    await message.reply("\n".join(lines))


@admin_router.message(Command("diag"))
async def cmd_diag(message: Message):
    """Diagnostics: shows current chat info + what the bot actually sees.

    Useful when the bot seems silent in a group — confirms whether messages
    are arriving and whether Privacy Mode is blocking them.
    """
    if not _is_admin(message):
        return
    c = message.chat
    u = message.from_user
    info = [
        f"🔧 Диагностика:",
        f"Бот: @{config.BOT_USERNAME} (id={config.BOT_ID})",
        f"Текущий чат: id={c.id}, тип={c.type}, title={c.title or '—'}",
        f"Чат username: @{c.username}" if c.username else "Чат: без username (приватный)",
        f"Ты: {u.first_name} (id={u.id})",
        f"",
        f"Владелец: {config.OWNER_ID} (ты{' ✓' if u.id == config.OWNER_ID else ' ✗'})",
        f"Провайдеры: {config.providers_status()}",
    ]
    # Show recent group messages the bot logged in THIS chat
    try:
        recent = await db.get_recent_group_messages(c.id, limit=5)
        info.append(f"")
        info.append(f"Лог сообщений этого чата (последние {len(recent)}):")
        if not recent:
            info.append("  (пусто — бот не получил ни одного сообщения в этом чате)")
            info.append("  → Если это группа: проверь Privacy Mode у @BotFather!")
            info.append("    /mybots → бот → Bot Settings → Group Privacy → Turn OFF")
        else:
            for m in recent[-5:]:
                who = m.get("first_name") or m.get("username") or "?"
                if m.get("user_id") == config.BOT_ID:
                    who = "Василий"
                content = (m.get("content") or "")[:50]
                info.append(f"  {who}: {content}")
    except Exception as e:
        info.append(f"(лог чата недоступен: {e})")
    try:
        await message.reply("\n".join(info))
    except Exception:
        # If reply fails (e.g. bot can't post in channel), try send_message
        try:
            await message.bot.send_message(c.id, "\n".join(info))
        except Exception as e:
            logger.error(f"diag reply failed: {e}")


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
