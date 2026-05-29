"""
Хэндлер чата с AI — основной режим общения
"""

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import (
    can_use_chat, increment_chat_usage, get_user, check_and_update_plan
)
from services.ai_service import chat_completion, clear_context
from config import Config

logger = logging.getLogger(__name__)
router = Router()

# Отслеживание активного режима пользователя
user_modes: dict[int, str] = {}


@router.callback_query(F.data == "mode_chat")
async def mode_chat(callback: CallbackQuery):
    """Переключение в режим чата"""
    user_id = callback.from_user.id
    user_modes[user_id] = "chat"

    can, remaining = await can_use_chat(user_id)
    user = await get_user(user_id)

    if user and user['plan'] == 'free':
        limit_text = f"Осталось сегодня: {remaining}/{Config.FREE_CHAT_LIMIT}"
    else:
        limit_text = "Безлимит ⭐"

    text = (
        f"💬 **Режим чата с AI**\n\n"
        f"Просто напиши сообщение — я отвечу!\n"
        f"Я помню контекст нашего диалога.\n\n"
        f"📊 {limit_text}\n\n"
        f"💡 **Подсказки:**\n"
        f"• Задавай вопросы на любом языке\n"
        f"• Проси написать код, текст, решение задачи\n"
        f"• /clear — очистить контекст диалога\n"
        f"• /menu — вернуться в меню"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Очистить контекст", callback_data="clear_context")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="back_to_menu")],
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


@router.message(F.text == "/clear")
async def cmd_clear(message: Message):
    """Очистить контекст диалога"""
    user_id = message.from_user.id
    clear_context(user_id)
    await message.answer("🗑 Контекст диалога очищен. Начинаем заново!")


@router.message(F.text == "/menu")
async def cmd_menu(message: Message):
    """Вернуться в меню"""
    from handlers.start import main_menu_keyboard
    await message.answer("🏠 Главное меню:", reply_markup=main_menu_keyboard())


@router.message(F.text)
async def handle_text_message(message: Message):
    """Обработка текстовых сообщений — маршрутизация по режимам"""
    user_id = message.from_user.id
    user = await get_user(user_id)

    if not user:
        await message.answer("Нажми /start чтобы начать!")
        return

    if user.get('is_banned'):
        await message.answer("⛔ Ваш аккаунт заблокирован.")
        return

    # Определяем режим (по умолчанию — чат)
    mode = user_modes.get(user_id, "chat")

    if mode == "chat":
        await handle_chat_message(message)
    elif mode == "copywrite":
        # Если режим копирайтинга, но текст не через inline — перенаправляем
        await message.answer(
            "✍️ Для копирайтинга используй кнопку в меню.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✍️ Копирайтинг", callback_data="mode_copywrite")],
            ])
        )
    else:
        await handle_chat_message(message)


async def handle_chat_message(message: Message):
    """Обработка сообщения в режиме чата"""
    user_id = message.from_user.id

    # Проверяем лимиты
    can, remaining = await can_use_chat(user_id)
    if not can:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Оформить Pro", callback_data="subscribe"),
             InlineKeyboardButton(text="👥 Пригласить друга", callback_data="referral_info")],
        ])
        await message.answer(
            f"😔 Лимит бесплатных сообщений исчерпан ({Config.FREE_CHAT_LIMIT}/день).\n\n"
            f"⭐ **Pro-подписка** — безлимитный доступ ко всем функциям!\n"
            f"👥 Или пригласи друга и получи +{Config.REFERRAL_BONUS_DAYS} дня Pro бесплатно!",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        return

    # Показываем "печатает..."
    await message.bot.send_chat_action(user_id, "typing")

    # Получаем ответ AI
    response_text = await chat_completion(user_id, message.text)

    # Увеличиваем счётчик
    await increment_chat_usage(user_id)

    # Формируем ответ с водяным знаком для бесплатных
    user = await get_user(user_id)
    if user and user['plan'] == 'free':
        remaining_after = Config.FREE_CHAT_LIMIT - user['chat_used_today'] - 1
        watermark = f"\n\n_💬 Осталось: {max(0, remaining_after)}/{Config.FREE_CHAT_LIMIT} | ⭐ Pro — безлимит_"
        response_text += watermark

    # Кнопки действий
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 Поделиться", callback_data="share_result"),
            InlineKeyboardButton(text="⭐ Pro", callback_data="subscribe"),
        ],
    ])

    # Отправляем ответ (разбиваем если слишком длинное)
    if len(response_text) > 4096:
        parts = [response_text[i:i+4096] for i in range(0, len(response_text), 4096)]
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                await message.answer(part, reply_markup=kb, parse_mode="Markdown")
            else:
                await message.answer(part, parse_mode="Markdown")
    else:
        await message.answer(response_text, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data == "share_result")
async def share_result(callback: CallbackQuery):
    """Поделиться результатом — виральная механика"""
    bot_username = (await callback.bot.get_me()).username
    share_url = f"https://t.me/share/url?url=https://t.me/{bot_username}&text=Попробуй AI-бота! Чат, картинки, копирайтинг 🤖"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться в Telegram", url=share_url)],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")],
    ])

    await callback.message.edit_reply_markup(reply_markup=kb)


@router.callback_query(F.data == "clear_context")
async def clear_context_callback(callback: CallbackQuery):
    """Очистить контекст через кнопку"""
    user_id = callback.from_user.id
    clear_context(user_id)
    await callback.answer("🗑 Контекст очищен!")
    await mode_chat(callback)
