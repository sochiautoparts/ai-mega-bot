"""
AI Mega Bot — Payment Handler.

Handles Telegram Stars payments, license activation, and subscription management.
CRITICAL for monetization.

Payment flow:
1. User selects plan → buy:tier:period callback
2. Confirmation → confirm:tier:period callback → send_invoice
3. pre_checkout_query → always answer ok=True
4. successful_payment → create license, record payment, confirm to user
"""
import logging
import time

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    LabeledPrice,
    PreCheckoutQuery,
    SuccessfulPayment,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import PLANS, TIER_LIMITS, ADMIN_IDS
from bot.keyboards import (
    subscribe_kb,
    confirm_purchase_kb,
    back_kb,
    main_menu_kb,
)

logger = logging.getLogger(__name__)
router = Router()


# ── FSM States ────────────────────────────────────────────────
class LicenseActivation(StatesGroup):
    """FSM for license key activation."""
    waiting_for_key = State()


# ── Duration mapping ──────────────────────────────────────────
PERIOD_DURATION = {
    "month": 30,
    "year": 365,
    "lifetime": 0,  # 0 = never expires
}

PERIOD_NAMES = {
    "month": "1 месяц",
    "year": "1 год",
    "lifetime": "навсегда",
}

TIER_NAMES = {
    "pro": "⭐ Pro",
    "ultra": "💎 Ultra",
}


# ── /subscribe ────────────────────────────────────────────────
@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message) -> None:
    """Show subscription plans."""
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
    await message.answer(text, parse_mode="HTML", reply_markup=subscribe_kb())


# ── Buy callback (buy:tier:period) ───────────────────────────
@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(callback: CallbackQuery) -> None:
    """Handle buy:tier:period callback — show confirmation."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("❌ Неверный формат.", show_alert=True)
        return

    _, tier, period = parts

    if tier not in PLANS:
        await callback.answer("❌ Неизвестный тариф.", show_alert=True)
        return

    if period not in PERIOD_DURATION:
        await callback.answer("❌ Неизвестный период.", show_alert=True)
        return

    plan = PLANS[tier]
    price_map = {
        "month": plan.month,
        "year": plan.year,
        "lifetime": plan.lifetime,
    }
    price = price_map[period]

    tier_name = TIER_NAMES.get(tier, tier)
    period_name = PERIOD_NAMES.get(period, period)

    text = (
        f"🛒 <b>Подтверждение покупки</b>\n\n"
        f"📦 Тариф: {tier_name}\n"
        f"📅 Период: {period_name}\n"
        f"💰 Стоимость: {price.stars} ★ (Telegram Stars)\n\n"
        f"<i>{price.description}</i>\n\n"
        "Нажмите «Оплатить» для продолжения."
    )

    await callback.answer()
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=confirm_purchase_kb(tier, period),
    )


# ── Confirm purchase callback ────────────────────────────────
@router.callback_query(F.data.startswith("confirm:"))
async def cb_confirm_purchase(callback: CallbackQuery) -> None:
    """Handle confirm:tier:period callback — send invoice."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("❌ Неверный формат.", show_alert=True)
        return

    _, tier, period = parts
    user_id = callback.from_user.id

    if tier not in PLANS:
        await callback.answer("❌ Неизвестный тариф.", show_alert=True)
        return

    plan = PLANS[tier]
    price_map = {
        "month": plan.month,
        "year": plan.year,
        "lifetime": plan.lifetime,
    }
    price = price_map.get(period)
    if not price:
        await callback.answer("❌ Неизвестный период.", show_alert=True)
        return

    # Build invoice payload
    payload = f"aih:{tier}:{period}:{user_id}"

    try:
        await callback.bot.send_invoice(
            chat_id=user_id,
            title=price.label,
            description=price.description,
            payload=payload,
            currency="XTR",
            provider_token="",
            prices=[LabeledPrice(label=price.label, amount=price.stars)],
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Failed to send invoice to user={user_id}: {e}")
        await callback.answer(
            "❌ Не удалось выставить счёт. Попробуйте позже.",
            show_alert=True,
        )


# ── Pre-checkout query ────────────────────────────────────────
@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery) -> None:
    """Handle pre-checkout query — ALWAYS answer ok=True."""
    logger.info(
        f"Pre-checkout: user={pre_checkout_query.from_user.id}, "
        f"payload={pre_checkout_query.invoice_payload}"
    )
    await pre_checkout_query.answer(ok=True)


# ── Successful payment ────────────────────────────────────────
@router.message(F.successful_payment)
async def successful_payment_handler(message: Message) -> None:
    """Handle successful payment — create license and confirm."""
    payment: SuccessfulPayment = message.successful_payment
    db = message.bot.get("db")

    if not db:
        logger.error("Database not available during payment processing!")
        await message.answer(
            "✅ Оплата получена! Однако возникла ошибка при обработке.\n"
            "Свяжитесь с поддержкой."
        )
        return

    user_id = message.from_user.id
    payload = payment.invoice_payload or ""
    stars_amount = payment.total_amount
    telegram_charge_id = payment.telegram_payment_charge_id or ""

    logger.info(
        f"Successful payment: user={user_id}, stars={stars_amount}, "
        f"payload={payload}, charge_id={telegram_charge_id}"
    )

    # Parse payload: aih:tier:period:user_id
    parts = payload.split(":")
    if len(parts) != 4 or parts[0] != "aih":
        logger.error(f"Invalid payment payload: {payload}")
        await message.answer(
            "✅ Оплата получена! Свяжитесь с поддержкой для активации."
        )
        return

    _, tier, period, payload_user_id = parts

    # Security: verify user_id matches
    if str(payload_user_id) != str(user_id):
        logger.warning(
            f"Payment user_id mismatch: payload={payload_user_id}, actual={user_id}"
        )
        await message.answer(
            "✅ Оплата получена! Свяжитесь с поддержкой для активации."
        )
        return

    # Calculate duration
    duration_days = PERIOD_DURATION.get(period, 30)

    try:
        # Ensure user exists
        await db.get_or_create_user(
            user_id=user_id,
            username=message.from_user.username or "",
            first_name=message.from_user.first_name or "",
            language_code=message.from_user.language_code or "ru",
        )

        # Create license
        license_key = await db.create_license(user_id, tier, duration_days)

        # Record payment
        await db.record_payment(
            user_id=user_id,
            plan=tier,
            stars_amount=stars_amount,
            telegram_charge_id=telegram_charge_id,
            license_key=license_key,
        )

        # Process referral bonus
        user = await db.get_or_create_user(user_id)
        referred_by = user.get("referred_by")
        if referred_by:
            try:
                bonus = await db.process_referral_bonus(referred_by, user_id)
                if bonus > 0:
                    logger.info(
                        f"Referral bonus: {bonus} ★ for referrer={referred_by} "
                        f"from user={user_id}"
                    )
            except Exception as e:
                logger.error(f"Failed to process referral bonus: {e}")

        tier_name = TIER_NAMES.get(tier, tier)
        period_name = PERIOD_NAMES.get(period, period)

        text = (
            f"🎉 <b>Подписка активирована!</b>\n\n"
            f"📦 Тариф: {tier_name}\n"
            f"📅 Период: {period_name}\n"
            f"💰 Оплачено: {stars_amount} ★\n"
            f"🔑 Лицензия: <code>{license_key}</code>\n\n"
            "Приятного использования! 🚀"
        )

        await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb())

        logger.info(
            f"License created: key={license_key}, user={user_id}, "
            f"tier={tier}, period={period}"
        )

    except Exception as e:
        logger.exception(f"Error processing payment for user={user_id}: {e}")
        await message.answer(
            "✅ Оплата получена! Возникла ошибка при активации.\n"
            f"Ваш charge ID: <code>{telegram_charge_id}</code>\n"
            "Свяжитесь с поддержкой.",
            parse_mode="HTML",
        )


# ── License key activation ────────────────────────────────────
@router.message(LicenseActivation.waiting_for_key, F.text)
async def process_license_key(message: Message, state: FSMContext) -> None:
    """Process license key input from user."""
    db = message.bot.get("db")
    if not db:
        await message.answer("❌ Ошибка базы данных.")
        await state.clear()
        return

    key = message.text.strip().upper()

    # Basic format validation
    if not key.startswith("AIP-"):
        await message.answer(
            "❌ Неверный формат ключа.\n"
            "Формат: <code>AIP-XXXX-XXXX</code>\n\n"
            "Попробуйте ещё раз или нажмите «Назад».",
            parse_mode="HTML",
        )
        return

    user_id = message.from_user.id

    try:
        # Try to activate
        success = await db.activate_license(user_id, key)

        if success:
            tier = await db.get_user_tier(user_id)
            tier_name = TIER_NAMES.get(tier, tier)
            await message.answer(
                f"✅ <b>Лицензия активирована!</b>\n\n"
                f"🔑 Ключ: <code>{key}</code>\n"
                f"📦 Тариф: {tier_name}\n\n"
                "Приятного использования! 🚀",
                parse_mode="HTML",
                reply_markup=main_menu_kb(),
            )
            logger.info(f"License activated: key={key}, user={user_id}")
        else:
            await message.answer(
                "❌ Не удалось активировать лицензию.\n"
                "Возможные причины:\n"
                "• Ключ уже использован\n"
                "• Ключ не существует\n"
                "• Ключ истёк\n\n"
                "Попробуйте другой ключ или нажмите «Назад».",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.exception(f"License activation error for user={user_id}: {e}")
        await message.answer(
            "❌ Ошибка при активации лицензии.\n"
            "Попробуйте позже."
        )
    finally:
        await state.clear()


# ── Cancel activation ─────────────────────────────────────────
@router.callback_query(F.data == "cancel", LicenseActivation.waiting_for_key)
async def cb_cancel_activation(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel license key activation."""
    await state.clear()
    await callback.answer()
    text = "🔑 Активация отменена."
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=subscribe_kb())


# ── Info callbacks for tiers ──────────────────────────────────
@router.callback_query(F.data.startswith("info:"))
async def cb_info_tier(callback: CallbackQuery) -> None:
    """Show tier details (info:free, info:pro, info:ultra)."""
    tier = callback.data.split(":")[1]
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])

    tier_names = {"free": "🆓 Free", "pro": "⭐ Pro", "ultra": "💎 Ultra"}
    tier_name = tier_names.get(tier, tier)

    text = (
        f"{tier_name} — подробности:\n\n"
        f"💬 Чат: {limits.text_requests if limits.text_requests < 9999 else '∞'}/день\n"
        f"🎨 Картинки: {limits.image_requests}/день\n"
        f"🎤 Транскрипция: {limits.audio_transcriptions}/день\n"
        f"🌍 Перевод: {limits.translations if limits.translations < 9999 else '∞'}/день\n"
        f"💻 Код: {limits.code_requests if limits.code_requests < 9999 else '∞'}/день\n"
        f"📚 История: {'нет' if limits.history_days == 0 else f'{limits.history_days} дн.'}\n"
        f"⚡ Быстрые модели: {'✅' if limits.fast_models else '❌'}\n"
    )

    if tier != "free" and tier in PLANS:
        plan = PLANS[tier]
        text += (
            "\n💰 <b>Цены:</b>\n"
            f"  1 месяц — {plan.month.stars} ★\n"
            f"  1 год — {plan.year.stars} ★\n"
            f"  Навсегда — {plan.lifetime.stars} ★"
        )

    await callback.answer()
    from bot.keyboards import tier_select_kb
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=tier_select_kb())
