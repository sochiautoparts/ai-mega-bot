"""
🤖 AI-Ассистент для Telegram
Мульти-AI бот: Чат + Генерация картинок + Копирайтинг
С встроенной монетизацией через Telegram Stars

Запуск: python bot.py
"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

from config import Config
from database import init_db

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)


async def main():
    # Валидация конфигурации
    errors = Config.validate()
    if errors:
        for error in errors:
            logger.error(f"Config error: {error}")
        logger.error("Заполните .env файл! См. .env.example")
        sys.exit(1)

    # Инициализация базы данных
    await init_db()
    logger.info("Database initialized")

    # Создание бота и диспетчера
    bot = Bot(
        token=Config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="Markdown")
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Регистрация роутеров (порядок важен!)
    from handlers.start import router as start_router
    from handlers.payment import router as payment_router
    from handlers.image import router as image_router
    from handlers.copywrite import router as copywrite_router
    from handlers.chat import router as chat_router
    from handlers.admin import router as admin_router

    # Сначала специфичные хэндлеры, потом общие
    dp.include_router(start_router)       # /start, меню, профиль, рефералы
    dp.include_router(payment_router)     # Оплата и подписки
    dp.include_router(image_router)       # Генерация картинок
    dp.include_router(copywrite_router)   # Копирайтинг
    dp.include_router(chat_router)        # Чат (самый общий — последним)
    dp.include_router(admin_router)       # Админка

    logger.info("All routers registered")

    # Информация о боте
    me = await bot.get_me()
    logger.info(f"Bot started: @{me.username} ({me.first_name})")
    logger.info(f"Admin IDs: {Config.ADMIN_IDS}")
    logger.info(f"Free limits: chat={Config.FREE_CHAT_LIMIT}, "
                f"image={Config.FREE_IMAGE_LIMIT}, copy={Config.FREE_COPYWRITE_LIMIT}")
    logger.info(f"Pro prices: {Config.PRICE_STARS_MONTH}/{Config.PRICE_STARS_3MONTH}/"
                f"{Config.PRICE_STARS_YEAR} Stars")

    # Уведомление админам о запуске
    for admin_id in Config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🟢 **Бот запущен!**\n\n"
                f"🤖 @{me.username}\n"
                f"⭐ Pro: {Config.PRICE_STARS_MONTH} Stars/мес\n"
                f"🆓 Free: {Config.FREE_CHAT_LIMIT} чат, "
                f"{Config.FREE_IMAGE_LIMIT} карт, "
                f"{Config.FREE_COPYWRITE_LIMIT} текст/день\n"
                f"👥 Реферал: +{Config.REFERRAL_BONUS_DAYS} дня Pro\n"
                f"🎁 Триал: {Config.TRIAL_PRO_DAYS} дня Pro"
            )
        except Exception:
            pass

    # Запуск поллинга
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
