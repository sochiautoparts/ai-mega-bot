"""
Хэндлер генерации изображений через DALL-E
"""

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import can_use_image, increment_image_usage, get_user
from services.ai_service import generate_image
from config import Config

logger = logging.getLogger(__name__)
router = Router()

# Временное хранилище ожидающих промптов
pending_image_prompts: dict[int, bool] = {}


@router.callback_query(F.data == "mode_image")
async def mode_image(callback: CallbackQuery):
    """Переключение в режим генерации картинок"""
    user_id = callback.from_user.id
    can, remaining = await can_use_image(user_id)
    user = await get_user(user_id)

    if user and user['plan'] == 'free':
        limit_text = f"Осталось сегодня: {remaining}/{Config.FREE_IMAGE_LIMIT}"
    else:
        limit_text = "Безлимит ⭐"

    text = (
        f"🎨 **Генерация изображений**\n\n"
        f"Опиши что хочешь увидеть — я нарисую!\n\n"
        f"📊 {limit_text}\n\n"
        f"💡 **Примеры запросов:**\n"
        f"• Кот-астронавт на Марсе\n"
        f"• Футуристический город на закате\n"
        f"• Логотип для IT-стартапа, минимализм\n"
        f"• Портрет девушки в стиле аниме\n\n"
        f"📐 **Размеры:**\n"
        f"• Квадрат (по умолчанию)\n"
        f"• Пейзаж — добавь слово «пейзаж»\n"
        f"• Портрет — добавь слово «вертикальный»"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Меню", callback_data="back_to_menu")],
    ])

    pending_image_prompts[user_id] = True
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


@router.message(F.text)
async def handle_image_prompt(message: Message):
    """Обработка текста как промпта для генерации картинки"""
    user_id = message.from_user.id

    if user_id not in pending_image_prompts:
        return  # Не в режиме генерации картинок — передаём дальше

    # Проверяем лимиты
    can, remaining = await can_use_image(user_id)
    if not can:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Оформить Pro", callback_data="subscribe"),
             InlineKeyboardButton(text="👥 Пригласить друга", callback_data="referral_info")],
        ])
        await message.answer(
            f"😔 Лимит бесплатных генераций исчерпан ({Config.FREE_IMAGE_LIMIT}/день).\n\n"
            f"⭐ **Pro-подписка** — безлимитная генерация!",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        return

    # Убираем из режима ожидания
    del pending_image_prompts[user_id]

    # Определяем размер
    prompt = message.text
    size = "1024x1024"
    if any(word in prompt.lower() for word in ["пейзаж", "широкий", "горизонтальный", "landscape"]):
        size = "1792x1024"
    elif any(word in prompt.lower() for word in ["вертикальный", "портрет", "телефон", "portrait"]):
        size = "1024x1792"

    # Показываем статус
    status_msg = await message.answer("🎨 Генерирую изображение... Это займёт ~15 секунд")

    # Генерируем
    image_url = await generate_image(prompt, size)

    if image_url:
        await increment_image_usage(user_id)

        # Водяной знак для бесплатных
        user = await get_user(user_id)
        caption = f"🎨 **{prompt}**"
        if user and user['plan'] == 'free':
            remaining_after = Config.FREE_IMAGE_LIMIT - user['image_used_today'] - 1
            caption += f"\n\n_💬 Осталось: {max(0, remaining_after)}/{Config.FREE_IMAGE_LIMIT} | ⭐ Pro — безлимит_"

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🎨 Ещё картинку", callback_data="mode_image"),
                InlineKeyboardButton(text="📤 Поделиться", callback_data="share_result"),
            ],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="back_to_menu")],
        ])

        # Удаляем статус и отправляем картинку
        await status_msg.delete()
        await message.answer_photo(
            photo=image_url,
            caption=caption,
            reply_markup=kb,
            parse_mode="Markdown"
        )
    else:
        await status_msg.edit_text(
            "❌ Не удалось сгенерировать изображение. Попробуй другой запрос.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="mode_image")],
                [InlineKeyboardButton(text="🔙 Меню", callback_data="back_to_menu")],
            ])
        )
