"""
AI Mega Bot — Main Entry Point.

Runs Telegram bot (aiogram 3.x) + Flask API server concurrently.
Designed for 24/7 operation via GitHub Actions.
"""
import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

# ── Logging Setup ────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO"), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ai-mega-bot")

# ── Import Config ────────────────────────────────────────────
from bot.config import (
    BOT_TOKEN, ADMIN_IDS, API_HOST, API_PORT, DB_PATH,
    SESSION_DURATION_SECONDS, GH_REPO, validate_config, OWNER_ID,
)

# Validate required config
missing = validate_config()
if missing:
    logger.critical(f"Missing required config: {', '.join(missing)}")
    logger.critical("Set environment variables before starting the bot.")
    sys.exit(1)

# ── Imports ──────────────────────────────────────────────────
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from bot.database import Database
from bot.handlers import all_routers
from bot.middleware import (
    ErrorHandlingMiddleware,
    TierCheckMiddleware,
    LoggingMiddleware,
    RateLimitMiddleware,
)
from ai.router import AIRouter


# ── Global instances ─────────────────────────────────────────
db: Database = None
ai_router: AIRouter = None
bot: Bot = None
dp: Dispatcher = None
_start_time: float = 0


async def on_startup(**kwargs) -> None:
    """Initialize all resources on bot startup."""
    global db, ai_router, _start_time, bot
    _start_time = time.time()

    logger.info("=== AI Mega Bot Starting ===")

    # Initialize database
    db = Database(DB_PATH)
    await db.init()
    logger.info("Database initialized")

    # Initialize AI Router
    ai_router = AIRouter(db)
    await ai_router.init()
    logger.info(f"AI Router initialized with {len(ai_router.providers)} providers")

    # Ensure owner has permanent Ultra license
    try:
        owner_tier = await db.get_user_tier(OWNER_ID)
        if owner_tier != "ultra":
            # Create or ensure owner user
            await db.get_or_create_user(
                user_id=OWNER_ID,
                username="owner",
                first_name="Owner",
                language_code="ru",
            )
            # Check if owner already has an ultra license
            license_info = await db.check_user_license(OWNER_ID)
            if not license_info.get("has_license") or license_info.get("plan") != "ultra":
                license_key = await db.create_license(OWNER_ID, "ultra", duration_days=0)  # 0 = forever
                logger.info(f"Owner Ultra license created: {license_key}")
            else:
                logger.info(f"Owner already has active Ultra license")
    except Exception as e:
        logger.error(f"Failed to set up owner license: {e}")

    # Store in dispatcher workflow_data for handler access
    # In aiogram 3.x, workflow_data is passed to handlers as kwargs
    dp_ref = kwargs.get("dispatcher")
    if dp_ref:
        dp_ref.workflow_data["db"] = db
        dp_ref.workflow_data["ai_router"] = ai_router
        dp_ref.workflow_data["start_time"] = _start_time

    # Also store on bot object via setattr (for easy handler access)
    if bot:
        setattr(bot, "_db", db)
        setattr(bot, "_ai_router", ai_router)

    # Send startup notification to admins
    if bot:
        for admin_id in ADMIN_IDS:
            if admin_id:
                try:
                    provider_list = ", ".join(ai_router.providers.keys())
                    await bot.send_message(
                        admin_id,
                        f"🟢 <b>AI Mega Bot запущен</b>\n\n"
                        f"🤖 Провайдеров: {len(ai_router.providers)} ({provider_list})\n"
                        f"📊 БД: {DB_PATH}\n"
                        f"⏱ Сессия: {SESSION_DURATION_SECONDS // 60} мин\n"
                        f"👤 Владелец: Ultra (навсегда)",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning(f"Failed to notify admin {admin_id}: {e}")

    logger.info("=== AI Mega Bot Ready ===")


async def on_shutdown(**kwargs) -> None:
    """Cleanup on shutdown."""
    global db, ai_router

    logger.info("=== AI Mega Bot Shutting Down ===")

    # Notify admins
    if bot:
        for admin_id in ADMIN_IDS:
            if admin_id:
                try:
                    uptime = int(time.time() - _start_time) if _start_time else 0
                    hours, remainder = divmod(uptime, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    await bot.send_message(
                        admin_id,
                        f"🔴 <b>AI Mega Bot остановлен</b>\n\n"
                        f"⏱ Uptime: {hours}ч {minutes}м {seconds}с",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

    # Export data
    if db:
        try:
            licenses = await db.export_licenses()
            stats = await db.export_stats()

            data_dir = Path("data")
            data_dir.mkdir(exist_ok=True)

            with open(data_dir / "licenses.json", "w", encoding="utf-8") as f:
                json.dump(licenses, f, ensure_ascii=False, indent=2)

            with open(data_dir / "stats.json", "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)

            logger.info("Data exported successfully")
        except Exception as e:
            logger.error(f"Failed to export data: {e}")

    # Close AI providers
    if ai_router:
        await ai_router.close()

    # Close database
    if db:
        await db.close()

    logger.info("=== AI Mega Bot Stopped ===")


def setup_dispatcher() -> Dispatcher:
    """Configure dispatcher with all routers and middleware."""
    global dp

    dp = Dispatcher()

    # Register middleware (order matters: outer first)
    dp.message.middleware(RateLimitMiddleware(max_per_minute=30))
    dp.callback_query.middleware(RateLimitMiddleware(max_per_minute=30))
    dp.message.middleware(TierCheckMiddleware())
    dp.callback_query.middleware(TierCheckMiddleware())
    dp.message.middleware(LoggingMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())
    dp.message.outer_middleware(ErrorHandlingMiddleware())
    dp.callback_query.outer_middleware(ErrorHandlingMiddleware())

    # Register all routers
    for router in all_routers:
        dp.include_router(router)

    # Register startup/shutdown
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    return dp


# ── Flask API Server ─────────────────────────────────────────
def create_flask_app():
    """Create Flask API server for license verification."""
    from flask import Flask, jsonify, request

    app = Flask(__name__)

    @app.route("/api/v1/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "ok", "bot": "ai-mega-bot", "version": "1.0.0"})

    @app.route("/api/v1/check-license", methods=["POST"])
    def check_license():
        """Check if a license key is valid."""
        from bot.config import API_SECRET

        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {API_SECRET}":
            return jsonify({"error": "unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        key = data.get("key", "")

        if not key:
            return jsonify({"error": "key is required"}), 400

        # Check in licenses.json (works even when bot is down)
        try:
            with open("data/licenses.json", "r") as f:
                licenses = json.load(f)
            for lic in licenses:
                if lic["key"] == key and lic.get("active", True):
                    now = time.time()
                    if lic.get("expires_at", 0) == 0 or lic["expires_at"] > now:
                        return jsonify({
                            "valid": True,
                            "plan": lic["plan"],
                            "expires_at": lic["expires_at"],
                        })
            return jsonify({"valid": False, "reason": "not_found_or_expired"})
        except FileNotFoundError:
            return jsonify({"valid": False, "reason": "no_license_data"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/v1/stats", methods=["GET"])
    def get_stats():
        """Get public bot statistics."""
        try:
            with open("data/stats.json", "r") as f:
                stats = json.load(f)
            return jsonify(stats)
        except FileNotFoundError:
            return jsonify({"error": "stats not available"}), 404

    @app.route("/api/v1/providers", methods=["GET"])
    def get_providers():
        """Get provider status (admin only)."""
        from bot.config import API_SECRET

        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {API_SECRET}":
            return jsonify({"error": "unauthorized"}), 401

        # Return cached provider info
        return jsonify({"providers": "use /providerstats in bot"})

    return app


def run_flask():
    """Run Flask API server in a separate thread."""
    app = create_flask_app()
    app.run(host=API_HOST, port=API_PORT, threaded=True, use_reloader=False)


# ── Main ─────────────────────────────────────────────────────
async def main():
    """Main entry point."""
    global bot

    # Create bot instance FIRST (needed for on_startup)
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Setup dispatcher
    dp = setup_dispatcher()

    # Start Flask in background thread
    import threading
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Flask API server started on {API_HOST}:{API_PORT}")

    # Calculate session end time
    session_end = time.time() + SESSION_DURATION_SECONDS
    logger.info(f"Session will end at {time.strftime('%H:%M:%S', time.localtime(session_end))}")

    # Start polling with session timeout
    try:
        # Schedule graceful shutdown before GitHub Actions timeout
        async def session_timeout():
            await asyncio.sleep(SESSION_DURATION_SECONDS)
            logger.info("Session duration reached, shutting down gracefully...")
            raise SystemExit(0)

        timeout_task = asyncio.create_task(session_timeout())

        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except SystemExit:
        logger.info("Bot stopped due to session timeout")
    except Exception as e:
        logger.critical(f"Bot polling error: {e}")
    finally:
        timeout_task.cancel() if 'timeout_task' in dir() else None
        await on_shutdown()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt)")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        sys.exit(1)
