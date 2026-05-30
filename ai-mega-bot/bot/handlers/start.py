"""
AI Mega Bot — Start & Menu Handlers.

Handles /start, /help, /refer, /limits, /mylicenses, /settings
and all menu:* callback queries.
"""
import logging

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.config import TIER_LIMITS, BOT_USERNAME, PLANS
from bot.keyboards import (
    main_menu_kb,
    subscribe_kb,
    tier_select_kb,
    settings_kb,
    back_kb,
)

logger = logging.getLogger(__name__)
router = Router()


# ── /start ────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db=None) -> None:
    """Handle /start with optional referral deep-link."""
    await state.clear()
    user = message.from_user
    args = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""

    # db is injected from workflow_data

    referred_by = None
    if args.startswith("REF"):
        try:
            referred_by = int(args[3:], 16) if len(args) > 3 else None
            # Alternative: lookup referral code in DB
            # For now we try to parse it; the DB handles the referral
        except (ValueError, TypeError):
            referred_by = None

    if db:
        await db.get_or_create_user(
            user_id=user.id,
            username=user.username or "",
            first_name=user.first_name or "",
            language_code=user.language_code or "ru",
            referred_by=referred_by,
        )

    welcome = (
        f"👋 Привет, {user.first_name}!\n\n"
        "🤖 <b>AI Mega Bot</b> — мультифункциональный AI-хаб:\n\n"
        "💬 <b>Чат с AI</b> — общайтесь с нейросетью\n"
        "🎨 <b>Генерация картинок</b> — создавайте изображения\n"
        "🎤 <b>Транскрипция аудио</b> — голос в текст\n"
        "🌍 <b>Перевод</b> — мгновенный перевод текста\n"
        "💻 <b>Помощь с кодом</b> — отладка и оптимизация\n\n"
        "Выберите действие в меню ниже 👇"
    )
    await message.answer(welcome, reply_markup=main_menu_kb(), parse_mode="HTML")

    if referred_by:
        logger.info(f"Referral: user={user.id} referred_by={referred_by}")


# ── /help ─────────────────────────────────────────────────────
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Show available commands."""
    text = (
        "📖 <b>Справка по командам AI Mega Bot</b>\n\n"
        "🔹 <b>Основные:</b>\n"
        "  /start — Главное меню\n"
        "  /help — Эта справка\n"
        "  /limits — Ваши лимиты\n"
        "  /settings — Настройки\n\n"
        "🔹 <b>AI функции:</b>\n"
        "  Просто напишите текст — чат с AI\n"
        "  /image &lt;описание&gt; — генерация картинки\n"
        "  /transcribe — отправьте голосовое сообщение\n"
        "  /tts &lt;текст&gt; — текст в речь (Pro+)\n"
        "  /translate &lt;текст&gt; — перевод текста\n"
        "  /code &lt;вопрос&gt; — помощь с кодом\n\n"
        "🔹 <b>Подписка:</b>\n"
        "  /subscribe — Оформить подписку\n"
        "  /mylicenses — Мои лицензии\n"
        "  /refer — Реферальная программа\n\n"
        "🔹 <b>Чат:</b>\n"
        "  /clear — Очистить историю чата"
    )
    await message.answer(text, parse_mode="HTML")


# ── /refer ────────────────────────────────────────────────────
@router.message(Command("refer"))
async def cmd_refer(message: Message, db=None) -> None:
    """Show referral link and stats."""
    # db is injected from workflow_data
    if not db:
        await message.answer("❌ Ошибка базы данных.")
        return

    user_id = message.from_user.id
    user = await db.get_or_create_user(user_id)
    ref_code = user.get("referral_code", "")
    stats = await db.get_referral_stats(user_id)

    tier = await db.get_user_tier(user_id)
    bonus = TIER_LIMITS.get(tier, TIER_LIMITS["free"]).referral_bonus

    ref_link = f"https://t.me/{BOT_USERNAME}?start={ref_code}"

    text = (
        "🔗 <b>Реферальная программа</b>\n\n"
        f"Ваша ссылка:\n<code>{ref_link}</code>\n\n"
        f"📊 Приглашено: <b>{stats['total_referrals']}</b>\n"
        f"✅ Оформили подписку: <b>{stats['converted']}</b>\n"
        f"🎁 Бонус за каждую подписку: <b>{bonus} ★</b>\n\n"
        "Отправляйте ссылку друзьям — получайте бонусы "
        "за каждую их подписку!"
    )
    await message.answer(text, parse_mode="HTML")


# ── /limits ───────────────────────────────────────────────────
@router.message(Command("limits"))
async def cmd_limits(message: Message, db=None) -> None:
    """Show current usage vs limits for user's tier."""
    # db is injected from workflow_data
    if not db:
        await message.answer("❌ Ошибка базы данных.")
        return

    user_id = message.from_user.id
    tier = await db.get_user_tier(user_id)
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
    usage = await db.get_usage_stats(user_id)

    tier_names = {"free": "🆓 Free", "pro": "⭐ Pro", "ultra": "💎 Ultra"}
    tier_name = tier_names.get(tier, tier)

    def bar(current: int, maximum: int) -> str:
        if maximum >= 9999:
            return f"{current}/∞"
        pct = min(current / maximum, 1.0) if maximum else 0
        filled = int(pct * 10)
        bar_str = "█" * filled + "░" * (10 - filled)
        return f"{current}/{maximum} [{bar_str}]"

    text = (
        f"📋 <b>Ваши лимиты</b> — {tier_name}\n\n"
        f"💬 Чат: {bar(usage.get('text', 0), limits.text_requests)}\n"
        f"🎨 Картинки: {bar(usage.get('image', 0), limits.image_requests)}\n"
        f"🎤 Транскрипция: {bar(usage.get('audio_stt', 0), limits.audio_transcriptions)}\n"
        f"🌍 Перевод: {bar(usage.get('translate', 0), limits.translations)}\n"
        f"💻 Код: {bar(usage.get('code', 0), limits.code_requests)}\n\n"
        f"📚 История: {limits.history_days} дн.\n"
        f"⚡ Быстрые модели: {'✅' if limits.fast_models else '❌'}\n"
    )

    if tier == "free":
        text += "\n💡 Оформите подписку для увеличения лимитов: /subscribe"

    await message.answer(text, parse_mode="HTML", reply_markup=tier_select_kb())


# ── /mylicenses ───────────────────────────────────────────────
@router.message(Command("mylicenses"))
async def cmd_mylicenses(message: Message, db=None) -> None:
    """Show active licenses."""
    # db is injected from workflow_data
    if not db:
        await message.answer("❌ Ошибка базы данных.")
        return

    user_id = message.from_user.id
    licenses = await db.get_user_licenses(user_id)
    license_info = await db.check_user_license(user_id)

    if not licenses:
        text = (
            "🔑 <b>Ваши лицензии</b>\n\n"
            "У вас нет активных лицензий.\n"
            "Оформите подписку: /subscribe"
        )
    else:
        lines = ["🔑 <b>Ваши лицензии</b>\n"]
        for lic in licenses:
            status = "✅" if lic["active"] else "❌"
            plan_name = {"pro": "⭐ Pro", "ultra": "💎 Ultra"}.get(lic["plan"], lic["plan"])
            expires = ""
            if lic["expires_at"] == 0:
                expires = " (навсегда)"
            elif lic["expires_at"]:
                import time
                days_left = max(0, int((lic["expires_at"] - time.time()) / 86400))
                expires = f" ({days_left} дн.)"
            lines.append(f"  {status} <code>{lic['key']}</code> — {plan_name}{expires}")

        text = "\n".join(lines)

    await message.answer(text, parse_mode="HTML")


# ── /settings ─────────────────────────────────────────────────
@router.message(Command("settings"))
async def cmd_settings(message: Message, db=None) -> None:
    """Show settings keyboard."""
    # db is injected from workflow_data
    tier = "free"
    if db:
        tier = await db.get_user_tier(message.from_user.id)

    tier_names = {"free": "🆓 Free", "pro": "⭐ Pro", "ultra": "💎 Ultra"}
    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"Текущий тариф: {tier_names.get(tier, tier)}\n\n"
        "Выберите параметр для изменения:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=settings_kb())


# ── Menu Callbacks ────────────────────────────────────────────
@router.callback_query(F.data == "menu:chat")
async def cb_menu_chat(callback: CallbackQuery) -> None:
    """Chat menu button — prompt user to type."""
    await callback.answer()
    await callback.message.edit_text(
        "💬 <b>Чат с AI</b>\n\n"
        "Просто напишите сообщение, и я отвечу!\n"
        "Контекст разговора сохраняется.\n\n"
        "Команды:\n"
        "  /clear — очистить историю\n"
        "  /limits — проверить лимиты",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )


@router.callback_query(F.data == "menu:image")
async def cb_menu_image(callback: CallbackQuery) -> None:
    """Image generation menu button."""
    await callback.answer()
    await callback.message.edit_text(
        "🎨 <b>Генерация картинок</b>\n\n"
        "Используйте команду:\n"
        "<code>/image описание картинки</code>\n\n"
        "Пример:\n"
        "<code>/image кот в космосе, digital art</code>",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )


@router.callback_query(F.data == "menu:audio")
async def cb_menu_audio(callback: CallbackQuery, db=None) -> None:
    """Audio menu button."""
    await callback.answer()
    # db is injected from workflow_data
    tier = "free"
    if db:
        tier = await db.get_user_tier(callback.from_user.id)

    tts_info = ""
    if tier in ("pro", "ultra"):
        tts_info = "\n🔹 /tts <i>текст</i> — текст в речь ✅"
    else:
        tts_info = "\n🔹 /tts — текст в речь (только Pro+)"

    await callback.message.edit_text(
        "🎤 <b>Аудио функции</b>\n\n"
        "🔹 Отправьте голосовое/аудио сообщение для транскрипции"
        f"{tts_info}",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )


@router.callback_query(F.data == "menu:translate")
async def cb_menu_translate(callback: CallbackQuery) -> None:
    """Translate menu button."""
    await callback.answer()
    await callback.message.edit_text(
        "🌍 <b>Перевод текста</b>\n\n"
        "Используйте команду:\n"
        "<code>/translate текст</code> — перевод на русский (по умолчанию)\n"
        "<code>/translate en:текст</code> — перевод на английский\n\n"
        "Поддерживаемые языки: ru, en, de, fr, es, it, pt, zh, ja, ko и др.",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )


@router.callback_query(F.data == "menu:code")
async def cb_menu_code(callback: CallbackQuery) -> None:
    """Code menu button."""
    await callback.answer()
    await callback.message.edit_text(
        "💻 <b>Помощь с кодом</b>\n\n"
        "Используйте команду:\n"
        "<code>/code ваш вопрос</code>\n\n"
        "Примеры:\n"
        "<code>/code как отсортировать список в Python</code>\n"
        "<code>/code найди ошибку в этом коде: ...</code>",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )


@router.callback_query(F.data == "menu:limits")
async def cb_menu_limits(callback: CallbackQuery, db=None) -> None:
    """Limits menu button — show limits inline."""
    await callback.answer()
    # db is injected from workflow_data
    if not db:
        await callback.message.edit_text("❌ Ошибка базы данных.")
        return

    user_id = callback.from_user.id
    tier = await db.get_user_tier(user_id)
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
    usage = await db.get_usage_stats(user_id)

    tier_names = {"free": "🆓 Free", "pro": "⭐ Pro", "ultra": "💎 Ultra"}
    tier_name = tier_names.get(tier, tier)

    def bar(current: int, maximum: int) -> str:
        if maximum >= 9999:
            return f"{current}/∞"
        pct = min(current / maximum, 1.0) if maximum else 0
        filled = int(pct * 10)
        bar_str = "█" * filled + "░" * (10 - filled)
        return f"{current}/{maximum} [{bar_str}]"

    text = (
        f"📋 <b>Ваши лимиты</b> — {tier_name}\n\n"
        f"💬 Чат: {bar(usage.get('text', 0), limits.text_requests)}\n"
        f"🎨 Картинки: {bar(usage.get('image', 0), limits.image_requests)}\n"
        f"🎤 Транскрипция: {bar(usage.get('audio_stt', 0), limits.audio_transcriptions)}\n"
        f"🌍 Перевод: {bar(usage.get('translate', 0), limits.translations)}\n"
        f"💻 Код: {bar(usage.get('code', 0), limits.code_requests)}\n\n"
        f"📚 История: {limits.history_days} дн.\n"
        f"⚡ Быстрые модели: {'✅' if limits.fast_models else '❌'}\n"
    )

    if tier == "free":
        text += "\n💡 Оформите подписку: /subscribe"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=tier_select_kb())


@router.callback_query(F.data == "menu:subscribe")
async def cb_menu_subscribe(callback: CallbackQuery) -> None:
    """Subscribe menu button."""
    await callback.answer()
    text = (
        "💎 <b>Подписка AI Mega Bot</b>\n\n"
        "⭐ <b>Pro</b> — для активных пользователей\n"
        "  • 200 чатов/день, 30 картинок, 20 аудио\n"
        "  • Быстрые модели, история 7 дней\n"
        "  • От 149 ★/мес\n\n"
        "💎 <b>Ultra</b> — без ограничений\n"
        "  • Безлимитный чат, 100 картинок, 50 аудио\n"
        "  • Все модели, история 30 дней\n"
        "  • От 499 ★/мес\n\n"
        "🔑 Также можно ввести лицензионный ключ\n\n"
        "Выберите план:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=subscribe_kb())


@router.callback_query(F.data == "menu:settings")
async def cb_menu_settings(callback: CallbackQuery, db=None) -> None:
    """Settings menu button."""
    await callback.answer()
    # db is injected from workflow_data
    tier = "free"
    if db:
        tier = await db.get_user_tier(callback.from_user.id)

    tier_names = {"free": "🆓 Free", "pro": "⭐ Pro", "ultra": "💎 Ultra"}
    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"Текущий тариф: {tier_names.get(tier, tier)}\n\n"
        "Выберите параметр для изменения:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=settings_kb())


@router.callback_query(F.data == "menu:back")
async def cb_menu_back(callback: CallbackQuery) -> None:
    """Back button — return to main menu."""
    await callback.answer()
    user = callback.from_user
    text = (
        f"👋 {user.first_name}!\n\n"
        "🤖 <b>AI Mega Bot</b> — выберите действие:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu:activate")
async def cb_menu_activate(callback: CallbackQuery, state: FSMContext) -> None:
    """Activate license key — ask for input."""
    await callback.answer()
    from bot.handlers.payment import LicenseActivation
    await state.set_state(LicenseActivation.waiting_for_key)
    await callback.message.edit_text(
        "🔑 <b>Активация лицензии</b>\n\n"
        "Введите ваш лицензионный ключ:\n"
        "<i>Формат: AIP-XXXX-XXXX</i>",
        parse_mode="HTML",
        reply_markup=back_kb("menu:subscribe"),
    )


# ── Tier info callbacks ──────────────────────────────────────
@router.callback_query(F.data == "info:free")
async def cb_info_free(callback: CallbackQuery) -> None:
    """Show Free tier details."""
    await callback.answer()
    limits = TIER_LIMITS["free"]
    text = (
        "🆓 <b>Free тариф</b>\n\n"
        f"💬 Чат: {limits.text_requests}/день\n"
        f"🎨 Картинки: {limits.image_requests}/день\n"
        f"🎤 Транскрипция: {limits.audio_transcriptions}/день\n"
        f"🌍 Перевод: {limits.translations}/день\n"
        f"💻 Код: {limits.code_requests}/день\n"
        f"📚 История: {'нет' if limits.history_days == 0 else f'{limits.history_days} дн.'}\n"
        f"⚡ Быстрые модели: {'✅' if limits.fast_models else '❌'}\n\n"
        "💡 Хотите больше? Оформите подписку!"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=tier_select_kb())


@router.callback_query(F.data == "info:pro")
async def cb_info_pro(callback: CallbackQuery) -> None:
    """Show Pro tier details."""
    await callback.answer()
    limits = TIER_LIMITS["pro"]
    plan = PLANS["pro"]
    text = (
        "⭐ <b>Pro тариф</b>\n\n"
        f"💬 Чат: {limits.text_requests}/день\n"
        f"🎨 Картинки: {limits.image_requests}/день\n"
        f"🎤 Транскрипция: {limits.audio_transcriptions}/день\n"
        f"🌍 Перевод: {limits.translations}/день\n"
        f"💻 Код: {limits.code_requests}/день\n"
        f"📚 История: {limits.history_days} дн.\n"
        f"⚡ Быстрые модели: ✅\n"
        f"🎤 TTS: ✅\n\n"
        "💰 <b>Цены:</b>\n"
        f"  1 месяц — {plan.month.stars} ★\n"
        f"  1 год — {plan.year.stars} ★ (экономия 44%)\n"
        f"  Навсегда — {plan.lifetime.stars} ★"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=tier_select_kb())


@router.callback_query(F.data == "info:ultra")
async def cb_info_ultra(callback: CallbackQuery) -> None:
    """Show Ultra tier details."""
    await callback.answer()
    limits = TIER_LIMITS["ultra"]
    plan = PLANS["ultra"]
    text = (
        "💎 <b>Ultra тариф</b>\n\n"
        f"💬 Чат: ∞\n"
        f"🎨 Картинки: {limits.image_requests}/день\n"
        f"🎤 Транскрипция: {limits.audio_transcriptions}/день\n"
        f"🌍 Перевод: ∞\n"
        f"💻 Код: ∞\n"
        f"📚 История: {limits.history_days} дн.\n"
        f"⚡ Быстрые модели: ✅\n"
        f"🎤 TTS: ✅\n\n"
        "💰 <b>Цены:</b>\n"
        f"  1 месяц — {plan.month.stars} ★\n"
        f"  1 год — {plan.year.stars} ★ (экономия 42%)\n"
        f"  Навсегда — {plan.lifetime.stars} ★"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=tier_select_kb())


# ── Settings callbacks ────────────────────────────────────────
@router.callback_query(F.data == "set:lang")
async def cb_set_lang(callback: CallbackQuery) -> None:
    """Language selection."""
    await callback.answer()
    from bot.keyboards import language_kb
    await callback.message.edit_text(
        "🌐 <b>Выберите язык:</b>",
        parse_mode="HTML",
        reply_markup=language_kb(),
    )


@router.callback_query(F.data.startswith("lang:"))
async def cb_lang_selected(callback: CallbackQuery, db=None) -> None:
    """Handle language selection."""
    lang = callback.data.split(":")[1]
    # db is injected from workflow_data
    if db:
        # Update user language
        try:
            await db._db.execute(
                "UPDATE users SET language_code = ? WHERE user_id = ?",
                (lang, callback.from_user.id),
            )
            await db._db.commit()
        except Exception as e:
            logger.error(f"Failed to update language: {e}")

    lang_names = {"ru": "Русский 🇷🇺", "en": "English 🇬🇧"}
    await callback.answer(f"Язык: {lang_names.get(lang, lang)}")
    await callback.message.edit_text(
        f"✅ Язык изменён на: <b>{lang_names.get(lang, lang)}</b>",
        parse_mode="HTML",
        reply_markup=settings_kb(),
    )


@router.callback_query(F.data == "set:model")
async def cb_set_model(callback: CallbackQuery, db=None) -> None:
    """Model selection (Pro+)."""
    # db is injected from workflow_data
    tier = "free"
    if db:
        tier = await db.get_user_tier(callback.from_user.id)

    if tier == "free":
        await callback.answer("⭐ Требуется Pro подписка!", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        "🤖 <b>Выбор модели</b>\n\n"
        "Данная функция в разработке.\n"
        "Сейчас используется оптимальная модель автоматически.",
        parse_mode="HTML",
        reply_markup=settings_kb(),
    )


@router.callback_query(F.data == "set:clear_history")
async def cb_set_clear_history(callback: CallbackQuery, db=None) -> None:
    """Clear chat history."""
    await callback.answer()
    # db is injected from workflow_data
    if db:
        await db.clear_chat_history(callback.from_user.id)

    await callback.message.edit_text(
        "🗑 История чата очищена!",
        parse_mode="HTML",
        reply_markup=settings_kb(),
    )
