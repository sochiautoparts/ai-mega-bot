"""
AI Mega Bot — Admin Handler.

Admin-only commands: /admin, /genkey, /resetlimits, /providerstats, /broadcast.
"""
import asyncio
import logging
import secrets

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.config import ADMIN_IDS, TIER_LIMITS
from bot.keyboards import admin_kb, back_kb

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return user_id in ADMIN_IDS


# ── /admin ────────────────────────────────────────────────────
@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    """Show admin panel."""
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    await message.answer(
        "🔧 <b>Админ-панель</b>\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=admin_kb(),
    )


# ── /genkey ──────────────────────────────────────────────────
@router.message(Command("genkey"))
async def cmd_genkey(message: Message, db=None) -> None:
    """Generate a license key manually."""
    if not _is_admin(message.from_user.id):
        return

    # db is injected from workflow_data
    if not db:
        await message.answer("❌ Ошибка базы данных.")
        return

    parts = message.text.split()
    tier = parts[1] if len(parts) > 1 else "pro"
    user_id = int(parts[2]) if len(parts) > 2 else 0

    if tier not in ("pro", "ultra"):
        await message.answer("❌ Тариф должен быть: pro или ultra\n\n<code>/genkey pro [user_id]</code>", parse_mode="HTML")
        return

    key = await db.genkey(tier, user_id)
    await message.answer(
        f"✅ <b>Ключ сгенерирован</b>\n\n"
        f"📦 Тариф: {tier}\n"
        f"🔑 Ключ: <code>{key}</code>\n"
        f"👤 User ID: {user_id or 'не привязан'}",
        parse_mode="HTML",
    )
    logger.info(f"Admin generated key: {key} tier={tier} user_id={user_id}")


# ── /resetlimits ─────────────────────────────────────────────
@router.message(Command("resetlimits"))
async def cmd_resetlimits(message: Message, db=None) -> None:
    """Reset daily limits for a user."""
    if not _is_admin(message.from_user.id):
        return

    # db is injected from workflow_data
    if not db:
        await message.answer("❌ Ошибка базы данных.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Укажите user_id:\n\n<code>/resetlimits 123456789</code>", parse_mode="HTML")
        return

    try:
        target_uid = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный user_id.")
        return

    await db.reset_user_limits(target_uid)
    await message.answer(f"✅ Лимиты сброшены для user_id={target_uid}")


# ── /providerstats ───────────────────────────────────────────
@router.message(Command("providerstats"))
async def cmd_providerstats(message: Message, ai_router=None) -> None:
    """Show AI provider usage statistics."""
    if not _is_admin(message.from_user.id):
        return

    # ai_router is injected from workflow_data
    if not ai_router:
        await message.answer("❌ AI Router не инициализирован.")
        return

    status = await ai_router.get_status()
    lines = ["📊 <b>Статистика провайдеров</b>\n"]
    for name, info in status.items():
        remaining = info.get("remaining", "?")
        limit = info.get("daily_limit", "?")
        used = info.get("used_today", 0)
        lines.append(f"  • {name}: {used}/{limit} (ост. {remaining})")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ── /broadcast ───────────────────────────────────────────────
@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, db=None) -> None:
    """Broadcast message to all users."""
    if not _is_admin(message.from_user.id):
        return

    # db is injected from workflow_data
    if not db:
        await message.answer("❌ Ошибка базы данных.")
        return

    parts = message.text.split(maxsplit=1)
    text = parts[1] if len(parts) > 1 else ""

    if not text:
        await message.answer("❌ Укажите текст рассылки:\n\n<code>/broadcast Ваше сообщение</code>", parse_mode="HTML")
        return

    # Get all user IDs
    async with db._db.execute("SELECT user_id FROM users") as cur:
        user_ids = [row[0] for row in await cur.fetchall()]

    sent = 0
    failed = 0

    status_msg = await message.answer(f"📢 Рассылка начата...\nПолучателей: {len(user_ids)}")

    for uid in user_ids:
        try:
            await message.bot.send_message(uid, f"📢 <b>Сообщение от AI Mega Bot</b>\n\n{text}", parse_mode="HTML")
            sent += 1
        except Exception as e:
            failed += 1
            logger.debug(f"Broadcast failed for user={uid}: {e}")

        # Rate limit: 30 messages per second
        if sent % 30 == 0:
            await asyncio.sleep(1)

    await status_msg.edit_text(
        f"📢 <b>Рассылка завершена</b>\n\n"
        f"✅ Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n"
        f"👥 Всего: {len(user_ids)}",
        parse_mode="HTML",
    )


# ── Admin callbacks ──────────────────────────────────────────
@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: CallbackQuery, db=None) -> None:
    """Show full admin statistics."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    # db is injected from workflow_data
    if not db:
        await callback.message.edit_text("❌ Ошибка базы данных.")
        return

    stats = await db.get_all_stats()
    tier_dist = stats.get("tier_distribution", {})

    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: <b>{stats.get('total_users', 0)}</b>\n"
        f"💰 Платящих: <b>{stats.get('paying_users', 0)}</b>\n"
        f"⭐ Общая выручка: <b>{stats.get('total_revenue_stars', 0)} ★</b>\n\n"
        "📦 <b>Распределение тарифов:</b>\n"
    )
    for tier, count in tier_dist.items():
        tier_name = {"free": "🆓 Free", "pro": "⭐ Pro", "ultra": "💎 Ultra"}.get(tier, tier)
        text += f"  • {tier_name}: {count}\n"

    usage = stats.get("usage_today", {})
    if usage:
        text += "\n📈 <b>Использование сегодня:</b>\n"
        for task, data in usage.items():
            text += f"  • {task}: {data.get('requests', 0)} запр., {data.get('tokens', 0)} токенов\n"

    provider_stats = stats.get("provider_stats", {})
    if provider_stats:
        text += "\n🤖 <b>Провайдеры сегодня:</b>\n"
        for prov, data in provider_stats.items():
            text += f"  • {prov}: {data.get('used_today', 0)} запр.\n"

    await callback.answer()
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb())


@router.callback_query(F.data == "admin:genkey")
async def cb_admin_genkey(callback: CallbackQuery) -> None:
    """Admin genkey prompt."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        "🔑 <b>Генерация ключа</b>\n\n"
        "Используйте команду:\n"
        "<code>/genkey pro</code> — ключ Pro\n"
        "<code>/genkey ultra 123456789</code> — ключ Ultra для пользователя",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )


@router.callback_query(F.data == "admin:providers")
async def cb_admin_providers(callback: CallbackQuery, ai_router=None) -> None:
    """Show provider statistics."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    # ai_router is injected from workflow_data
    if not ai_router:
        await callback.message.edit_text("❌ AI Router не инициализирован.")
        return

    status = await ai_router.get_status()
    lines = ["🤖 <b>Статистика провайдеров</b>\n"]
    for name, info in status.items():
        remaining = info.get("remaining", "?")
        limit = info.get("daily_limit", "?")
        used = info.get("used_today", 0)
        pct = (used / limit * 100) if isinstance(limit, (int, float)) and limit > 0 else 0
        lines.append(f"  • <b>{name}</b>: {used}/{limit} ({pct:.0f}%) — ост. {remaining}")

    await callback.answer()
    await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=back_kb())


@router.callback_query(F.data == "admin:broadcast")
async def cb_admin_broadcast(callback: CallbackQuery) -> None:
    """Broadcast prompt."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\n"
        "Используйте команду:\n"
        "<code>/broadcast Текст сообщения</code>",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )
