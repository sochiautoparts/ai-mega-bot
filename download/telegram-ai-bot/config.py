"""
Конфигурация AI-бота для Telegram
Все настройки через переменные окружения (.env файл)
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # === Telegram ===
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    # === OpenAI ===
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_IMAGE_MODEL: str = os.getenv("OPENAI_IMAGE_MODEL", "dall-e-3")

    # === Лимиты бесплатного плана ===
    FREE_CHAT_LIMIT: int = int(os.getenv("FREE_CHAT_LIMIT", "5"))       # сообщений в день
    FREE_IMAGE_LIMIT: int = int(os.getenv("FREE_IMAGE_LIMIT", "2"))     # картинок в день
    FREE_COPYWRITE_LIMIT: int = int(os.getenv("FREE_COPYWRITE_LIMIT", "3"))  # текстов в день
    TRIAL_PRO_DAYS: int = int(os.getenv("TRIAL_PRO_DAYS", "3"))         # дней Pro при регистрации

    # === Цены подписки (в Telegram Stars) ===
    PRICE_STARS_MONTH: int = int(os.getenv("PRICE_STARS_MONTH", "250"))    # ~$2.5/мес
    PRICE_STARS_3MONTH: int = int(os.getenv("PRICE_STARS_3MONTH", "600"))  # ~$6/3мес
    PRICE_STARS_YEAR: int = int(os.getenv("PRICE_STARS_YEAR", "2000"))     # ~$20/год

    # === Реферальная система ===
    REFERRAL_BONUS_DAYS: int = int(os.getenv("REFERRAL_BONUS_DAYS", "3"))  # дней Pro за реферала

    # === Админ ===
    ADMIN_IDS: list[int] = [
        int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
    ]

    # === База данных ===
    DB_PATH: str = os.getenv("DB_PATH", "bot_database.db")

    # === Канал бота (для подписки как бонус) ===
    CHANNEL_USERNAME: str = os.getenv("CHANNEL_USERNAME", "")  # @channel_name

    @classmethod
    def validate(cls) -> list[str]:
        """Проверка обязательных настроек"""
        errors = []
        if not cls.BOT_TOKEN:
            errors.append("BOT_TOKEN не задан")
        if not cls.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY не задан")
        if not cls.ADMIN_IDS:
            errors.append("ADMIN_IDS не задан (нужен хотя бы один admin)")
        return errors
