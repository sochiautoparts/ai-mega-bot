"""
Usage tracking — Free tier limits and Pro license validation
"""

import sqlite3
import time
from pathlib import Path
from datetime import datetime, timedelta

from gitmoji_ai.config import get_settings


def _get_db() -> sqlite3.Connection:
    settings = get_settings()
    settings.ensure_config_dir()
    conn = sqlite3.connect(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            timestamp REAL NOT NULL,
            details TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS license (
            key TEXT PRIMARY KEY,
            activated_at REAL,
            expires_at REAL,
            email TEXT DEFAULT '',
            active INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    return conn


def track_usage(action: str, details: str = "") -> None:
    """Record a usage event"""
    conn = _get_db()
    conn.execute(
        "INSERT INTO usage (action, timestamp, details) VALUES (?, ?, ?)",
        (action, time.time(), details),
    )
    conn.commit()
    conn.close()


def get_monthly_usage(action: str) -> int:
    """Get usage count for the current month"""
    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0).timestamp()
    conn = _get_db()
    cursor = conn.execute(
        "SELECT COUNT(*) as cnt FROM usage WHERE action = ? AND timestamp >= ?",
        (action, month_start),
    )
    count = cursor.fetchone()["cnt"]
    conn.close()
    return count


def check_limit(action: str) -> tuple[bool, int]:
    """Check if action is within limits. Returns (allowed, remaining)"""
    settings = get_settings()

    # Pro users have no limits
    if settings.is_pro:
        return True, 999

    used = get_monthly_usage(action)

    if action == "commit":
        limit = settings.free_commits_per_month
    elif action == "changelog":
        limit = settings.free_changelog_per_month
    else:
        limit = 50  # default

    remaining = max(0, limit - used)
    return used < limit, remaining


def activate_license(key: str, email: str = "") -> bool:
    """Activate a Pro license key"""
    # In production, validate against API
    # For now, accept any non-empty key
    if not key or len(key) < 10:
        return False

    conn = _get_db()
    now = time.time()
    expires = now + (365 * 86400)  # 1 year

    conn.execute(
        "INSERT OR REPLACE INTO license (key, activated_at, expires_at, email, active) VALUES (?, ?, ?, ?, 1)",
        (key, now, expires, email),
    )
    conn.commit()
    conn.close()
    return True


def check_license_valid() -> bool:
    """Check if current license is valid"""
    settings = get_settings()
    if not settings.pro_license_key:
        return False

    conn = _get_db()
    cursor = conn.execute(
        "SELECT * FROM license WHERE key = ? AND active = 1 AND expires_at > ?",
        (settings.pro_license_key, time.time()),
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None


def get_usage_stats() -> dict:
    """Get usage statistics"""
    return {
        "commits_this_month": get_monthly_usage("commit"),
        "changelogs_this_month": get_monthly_usage("changelog"),
        "commit_limit": get_settings().free_commits_per_month,
        "changelog_limit": get_settings().free_changelog_per_month,
        "is_pro": get_settings().is_pro,
    }
