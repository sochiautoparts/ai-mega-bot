"""
SQLite storage for AI Mega Bot — async (aiosqlite), WAL mode for concurrency.

Tables:
  channels          — known channels + enabled flag (reactions on/off)
  group_messages    — recent message context window per group (FIFO)
  group_memory      — per-group facts about users
  users             — GLOBAL user profiles (name, seen, counts) — survives restarts
  user_facts        — GLOBAL facts about users across ALL chats (private + groups)
  private_messages  — persistent private chat history (survives restarts)
  reactions_dedup   — recent message_ids we reacted to (anti-duplicate)

The DB file lives at config.DB_PATH (data/bot.db). In GitHub Actions it is
cached across runs + committed to git for memory persistence — so Василий
remembers people and conversations across restarts.
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

CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    username     TEXT DEFAULT '',
    first_name   TEXT DEFAULT '',
    last_name    TEXT DEFAULT '',
    is_bot       INTEGER DEFAULT 0,
    first_seen   INTEGER NOT NULL,
    last_seen    INTEGER NOT NULL,
    msg_count    INTEGER DEFAULT 0,
    private_msgs INTEGER DEFAULT 0,
    group_msgs   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    fact        TEXT NOT NULL,
    source_chat INTEGER NOT NULL,
    ts          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_uf_user ON user_facts(user_id, id DESC);

CREATE TABLE IF NOT EXISTS private_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    role        TEXT NOT NULL,   -- 'user' | 'assistant'
    content     TEXT NOT NULL,
    ts          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pm_user_ts ON private_messages(user_id, id DESC);

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


async def get_active_group_chats(within_hours: int = 24, limit: int = 20) -> List[int]:
    """Return chat_ids of groups that had activity in the last N hours."""
    cutoff = int(time.time()) - within_hours * 3600
    cur = await _conn().execute(
        "SELECT DISTINCT chat_id FROM group_messages WHERE ts > ? AND chat_id < 0 LIMIT ?",
        (cutoff, limit),
    )
    rows = await cur.fetchall()
    return [r["chat_id"] for r in rows]


async def last_bot_message_time(chat_id: int) -> float:
    """Timestamp of the bot's most recent message in a chat (0 if none)."""
    cur = await _conn().execute(
        "SELECT ts FROM group_messages WHERE chat_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
        (chat_id, config.BOT_ID),
    )
    row = await cur.fetchone()
    return float(row["ts"]) if row else 0.0


async def last_message_time(chat_id: int) -> float:
    """Timestamp of the most recent message in a chat (0 if none)."""
    cur = await _conn().execute(
        "SELECT ts FROM group_messages WHERE chat_id=? ORDER BY id DESC LIMIT 1",
        (chat_id,),
    )
    row = await cur.fetchone()
    return float(row["ts"]) if row else 0.0


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


# ── Global user profiles ────────────────────────────────────────────────────
async def upsert_user(user_id: int, username: str = "", first_name: str = "",
                      last_name: str = "", is_bot: bool = False,
                      in_private: bool = False, in_group: bool = False) -> None:
    """Create or update a global user profile. Bumps message counters."""
    now = int(time.time())
    c = _conn()
    await c.execute(
        "INSERT INTO users(user_id, username, first_name, last_name, is_bot, "
        "first_seen, last_seen, msg_count, private_msgs, group_msgs) "
        "VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET "
        "username=excluded.username, first_name=excluded.first_name, "
        "last_name=excluded.last_name, last_seen=excluded.last_seen, "
        "msg_count=users.msg_count+1, "
        "private_msgs=users.private_msgs+?, "
        "group_msgs=users.group_msgs+?",
        (user_id, username, first_name, last_name, int(is_bot),
         now, now, 1, int(in_private), int(in_group),
         int(in_private), int(in_group)),
    )
    await c.commit()


async def get_user(user_id: int) -> Optional[dict]:
    cur = await _conn().execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def add_user_fact(user_id: int, fact: str, source_chat: int = 0) -> None:
    """Store a fact learned about a user (globally, across all chats)."""
    await _conn().execute(
        "INSERT INTO user_facts(user_id, fact, source_chat, ts) VALUES(?,?,?,?)",
        (user_id, fact, source_chat, int(time.time())),
    )
    await _conn().commit()


async def get_user_facts(user_id: int, limit: int = 12) -> List[dict]:
    cur = await _conn().execute(
        "SELECT fact FROM user_facts WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def has_user_fact(user_id: int, fact: str) -> bool:
    """Check if a similar fact already exists (substring match, case-insensitive)."""
    cur = await _conn().execute(
        "SELECT 1 FROM user_facts WHERE user_id=? AND LOWER(fact)=LOWER(?) LIMIT 1",
        (user_id, fact),
    )
    return await cur.fetchone() is not None


async def clear_user_facts(user_id: int) -> int:
    """Delete all facts for a user. Returns number deleted."""
    cur = await _conn().execute(
        "DELETE FROM user_facts WHERE user_id=?", (user_id,)
    )
    await _conn().commit()
    return cur.rowcount or 0


# ── Private chat history (persistent) ───────────────────────────────────────
async def add_private_message(user_id: int, role: str, content: str) -> None:
    await _conn().execute(
        "INSERT INTO private_messages(user_id, role, content, ts) VALUES(?,?,?,?)",
        (user_id, role, content, int(time.time())),
    )
    await _conn().commit()
    # Trim to last 40 turns per user (80 rows) to bound DB growth
    await _conn().execute(
        "DELETE FROM private_messages WHERE user_id=? AND id NOT IN "
        "(SELECT id FROM private_messages WHERE user_id=? ORDER BY id DESC LIMIT 80)",
        (user_id, user_id),
    )
    await _conn().commit()


async def get_private_history(user_id: int, limit: int = 16) -> List[dict]:
    """Returns chronological list of {role, content} for a user."""
    cur = await _conn().execute(
        "SELECT role, content FROM private_messages WHERE user_id=? "
        "ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    rows = await cur.fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def clear_private_history(user_id: int) -> int:
    cur = await _conn().execute(
        "DELETE FROM private_messages WHERE user_id=?", (user_id,)
    )
    await _conn().commit()
    return cur.rowcount or 0


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
