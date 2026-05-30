"""
AI Mega Bot — Chat Handler.

Routes plain text messages to AI as "text" task.
Manages chat history and daily limits.
Supports conversation context (memory).
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import TIER_LIMITS, OWNER_ID, ADMIN_IDS
from ai.router import AllProvidersExhaustedError

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("clear"))
async def cmd_clear(message: Message, db=None) -> None:
    """Clear chat history."""
    if db:
        await db.clear_chat_history(message.from_user.id)
    await message.answer("🗑 История чата очищена! Теперь я начну диалог заново.")


@router.message(F.text, ~F.text.startswith("/"))
async def handle_chat(message: Message, db=None, ai_router=None) -> None:
    """Handle any text message (non-command) as AI chat with context memory."""
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

    # Check daily limit (owner/admins bypass)
    if user_id not in ADMIN_IDS and user_id != OWNER_ID:
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

    # Save user message FIRST (so it's in history)
    await db.add_chat_message(user_id, "user", text)

    # Get chat history (includes the message we just saved)
    # All users get context memory: Pro/Ultra get full history, Free gets session (1 hour)
    history = await db.get_chat_history(
        user_id,
        limit=30 if limits.history_days > 0 else 10,
        max_age_days=limits.history_days if limits.history_days > 0 else 0,
    )

    # Build system prompt for context
    system_prompt = (
        "Ты — AI Mega Bot, дружелюбный и умный AI-ассистент. "
        "Отвечай на том языке, на котором задаёт вопрос пользователь. "
        "Будь полезным, точным и лаконичным. "
        "Помни контекст предыдущих сообщений в этом разговоре. "
        "Если пользователь ссылается на что-то из предыдущих сообщений, используй этот контекст."
    )

    try:
        # Route to AI with conversation history
        result = await ai_router.route(
            task_type="text",
            prompt=text,
            user_id=user_id,
            tier=tier,
            system_prompt=system_prompt,
            history=history,  # <-- KEY FIX: pass history for context
            skip_cache=True,  # Never cache chat — context changes each time
        )

        # Record usage
        await db.record_usage(
            user_id, "text", result.provider, tokens=result.tokens_used
        )

        # Save assistant message to history
        response_text = result.text or "⚠️ Пустой ответ от AI."
        await db.add_chat_message(
            user_id, "assistant", response_text, tokens=result.tokens_used
        )

        # Send response (truncate if too long for Telegram)
        if len(response_text) > 4096:
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
