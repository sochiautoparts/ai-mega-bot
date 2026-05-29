"""
Хэндлер AI-копирайтинга — генерация текстов для бизнеса
"""

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import can_use_copywrite, increment_copywrite_usage, get_user
from services.ai_service import copywrite_text
from config import Config

logger = logging.getLogger(__name__)
router = Router()

# Временное хранилище состояния копирайтинга
copywrite_state: dict[int, dict] = {}


@router.callback_query(F.data == "mode_copywrite")
async def mode_copywrite(callback: CallbackQuery):
    """Меню копирайтинга — выбор типа текста"""
    user_id = callback.from_user.id
    can, remaining = await can_use_copywrite(user_id)
    user = await get_user(user_id)

    if user and user['plan'] == 'free':
        limit_text = f"Осталось сегодня: {remaining}/{Config.FREE_COPYWRITE_LIMIT}"
    else:
        limit_text = "Безлимит ⭐"

    text = (
        f"✍️ **AI-Копирайтер**\n\n"
        f"Выбери тип текста, который нужен:\n\n"
        f"📊 {limit_text}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Пост для соцсетей", callback_data="copy_post"),
         InlineKeyboardButton(text="📧 Email-рассылка", callback_data="copy_email")],
        [InlineKeyboardButton(text="🎯 Рекламный текст", callback_data="copy_ad"),
         InlineKeyboardButton(text="🔍 SEO-статья", callback_data="copy_seo")],
        [InlineKeyboardButton(text="🛒 Описание товара", callback_data="copy_product")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="back_to_menu")],
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("copy_"))
async def copywrite_select_type(callback: CallbackQuery):
    """Выбор типа копирайтинга"""
    user_id = callback.from_user.id
    task_type = callback.data.replace("copy_", "")

    task_names = {
        "post": "📱 Пост для соцсетей",
        "email": "📧 Email-рассылка",
        "ad": "🎯 Рекламный текст",
        "seo": "🔍 SEO-статья",
        "product": "🛒 Описание товара",
    }

    copywrite_state[user_id] = {"task": task_type}

    text = (
        f"{task_names.get(task_type, '✍️ Текст')}\n\n"
        f"📝 **Опиши тему или что нужно написать:**\n\n"
        f"💡 Например:\n"
        f"• «Пост о запуске нового курса по Python»\n"
        f"• «Реклама доставки еды для офиса»\n"
        f"• «Описание беспроводных наушников на маркетплейс»"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К типам текстов", callback_data="mode_copywrite")],
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


@router.message(F.text)
async def handle_copywrite_prompt(message: Message):
    """Обработка промпта для копирайтинга"""
    user_id = message.from_user.id

    if user_id not in copywrite_state:
        return  # Не в режиме копирайтинга

    state = copywrite_state.pop(user_id)
    task = state.get("task", "post")

    # Проверяем лимиты
    can, remaining = await can_use_copywrite(user_id)
    if not can:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Оформить Pro", callback_data="subscribe")],
        ])
        await message.answer(
            f"😔 Лимит бесплатных текстов исчерпан ({Config.FREE_COPYWRITE_LIMIT}/день).\n"
            f"⭐ Pro — безлимитный копирайтинг!",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        return

    # Показываем статус
    status_msg = await message.answer("✍️ Пишу текст... ~10 секунд")

    # Генерируем
    result = await copywrite_text(
        task=task,
        topic=message.text,
        tone="профессиональный",
        length="средний"
    )

    await increment_copywrite_usage(user_id)

    # Добавляем водяной знак
    user = await get_user(user_id)
    if user and user['plan'] == 'free':
        remaining_after = Config.FREE_COPYWRITE_LIMIT - user['copy_used_today'] - 1
        result += f"\n\n_💬 Осталось: {max(0, remaining_after)}/{Config.FREE_COPYWRITE_LIMIT} | ⭐ Pro — безлимит_"

    # Удаляем статус
    await status_msg.delete()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✍️ Ещё текст", callback_data="mode_copywrite"),
            InlineKeyboardButton(text="📤 Поделиться", callback_data="share_result"),
        ],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="back_to_menu")],
    ])

    # Разбиваем если длинный
    if len(result) > 4096:
        parts = [result[i:i+4096] for i in range(0, len(result), 4096)]
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                await message.answer(part, reply_markup=kb, parse_mode="Markdown")
            else:
                await message.answer(part, parse_mode="Markdown")
    else:
        await message.answer(result, reply_markup=kb, parse_mode="Markdown")
