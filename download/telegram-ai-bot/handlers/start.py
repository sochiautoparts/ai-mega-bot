"""
Хэндлер команды /start — регистрация + реферальная система
"""

import time
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import create_user, get_user, check_and_update_plan
from config import Config

logger = logging.getLogger(__name__)
router = Router()


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню бота"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Чат с AI", callback_data="mode_chat")],
        [InlineKeyboardButton(text="🎨 Генерация картинок", callback_data="mode_image"),
         InlineKeyboardButton(text="✍️ Копирайтинг", callback_data="mode_copywrite")],
        [InlineKeyboardButton(text="⭐ Подписка Pro", callback_data="subscribe"),
         InlineKeyboardButton(text="👥 Рефералы", callback_data="referral_info")],
        [InlineKeyboardButton(text="📊 Мой профиль", callback_data="my_profile")],
    ])


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработка /start с поддержкой реферальных ссылок"""
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""

    # Проверяем реферальный параметр
    referrer_id = 0
    if message.text and message.text.startswith("/start ref_"):
        try:
            referrer_id = int(message.text.split("ref_")[1])
        except ValueError:
            pass

    # Создаём или получаем пользователя
    user = await get_user(user_id)
    if not user:
        user = await create_user(
            user_id=user_id,
            username=username,
            first_name=first_name,
            referrer_id=referrer_id
        )
        logger.info(f"New user: {user_id} ({username}), referrer: {referrer_id}")

    # Обновляем данные
    user = await check_and_update_plan(user_id)

    # Приветственное сообщение
    plan_emoji = "⭐ Pro" if user['plan'] != 'free' else "🆓 Free"
    trial_info = ""
    if user['plan'] == 'pro' and user['plan_expires_at'] > time.time():
        days_left = int((user['plan_expires_at'] - time.time()) / 86400)
        trial_info = f"\n🕐 Pro действует ещё {days_left} дн."

    text = (
        f"👋 Привет, {first_name}!\n\n"
        f"Я — **AI-Ассистент** в Telegram. Умею:\n"
        f"💬 Отвечать на любые вопросы (ChatGPT)\n"
        f"🎨 Генерировать картинки по описанию (DALL-E)\n"
        f"✍️ Писать тексты для бизнеса (копирайтинг)\n\n"
        f"Ваш тариф: {plan_emoji}{trial_info}\n\n"
        f"🎁 **Бонус:** {Config.TRIAL_PRO_DAYS} дня Pro бесплатно при регистрации!\n"
        f"👥 Пригласи друга — получи +{Config.REFERRAL_BONUS_DAYS} дня Pro!\n\n"
        f"Выбирай, что нужно 👇"
    )

    await message.answer(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    """Возврат в главное меню"""
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if not user:
        await callback.answer("Сначала нажми /start")
        return

    user = await check_and_update_plan(user_id)
    plan_emoji = "⭐ Pro" if user['plan'] != 'free' else "🆓 Free"

    text = (
        f"🏠 **Главное меню**\n\n"
        f"Тариф: {plan_emoji}\n"
        f"Выбирай действие 👇"
    )

    await callback.message.edit_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")


@router.callback_query(F.data == "my_profile")
async def my_profile(callback: CallbackQuery):
    """Показать профиль пользователя"""
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if not user:
        await callback.answer("Сначала нажми /start")
        return

    user = await check_and_update_plan(user_id)
    plan_emoji = "⭐ Pro" if user['plan'] != 'free' else "🆓 Free"

    if user['plan'] == 'pro' and user['plan_expires_at'] > time.time():
        days_left = int((user['plan_expires_at'] - time.time()) / 86400)
        plan_info = f"Pro (осталось {days_left} дн.)"
    else:
        remaining_chat = Config.FREE_CHAT_LIMIT - user['chat_used_today']
        remaining_image = Config.FREE_IMAGE_LIMIT - user['image_used_today']
        remaining_copy = Config.FREE_COPYWRITE_LIMIT - user['copy_used_today']
        plan_info = (
            f"Free\n"
            f"  💬 Чат: {remaining_chat}/{Config.FREE_CHAT_LIMIT}\n"
            f"  🎨 Картинки: {remaining_image}/{Config.FREE_IMAGE_LIMIT}\n"
            f"  ✍️ Копирайтинг: {remaining_copy}/{Config.FREE_COPYWRITE_LIMIT}"
        )

    text = (
        f"📊 **Твой профиль**\n\n"
        f"👤 {user['first_name']} (@{user['username'] or 'нет'})\n"
        f"📋 Тариф: {plan_emoji} — {plan_info}\n"
        f"💬 Всего сообщений: {user['total_messages']}\n"
        f"🎨 Всего картинок: {user['total_images']}\n"
        f"✍️ Всего текстов: {user['total_copywrites']}\n"
        f"👥 Приглашено друзей: {user['referral_count']}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Улучшить тариф", callback_data="subscribe")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")],
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data == "referral_info")
async def referral_info(callback: CallbackQuery):
    """Информация о реферальной программе"""
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if not user:
        await callback.answer("Сначала нажми /start")
        return

    bot_username = (await callback.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    text = (
        f"👥 **Реферальная программа**\n\n"
        f"Приглашай друзей и получай бонусы!\n\n"
        f"🎁 За каждого друга: **+{Config.REFERRAL_BONUS_DAYS} дня Pro**\n"
        f"🎁 Друг тоже получает: **+{Config.TRIAL_PRO_DAYS} дня Pro** при регистрации\n\n"
        f"📎 Твоя ссылка:\n`{ref_link}`\n\n"
        f"📊 Приглашено друзей: **{user['referral_count']}**\n"
        f"💰 Заработано Pro-дней: **{user['referral_count'] * Config.REFERRAL_BONUS_DAYS}**\n\n"
        f"💡 **Совет:** Делись ссылкой в чатах, на форумах, в соцсетях!"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться ссылкой", url=f"https://t.me/share/url?url={ref_link}&text=Попробуй AI-бота в Telegram! Чат, картинки, копирайтинг 🤖")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")],
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
