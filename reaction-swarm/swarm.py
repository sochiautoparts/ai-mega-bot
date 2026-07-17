#!/usr/bin/env python3
"""
Reaction Swarm v3 — Single-shot processor для sandbox resilience.

ПРОБЛЕМА:
  Sandbox убивает длинные фоновые процессы каждые ~30-60с.
  Daemon + supervise.sh не выживает (supervise.sh тоже убивается).
  5-мин watchdog = до 5 мин простоя.

РЕШЕНИЕ:
  Single-shot: один запуск обрабатывает все pending updates и выходит.
  Cron запускает каждые 2 минуты. Max latency: 2 мин.
  Каждый запуск: init → getUpdates → process → save offsets → exit (~10с).

БЕЗОПАСНОСТЬ:
  - Flock: нет дублей (параллельные запуски)
  - CommentGuard: нет дублей комментариев (persistent file)
  - OffsetStore: at-least-once delivery (reprocess on crash = безопасно)
  - Idempotent reactions: setMessageReaction можно повторять
  - 25с timeout: всегда завершается в пределах sandbox window

ИСПОЛЬЗОВАНИЕ:
  python3 swarm.py            # single-shot (default, для cron)
  python3 swarm.py --daemon   # long-polling daemon (для non-sandbox)

ЗАВИСИМОСТИ: aiohttp, python-dotenv.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import random
import signal
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

# ===========================================================================
# .env автозагрузка
# ===========================================================================
_dotenv_path = Path(__file__).resolve().parent / ".env"
if _dotenv_path.is_file() and not os.getenv("_SWARM_ENV_LOADED"):
    try:
        from dotenv import load_dotenv
        load_dotenv(_dotenv_path, override=False)
        os.environ["_SWARM_ENV_LOADED"] = "1"
    except ImportError:
        pass

# ===========================================================================
# Логирование
# ===========================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
    force=True,
)
log = logging.getLogger("swarm")

# ===========================================================================
# Конфигурация
# ===========================================================================
TELEGRAM_API = "https://api.telegram.org"

CHANNEL_FILTER = {
    c.strip().lstrip("@").lower()
    for c in os.getenv("SWARM_CHANNELS", "").split(",")
    if c.strip()
} or None

SKIP_KEYWORDS = [
    "войн", "политик", "выбор", "путин", "зеленск", "наводн", "теракт",
    "взрыв", "погиб", "жертв", "ракет", "обстрел", "дрон", "мобилиз",
    "спецопераци", "воорудж", "cvобода", "санкци",
]

REACTION_POOL = [
    "👍", "👍", "👍", "👍", "❤️", "❤️", "❤️", "🔥", "🔥",
    "👏", "🎉", "😄", "🤝", "💯",
]

QUICK_COMMENTS = [
    "Огонь! 🔥", "Согласен полностью 💯", "Вот это новость!", "Интересно 🤔",
    "Жду больше деталей", "Топ контент 👍", "Спасибо за новость!", "Вот это да!",
    "Поддерживаю!", "Качественный пост 🔥", "Беру на заметку", "Супер!",
    "Вот это поворот...", "Не ожидал такого", "Отличный разбор 👏",
    "Согласен с редакцией", "Точно подмечено!", "Интересная мысль 💭",
    "Вот это тема!", "Качественно 🔥", "Респект автору 👍", "Полезно, спасибо!",
    "Вот это инфа!", "Держите марку 💪", "Читаю с удовольствием",
    "Это надо обсудить!", "Хороший пост 🙌", "Одобряю!", "Дельная новость",
    "Спасибо, полезно 👍", "Зачёт 🔥", "Браво!", "Толково",
]

COMMENT_PROB = 0.45

# Короткие задержки для single-shot (cron 2мин даёт естественный spacing)
REACT_DELAY_MIN, REACT_DELAY_MAX = 0.2, 1.0
COMMENT_DELAY_MIN, COMMENT_DELAY_MAX = 0.5, 2.0

STALE_WINDOW_SEC = int(os.getenv("SWARM_STALE_WINDOW", "7200"))

# Long-poll timeout для getUpdates.
# Single-shot (sandbox): 5 сек — быстрый возврат, запуск завершается за 10-30с.
# Daemon (GH Actions): 30 сек — экономит rate limit, мгновенный возврат при updates.
# Env-configurable через SWARM_LONG_POLL_TIMEOUT.
LONG_POLL_TIMEOUT = int(os.getenv("SWARM_LONG_POLL_TIMEOUT", "5"))

# Боты которые надо ВЫКЛЮЧИТЬ (через env, comma-separated).
# Пример: SWARM_DISABLED_BOTS=allstarspay,tires24
_DISABLED_SET = {
    n.strip().lower()
    for n in os.getenv("SWARM_DISABLED_BOTS", "").split(",")
    if n.strip()
}

# Hard timeout для всего single-shot запуска
# 30с — sandbox убивает ~30-60с, даём запас
SINGLE_SHOT_TIMEOUT = 30

# Лимит updates за один getUpdates вызов (per bot)
# 30 = баланс между catch-up и rate limits
UPDATES_LIMIT = 30

# Max concurrent handle_update задач на одного бота
# 5 = не превышаем Telegram rate limit (30 req/s per bot)
MAX_CONCURRENT_PER_BOT = 5

# 10 ботов
SWARM_BOTS = [
    ("allstarspay", "BOT_TOKEN_ALLSTARSPAY"),
    ("tires24",     "BOT_TOKEN_TIRES24"),
    ("rosskozap",   "BOT_TOKEN_ROSSKOZAP"),
    ("activglobal", "BOT_TOKEN_ACTIVGLOBAL"),
    ("recars",      "BOT_TOKEN_RECARS"),
    ("bilet_avia",  "BOT_TOKEN_BILET_AVIA"),
    ("kolesopro",   "BOT_TOKEN_KOLESPRO"),
    ("autokod",     "BOT_TOKEN_AUTOKOD"),
    ("zaponline",   "BOT_TOKEN_ZAPONLINE"),
    ("lukoil",      "BOT_TOKEN_LUKOILOIL"),
]

BASE_DIR = Path(__file__).resolve().parent
_COMMENTED_FILE = BASE_DIR / ".commented.json"
_OFFSETS_FILE = BASE_DIR / ".offsets.json"
_HEARTBEAT_FILE = BASE_DIR / ".heartbeat"
_RUN_LOCK = BASE_DIR / ".run.lock"


def load_bot_tokens() -> list[tuple[str, str]]:
    """Загружает токены ботов из env, пропуская явно отключённых
    (через SWARM_DISABLED_BOTS=allstarspay,...)."""
    out = []
    for name, env_key in SWARM_BOTS:
        if name.lower() in _DISABLED_SET:
            log.info("⏸ %s: отключён через SWARM_DISABLED_BOTS", name)
            continue
        tok = os.getenv(env_key, "").strip()
        if tok and ":" in tok:
            out.append((name, tok))
    return out


# ===========================================================================
# CommentGuard — persistent защита от дублей комментариев
# ===========================================================================
class CommentGuard:
    """Файловый guard: (bot, chat, msg) → уже комментировано?
    Переживает рестарт процесса — нет дублей комментариев."""

    def __init__(self):
        self._data: set[str] = set()
        self._load()

    def _load(self):
        try:
            if _COMMENTED_FILE.is_file():
                self._data = set(json.loads(_COMMENTED_FILE.read_text("utf-8")))
        except Exception:
            pass

    def _save(self):
        try:
            tmp = _COMMENTED_FILE.with_suffix(".tmp")
            items = sorted(self._data)[-5000:]
            tmp.write_text(json.dumps(items, ensure_ascii=False), "utf-8")
            tmp.replace(_COMMENTED_FILE)
        except Exception:
            pass

    def already(self, key: str) -> bool:
        return key in self._data

    def mark(self, key: str):
        self._data.add(key)
        self._save()


comment_guard = CommentGuard()


# ===========================================================================
# OffsetStore — persistent offsets для single-shot mode
# ===========================================================================
class OffsetStore:
    """Per-bot offsets. At-least-once delivery:
    - offset сохраняется ПОСЛЕ обработки updates
    - если процесс убит до save → next run reprocess (безопасно:
      CommentGuard + idempotent reactions)"""

    def __init__(self):
        self._data: dict[str, int] = {}
        self._load()

    def _load(self):
        try:
            if _OFFSETS_FILE.is_file():
                self._data = json.loads(_OFFSETS_FILE.read_text("utf-8"))
        except Exception:
            self._data = {}

    def get(self, bot_name: str) -> int:
        return self._data.get(bot_name, 0)

    def save(self, bot_name: str, offset: int):
        self._data[bot_name] = offset
        try:
            tmp = _OFFSETS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data), "utf-8")
            tmp.replace(_OFFSETS_FILE)
        except Exception:
            pass


offset_store = OffsetStore()


# ===========================================================================
# Heartbeat — для мониторинга
# ===========================================================================
def write_heartbeat(status: str = "alive", extra: str = ""):
    try:
        ts = datetime.now(timezone.utc).isoformat()
        _HEARTBEAT_FILE.write_text(f"{ts}|{status}|{extra}\n", "utf-8")
    except Exception:
        pass


# ===========================================================================
# BotRunner — один бот, свой HTTP-сессия
# ===========================================================================
class BotRunner:
    __slots__ = ("name", "token", "session", "offset", "reacted",
                 "linked_cache", "me", "log", "stats", "dead")

    def __init__(self, name: str, token: str):
        self.name = name
        self.token = token
        self.session: aiohttp.ClientSession | None = None
        self.offset = offset_store.get(name)
        self.reacted: set[tuple] = set()
        self.linked_cache: dict[int, int | None] = {}
        self.me: dict = {}
        self.log = logging.getLogger(f"bot.{name}")
        self.stats = defaultdict(int)
        self.dead = False

    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                connector=aiohttp.TCPConnector(limit=5, limit_per_host=5),
            )

    async def tg(self, method: str, **params) -> dict:
        await self._ensure_session()
        url = f"{TELEGRAM_API}/bot{self.token}/{method}"
        if "reaction" in params:
            params = dict(params)
            params["reaction"] = json.dumps(params["reaction"])
        try:
            async with self.session.post(
                url, data=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                return await r.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def tg_get(self, method: str, **params) -> dict:
        await self._ensure_session()
        url = f"{TELEGRAM_API}/bot{self.token}/{method}"
        try:
            async with self.session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                return await r.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def init(self) -> bool:
        """getMe + deleteWebhook. Returns False on failure."""
        data = await self.tg_get("getMe")
        if not data.get("ok"):
            self.log.error("getMe FAILED: %s", str(data.get("description", ""))[:100])
            self.dead = True
            return False
        self.me = data["result"]
        # deleteWebhook сбрасывает lingering getUpdates-сессию → меньше 409
        await self.tg_get("deleteWebhook", drop_pending_updates=False)
        self.log.info("ONLINE @%s (id=%s)", self.me.get("username"), self.me.get("id"))
        return True

    async def get_updates(self) -> list[dict]:
        """Один getUpdates вызов. Short timeout для single-shot."""
        url = f"{TELEGRAM_API}/bot{self.token}/getUpdates"
        params = {
            "offset": self.offset,
            "timeout": LONG_POLL_TIMEOUT,
            "limit": UPDATES_LIMIT,
            "allowed_updates": json.dumps(["channel_post", "message"]),
        }
        try:
            async with self.session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=LONG_POLL_TIMEOUT + 15),
            ) as r:
                data = await r.json()
                if not data.get("ok"):
                    if data.get("error_code") == 409:
                        self.log.warning("409 Conflict — другой инстанс. Пропуск.")
                        self.dead = True
                    else:
                        self.log.warning("getUpdates: %s",
                                         str(data.get("description", ""))[:100])
                    return []
                updates = data.get("result", [])
                if updates:
                    max_uid = max(u.get("update_id", 0) for u in updates)
                    self.offset = max_uid + 1
                return updates
        except Exception as e:
            self.log.warning("getUpdates error: %s", e)
            return []

    async def set_reaction(self, chat_id: int, msg_id: int, emoji: str) -> bool:
        res = await self.tg(
            "setMessageReaction",
            chat_id=chat_id, message_id=msg_id,
            reaction=[{"type": "emoji", "emoji": emoji}],
        )
        if res.get("ok"):
            return True
        # 429 Too Many Requests — не делаем fallback, просто пропускаем
        if res.get("error_code") == 429:
            self.stats["rate_limited"] += 1
            return False
        # fallback: 👍 универсальный
        if emoji != "👍":
            res2 = await self.tg(
                "setMessageReaction",
                chat_id=chat_id, message_id=msg_id,
                reaction=[{"type": "emoji", "emoji": "👍"}],
            )
            if res2.get("ok"):
                return True
        self.log.warning("⚠ reaction fail %s/%s %s: %s",
                         chat_id, msg_id, emoji,
                         str(res.get("description", ""))[:80])
        return False

    async def get_linked_chat(self, chat_id: int) -> int | None:
        if chat_id in self.linked_cache:
            return self.linked_cache[chat_id]
        data = await self.tg_get("getChat", chat_id=chat_id)
        linked = None
        if data.get("ok"):
            linked = data["result"].get("linked_chat_id")
        self.linked_cache[chat_id] = linked
        return linked

    async def send_comment(self, chat_id: int, msg_id: int) -> bool:
        linked = await self.get_linked_chat(chat_id)
        if not linked:
            self.stats["no_discussion"] += 1
            return False
        # Persistent guard — нет дублей после рестарта
        key = f"{self.name}:{chat_id}:{msg_id}"
        if comment_guard.already(key):
            self.stats["comment_dup"] += 1
            return False
        text = random.choice(QUICK_COMMENTS)
        # message_thread_id (Bot API 6.3+): в discussion group канала
        # Telegram создаёт thread с thread_id == message_id поста канала.
        # sendMessage с message_thread_id = РЕАЛЬНЫЙ комментарий к посту.
        res = await self.tg(
            "sendMessage",
            chat_id=linked,
            message_thread_id=msg_id,
            text=text,
        )
        if not res.get("ok"):
            # fallback: без thread
            res = await self.tg("sendMessage", chat_id=linked, text=text)
        if res.get("ok"):
            comment_guard.mark(key)
            self.stats["comments"] += 1
            self.log.info("💬 %s (пост %s): %s", linked, msg_id, text)
            return True
        self.log.warning("⚠ comment fail %s/%s: %s",
                         chat_id, msg_id,
                         str(res.get("description", ""))[:80])
        return False

    def _should_skip(self, text: str) -> bool:
        if not text:
            return False
        low = text.lower()
        return any(k in low for k in SKIP_KEYWORDS)

    def _channel_allowed(self, chat: dict) -> bool:
        if CHANNEL_FILTER is None:
            return True
        return (chat.get("username") or "").lower() in CHANNEL_FILTER

    async def handle_update(self, update: dict, sem: asyncio.Semaphore) -> None:
        msg = update.get("channel_post")
        if msg is None:
            m = update.get("message") or {}
            sc = m.get("sender_chat") or {}
            if sc.get("type") == "channel" and m.get("forward_from_chat"):
                msg = m
        if not msg:
            return

        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        msg_id = msg.get("message_id")
        if chat_id is None or msg_id is None:
            return
        if chat.get("type") != "channel":
            return
        if not self._channel_allowed(chat):
            return

        # Фильтр старых постов
        msg_date = msg.get("date", 0)
        if msg_date:
            age = datetime.now(timezone.utc).timestamp() - msg_date
            if age > STALE_WINDOW_SEC:
                self.stats["skipped_stale"] += 1
                return

        text = msg.get("text") or msg.get("caption") or ""
        if self._should_skip(text):
            self.stats["skipped_politics"] += 1
            return

        key = (chat_id, msg_id)
        if key in self.reacted:
            return

        # Semaphore: не больше MAX_CONCURRENT_PER_BOT concurrently
        async with sem:
            self.reacted.add(key)

            # Staggered delay (короткие для single-shot)
            await asyncio.sleep(random.uniform(REACT_DELAY_MIN, REACT_DELAY_MAX))

            emoji = random.choice(REACTION_POOL)
            ok = await self.set_reaction(chat_id, msg_id, emoji)
            if ok:
                self.stats["reactions"] += 1
                uname = chat.get("username") or chat_id
                self.log.info("✅ %s на пост %s/%s", emoji, uname, msg_id)

            # Комментарий с вероятностью COMMENT_PROB
            if random.random() < COMMENT_PROB:
                await asyncio.sleep(random.uniform(COMMENT_DELAY_MIN, COMMENT_DELAY_MAX))
                await self.send_comment(chat_id, msg_id)

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


# ===========================================================================
# Flock — нет дублей инстансов
# ===========================================================================
def acquire_lock() -> bool:
    """flock автоматически освобождается при смерти процесса (даже SIGKILL)."""
    fd = os.open(str(_RUN_LOCK), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (BlockingIOError, OSError):
        return False


# ===========================================================================
# SINGLE-SHOT MODE — основной режим для sandbox
# ===========================================================================
async def run_single_shot(bots: list[tuple[str, str]]) -> int:
    """Process pending updates for all bots, then exit. ~10с."""
    runners = [BotRunner(name, token) for name, token in bots]

    # 1. Параллельный init (getMe + deleteWebhook)
    log.info("init %d bots...", len(runners))
    await asyncio.gather(*[r.init() for r in runners], return_exceptions=True)
    alive = [r for r in runners if not r.dead]
    if not alive:
        log.error("DEAD: ни один бот не смог инициализироваться")
        write_heartbeat("dead", "no bots alive")
        for r in runners:
            await r.close()
        return 1
    log.info("alive: %d/%d", len(alive), len(runners))

    # 2. Параллельный getUpdates (timeout=5, все одновременно)
    log.info("getUpdates (timeout=%ds)...", LONG_POLL_TIMEOUT)
    results = await asyncio.gather(
        *[r.get_updates() for r in alive], return_exceptions=True
    )
    for r, res in zip(alive, results):
        if isinstance(res, Exception):
            r.log.warning("getUpdates exception: %s", res)
            res = []
        if res:
            r.log.info("📥 %d updates", len(res))

    # 3. Параллельная обработка всех updates (per-bot semaphore для rate limit)
    process_tasks = []
    total_updates = 0
    for i, r in enumerate(alive):
        updates = results[i] if isinstance(results[i], list) else []
        # Каждый бот имеет свой semaphore — max MAX_CONCURRENT_PER_BOT concurrent
        sem = asyncio.Semaphore(MAX_CONCURRENT_PER_BOT)
        for u in updates:
            process_tasks.append(r.handle_update(u, sem))
            total_updates += 1

    if process_tasks:
        log.info("processing %d updates in parallel...", total_updates)
        await asyncio.gather(*process_tasks, return_exceptions=True)

    # 4. Сохранить offsets (после обработки — at-least-once)
    for r in alive:
        offset_store.save(r.name, r.offset)

    # 5. Статистика
    total_reactions = sum(r.stats.get("reactions", 0) for r in alive)
    total_comments = sum(r.stats.get("comments", 0) for r in alive)
    log.info("Done: %d reactions, %d comments", total_reactions, total_comments)
    write_heartbeat("alive",
                    f"bots={len(alive)}/{len(runners)} "
                    f"rxn={total_reactions} com={total_comments}")

    # 6. Cleanup (даём aiohttp время закрыть соединения)
    for r in runners:
        await r.close()
    await asyncio.sleep(0.2)

    return 0


# ===========================================================================
# DAEMON MODE — для non-sandbox (--daemon флаг)
# ===========================================================================
async def run_daemon(bots: list[tuple[str, str]]) -> int:
    """Long-polling loop. Для non-sandbox environments."""
    runners = [BotRunner(name, token) for name, token in bots]

    await asyncio.gather(*[r.init() for r in runners], return_exceptions=True)
    alive = [r for r in runners if not r.dead]
    log.info("Daemon: %d/%d bots alive", len(alive), len(runners))
    if not alive:
        return 1

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    async def heartbeat():
        while not stop.is_set():
            write_heartbeat("alive", f"daemon bots={len(alive)}")
            await asyncio.sleep(15)

    hb_task = asyncio.create_task(heartbeat())

    async def bot_loop(r: BotRunner):
        r.log.info("▶ long-polling")
        sem = asyncio.Semaphore(MAX_CONCURRENT_PER_BOT)
        while not stop.is_set() and not r.dead:
            try:
                updates = await r.get_updates()
                if updates:
                    r.log.info("📥 %d updates", len(updates))
                for u in updates:
                    try:
                        await r.handle_update(u, sem)
                    except Exception as e:
                        r.log.warning("handle: %s", e)
                offset_store.save(r.name, r.offset)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                r.log.error("loop error: %s", e)
                await asyncio.sleep(3)

    bot_tasks = [asyncio.create_task(bot_loop(r)) for r in alive]
    stop_task = asyncio.create_task(stop.wait())

    await asyncio.wait(bot_tasks + [stop_task], return_when=asyncio.ALL_COMPLETED)

    hb_task.cancel()
    for t in bot_tasks:
        if not t.done():
            t.cancel()
    for r in runners:
        await r.close()
    return 0


# ===========================================================================
# Main
# ===========================================================================
async def amain() -> int:
    if not acquire_lock():
        log.info("уже запущен (flock занят) — выхожу")
        return 0

    bots = load_bot_tokens()
    log.info("загружено ботов с токенами: %d / %d", len(bots), len(SWARM_BOTS))
    for name, _ in bots:
        log.info("  • %s", name)
    enabled_names = {n for n, _ in SWARM_BOTS if n.lower() not in _DISABLED_SET}
    missing = [n for n, _ in SWARM_BOTS
               if n not in {b[0] for b in bots} and n in enabled_names]
    if missing:
        log.warning("⚠ без токенов: %s", ", ".join(missing))

    if not bots:
        log.error("❌ Нет ботов с токенами. Заполни .env.")
        return 2

    daemon_mode = "--daemon" in sys.argv

    if daemon_mode:
        log.info("=== DAEMON MODE ===")
        return await run_daemon(bots)
    else:
        log.info("=== SINGLE-SHOT MODE ===")
        try:
            return await asyncio.wait_for(
                run_single_shot(bots), timeout=SINGLE_SHOT_TIMEOUT
            )
        except asyncio.TimeoutError:
            log.warning("⏱ single-shot timed out after %ds", SINGLE_SHOT_TIMEOUT)
            write_heartbeat("timeout", f"limit={SINGLE_SHOT_TIMEOUT}s")
            return 1


def main() -> int:
    try:
        return asyncio.run(amain())
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        log.exception("FATAL: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
