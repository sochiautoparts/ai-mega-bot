"""
AI Mega Bot — Chat Handler.

Routes plain text messages to AI as "text" task.
Manages chat history and daily limits.
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import TIER_LIMITS
from ai.router import AllProvidersExhaustedError

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("clear"))
async def cmd_clear(message: Message) -> None:
    """Clear chat history."""
    db = message.bot.get("db")
    if db:
        await db.clear_chat_history(message.from_user.id)
    await message.answer("🗑 История чата очищена!")


@router.message(F.text, ~F.text.startswith("/"))
async def handle_chat(message: Message) -> None:
    """Handle any text message (non-command) as AI chat."""
    db = message.bot.get("db")
    ai_router = message.bot.get("ai_router")

    if not db or not ai_router:
        await message.answer("❌ Сервис временно недоступен. Попробуйте позже.")
        return

    user_id = message.from_user.id
    text = message.text

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
    daily_usage = await db.get_daily_usage(user_id, "text")
    if daily_usage >= limits.text_requests:
        if limits.text_requests >= 9999:
            pass  # Unlimited
        else:
            await message.answer(
                f"⏳ Вы достигли дневного лимита чата ({limits.text_requests}).\n"
                "Оформите подписку для увеличения лимитов: /subscribe"
            )
            return

    # Show typing indicator
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    # Get chat history
    history = []
    if limits.history_days > 0:
        history = await db.get_chat_history(
            user_id,
            limit=20,
            max_age_days=limits.history_days,
        )

    # Build messages for context
    messages = []
    if history:
        messages.extend(history)

    # Save user message
    await db.add_chat_message(user_id, "user", text)

    try:
        # Route to AI
        kwargs = {}
        if messages:
            kwargs["messages"] = messages

        result = await ai_router.route(
            task_type="text",
            prompt=text,
            user_id=user_id,
            tier=tier,
            **kwargs,
        )

        # Record usage
        await db.record_usage(
            user_id, "text", result.provider, tokens=result.tokens_used
        )

        # Save assistant message
        response_text = result.text or "⚠️ Пустой ответ от AI."
        await db.add_chat_message(
            user_id, "assistant", response_text, tokens=result.tokens_used
        )

        # Send response (truncate if too long for Telegram)
        if len(response_text) > 4096:
            # Split long messages
            for i in range(0, len(response_text), 4096):
                chunk = response_text[i:i + 4096]
                await message.answer(chunk)
        else:
            await message.answer(response_text)

    except AllProvidersExhaustedError:
        logger.error(f"All providers exhausted for text task, user={user_id}")
        await message.answer(
            "😔 Все AI-провайдеры сейчас недоступны.\n"
            "Попробуйте через пару минут."
        )
    except Exception as e:
        logger.exception(f"Chat error for user={user_id}: {e}")
        await message.answer(
            "❌ Произошла ошибка при обработке запроса.\n"
            "Попробуйте ещё раз."
        )
