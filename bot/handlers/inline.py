"""
Inline query handler — users can type @aimega_bot <question> in ANY chat
(even where the bot isn't a member) and get an instant AI response.

This makes Василий universally available, not just in chats where he's added.
Requires 'Inline Mode' enabled via @BotFather (/setinline).

The bot returns up to 1 result (article type) with the AI response.
Uses the fast Pollinations path for sub-second responses.
"""

import asyncio
import logging

from aiogram import Router, F
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from aiogram.exceptions import TelegramRetryAfter

from bot.persona import SYSTEM_PROMPT
from ai import client as ai_client

logger = logging.getLogger("mega.inline")

inline_router = Router()


@inline_router.inline_query(F.query)
async def handle_inline_query(inline_query: InlineQuery):
    """Answer inline queries with an instant AI response.

    Users type: @aimega_bot <their question>
    Bot returns: an article result with the AI answer.
    """
    query = (inline_query.query or "").strip()
    if len(query) < 2:
        # Too short — return a hint
        results = [InlineQueryResultArticle(
            id="hint",
            title="Василий — задай вопрос",
            description="Напиши вопрос после @aimega_bot — отвечу сразу",
            input_message_content=InputTextMessageContent(
                message_text="Напиши вопрос после @aimega_bot 🙂"
            ),
        )]
        try:
            await inline_query.answer(results, cache_time=10)
        except Exception:
            pass
        return

    # Get AI response via fast Pollinations path
    try:
        answer = await asyncio.wait_for(
            ai_client.chat(
                query,
                system=SYSTEM_PROMPT,
                fast=True,
                max_tokens=400,
                temperature=0.9,
                allow_static_fallback=True,
            ),
            timeout=20.0,
        )
    except asyncio.TimeoutError:
        answer = "Василий задумался надолго 🙈 Попробуй ещё раз."
    except Exception as e:
        logger.debug(f"inline AI error: {e}")
        answer = "Что-то пошло не так. Попробуй переформулировать."

    if not answer:
        answer = "Не уловил мысль. Давай иначе?"

    # Truncate for inline result (Telegram limit ~4096 for message content)
    answer = answer[:3900]

    results = [
        InlineQueryResultArticle(
            id="vasiliy_answer",
            title=f"Василий: {query[:60]}",
            description=answer[:100] + ("..." if len(answer) > 100 else ""),
            input_message_content=InputTextMessageContent(
                message_text=f"❓ {query}\n\nВасилий: {answer}"
            ),
        ),
    ]

    try:
        await inline_query.answer(results, cache_time=30)
    except TelegramRetryAfter as e:
        logger.debug(f"inline RetryAfter {e.retry_after}s")
        await asyncio.sleep(e.retry_after)
        try:
            await inline_query.answer(results, cache_time=30)
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"inline answer error: {e}")
