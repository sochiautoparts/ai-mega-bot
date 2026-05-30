"""Bot Handlers."""
from aiogram import Router
from bot.handlers.start import router as start_router
from bot.handlers.chat import router as chat_router
from bot.handlers.image import router as image_router
from bot.handlers.audio import router as audio_router
from bot.handlers.translate import router as translate_router
from bot.handlers.code import router as code_router
from bot.handlers.payment import router as payment_router
from bot.handlers.admin import router as admin_router
from bot.handlers.media import router as media_router

all_routers = [
    start_router,
    chat_router,
    image_router,
    audio_router,
    translate_router,
    code_router,
    payment_router,
    admin_router,
    media_router,
]
