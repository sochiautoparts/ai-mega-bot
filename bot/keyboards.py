"""
AI Mega Bot — Inline Keyboards.

All keyboards are constructed with aiogram 3.x InlineKeyboardBuilder.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    """Main menu keyboard after /start."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Чат с AI", callback_data="menu:chat")
    builder.button(text="🎨 Генерация картинок", callback_data="menu:image")
    builder.button(text="🎤 Транскрипция аудио", callback_data="menu:audio")
    builder.button(text="🌍 Перевод", callback_data="menu:translate")
    builder.button(text="💻 Помощь с кодом", callback_data="menu:code")
    builder.button(text="📋 Мои лимиты", callback_data="menu:limits")
    builder.button(text="💎 Подписка", callback_data="menu:subscribe")
    builder.button(text="⚙️ Настройки", callback_data="menu:settings")
    builder.adjust(2, 2, 2, 2)
    return builder.as_markup()


def subscribe_kb() -> InlineKeyboardMarkup:
    """Subscription selection keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Pro — 149 ★/мес", callback_data="buy:pro:month")
    builder.button(text="⭐ Pro — 999 ★/год", callback_data="buy:pro:year")
    builder.button(text="⭐ Pro — 2999 ★ навсегда", callback_data="buy:pro:lifetime")
    builder.button(text="💎 Ultra — 499 ★/мес", callback_data="buy:ultra:month")
    builder.button(text="💎 Ultra — 3499 ★/год", callback_data="buy:ultra:year")
    builder.button(text="💎 Ultra — 9999 ★ навсегда", callback_data="buy:ultra:lifetime")
    builder.button(text="🔑 Ввести ключ", callback_data="menu:activate")
    builder.button(text="◀️ Назад", callback_data="menu:back")
    builder.adjust(3, 3, 2)
    return builder.as_markup()


def tier_select_kb() -> InlineKeyboardMarkup:
    """Quick tier comparison keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🆓 Free", callback_data="info:free")
    builder.button(text="⭐ Pro", callback_data="info:pro")
    builder.button(text="💎 Ultra", callback_data="info:ultra")
    builder.button(text="💎 Оформить подписку", callback_data="menu:subscribe")
    builder.button(text="◀️ Назад", callback_data="menu:back")
    builder.adjust(3, 2)
    return builder.as_markup()


def back_kb(callback_data: str = "menu:back") -> InlineKeyboardMarkup:
    """Simple back button keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data=callback_data)
    return builder.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    """Cancel action keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="cancel")
    return builder.as_markup()


def confirm_purchase_kb(tier: str, period: str) -> InlineKeyboardMarkup:
    """Confirm purchase keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Оплатить", callback_data=f"confirm:{tier}:{period}")
    builder.button(text="❌ Отмена", callback_data="menu:subscribe")
    builder.adjust(2)
    return builder.as_markup()


def settings_kb() -> InlineKeyboardMarkup:
    """Settings menu keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🌐 Язык", callback_data="set:lang")
    builder.button(text="🤖 Модель по умолчанию", callback_data="set:model")
    builder.button(text="🗑 Очистить историю", callback_data="set:clear_history")
    builder.button(text="◀️ Назад", callback_data="menu:back")
    builder.adjust(2, 2)
    return builder.as_markup()


def language_kb() -> InlineKeyboardMarkup:
    """Language selection keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🇷🇺 Русский", callback_data="lang:ru")
    builder.button(text="🇬🇧 English", callback_data="lang:en")
    builder.button(text="◀️ Назад", callback_data="menu:settings")
    builder.adjust(2, 1)
    return builder.as_markup()


def admin_kb() -> InlineKeyboardMarkup:
    """Admin panel keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin:stats")
    builder.button(text="🔑 Генерация ключа", callback_data="admin:genkey")
    builder.button(text="📈 Провайдеры", callback_data="admin:providers")
    builder.button(text="📢 Рассылка", callback_data="admin:broadcast")
    builder.button(text="◀️ Назад", callback_data="menu:back")
    builder.adjust(2, 2, 1)
    return builder.as_markup()
