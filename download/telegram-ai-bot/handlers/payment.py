"""
Хэндлер подписок и платежей через Telegram Stars
"""

import logging
import time
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, LabeledPrice, PreCheckoutQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import activate_subscription, get_user, check_and_update_plan
from config import Config

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "subscribe")
async def subscribe_menu(callback: CallbackQuery):
    """Меню подписки"""
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if not user:
        await callback.answer("Нажми /start")
        return

    user = await check_and_update_plan(user_id)
    current_plan = user['plan']

    if current_plan == 'pro' and user['plan_expires_at'] > time.time():
        days_left = int((user['plan_expires_at'] - time.time()) / 86400)
        text = (
            f"⭐ **У тебя уже Pro!**\n\n"
            f"Осталось: **{days_left} дн.**\n\n"
            f"Можешь продлить заранее — время приплюсуется."
        )
    else:
        text = (
            f"⭐ **Pro-подписка**\n\n"
            f"🔓 Снимаем все лимиты:\n"
            f"  💬 Безлимитный чат с AI\n"
            f"  🎨 Безлимитная генерация картинок\n"
            f"  ✍️ Безлимитный копирайтинг\n"
            f"  🚀 Приоритетные ответы\n"
            f"  💎 Ранний доступ к новым функциям\n\n"
            f"🆓 Сейчас: {Config.FREE_CHAT_LIMIT} чат / {Config.FREE_IMAGE_LIMIT} картинки / {Config.FREE_COPYWRITE_LIMIT} текста в день\n"
            f"⭐ Pro: **всё безлимитно!**\n\n"
            f"💳 Оплата через Telegram Stars (безопасно, мгновенно)"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"1 месяц — {Config.PRICE_STARS_MONTH} ⭐",
            callback_data="pay_1month"
        )],
        [InlineKeyboardButton(
            text=f"3 месяца — {Config.PRICE_STARS_3MONTH} ⭐ (выгодно!)",
            callback_data="pay_3month"
        )],
        [InlineKeyboardButton(
            text=f"1 год — {Config.PRICE_STARS_YEAR} ⭐ (скидка 33%!)",
            callback_data="pay_1year"
        )],
        [InlineKeyboardButton(text="👥 Бонус: Пригласи друга", callback_data="referral_info")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="back_to_menu")],
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("pay_"))
async def process_payment(callback: CallbackQuery):
    """Обработка выбора тарифа — отправка инвойса"""
    user_id = callback.from_user.id

    plans = {
        "pay_1month": {"months": 1, "stars": Config.PRICE_STARS_MONTH, "title": "Pro — 1 месяц"},
        "pay_3month": {"months": 3, "stars": Config.PRICE_STARS_3MONTH, "title": "Pro — 3 месяца"},
        "pay_1year": {"months": 12, "stars": Config.PRICE_STARS_YEAR, "title": "Pro — 1 год"},
    }

    plan = plans.get(callback.data)
    if not plan:
        return

    await callback.bot.send_invoice(
        chat_id=user_id,
        title=plan["title"],
        description=(
            f"Безлимитный доступ к AI-ассистенту на {plan['months']} мес.\n"
            f"💬 Чат + 🎨 Картинки + ✍️ Копирайтинг"
        ),
        provider_token="",  # Пустая строка для Telegram Stars
        currency="XTR",     # XTR = Telegram Stars
        prices=[LabeledPrice(label=plan["title"], amount=plan["stars"])],
        payload=f"sub_{plan['months']}m_user{user_id}",
        start_parameter=f"sub_{plan['months']}m",
    )

    await callback.answer("Открываю оплату...")


@router.pre_checkout_query()
async def pre_checkout_query(pre_checkout_q: PreCheckoutQuery):
    """Подтверждение предчекаута"""
    await pre_checkout_q.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    """Успешная оплата"""
    user_id = message.from_user.id
    payment = message.successful_payment

    # Определяем количество месяцев из payload
    payload = payment.invoice_payload
    months = 1
    if "3m" in payload:
        months = 3
    elif "12m" in payload:
        months = 12

    # Активируем подписку
    await activate_subscription(
        user_id=user_id,
        months=months,
        payment_id=payment.telegram_payment_charge_id
    )

    text = (
        f"🎉 **Оплата прошла успешно!**\n\n"
        f"⭐ Pro-подписка активирована на {months} мес.\n\n"
        f"Теперь тебе доступны:\n"
        f"  💬 Безлимитный чат\n"
        f"  🎨 Безлимитные картинки\n"
        f"  ✍️ Безлимитный копирайтинг\n\n"
        f"Приятного использования! 🚀"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")],
    ])

    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

    # Уведомление админу
    for admin_id in Config.ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                f"💰 Новая оплата!\n"
                f"👤 Пользователь: {user_id}\n"
                f"📅 План: {months} мес.\n"
                f"⭐ Сумма: {payment.total_amount} Stars"
            )
        except Exception:
            pass
