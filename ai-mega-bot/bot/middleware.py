"""
AI Mega Bot — Middleware.

Error handling, logging, tier enforcement middleware.
"""
import logging
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramAPIError

from bot.config import ADMIN_IDS, TIER_LIMITS

logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseMiddleware):
    """Global error handler for all bot updates."""

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except TelegramAPIError as e:
            logger.error(f"Telegram API error: {e}")
            # Try to notify user
            try:
                if isinstance(event, Message):
                    await event.answer(
                        "⚠️ Произошла ошибка при обработке запроса. "
                        "Попробуйте ещё раз через минуту."
                    )
                elif isinstance(event, CallbackQuery):
                    await event.answer("Ошибка. Попробуйте ещё раз.", show_alert=True)
            except Exception:
                pass
        except Exception as e:
            logger.exception(f"Unhandled error: {e}")
            try:
                if isinstance(event, Message):
                    await event.answer(
                        "❌ Внутренняя ошибка. Мы уже работаем над исправлением."
                    )
                elif isinstance(event, CallbackQuery):
                    await event.answer("Внутренняя ошибка.", show_alert=True)
            except Exception:
                pass


class TierCheckMiddleware(BaseMiddleware):
    """
    Server-side tier enforcement middleware.
    Checks user's subscription tier before allowing access to Pro/Ultra features.
    This middleware CANNOT be bypassed by client-side manipulation.
    """

    # Commands that require specific tiers
    PRO_ONLY_COMMANDS = {"/tts"}
    ULTRA_ONLY_COMMANDS = set()

    # Callback patterns that require Pro+
    PRO_ONLY_CALLBACKS = {"set:model"}

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        # Get database from data
        db = data.get("db")
        if not db:
            return await handler(event, data)

        # Determine user_id
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None

        if not user_id:
            return await handler(event, data)

        # Admins bypass all checks
        if user_id in ADMIN_IDS:
            data["tier"] = "ultra"
            return await handler(event, data)

        # Get user tier
        tier = await db.get_user_tier(user_id)
        data["tier"] = tier

        # Check command restrictions
        if isinstance(event, Message) and event.text:
            cmd = event.text.split()[0].lower()
            if cmd in self.PRO_ONLY_COMMANDS and tier == "free":
                await event.answer(
                    "⭐ Эта функция доступна только на Pro подписке.\n"
                    "Оформите подписку: /subscribe"
                )
                return
            if cmd in self.ULTRA_ONLY_COMMANDS and tier != "ultra":
                await event.answer(
                    "💎 Эта функция доступна только на Ultra подписке.\n"
                    "Оформите подписку: /subscribe"
                )
                return

        # Check callback restrictions
        if isinstance(event, CallbackQuery) and event.data:
            for pattern in self.PRO_ONLY_CALLBACKS:
                if event.data.startswith(pattern) and tier == "free":
                    await event.answer(
                        "⭐ Требуется Pro подписка!", show_alert=True
                    )
                    return

        return await handler(event, data)


class LoggingMiddleware(BaseMiddleware):
    """Log all incoming updates for monitoring."""

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        start = time.time()
        user_info = ""

        if isinstance(event, Message) and event.from_user:
            user_info = f"user={event.from_user.id} ({event.from_user.username or 'no_username'})"
            if event.text:
                logger.info(f"MSG {user_info}: {event.text[:100]}")
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_info = f"user={event.from_user.id} cb={event.data}"
            logger.info(f"CB {user_info}")

        result = await handler(event, data)
        elapsed = time.time() - start
        if elapsed > 3.0:
            logger.warning(f"Slow handler: {elapsed:.2f}s for {user_info}")
        return result


class RateLimitMiddleware(BaseMiddleware):
    """Per-user rate limiting to prevent abuse."""

    def __init__(self, max_per_minute: int = 30):
        self.max_per_minute = max_per_minute
        self._user_requests: Dict[int, list] = {}

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        user_id = None
        if isinstance(event, (Message, CallbackQuery)) and event.from_user:
            user_id = event.from_user.id

        if not user_id:
            return await handler(event, data)

        now = time.time()
        if user_id not in self._user_requests:
            self._user_requests[user_id] = []

        # Clean old entries
        self._user_requests[user_id] = [
            t for t in self._user_requests[user_id] if now - t < 60
        ]

        if len(self._user_requests[user_id]) >= self.max_per_minute:
            if isinstance(event, Message):
                await event.answer("⏳ Слишком много запросов. Подождите минуту.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Слишком много запросов!", show_alert=True)
            return

        self._user_requests[user_id].append(now)
        return await handler(event, data)
