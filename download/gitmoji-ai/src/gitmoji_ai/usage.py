"""
Usage tracking — Free tier limits and Pro license validation
Supports StarsPay API for real license validation
"""

import sqlite3
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta

import httpx

from gitmoji_ai.config import get_settings

logger = logging.getLogger(__name__)

# StarsPay API configuration
STARSPAY_API_URL = "https://starspay.example.com"  # Replace with your server
STARSPAY_API_KEY = ""  # Set via GMAI_STARSPAY_API_KEY env var
PRODUCT_ID = "gitmoji-ai"


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
            plan_id TEXT DEFAULT 'pro',
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


def validate_license_via_api(key: str, product_id: str = PRODUCT_ID) -> dict:
    """
    Validate a license key via StarsPay API.
    Returns: {"valid": bool, "plan_id": str, "expires_at": float, ...}
    """
    api_url = getattr(settings_instance(), 'starspay_api_url', STARSPAY_API_URL)
    api_key = getattr(settings_instance(), 'starspay_api_key', STARSPAY_API_KEY)

    try:
        response = httpx.get(
            f"{api_url}/api/v1/validate",
            params={"key": key, "product": product_id},
            headers={"X-API-Key": api_key},
            timeout=10,
        )
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.warning(f"API validation failed, falling back to local: {e}")

    # Fallback: local validation
    return _local_validate(key)


def _local_validate(key: str) -> dict:
    """Local fallback validation"""
    if not key or len(key) < 10:
        return {"valid": False, "reason": "invalid_format"}

    if not key.startswith("SP-"):
        return {"valid": False, "reason": "invalid_prefix"}

    conn = _get_db()
    cursor = conn.execute(
        "SELECT * FROM license WHERE key = ? AND active = 1 AND expires_at > ?",
        (key, time.time()),
    )
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "valid": True,
            "plan_id": row["plan_id"] if "plan_id" in row.keys() else "pro",
            "expires_at": row["expires_at"],
        }
    return {"valid": False, "reason": "not_found"}


def settings_instance():
    """Get settings instance (avoid circular import issues)"""
    return get_settings()


def activate_license(key: str, email: str = "") -> bool:
    """
    Activate a Pro license key.
    Validates against StarsPay API first, then saves locally.
    """
    if not key or len(key) < 10:
        return False

    # Validate via StarsPay API
    result = validate_license_via_api(key)

    if not result.get("valid"):
        # Also try local validation for offline/cached keys
        local = _local_validate(key)
        if not local.get("valid"):
            return False
        result = local

    # Save locally
    conn = _get_db()
    now = time.time()
    expires_at = result.get("expires_at", now + (30 * 86400))
    plan_id = result.get("plan_id", "pro")

    conn.execute(
        "INSERT OR REPLACE INTO license (key, activated_at, expires_at, plan_id, email, active) VALUES (?, ?, ?, ?, ?, 1)",
        (key, now, expires_at, plan_id, email),
    )
    conn.commit()
    conn.close()
    return True


def check_license_valid() -> bool:
    """Check if current license is valid (local check)"""
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


def check_license_with_api() -> dict:
    """
    Full license check via API + local.
    Returns detailed info about the license status.
    """
    settings = get_settings()
    key = settings.pro_license_key

    if not key:
        return {"valid": False, "reason": "no_key", "tier": "free"}

    # Try API first
    result = validate_license_via_api(key)

    if result.get("valid"):
        return {
            "valid": True,
            "tier": result.get("plan_id", "pro"),
            "expires_at": result.get("expires_at"),
            "source": "api"
        }

    # Fallback to local
    if check_license_valid():
        return {
            "valid": True,
            "tier": "pro",
            "source": "local_cache"
        }

    return {"valid": False, "reason": result.get("reason", "expired"), "tier": "free"}


def get_usage_stats() -> dict:
    """Get usage statistics"""
    return {
        "commits_this_month": get_monthly_usage("commit"),
        "changelogs_this_month": get_monthly_usage("changelog"),
        "commit_limit": get_settings().free_commits_per_month,
        "changelog_limit": get_settings().free_changelog_per_month,
        "is_pro": get_settings().is_pro,
        "license_status": check_license_with_api(),
    }
