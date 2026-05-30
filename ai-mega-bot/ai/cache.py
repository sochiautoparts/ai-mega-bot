"""Two-level caching: in-memory LRU + SQLite."""
import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import Any, Optional

from bot.config import CACHE_MAX_MEMORY, CACHE_TTL_TEXT, CACHE_TTL_IMAGE

logger = logging.getLogger(__name__)


class AICache:
    """Two-level cache: LRU memory + SQLite persistence."""

    def __init__(self, db, max_memory: int = CACHE_MAX_MEMORY):
        self.db = db
        self._memory: OrderedDict = OrderedDict()
        self._max_memory = max_memory

    def _make_key(self, prompt: str, task_type: str, **kwargs) -> str:
        """Create deterministic cache key from request parameters."""
        data = f"{task_type}:{prompt}"
        if kwargs:
            data += f":{json.dumps(kwargs, sort_keys=True, default=str)}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]

    async def get(self, prompt: str, task_type: str, **kwargs) -> Optional[dict]:
        """Get cached response."""
        key = self._make_key(prompt, task_type, **kwargs)

        # Level 1: Memory cache
        if key in self._memory:
            entry = self._memory[key]
            if time.time() - entry["ts"] < self._get_ttl(task_type):
                self._memory.move_to_end(key)
                return entry["data"]
            del self._memory[key]

        # Level 2: SQLite cache (if db has cache table)
        try:
            async with self.db._db.execute(
                "SELECT response_data, created_at FROM ai_cache WHERE cache_key = ?",
                (key,),
            ) as cur:
                row = await cur.fetchone()
                if row:
                    ttl = self._get_ttl(task_type)
                    if time.time() - row[1] < ttl:
                        data = json.loads(row[0])
                        # Promote to memory cache
                        self._put_memory(key, data)
                        return data
                    # Expired, delete
                    await self.db._db.execute(
                        "DELETE FROM ai_cache WHERE cache_key = ?", (key,)
                    )
                    await self.db._db.commit()
        except Exception:
            pass

        return None

    async def put(self, prompt: str, task_type: str, response: dict, **kwargs) -> None:
        """Store response in cache."""
        key = self._make_key(prompt, task_type, **kwargs)

        # Level 1: Memory
        self._put_memory(key, response)

        # Level 2: SQLite
        try:
            now = time.time()
            await self.db._db.execute(
                """INSERT OR REPLACE INTO ai_cache (cache_key, task_type, response_data, created_at)
                VALUES (?, ?, ?, ?)""",
                (key, task_type, json.dumps(response, default=str), now),
            )
            await self.db._db.commit()
        except Exception:
            # If ai_cache table doesn't exist, create it
            try:
                await self.db._db.execute("""
                    CREATE TABLE IF NOT EXISTS ai_cache (
                        cache_key TEXT PRIMARY KEY,
                        task_type TEXT,
                        response_data TEXT,
                        created_at REAL
                    )
                """)
                await self.db._db.commit()
                # Retry
                now = time.time()
                await self.db._db.execute(
                    """INSERT OR REPLACE INTO ai_cache (cache_key, task_type, response_data, created_at)
                    VALUES (?, ?, ?, ?)""",
                    (key, task_type, json.dumps(response, default=str), now),
                )
                await self.db._db.commit()
            except Exception as e:
                logger.debug(f"Cache write failed: {e}")

    def _put_memory(self, key: str, data: dict) -> None:
        """Put entry in memory cache, evicting LRU if needed."""
        self._memory[key] = {"data": data, "ts": time.time()}
        self._memory.move_to_end(key)
        while len(self._memory) > self._max_memory:
            self._memory.popitem(last=False)

    def _get_ttl(self, task_type: str) -> int:
        """Get TTL based on task type."""
        if task_type in ("image",):
            return CACHE_TTL_IMAGE
        return CACHE_TTL_TEXT

    async def cleanup(self) -> int:
        """Remove expired entries from both cache levels."""
        count = 0
        now = time.time()

        # Memory cleanup
        expired_keys = [
            k for k, v in self._memory.items()
            if now - v["ts"] > self._get_ttl("text")
        ]
        for k in expired_keys:
            del self._memory[k]
            count += 1

        # SQLite cleanup
        try:
            cursor = await self.db._db.execute(
                "DELETE FROM ai_cache WHERE created_at < ?", (now - CACHE_TTL_IMAGE,)
            )
            count += cursor.rowcount
            await self.db._db.commit()
        except Exception:
            pass

        return count
