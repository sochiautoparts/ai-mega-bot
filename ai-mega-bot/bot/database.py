"""
AI Mega Bot — Database Module.

SQLite with WAL mode for concurrent access.
All operations are async via aiosqlite.
"""
import aiosqlite
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bot.config import DB_PATH, TIER_LIMITS, LICENSE_PREFIX

logger = logging.getLogger(__name__)

# ── Schema Version ───────────────────────────────────────────
SCHEMA_VERSION = 1

# ── SQL Schema ───────────────────────────────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    language_code TEXT DEFAULT 'ru',
    referred_by INTEGER,
    referral_code TEXT UNIQUE,
    subscription_tier TEXT DEFAULT 'free',
    created_at REAL
);

CREATE TABLE IF NOT EXISTS licenses (
    key TEXT PRIMARY KEY,
    user_id INTEGER,
    project TEXT DEFAULT 'ai-mega-bot',
    plan TEXT,
    activated_at REAL,
    expires_at REAL DEFAULT 0,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    project TEXT,
    plan TEXT,
    stars_amount INTEGER,
    telegram_charge_id TEXT,
    license_key TEXT,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS referrals (
    referrer_id INTEGER,
    referred_id INTEGER,
    bonus_given INTEGER DEFAULT 0,
    created_at REAL,
    PRIMARY KEY (referrer_id, referred_id)
);

CREATE TABLE IF NOT EXISTS ai_usage (
    user_id INTEGER,
    task_type TEXT,
    provider TEXT,
    date TEXT,
    count INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, task_type, provider, date)
);

CREATE TABLE IF NOT EXISTS provider_limits (
    provider TEXT PRIMARY KEY,
    model TEXT,
    daily_limit INTEGER,
    used_today INTEGER DEFAULT 0,
    last_reset TEXT
);

CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    role TEXT,
    content TEXT,
    tokens INTEGER DEFAULT 0,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS api_keys (
    key TEXT PRIMARY KEY,
    project TEXT,
    description TEXT,
    created_at REAL
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_users_tier ON users(subscription_tier);
CREATE INDEX IF NOT EXISTS idx_licenses_user ON licenses(user_id, active);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_ai_usage_user_date ON ai_usage(user_id, date);
CREATE INDEX IF NOT EXISTS idx_chat_history_user ON chat_history(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_payments_created ON payments(created_at);
"""


class Database:
    """Async SQLite database with WAL mode."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def init(self) -> None:
        """Initialize database connection and create schema."""
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path)
        # Enable WAL mode for concurrent read/write
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA cache_size=-64000")  # 64MB cache
        await self._db.execute("PRAGMA temp_store=MEMORY")

        # Create schema
        await self._db.executescript(SCHEMA_SQL)

        # Check/set schema version
        async with self._db.execute("SELECT version FROM schema_version") as cur:
            row = await cur.fetchone()
            if row is None:
                await self._db.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (SCHEMA_VERSION,)
                )

        await self._db.commit()
        logger.info(f"Database initialized: {self.db_path}")

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # ── User Operations ──────────────────────────────────────

    async def get_or_create_user(
        self, user_id: int, username: str = "", first_name: str = "",
        language_code: str = "ru", referred_by: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get user or create if not exists. Returns user dict."""
        async with self._db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, row))

        # Generate referral code
        import secrets
        ref_code = f"REF{secrets.token_hex(4).upper()}"

        now = time.time()
        await self._db.execute(
            """INSERT OR IGNORE INTO users
            (user_id, username, first_name, language_code, referred_by,
             referral_code, subscription_tier, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'free', ?)""",
            (user_id, username, first_name, language_code,
             referred_by, ref_code, now)
        )
        await self._db.commit()

        # Record referral
        if referred_by:
            await self._db.execute(
                """INSERT OR IGNORE INTO referrals
                (referrer_id, referred_id, bonus_given, created_at)
                VALUES (?, ?, 0, ?)""",
                (referred_by, user_id, now)
            )
            await self._db.commit()

        return {
            "user_id": user_id, "username": username,
            "first_name": first_name, "language_code": language_code,
            "referred_by": referred_by, "referral_code": ref_code,
            "subscription_tier": "free", "created_at": now,
        }

    async def get_user_tier(self, user_id: int) -> str:
        """Get user's subscription tier (free/pro/ultra)."""
        # Check active license first
        now = time.time()
        async with self._db.execute(
            """SELECT plan FROM licenses
            WHERE user_id = ? AND active = 1
            AND (expires_at = 0 OR expires_at > ?)
            ORDER BY
                CASE plan
                    WHEN 'ultra' THEN 3
                    WHEN 'pro' THEN 2
                    ELSE 1
                END DESC
            LIMIT 1""",
            (user_id, now)
        ) as cur:
            row = await cur.fetchone()
            if row and row[0] in ("pro", "ultra"):
                return row[0]

        # Fallback to user record
        async with self._db.execute(
            "SELECT subscription_tier FROM users WHERE user_id = ?",
            (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else "free"

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        async with self._db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, row))
        return None

    # ── License Operations ───────────────────────────────────

    async def create_license(
        self, user_id: int, plan: str, duration_days: int = 0
    ) -> str:
        """Generate and activate a license key."""
        import secrets
        tier_code = plan[0].upper()  # P for pro, U for ultra
        part1 = secrets.token_hex(2).upper()
        part2 = secrets.token_hex(2).upper()
        key = f"{LICENSE_PREFIX}-{tier_code}{part1}-{part2}"

        now = time.time()
        expires_at = 0.0
        if duration_days > 0:
            expires_at = now + (duration_days * 86400)

        await self._db.execute(
            """INSERT INTO licenses
            (key, user_id, plan, activated_at, expires_at, active)
            VALUES (?, ?, ?, ?, ?, 1)""",
            (key, user_id, plan, now, expires_at)
        )

        # Update user tier
        await self._db.execute(
            "UPDATE users SET subscription_tier = ? WHERE user_id = ?",
            (plan, user_id)
        )
        await self._db.commit()
        return key

    async def activate_license(self, user_id: int, key: str) -> bool:
        """Activate a license key for a user."""
        async with self._db.execute(
            "SELECT key, plan, active FROM licenses WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            if not row or row[2] == 0:
                return False

        # Deactivate if already used by someone else
        await self._db.execute(
            "UPDATE licenses SET active = 0, user_id = ? WHERE key = ?",
            (user_id, key)
        )
        # Actually activate it
        await self._db.execute(
            "UPDATE licenses SET active = 1, user_id = ? WHERE key = ?",
            (user_id, key)
        )

        plan = row[1]
        await self._db.execute(
            "UPDATE users SET subscription_tier = ? WHERE user_id = ?",
            (plan, user_id)
        )
        await self._db.commit()
        return True

    async def get_user_licenses(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all licenses for a user."""
        async with self._db.execute(
            """SELECT key, plan, activated_at, expires_at, active
            FROM licenses WHERE user_id = ?
            ORDER BY activated_at DESC""",
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in rows]

    async def check_user_license(self, user_id: int) -> Dict[str, Any]:
        """Check if user has an active license."""
        now = time.time()
        async with self._db.execute(
            """SELECT key, plan, activated_at, expires_at
            FROM licenses
            WHERE user_id = ? AND active = 1
            AND (expires_at = 0 OR expires_at > ?)
            ORDER BY activated_at DESC LIMIT 1""",
            (user_id, now)
        ) as cur:
            row = await cur.fetchone()
            if row:
                columns = [desc[0] for desc in cur.description]
                return {"has_license": True, **dict(zip(columns, row))}
        return {"has_license": False}

    # ── Payment Operations ───────────────────────────────────

    async def record_payment(
        self, user_id: int, plan: str, stars_amount: int,
        telegram_charge_id: str, license_key: str
    ) -> int:
        """Record a payment."""
        now = time.time()
        cur = await self._db.execute(
            """INSERT INTO payments
            (user_id, project, plan, stars_amount, telegram_charge_id,
             license_key, created_at)
            VALUES (?, 'ai-mega-bot', ?, ?, ?, ?, ?)""",
            (user_id, plan, stars_amount, telegram_charge_id,
             license_key, now)
        )
        await self._db.commit()
        return cur.lastrowid

    # ── AI Usage Operations ──────────────────────────────────

    async def get_daily_usage(self, user_id: int, task_type: str) -> int:
        """Get today's usage count for a user and task type."""
        today = time.strftime("%Y-%m-%d")
        async with self._db.execute(
            """SELECT COALESCE(SUM(count), 0) FROM ai_usage
            WHERE user_id = ? AND task_type = ? AND date = ?""",
            (user_id, task_type, today)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def record_usage(
        self, user_id: int, task_type: str, provider: str,
        tokens: int = 0
    ) -> None:
        """Record an AI usage event."""
        today = time.strftime("%Y-%m-%d")
        await self._db.execute(
            """INSERT INTO ai_usage (user_id, task_type, provider, date, count, tokens_used)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(user_id, task_type, provider, date)
            DO UPDATE SET count = count + 1, tokens_used = tokens_used + ?""",
            (user_id, task_type, provider, today, tokens, tokens)
        )
        await self._db.commit()

    async def get_usage_stats(self, user_id: int) -> Dict[str, int]:
        """Get today's usage stats for all task types."""
        today = time.strftime("%Y-%m-%d")
        stats = {}
        async with self._db.execute(
            """SELECT task_type, COALESCE(SUM(count), 0)
            FROM ai_usage
            WHERE user_id = ? AND date = ?
            GROUP BY task_type""",
            (user_id, today)
        ) as cur:
            async for row in cur:
                stats[row[0]] = row[1]
        return stats

    # ── Chat History ─────────────────────────────────────────

    async def add_chat_message(
        self, user_id: int, role: str, content: str, tokens: int = 0
    ) -> None:
        """Add a message to chat history."""
        now = time.time()
        await self._db.execute(
            """INSERT INTO chat_history (user_id, role, content, tokens, created_at)
            VALUES (?, ?, ?, ?, ?)""",
            (user_id, role, content, tokens, now)
        )
        await self._db.commit()

    async def get_chat_history(
        self, user_id: int, limit: int = 20, max_age_days: int = 30
    ) -> List[Dict[str, str]]:
        """Get chat history for a user. max_age_days=0 means current session only (1 hour)."""
        if max_age_days <= 0:
            # Current session only: last 1 hour
            cutoff = time.time() - 3600
        else:
            cutoff = time.time() - (max_age_days * 86400)
        messages = []
        async with self._db.execute(
            """SELECT role, content FROM chat_history
            WHERE user_id = ? AND created_at > ?
            ORDER BY created_at DESC LIMIT ?""",
            (user_id, cutoff, limit)
        ) as cur:
            async for row in cur:
                messages.append({"role": row[0], "content": row[1]})
        # Return in chronological order
        messages.reverse()
        return messages

    async def clear_chat_history(self, user_id: int) -> None:
        """Clear chat history for a user."""
        await self._db.execute(
            "DELETE FROM chat_history WHERE user_id = ?", (user_id,)
        )
        await self._db.commit()

    # ── Provider Limits ──────────────────────────────────────

    async def get_provider_usage(self, provider: str) -> int:
        """Get today's usage count for a provider."""
        today = time.strftime("%Y-%m-%d")
        async with self._db.execute(
            """SELECT used_today FROM provider_limits
            WHERE provider = ? AND last_reset = ?""",
            (provider, today)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def increment_provider_usage(self, provider: str) -> None:
        """Increment provider usage counter."""
        today = time.strftime("%Y-%m-%d")
        await self._db.execute(
            """INSERT INTO provider_limits (provider, model, daily_limit, used_today, last_reset)
            VALUES (?, '', 0, 1, ?)
            ON CONFLICT(provider) DO UPDATE SET
                used_today = CASE WHEN last_reset = ? THEN used_today + 1 ELSE 1 END,
                last_reset = ?""",
            (provider, today, today, today)
        )
        await self._db.commit()

    # ── Referral Operations ──────────────────────────────────

    async def process_referral_bonus(self, referrer_id: int, referred_id: int) -> int:
        """Process referral bonus when referred user makes a payment."""
        tier = await self.get_user_tier(referrer_id)
        bonus = TIER_LIMITS.get(tier, TIER_LIMITS["free"]).referral_bonus

        async with self._db.execute(
            """SELECT bonus_given FROM referrals
            WHERE referrer_id = ? AND referred_id = ?""",
            (referrer_id, referred_id)
        ) as cur:
            row = await cur.fetchone()
            if row and not row[0]:
                await self._db.execute(
                    """UPDATE referrals SET bonus_given = 1
                    WHERE referrer_id = ? AND referred_id = ?""",
                    (referrer_id, referred_id)
                )
                await self._db.commit()
                return bonus
        return 0

    async def get_referral_stats(self, user_id: int) -> Dict[str, Any]:
        """Get referral statistics for a user."""
        async with self._db.execute(
            """SELECT COUNT(*) as total,
                   SUM(CASE WHEN bonus_given = 1 THEN 1 ELSE 0 END) as converted
            FROM referrals WHERE referrer_id = ?""",
            (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return {
                "total_referrals": row[0] if row else 0,
                "converted": row[1] if row else 0,
            }

    # ── Data Export ──────────────────────────────────────────

    async def export_licenses(self) -> List[Dict[str, Any]]:
        """Export active licenses for public JSON API."""
        now = time.time()
        licenses = []
        async with self._db.execute(
            """SELECT key, user_id, plan, activated_at, expires_at
            FROM licenses WHERE active = 1
            AND (expires_at = 0 OR expires_at > ?)""",
            (now,)
        ) as cur:
            async for row in cur:
                licenses.append({
                    "key": row[0],
                    "user_id": row[1],
                    "plan": row[2],
                    "activated_at": row[3],
                    "expires_at": row[4],
                })
        return licenses

    async def export_stats(self) -> Dict[str, Any]:
        """Export bot statistics."""
        async with self._db.execute("SELECT COUNT(*) FROM users") as cur:
            total_users = (await cur.fetchone())[0]

        async with self._db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM payments"
        ) as cur:
            paying_users = (await cur.fetchone())[0]

        today = time.strftime("%Y-%m-%d")
        async with self._db.execute(
            """SELECT task_type, SUM(count), SUM(tokens_used)
            FROM ai_usage WHERE date = ? GROUP BY task_type""",
            (today,)
        ) as cur:
            usage_today = {}
            async for row in cur:
                usage_today[row[0]] = {
                    "requests": row[1],
                    "tokens": row[2],
                }

        return {
            "total_users": total_users,
            "paying_users": paying_users,
            "usage_today": usage_today,
            "timestamp": time.time(),
        }

    # ── Admin Operations ─────────────────────────────────────

    async def get_all_stats(self) -> Dict[str, Any]:
        """Get comprehensive admin statistics."""
        stats = await self.export_stats()

        async with self._db.execute(
            "SELECT subscription_tier, COUNT(*) FROM users GROUP BY subscription_tier"
        ) as cur:
            tier_dist = {}
            async for row in cur:
                tier_dist[row[0]] = row[1]
        stats["tier_distribution"] = tier_dist

        async with self._db.execute(
            """SELECT provider, used_today, last_reset
            FROM provider_limits WHERE last_reset = ?""",
            (time.strftime("%Y-%m-%d"),)
        ) as cur:
            provider_stats = {}
            async for row in cur:
                provider_stats[row[0]] = {
                    "used_today": row[1],
                    "last_reset": row[2],
                }
        stats["provider_stats"] = provider_stats

        async with self._db.execute(
            "SELECT COALESCE(SUM(stars_amount), 0) FROM payments"
        ) as cur:
            stats["total_revenue_stars"] = (await cur.fetchone())[0]

        return stats

    async def reset_user_limits(self, user_id: int) -> None:
        """Reset daily limits for a user (admin only)."""
        today = time.strftime("%Y-%m-%d")
        await self._db.execute(
            "DELETE FROM ai_usage WHERE user_id = ? AND date = ?",
            (user_id, today)
        )
        await self._db.commit()

    async def genkey(self, tier: str, user_id: int = 0) -> str:
        """Generate a license key (admin only)."""
        return await self.create_license(user_id, tier, duration_days=0)
