"""
AI Mega Bot — Image Generation Handler.

Handles /image <prompt> command for AI image generation.
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile

from bot.config import TIER_LIMITS
from ai.router import AllProvidersExhaustedError

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("image"))
async def cmd_image(message: Message) -> None:
    """Generate image from text prompt."""
    db = message.bot.get("db")
    ai_router = message.bot.get("ai_router")

    if not db or not ai_router:
        await message.answer("❌ Сервис временно недоступен. Попробуйте позже.")
        return

    user_id = message.from_user.id

    # Extract prompt
    prompt = message.text.get_args() if hasattr(message.text, "get_args") else ""
    if not prompt:
        # Fallback: manually parse
        parts = message.text.split(maxsplit=1)
        prompt = parts[1] if len(parts) > 1 else ""

    if not prompt:
        await message.answer(
            "🎨 Укажите описание картинки:\n\n"
            "<code>/image кот в космосе, digital art</code>",
            parse_mode="HTML",
        )
        return

    # Ensure user exists
    await db.get_or_create_user(
        user_id=user_id,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name or "",
        language_code=message.from_user.language_code or "ru",
    )

    # Get tier and limits
    tier = await db.get_user_tier(user_id)
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])

    # Check daily limit
    daily_usage = await db.get_daily_usage(user_id, "image")
    if daily_usage >= limits.image_requests:
        await message.answer(
            f"⏳ Вы достигли дневного лимита генерации картинок ({limits.image_requests}).\n"
            "Оформите подписку для увеличения лимитов: /subscribe"
        )
        return

    # Show action indicator
    await message.bot.send_chat_action(chat_id=message.chat.id, action="upload_photo")

    status_msg = await message.answer("🎨 Генерирую картинку... ⏳")

    try:
        result = await ai_router.route(
            task_type="image",
            prompt=prompt,
            user_id=user_id,
            tier=tier,
        )

        # Record usage
        await db.record_usage(
            user_id, "image", result.provider, tokens=result.tokens_used
        )

        # Send image
        if result.image_bytes:
            photo = BufferedInputFile(result.image_bytes, filename="generated.png")
            await message.answer_photo(
                photo=photo,
                caption=f"🎨 <b>{prompt[:200]}</b>\n\n🤖 Провайдер: {result.provider}",
                parse_mode="HTML",
            )
        elif result.image_url:
            await message.answer_photo(
                photo=result.image_url,
                caption=f"🎨 <b>{prompt[:200]}</b>\n\n🤖 Провайдер: {result.provider}",
                parse_mode="HTML",
            )
        else:
            # Fallback: send as text
            await message.answer(
                f"🎨 Результат для: <b>{prompt[:200]}</b>\n\n"
                f"{result.text or 'Картинка сгенерирована, но не удалось её отправить.'}\n\n"
                f"🤖 Провайдер: {result.provider}",
                parse_mode="HTML",
            )

        # Delete status message
        try:
            await status_msg.delete()
        except Exception:
            pass

    except AllProvidersExhaustedError:
        logger.error(f"All providers exhausted for image task, user={user_id}")
        await status_msg.edit_text(
            "😔 Все сервисы генерации картинок недоступны.\n"
            "Попробуйте через пару минут."
        )
    except Exception as e:
        logger.exception(f"Image generation error for user={user_id}: {e}")
        try:
            await status_msg.edit_text(
                "❌ Ошибка при генерации картинки.\n"
                "Попробуйте ещё раз."
            )
        except Exception:
            await message.answer("❌ Ошибка при генерации картинки.")
