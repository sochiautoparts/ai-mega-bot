"""
Хэндлер админки — статистика, управление пользователями
"""

import time
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from database import get_stats, get_recent_users, ban_user
from config import Config

logger = logging.getLogger(__name__)
router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in Config.ADMIN_IDS


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Панель администратора"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return

    stats = await get_stats()

    # Конвертируем Stars в примерный USD (1 Star ≈ $0.01)
    revenue_usd = stats['total_revenue_stars'] * 0.01

    text = (
        f"🔧 **Админ-панель**\n\n"
        f"📊 **Статистика:**\n"
        f"  👥 Всего пользователей: {stats['total_users']}\n"
        f"  ⭐ Платных подписок: {stats['paid_users']}\n"
        f"  💬 Всего сообщений: {stats['total_messages']}\n"
        f"  🎨 Всего картинок: {stats['total_images']}\n"
        f"  ✍️ Всего текстов: {stats['total_copywrites']}\n"
        f"  👥 Рефералов: {stats['total_referrals']}\n\n"
        f"💰 **Доход:**\n"
        f"  ⭐ {stats['total_revenue_stars']} Stars (~${revenue_usd:.2f})\n\n"
        f"📈 Конверсия в платное: "
        f"{(stats['paid_users'] / max(stats['total_users'], 1) * 100):.1f}%"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Последние пользователи", callback_data="admin_recent_users")],
        [InlineKeyboardButton(text="📊 Обновить статистику", callback_data="admin_refresh")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
    ])

    await message.answer(text, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data == "admin_refresh")
async def admin_refresh(callback: CallbackQuery):
    """Обновить статистику"""
    if not is_admin(callback.from_user.id):
        return

    stats = await get_stats()
    revenue_usd = stats['total_revenue_stars'] * 0.01

    text = (
        f"📊 **Обновлённая статистика**\n\n"
        f"👥 Пользователей: {stats['total_users']}\n"
        f"⭐ Платных: {stats['paid_users']} "
        f"({stats['paid_users'] / max(stats['total_users'], 1) * 100:.1f}%)\n"
        f"💬 Сообщений: {stats['total_messages']}\n"
        f"🎨 Картинок: {stats['total_images']}\n"
        f"💰 Доход: {stats['total_revenue_stars']} ⭐ (~${revenue_usd:.2f})"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_refresh")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_recent_users")],
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data == "admin_recent_users")
async def admin_recent_users(callback: CallbackQuery):
    """Последние пользователи"""
    if not is_admin(callback.from_user.id):
        return

    users = await get_recent_users(10)
    if not users:
        await callback.answer("Пользователей пока нет")
        return

    lines = ["👥 **Последние 10 пользователей:**\n"]
    for i, u in enumerate(users, 1):
        plan_emoji = "⭐" if u['plan'] != 'free' else "🆓"
        reg_date = time.strftime("%d.%m", time.localtime(u['registered_at']))
        lines.append(
            f"{i}. {plan_emoji} {u['first_name']} (@{u['username'] or 'нет'}) "
            f"— {u['plan']} | {reg_date} | 💬{u['total_messages']} 🎨{u['total_images']}"
        )

    text = "\n".join(lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Админка", callback_data="admin_back")],
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery):
    """Начало рассылки"""
    if not is_admin(callback.from_user.id):
        return

    text = (
        "📢 **Рассылка**\n\n"
        "Отправь сообщение для рассылки всем пользователям.\n\n"
        "⚠️ Используй осторожно! Сообщение получат ВСЕ пользователи.\n\n"
        "Для отмены отправь /cancel"
    )

    await callback.message.edit_text(text, parse_mode="Markdown")


@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    """Возврат в админку"""
    if not is_admin(callback.from_user.id):
        return

    stats = await get_stats()
    revenue_usd = stats['total_revenue_stars'] * 0.01

    text = (
        f"🔧 **Админ-панель**\n\n"
        f"👥 Пользователей: {stats['total_users']}\n"
        f"⭐ Платных: {stats['paid_users']}\n"
        f"💰 Доход: {stats['total_revenue_stars']} ⭐ (~${revenue_usd:.2f})"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_recent_users")],
        [InlineKeyboardButton(text="📊 Обновить", callback_data="admin_refresh")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
