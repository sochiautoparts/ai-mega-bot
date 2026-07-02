"""
SQLite storage for AI Mega Bot — async (aiosqlite), WAL mode for concurrency.

Tables:
  channels          — known channels + enabled flag (reactions on/off)
  group_messages    — recent message context window per group (FIFO)
  group_memory      — long-term facts about users per group
  reactions_dedup   — recent message_ids we reacted to (anti-duplicate)

The DB file lives at config.DB_PATH (data/bot.db). In GitHub Actions it is
cached across runs + committed to git for memory persistence.
"""

import logging
import time
from typing import List, Optional

import aiosqlite

from bot.config import config

logger = logging.getLogger("mega.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    chat_id    INTEGER PRIMARY KEY,
    username   TEXT DEFAULT '',
    title      TEXT DEFAULT '',
    enabled    INTEGER DEFAULT 1,
    seen       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS group_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    username        TEXT DEFAULT '',
    first_name      TEXT DEFAULT '',
    content         TEXT DEFAULT '',
    is_media        INTEGER DEFAULT 0,
    media_caption   TEXT DEFAULT '',
    is_bot          INTEGER DEFAULT 0,
    ts              INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gm_chat_ts ON group_messages(chat_id, id DESC);

CREATE TABLE IF NOT EXISTS group_memory (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id   INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    fact      TEXT NOT NULL,
    ts        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gmem_chat ON group_memory(chat_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_gmem_chat_user ON group_memory(chat_id, user_id);

CREATE TABLE IF NOT EXISTS reactions_dedup (
    message_id  INTEGER NOT NULL,
    chat_id     INTEGER NOT NULL,
    ts          INTEGER NOT NULL,
    PRIMARY KEY (chat_id, message_id)
);
"""

_db: Optional[aiosqlite.Connection] = None


async def init_db() -> None:
    global _db
    import os
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    _db = await aiosqlite.connect(config.DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL;")
    await _db.execute("PRAGMA synchronous=NORMAL;")
    await _db.executescript(_SCHEMA)
    await _db.commit()
    logger.info(f"DB ready at {config.DB_PATH}")


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


def _conn() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("DB not initialised — call init_db() first")
    return _db


# ── Channels ─────────────────────────────────────────────────────────────────
async def upsert_channel(chat_id: int, username: str = "", title: str = "") -> None:
    await _conn().execute(
        "INSERT INTO channels(chat_id, username, title, enabled, seen) "
        "VALUES(?, ?, ?, 1, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET username=excluded.username, title=excluded.title, seen=excluded.seen",
        (chat_id, username, title, int(time.time())),
    )
    await _conn().commit()


async def is_channel_enabled(chat_id: int) -> bool:
    cur = await _conn().execute("SELECT enabled FROM channels WHERE chat_id=?", (chat_id,))
    row = await cur.fetchone()
    return row is None or row["enabled"] == 1  # default enabled for new channels


async def set_channel_enabled(chat_id: int, enabled: bool) -> None:
    await _conn().execute(
        "INSERT INTO channels(chat_id, enabled, seen) VALUES(?, ?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET enabled=excluded.enabled",
        (chat_id, 1 if enabled else 0, int(time.time())),
    )
    await _conn().commit()


# ── Group messages (context window) ──────────────────────────────────────────
async def add_group_message(chat_id: int, user_id: int, username: str, first_name: str,
                            content: str, is_media: bool = False, media_caption: str = "",
                            is_bot: bool = False) -> None:
    await _conn().execute(
        "INSERT INTO group_messages(chat_id, user_id, username, first_name, content, "
        "is_media, media_caption, is_bot, ts) VALUES(?,?,?,?,?,?,?,?,?)",
        (chat_id, user_id, username, first_name, content, int(is_media),
         media_caption, int(is_bot), int(time.time())),
    )
    await _conn().commit()
    # Trim to context window
    await _conn().execute(
        "DELETE FROM group_messages WHERE chat_id=? AND id NOT IN "
        "(SELECT id FROM group_messages WHERE chat_id=? ORDER BY id DESC LIMIT ?)",
        (chat_id, chat_id, config.GROUP_MEMORY_SIZE * 2),
    )
    await _conn().commit()


async def get_recent_group_messages(chat_id: int, limit: int = 12) -> List[dict]:
    cur = await _conn().execute(
        "SELECT * FROM group_messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",
        (chat_id, limit),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in reversed(rows)]  # chronological order


# ── Long-term memory (facts about users) ────────────────────────────────────
async def add_group_memory(chat_id: int, user_id: int, fact: str) -> None:
    await _conn().execute(
        "INSERT INTO group_memory(chat_id, user_id, fact, ts) VALUES(?,?,?,?)",
        (chat_id, user_id, fact, int(time.time())),
    )
    await _conn().commit()


async def get_group_memory(chat_id: int, user_id: Optional[int] = None,
                           limit: int = 8) -> List[dict]:
    if user_id is not None:
        cur = await _conn().execute(
            "SELECT * FROM group_memory WHERE chat_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, user_id, limit),
        )
    else:
        cur = await _conn().execute(
            "SELECT * FROM group_memory WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Reaction dedup ───────────────────────────────────────────────────────────
async def already_reacted(chat_id: int, message_id: int) -> bool:
    cur = await _conn().execute(
        "SELECT 1 FROM reactions_dedup WHERE chat_id=? AND message_id=?",
        (chat_id, message_id),
    )
    return await cur.fetchone() is not None


async def mark_reacted(chat_id: int, message_id: int) -> None:
    await _conn().execute(
        "INSERT OR IGNORE INTO reactions_dedup(chat_id, message_id, ts) VALUES(?,?,?)",
        (chat_id, message_id, int(time.time())),
    )
    await _conn().commit()


async def run_periodic_cleanup() -> None:
    """Drop dedup entries older than 1h, every 10 min."""
    while True:
        await _sleep(600)
        try:
            cutoff = int(time.time()) - 3600
            await _conn().execute("DELETE FROM reactions_dedup WHERE ts < ?", (cutoff,))
            await _conn().commit()
        except Exception as e:
            logger.debug(f"cleanup error: {e}")


async def _sleep(sec: float) -> None:
    import asyncio
    await asyncio.sleep(sec)
