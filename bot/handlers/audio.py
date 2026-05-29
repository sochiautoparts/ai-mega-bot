"""
AI Mega Bot — Audio Handler.

Handles /transcribe (voice messages), /tts (text-to-speech, Pro+).
"""
import io
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile, Voice, Audio

from bot.config import TIER_LIMITS
from ai.router import AllProvidersExhaustedError

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("transcribe"))
async def cmd_transcribe(message: Message) -> None:
    """Prompt user to send a voice/audio message."""
    await message.answer(
        "🎤 Отправьте голосовое или аудио сообщение для транскрипции.\n\n"
        "Поддерживаемые форматы: голосовые сообщения Telegram, аудиофайлы."
    )


@router.message(F.voice | F.audio)
async def handle_voice(message: Message) -> None:
    """Transcribe voice/audio messages."""
    db = message.bot.get("db")
    ai_router = message.bot.get("ai_router")

    if not db or not ai_router:
        await message.answer("❌ Сервис временно недоступен. Попробуйте позже.")
        return

    user_id = message.from_user.id

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
    daily_usage = await db.get_daily_usage(user_id, "audio_stt")
    if daily_usage >= limits.audio_transcriptions:
        await message.answer(
            f"⏳ Вы достигли дневного лимита транскрипции ({limits.audio_transcriptions}).\n"
            "Оформите подписку для увеличения лимитов: /subscribe"
        )
        return

    # Show action indicator
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    status_msg = await message.answer("🎤 Обрабатываю аудио... ⏳")

    try:
        # Get the file
        if message.voice:
            file_id = message.voice.file_id
        elif message.audio:
            file_id = message.audio.file_id
        else:
            await status_msg.edit_text("❌ Неподдерживаемый формат аудио.")
            return

        file = await message.bot.get_file(file_id)

        # Download file
        audio_bytes = io.BytesIO()
        await message.bot.download_file(file_path=file.file_path, destination=audio_bytes)
        audio_data = audio_bytes.getvalue()

        if not audio_data:
            await status_msg.edit_text("❌ Не удалось загрузить аудио.")
            return

        # Route to AI
        result = await ai_router.route(
            task_type="audio_stt",
            prompt="",
            user_id=user_id,
            tier=tier,
            audio_data=audio_data,
        )

        # Record usage
        await db.record_usage(
            user_id, "audio_stt", result.provider, tokens=result.tokens_used
        )

        transcription = result.text or "⚠️ Не удалось распознать речь."

        await status_msg.edit_text(
            f"📝 <b>Транскрипция:</b>\n\n{transcription}\n\n"
            f"🤖 Провайдер: {result.provider}",
            parse_mode="HTML",
        )

    except AllProvidersExhaustedError:
        logger.error(f"All providers exhausted for audio_stt, user={user_id}")
        await status_msg.edit_text(
            "😔 Все сервисы транскрипции недоступны.\n"
            "Попробуйте через пару минут."
        )
    except Exception as e:
        logger.exception(f"Audio transcription error for user={user_id}: {e}")
        try:
            await status_msg.edit_text(
                "❌ Ошибка при обработке аудио.\n"
                "Попробуйте ещё раз."
            )
        except Exception:
            await message.answer("❌ Ошибка при обработке аудио.")


@router.message(Command("tts"))
async def cmd_tts(message: Message) -> None:
    """Text-to-speech (Pro+ only)."""
    db = message.bot.get("db")
    ai_router = message.bot.get("ai_router")

    if not db or not ai_router:
        await message.answer("❌ Сервис временно недоступен. Попробуйте позже.")
        return

    user_id = message.from_user.id

    # Check tier (Pro+ only — enforced by middleware too)
    tier = await db.get_user_tier(user_id)
    if tier == "free":
        await message.answer(
            "⭐ Функция TTS (текст в речь) доступна только на Pro подписке.\n"
            "Оформите подписку: /subscribe"
        )
        return

    # Extract text
    parts = message.text.split(maxsplit=1)
    text = parts[1] if len(parts) > 1 else ""

    if not text:
        await message.answer(
            "🎤 Укажите текст для озвучки:\n\n"
            "<code>/tts Привет! Это тестовое сообщение.</code>",
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

    limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])

    # Check daily limit (reuse audio_transcriptions for TTS)
    daily_usage = await db.get_daily_usage(user_id, "audio_tts")
    tts_limit = limits.audio_transcriptions  # Same limit pool
    if daily_usage >= tts_limit:
        await message.answer(
            f"⏳ Вы достигли дневного лимита TTS ({tts_limit}).\n"
            "Подождите до следующего дня."
        )
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action="upload_audio")
    status_msg = await message.answer("🎤 Генерирую речь... ⏳")

    try:
        result = await ai_router.route(
            task_type="audio_tts",
            prompt=text,
            user_id=user_id,
            tier=tier,
        )

        # Record usage
        await db.record_usage(
            user_id, "audio_tts", result.provider, tokens=result.tokens_used
        )

        # Send audio result
        if result.audio_bytes:
            audio_file = BufferedInputFile(result.audio_bytes, filename="tts_output.ogg")
            await message.answer_audio(
                audio=audio_file,
                caption=f"🎤 TTS\n🤖 Провайдер: {result.provider}",
            )
        elif result.text:
            # Some providers might return a URL or different format
            await message.answer(
                f"🎤 Результат TTS:\n\n{result.text}\n\n"
                f"🤖 Провайдер: {result.provider}"
            )
        else:
            await message.answer("⚠️ Не удалось сгенерировать речь.")

        try:
            await status_msg.delete()
        except Exception:
            pass

    except AllProvidersExhaustedError:
        logger.error(f"All providers exhausted for audio_tts, user={user_id}")
        await status_msg.edit_text(
            "😔 Все сервисы TTS недоступны.\n"
            "Попробуйте через пару минут."
        )
    except Exception as e:
        logger.exception(f"TTS error for user={user_id}: {e}")
        try:
            await status_msg.edit_text(
                "❌ Ошибка при генерации речи.\n"
                "Попробуйте ещё раз."
            )
        except Exception:
            await message.answer("❌ Ошибка при генерации речи.")
