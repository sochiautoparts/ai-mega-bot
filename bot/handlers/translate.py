"""
AI Mega Bot — Translation Handler.

Handles /translate <text> command with optional target language prefix.
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import TIER_LIMITS
from ai.router import AllProvidersExhaustedError

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("translate"))
async def cmd_translate(message: Message) -> None:
    """Translate text with optional target language prefix."""
    db = message.bot.get("db")
    ai_router = message.bot.get("ai_router")

    if not db or not ai_router:
        await message.answer("❌ Сервис временно недоступен. Попробуйте позже.")
        return

    user_id = message.from_user.id

    # Extract text argument
    parts = message.text.split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""

    if not arg:
        await message.answer(
            "🌍 Укажите текст для перевода:\n\n"
            "<code>/translate Привет, мир!</code> — перевод на русский (по умолчанию)\n"
            "<code>/translate en:Привет, мир!</code> — перевод на английский\n"
            "<code>/translate de:Hello world</code> — перевод на немецкий",
            parse_mode="HTML",
        )
        return

    # Parse target language prefix (e.g., "en:text" or "ru:text")
    target_lang = "ru"  # Default
    source_lang = "auto"
    text_to_translate = arg

    if ":" in arg:
        lang_prefix, _, rest = arg.partition(":")
        # Validate language code
        supported = {
            "ru", "en", "de", "fr", "es", "it", "pt", "zh", "ja", "ko",
            "ar", "hi", "tr", "pl", "nl", "sv", "uk", "cs", "ro", "hu",
            "fi", "da", "no", "bg", "el", "he", "th", "vi", "id", "ms",
        }
        if lang_prefix.lower() in supported:
            target_lang = lang_prefix.lower()
            text_to_translate = rest.strip()
        # If not a valid language code, treat entire arg as text

    if not text_to_translate:
        await message.answer("❌ Укажите текст для перевода.")
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
    daily_usage = await db.get_daily_usage(user_id, "translate")
    if daily_usage >= limits.translations:
        if limits.translations >= 9999:
            pass  # Unlimited
        else:
            await message.answer(
                f"⏳ Вы достигли дневного лимита переводов ({limits.translations}).\n"
                "Оформите подписку для увеличения лимитов: /subscribe"
            )
            return

    # Show typing indicator
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    try:
        result = await ai_router.route(
            task_type="translate",
            prompt=text_to_translate,
            user_id=user_id,
            tier=tier,
            source_lang=source_lang,
            target_lang=target_lang,
        )

        # Record usage
        await db.record_usage(
            user_id, "translate", result.provider, tokens=result.tokens_used
        )

        lang_names = {
            "ru": "Русский", "en": "Английский", "de": "Немецкий",
            "fr": "Французский", "es": "Испанский", "it": "Итальянский",
            "pt": "Португальский", "zh": "Китайский", "ja": "Японский",
            "ko": "Корейский", "ar": "Арабский", "hi": "Хинди",
            "tr": "Турецкий", "pl": "Польский", "uk": "Украинский",
        }

        translation = result.text or "⚠️ Не удалось перевести текст."
        target_name = lang_names.get(target_lang, target_lang.upper())

        await message.answer(
            f"🌍 <b>Перевод</b> → {target_name}\n\n"
            f"<i>Исходный текст:</i>\n{text_to_translate[:500]}\n\n"
            f"<b>Результат:</b>\n{translation}\n\n"
            f"🤖 Провайдер: {result.provider}",
            parse_mode="HTML",
        )

    except AllProvidersExhaustedError:
        logger.error(f"All providers exhausted for translate, user={user_id}")
        await message.answer(
            "😔 Все сервисы перевода недоступны.\n"
            "Попробуйте через пару минут."
        )
    except Exception as e:
        logger.exception(f"Translation error for user={user_id}: {e}")
        await message.answer(
            "❌ Ошибка при переводе текста.\n"
            "Попробуйте ещё раз."
        )
