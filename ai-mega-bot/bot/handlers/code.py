"""
AI Mega Bot — Code Analysis Handler.

Handles /code <question> command for programming help.
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import TIER_LIMITS
from ai.router import AllProvidersExhaustedError

logger = logging.getLogger(__name__)
router = Router()

CODE_SYSTEM_PROMPT = (
    "You are an expert programmer. Help with code, debug, explain, and optimize. "
    "Provide clear, well-commented code examples. Use markdown code blocks with "
    "language tags. If asked to debug, identify the issue and provide the fix. "
    "If asked to optimize, explain the performance implications. "
    "Respond in the same language as the user's question."
)


@router.message(Command("code"))
async def cmd_code(message: Message, db=None, ai_router=None) -> None:
    """Help with code questions."""
    # db and ai_router are injected from workflow_data

    if not db or not ai_router:
        await message.answer("❌ Сервис временно недоступен. Попробуйте позже.")
        return

    user_id = message.from_user.id

    # Extract question
    parts = message.text.split(maxsplit=1)
    question = parts[1] if len(parts) > 1 else ""

    if not question:
        await message.answer(
            "💻 Задайте вопрос о коде:\n\n"
            "<code>/code как отсортировать список в Python</code>\n"
            "<code>/code найди ошибку: def foo(x) return x*2</code>",
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
    daily_usage = await db.get_daily_usage(user_id, "code")
    if daily_usage >= limits.code_requests:
        if limits.code_requests >= 9999:
            pass  # Unlimited
        else:
            await message.answer(
                f"⏳ Вы достигли дневного лимита запросов кода ({limits.code_requests}).\n"
                "Оформите подписку для увеличения лимитов: /subscribe"
            )
            return

    # Show typing indicator
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    # Get chat history for code context
    tier_obj = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
    history = await db.get_chat_history(user_id, limit=10, max_age_days=1)

    try:
        result = await ai_router.route(
            task_type="code",
            prompt=question,
            user_id=user_id,
            tier=tier,
            system_prompt=CODE_SYSTEM_PROMPT,
            history=history,
            skip_cache=True,
        )

        # Record usage
        await db.record_usage(
            user_id, "code", result.provider, tokens=result.tokens_used
        )

        response = result.text or "⚠️ Пустой ответ от AI."

        # Truncate very long responses
        if len(response) > 4096:
            response = response[:4090] + "\n..."

        await message.answer(
            f"💻 <b>Ответ:</b>\n\n{response}\n\n"
            f"🤖 Провайдер: {result.provider}",
            parse_mode="HTML",
        )

    except AllProvidersExhaustedError:
        logger.error(f"All providers exhausted for code task, user={user_id}")
        await message.answer(
            "😔 Все AI-провайдеры сейчас недоступны.\n"
            "Попробуйте через пару минут."
        )
    except Exception as e:
        logger.exception(f"Code analysis error for user={user_id}: {e}")
        await message.answer(
            "❌ Ошибка при обработке запроса.\n"
            "Попробуйте ещё раз."
        )
