"""
AI Mega Bot — Main entry point.

Architecture:
  1. Generate OpenClaw config dynamically (only providers with keys + Pollinations).
  2. Start the OpenClaw Gateway as a subprocess (OpenAI-compatible API on localhost).
  3. Wait for the gateway to be ready.
  4. Start the aiogram bot — all AI calls go through OpenClaw (/v1/chat/completions).

In GitHub Actions this whole process is wrapped in an unlimited auto-restart
loop (see .github/workflows/run-bot.yml) so the bot runs 24/7 for free.
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import config
from bot import database as db
from bot.mood import mood_loop, current_mood_descriptor
from ai import client as ai_client

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("mega.main")
for noisy in ["aiogram.event", "httpx", "httpcore", "aiosqlite"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

# ── Routers (order: admin → chat → groups → channels) ───────────────────────
from bot.handlers.chat import chat_router
from bot.handlers.groups import group_router
from bot.handlers.channels import channel_router
from bot.handlers.admin import admin_router
from bot.handlers.inline import inline_router

OPENCLAW_STATE_DIR = os.getenv("OPENCLAW_STATE_DIR", str(Path.cwd() / ".openclaw-state"))
_openclaw_proc: subprocess.Popen | None = None


def _generate_openclaw_config() -> str:
    """Run the config generator and return the path to openclaw.json."""
    state_dir = OPENCLAW_STATE_DIR
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    out = str(Path(state_dir) / "openclaw.json")
    gen = str(Path(__file__).resolve().parent.parent / "scripts" / "gen_openclaw_config.py")
    env = os.environ.copy()
    env["OPENCLAW_STATE_DIR"] = state_dir
    r = subprocess.run([sys.executable, gen, "--out", out, "--state-dir", state_dir], env=env)
    if r.returncode != 0:
        raise RuntimeError(f"OpenClaw config generation failed (code {r.returncode})")
    return out


def _start_openclaw_gateway(config_path: str) -> subprocess.Popen:
    """Start the OpenClaw Gateway as a subprocess."""
    env = os.environ.copy()
    env["OPENCLAW_STATE_DIR"] = OPENCLAW_STATE_DIR
    env["OPENCLAW_CONFIG_PATH"] = config_path
    # Point npm-global bin into PATH if present (local installs)
    npm_global = os.path.expanduser("~/.npm-global/bin")
    env["PATH"] = npm_global + ":" + env.get("PATH", "")
    cmd = [
        config.OPENCLAW_BIN,
        "gateway",
        "--port", str(config.OPENCLAW_PORT),
        "--auth", "none",
        "--bind", "loopback",
        "--allow-unconfigured",
    ]
    log_path = str(Path(OPENCLAW_STATE_DIR) / "gateway.log")
    logger.info(f"Starting OpenClaw Gateway: {' '.join(cmd)}")
    logger.info(f"Gateway log: {log_path}")
    log_f = open(log_path, "a", buffering=1)
    proc = subprocess.Popen(
        cmd, env=env, stdout=log_f, stderr=subprocess.STDOUT,
        # detach from our stdin so it doesn't share the tty
        stdin=subprocess.DEVNULL,
    )
    return proc


async def _wait_for_gateway(timeout: float = 120.0) -> bool:
    """Poll the gateway /v1/models until it responds."""
    import httpx
    url = f"{config.OPENCLAW_URL}/v1/models"
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(url, timeout=5.0)
                if r.status_code == 200:
                    logger.info("OpenClaw Gateway is ready ✓")
                    return True
        except Exception:
            pass
        # check the gateway subprocess hasn't died
        if _openclaw_proc is not None and _openclaw_proc.poll() is not None:
            logger.error(f"OpenClaw Gateway exited early (code {_openclaw_proc.returncode})")
            return False
        await asyncio.sleep(2.0)
    return False


def _stop_openclaw_gateway() -> None:
    global _openclaw_proc
    if _openclaw_proc is not None:
        try:
            _openclaw_proc.terminate()
            try:
                _openclaw_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _openclaw_proc.kill()
        except Exception as e:
            logger.debug(f"gateway stop error: {e}")
        _openclaw_proc = None


class MegaBot:
    def __init__(self):
        if not config.BOT_TOKEN:
            raise RuntimeError("BOT_TOKEN not set")
        self.bot = Bot(
            token=config.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=None),
        )
        self.dp = Dispatcher(storage=MemoryStorage())
        self.dp.include_router(admin_router)
        self.dp.include_router(chat_router)
        self.dp.include_router(group_router)
        self.dp.include_router(channel_router)
        self.dp.include_router(inline_router)

        # Error handler — log but never crash the bot
        from aiogram.types import ErrorEvent

        @self.dp.error()
        async def on_error(event: ErrorEvent):
            try:
                exc = event.exception
                from aiogram.exceptions import TelegramRetryAfter
                if isinstance(exc, TelegramRetryAfter):
                    logger.warning(f"Flood control (RetryAfter {exc.retry_after}s) — handled")
                else:
                    logger.error(
                        f"Handler error (suppressed): {type(exc).__name__}: {exc}",
                        exc_info=False,
                    )
            except Exception:
                pass

    async def start(self) -> None:
        logger.info("=== Василий (OpenClaw) стартует ===")

        # Auto-detect bot identity from Telegram (robust — doesn't rely on
        # BOT_ID/BOT_USERNAME secrets being set). is_directed_at_bot() and
        # anti-self-reply checks depend on config.BOT_ID being correct.
        try:
            me = await self.bot.get_me()
            config.BOT_ID = me.id
            config.BOT_USERNAME = (me.username or config.BOT_USERNAME or "").lstrip("@")
            logger.info(f"Bot: @{config.BOT_USERNAME} (id={config.BOT_ID}) «{me.first_name or ''}», owner={config.OWNER_ID}")
        except Exception as e:
            logger.warning(f"get_me failed (using env fallback): {e}")
            logger.info(f"Bot: @{config.BOT_USERNAME} (id={config.BOT_ID}), owner={config.OWNER_ID}")

        await db.init_db()
        logger.info("DB initialized")

        await ai_client.initialize()
        logger.info(f"AI client ready — {config.providers_status()}")

        # Background tasks
        asyncio.create_task(mood_loop(), name="mood_loop")
        asyncio.create_task(db.run_periodic_cleanup(), name="cleanup_loop")
        # Proactive topic starter + conversation summarizer
        try:
            from bot.proactive import proactive_loop, summary_loop, set_bot
            set_bot(self.bot)
            asyncio.create_task(proactive_loop(), name="proactive_loop")
            asyncio.create_task(summary_loop(), name="summary_loop")
            logger.info("Proactive topic starter + summary loop enabled")
        except Exception as e:
            logger.warning(f"Proactive/summary loop failed to start (non-fatal): {e}")

        await self._notify_owner()

        try:
            await self.bot.delete_webhook(drop_pending_updates=False)
        except Exception as e:
            logger.warning(f"delete_webhook: {e}")

        allowed = ["message", "edited_message", "channel_post", "edited_channel_post", "inline_query", "chosen_inline_result"]
        logger.info("=== Василий в сети — слушаю сообщения ===")

        polling_retries = 0
        while True:
            try:
                await self.dp.start_polling(self.bot, allowed_updates=allowed)
                break
            except Exception as e:
                polling_retries += 1
                logger.error(f"Polling error (attempt {polling_retries}): {type(e).__name__}: {e}")
                if polling_retries > 50:
                    logger.error("Too many polling retries — exiting")
                    break
                wait = 5 if polling_retries <= 5 else 10
                logger.warning(f"Retrying polling in {wait}s...")
                await asyncio.sleep(wait)

        try:
            await ai_client.close()
        except Exception:
            pass

    async def _notify_owner(self) -> None:
        mood = await current_mood_descriptor()
        try:
            await self.bot.send_message(
                config.OWNER_ID,
                f"Я на связи 🤖 Василий, сейчас я {mood}. "
                f"OpenClaw gateway: {config.OPENCLAW_URL}. "
                f"Провайдеры: {config.providers_status()}. "
                f"Пиши в личку или добавь в группу/канал 💬"
            )
        except Exception as e:
            logger.warning(f"Could not notify owner: {e}")


async def main():
    global _openclaw_proc
    # 1. Generate OpenClaw config
    cfg_path = _generate_openclaw_config()
    logger.info(f"OpenClaw config: {cfg_path}")

    # 2. Start OpenClaw gateway subprocess
    _openclaw_proc = _start_openclaw_gateway(cfg_path)

    # 3. Wait for gateway
    ready = await _wait_for_gateway(timeout=120.0)
    if not ready:
        logger.error("OpenClaw Gateway did not become ready — exiting")
        _stop_openclaw_gateway()
        sys.exit(1)

    # 4. Start the bot
    bot = MegaBot()

    def _sig(*_):
        logger.info("Received shutdown signal")
        asyncio.create_task(bot.dp.stop_polling())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(sig, _sig)
        except NotImplementedError:
            signal.signal(sig, lambda *_: None)

    try:
        await bot.start()
    finally:
        _stop_openclaw_gateway()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.exception(f"Fatal: {e}")
        _stop_openclaw_gateway()
        sys.exit(1)
