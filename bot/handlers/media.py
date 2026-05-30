"""
AI Mega Bot — Media Handler.

Handles:
  - Photo messages → Vision AI analysis
  - Video messages → Frame extraction + Vision analysis
  - Document messages → Text extraction + AI analysis
  - Video notes (кружочки) → Frame extraction + analysis
  - Stickers → Description via vision
"""
import io
import logging
import os
import tempfile
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message
from aiogram.enums import ChatAction

from bot.config import TIER_LIMITS, OWNER_ID, ADMIN_IDS
from ai.router import AllProvidersExhaustedError

logger = logging.getLogger(__name__)
router = Router()

# Maximum image size for vision API (20MB)
MAX_IMAGE_SIZE = 20 * 1024 * 1024
# Maximum video duration for analysis (60 seconds)
MAX_VIDEO_DURATION = 60
# Maximum document size for text extraction (10MB)
MAX_DOCUMENT_SIZE = 10 * 1024 * 1024
# Text file extensions we can read directly
TEXT_EXTENSIONS = {
    ".txt", ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".csv", ".md",
    ".html", ".css", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".sh", ".bash", ".zsh", ".sql", ".r", ".java", ".c", ".cpp", ".h",
    ".hpp", ".go", ".rs", ".rb", ".php", ".pl", ".lua", ".swift", ".kt",
    ".scala", ".dart", ".vue", ".svelte", ".log", ".env", ".gitignore",
    ".dockerfile", ".makefile", ".cmake", ".gradle",
}


# ── Photo Handler ──────────────────────────────────────────────

@router.message(F.photo)
async def handle_photo(message: Message, db=None, ai_router=None) -> None:
    """Handle photo messages — analyze with vision AI."""
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

    # Check daily limit (uses text quota for vision)
    if user_id not in ADMIN_IDS and user_id != OWNER_ID:
        daily_usage = await db.get_daily_usage(user_id, "text")
        if daily_usage >= limits.text_requests:
            if limits.text_requests < 9999:
                await message.answer(
                    f"⏳ Вы достигли дневного лимита ({limits.text_requests}).\n"
                    "Оформите подписку: /subscribe"
                )
                return

    # Show typing indicator
    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    status_msg = await message.answer("🖼 Анализирую изображение... ⏳")

    try:
        # Get the highest resolution photo
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)

        # Check file size
        if file.file_size and file.file_size > MAX_IMAGE_SIZE:
            await status_msg.edit_text("❌ Изображение слишком большое (макс. 20 МБ).")
            return

        # Download photo
        photo_bytes = io.BytesIO()
        await message.bot.download_file(file_path=file.file_path, destination=photo_bytes)
        image_data = photo_bytes.getvalue()

        if not image_data:
            await status_msg.edit_text("❌ Не удалось загрузить изображение.")
            return

        # Get caption or default prompt
        prompt = message.caption or "Опиши что ты видишь на этом изображении подробно."

        # Check vision providers
        vision_providers = ai_router.get_vision_providers()
        if not vision_providers:
            await status_msg.edit_text(
                "😔 Нет доступных провайдеров для анализа изображений.\n"
                "Попробуйте позже."
            )
            return

        # Route to vision AI
        result = await ai_router.route(
            task_type="vision",
            prompt=prompt,
            user_id=user_id,
            tier=tier,
            image_data=image_data,
            system_prompt=(
                "Ты — AI-ассистент с компьютерным зрением. "
                "Отвечай на том языке, на котором задаёт вопрос пользователь. "
                "Анализируй изображение подробно и точно. "
                "Если на изображении есть текст, распознай его. "
                "Если это код, объясни что он делает."
            ),
        )

        # Record usage
        await db.record_usage(user_id, "text", result.provider, tokens=result.tokens_used)

        # Save to chat history
        await db.add_chat_message(user_id, "user", f"[Фото] {prompt[:200]}")
        response_text = result.text or "⚠️ Не удалось проанализировать изображение."
        await db.add_chat_message(user_id, "assistant", response_text, tokens=result.tokens_used)

        # Send response
        if len(response_text) > 4096:
            for i in range(0, len(response_text), 4096):
                chunk = response_text[i:i + 4096]
                await message.answer(chunk)
        else:
            await message.answer(response_text)

        try:
            await status_msg.delete()
        except Exception:
            pass

    except AllProvidersExhaustedError:
        logger.error(f"All vision providers exhausted, user={user_id}")
        await status_msg.edit_text(
            "😔 Все провайдеры анализа изображений недоступны.\n"
            "Попробуйте через пару минут."
        )
    except Exception as e:
        logger.exception(f"Photo analysis error for user={user_id}: {e}")
        try:
            await status_msg.edit_text(
                "❌ Ошибка при анализе изображения.\n"
                "Попробуйте ещё раз."
            )
        except Exception:
            await message.answer("❌ Ошибка при анализе изображения.")


# ── Video Handler ──────────────────────────────────────────────

@router.message(F.video | F.video_note)
async def handle_video(message: Message, db=None, ai_router=None) -> None:
    """Handle video messages — extract frames and analyze with vision AI."""
    if not db or not ai_router:
        await message.answer("❌ Сервис временно недоступен. Попробуйте позже.")
        return

    user_id = message.from_user.id

    await db.get_or_create_user(
        user_id=user_id,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name or "",
        language_code=message.from_user.language_code or "ru",
    )

    tier = await db.get_user_tier(user_id)
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])

    if user_id not in ADMIN_IDS and user_id != OWNER_ID:
        daily_usage = await db.get_daily_usage(user_id, "text")
        if daily_usage >= limits.text_requests:
            if limits.text_requests < 9999:
                await message.answer(
                    f"⏳ Вы достигли дневного лимита ({limits.text_requests}).\n"
                    "Оформите подписку: /subscribe"
                )
                return

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    status_msg = await message.answer("🎬 Обрабатываю видео... ⏳")

    try:
        # Get video file
        if message.video:
            video = message.video
            file_id = video.file_id
            duration = video.duration or 0
        elif message.video_note:
            video = message.video_note
            file_id = video.file_id
            duration = video.duration or 0
        else:
            await status_msg.edit_text("❌ Неподдерживаемый формат видео.")
            return

        # Check duration
        if duration > MAX_VIDEO_DURATION * 3:
            await status_msg.edit_text(
                f"⚠️ Видео слишком длинное (макс. {MAX_VIDEO_DURATION * 3} сек). "
                "Будет проанализирована только часть."
            )

        file = await message.bot.get_file(file_id)

        # Download video to temp file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            await message.bot.download_file(file_path=file.file_path, destination=tmp)
            tmp_path = tmp.name

        try:
            # Extract frames using ffmpeg
            frames = _extract_video_frames(tmp_path, max_frames=3)
        finally:
            os.unlink(tmp_path)

        if not frames:
            await status_msg.edit_text("❌ Не удалось извлечь кадры из видео.")
            return

        # Check vision providers
        vision_providers = ai_router.get_vision_providers()
        if not vision_providers:
            await status_msg.edit_text(
                "😔 Нет доступных провайдеров для анализа видео.\n"
                "Попробуйте позже."
            )
            return

        # Analyze first frame (most representative)
        prompt = message.caption or "Опиши что происходит на этом видео подробно."
        if len(frames) > 1:
            prompt += f" (анализ основан на {len(frames)} кадрах из видео длительностью {duration} сек)"

        result = await ai_router.route(
            task_type="vision",
            prompt=prompt,
            user_id=user_id,
            tier=tier,
            image_data=frames[0],
            system_prompt=(
                "Ты — AI-ассистент с компьютерным зрением. "
                "Пользователь отправил видео, и ты видишь один из его кадров. "
                "Отвечай на том языке, на котором задаёт вопрос пользователь. "
                "Опиши что происходит на видео, учитывая что это движущееся изображение. "
                "Если на кадрах есть текст, распознай его."
            ),
        )

        await db.record_usage(user_id, "text", result.provider, tokens=result.tokens_used)

        await db.add_chat_message(user_id, "user", f"[Видео] {prompt[:200]}")
        response_text = result.text or "⚠️ Не удалось проанализировать видео."
        await db.add_chat_message(user_id, "assistant", response_text, tokens=result.tokens_used)

        if len(response_text) > 4096:
            for i in range(0, len(response_text), 4096):
                chunk = response_text[i:i + 4096]
                await message.answer(chunk)
        else:
            await message.answer(response_text)

        try:
            await status_msg.delete()
        except Exception:
            pass

    except AllProvidersExhaustedError:
        logger.error(f"All vision providers exhausted for video, user={user_id}")
        await status_msg.edit_text(
            "😔 Все провайдеры анализа видео недоступны.\n"
            "Попробуйте через пару минут."
        )
    except Exception as e:
        logger.exception(f"Video analysis error for user={user_id}: {e}")
        try:
            await status_msg.edit_text(
                "❌ Ошибка при обработке видео.\n"
                "Попробуйте ещё раз."
            )
        except Exception:
            await message.answer("❌ Ошибка при обработке видео.")


# ── Document Handler ───────────────────────────────────────────

@router.message(F.document)
async def handle_document(message: Message, db=None, ai_router=None) -> None:
    """Handle document messages — extract text and analyze with AI."""
    if not db or not ai_router:
        await message.answer("❌ Сервис временно недоступен. Попробуйте позже.")
        return

    user_id = message.from_user.id

    await db.get_or_create_user(
        user_id=user_id,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name or "",
        language_code=message.from_user.language_code or "ru",
    )

    tier = await db.get_user_tier(user_id)
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])

    if user_id not in ADMIN_IDS and user_id != OWNER_ID:
        daily_usage = await db.get_daily_usage(user_id, "text")
        if daily_usage >= limits.text_requests:
            if limits.text_requests < 9999:
                await message.answer(
                    f"⏳ Вы достигли дневного лимита ({limits.text_requests}).\n"
                    "Оформите подписку: /subscribe"
                )
                return

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    status_msg = await message.answer("📄 Обрабатываю документ... ⏳")

    try:
        doc = message.document

        # Check file size
        if doc.file_size and doc.file_size > MAX_DOCUMENT_SIZE:
            await status_msg.edit_text("❌ Файл слишком большой (макс. 10 МБ).")
            return

        # Check if it's an image file (treat as photo)
        file_ext = ""
        if doc.file_name:
            _, file_ext = os.path.splitext(doc.file_name.lower())

        image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}
        if file_ext in image_extensions:
            # Treat as image — download and use vision
            file = await message.bot.get_file(doc.file_id)
            doc_bytes = io.BytesIO()
            await message.bot.download_file(file_path=file.file_path, destination=doc_bytes)
            image_data = doc_bytes.getvalue()

            if not image_data:
                await status_msg.edit_text("❌ Не удалось загрузить файл.")
                return

            prompt = message.caption or "Опиши что ты видишь на этом изображении подробно."

            vision_providers = ai_router.get_vision_providers()
            if not vision_providers:
                await status_msg.edit_text("😔 Нет провайдеров для анализа изображений.")
                return

            result = await ai_router.route(
                task_type="vision",
                prompt=prompt,
                user_id=user_id,
                tier=tier,
                image_data=image_data,
                system_prompt=(
                    "Ты — AI-ассистент с компьютерным зрением. "
                    "Отвечай на том языке, на котором задаёт вопрос пользователь. "
                    "Анализируй изображение подробно и точно."
                ),
            )

        elif file_ext in TEXT_EXTENSIONS or not file_ext:
            # Text file — read content and send to AI
            file = await message.bot.get_file(doc.file_id)
            doc_bytes = io.BytesIO()
            await message.bot.download_file(file_path=file.file_path, destination=doc_bytes)
            file_content = doc_bytes.getvalue()

            if not file_content:
                await status_msg.edit_text("❌ Не удалось загрузить файл.")
                return

            # Try to decode as text
            text_content = None
            for encoding in ("utf-8", "cp1251", "latin-1", "ascii"):
                try:
                    text_content = file_content.decode(encoding)
                    break
                except (UnicodeDecodeError, ValueError):
                    continue

            if text_content is None:
                await status_msg.edit_text("❌ Не удалось прочитать содержимое файла.")
                return

            # Truncate very long files
            if len(text_content) > 30000:
                text_content = text_content[:30000] + "\n\n... [файл обрезан]"

            file_name = doc.file_name or "document"
            prompt = message.caption or f"Проанализируй содержимое файла {file_name}"
            full_prompt = f"{prompt}\n\n--- Содержимое файла {file_name} ---\n```\n{text_content}\n```"

            result = await ai_router.route(
                task_type="code" if file_ext in {".py", ".js", ".ts", ".java", ".c", ".cpp", ".go", ".rs", ".rb", ".php"} else "text",
                prompt=full_prompt,
                user_id=user_id,
                tier=tier,
                system_prompt=(
                    "Ты — AI-ассистент. Пользователь отправил файл для анализа. "
                    "Отвечай на том языке, на котором задаёт вопрос пользователь. "
                    "Проанализируй содержимое файла, ответь на вопросы, "
                    "найди ошибки или предложи улучшения."
                ),
            )

        else:
            # Unsupported file type
            await status_msg.edit_text(
                f"❌ Формат файла `{file_ext or 'неизвестный'}` не поддерживается.\n\n"
                "Поддерживаемые форматы:\n"
                "🖼 Изображения: JPG, PNG, GIF, WebP\n"
                "📄 Текстовые: TXT, PY, JS, JSON, CSV, MD, HTML и др.\n"
                "🎬 Видео: MP4, MOV (отправляйте как видео, не как файл)",
                parse_mode="Markdown",
            )
            return

        # Record usage
        await db.record_usage(user_id, "text", result.provider, tokens=result.tokens_used)

        # Save to chat history
        file_name = doc.file_name or "файл"
        await db.add_chat_message(user_id, "user", f"[Файл: {file_name}] {message.caption or ''}")
        response_text = result.text or "⚠️ Не удалось проанализировать файл."
        await db.add_chat_message(user_id, "assistant", response_text, tokens=result.tokens_used)

        # Send response
        if len(response_text) > 4096:
            for i in range(0, len(response_text), 4096):
                chunk = response_text[i:i + 4096]
                await message.answer(chunk)
        else:
            await message.answer(response_text)

        try:
            await status_msg.delete()
        except Exception:
            pass

    except AllProvidersExhaustedError:
        logger.error(f"All providers exhausted for document, user={user_id}")
        await status_msg.edit_text(
            "😔 Все AI-провайдеры недоступны.\n"
            "Попробуйте через пару минут."
        )
    except Exception as e:
        logger.exception(f"Document analysis error for user={user_id}: {e}")
        try:
            await status_msg.edit_text(
                "❌ Ошибка при обработке документа.\n"
                "Попробуйте ещё раз."
            )
        except Exception:
            await message.answer("❌ Ошибка при обработке документа.")


# ── Sticker Handler ────────────────────────────────────────────

@router.message(F.sticker)
async def handle_sticker(message: Message, db=None, ai_router=None) -> None:
    """Handle sticker messages — describe the sticker."""
    if not db or not ai_router:
        return

    # Only process if sticker has an image (not animated/video)
    if not message.sticker.is_animated and not message.sticker.is_video:
        user_id = message.from_user.id
        tier = await db.get_user_tier(user_id)

        vision_providers = ai_router.get_vision_providers()
        if not vision_providers:
            return  # Silently ignore if no vision

        try:
            # Get sticker image
            file = await message.bot.get_file(message.sticker.file_id)
            sticker_bytes = io.BytesIO()
            await message.bot.download_file(file_path=file.file_path, destination=sticker_bytes)
            image_data = sticker_bytes.getvalue()

            if not image_data:
                return

            result = await ai_router.route(
                task_type="vision",
                prompt="Опиши этот стикер коротко.",
                user_id=user_id,
                tier=tier,
                image_data=image_data,
                system_prompt="Опиши стикер в 1-2 предложениях на русском языке.",
            )

            await db.record_usage(user_id, "text", result.provider, tokens=result.tokens_used)

            if result.text:
                await message.answer(f"🏷 {result.text}")

        except Exception as e:
            logger.debug(f"Sticker analysis failed: {e}")


# ── Helper Functions ───────────────────────────────────────────

def _extract_video_frames(video_path: str, max_frames: int = 3) -> list[bytes]:
    """Extract frames from video file using ffmpeg.

    Args:
        video_path: Path to the video file
        max_frames: Maximum number of frames to extract

    Returns:
        List of JPEG image bytes
    """
    frames = []

    try:
        import subprocess

        # Get video duration first
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]
        try:
            duration_output = subprocess.run(
                probe_cmd, capture_output=True, text=True, timeout=10
            )
            duration = float(duration_output.stdout.strip() or "0")
        except (ValueError, subprocess.TimeoutExpired, FileNotFoundError):
            duration = 0

        if duration <= 0:
            # Try to extract at least one frame
            duration = 5.0

        # Calculate frame timestamps (evenly distributed)
        if max_frames == 1:
            timestamps = [min(1.0, duration / 2)]
        else:
            interval = duration / (max_frames + 1)
            timestamps = [interval * (i + 1) for i in range(max_frames)]

        for ts in timestamps:
            try:
                frame_cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(ts),
                    "-i", video_path,
                    "-vframes", "1",
                    "-q:v", "2",
                    "-f", "image2pipe",
                    "-vcodec", "mjpeg",
                    "pipe:1",
                ]
                result = subprocess.run(
                    frame_cmd, capture_output=True, timeout=15
                )
                if result.returncode == 0 and result.stdout:
                    frames.append(result.stdout)
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                logger.warning(f"Frame extraction failed at {ts}s: {e}")
                continue

    except ImportError:
        logger.warning("ffmpeg not available for frame extraction")
    except Exception as e:
        logger.error(f"Video frame extraction error: {e}")

    return frames
