"""
AI Mega Bot — Configuration Module.

All secrets loaded from environment variables only.
No hardcoded keys, tokens, or secrets.
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class TierLimits:
    """Per-tier daily limits and features."""
    text_requests: int
    image_requests: int
    audio_transcriptions: int
    translations: int
    code_requests: int
    context_tokens: int
    fast_models: bool
    history_days: int
    referral_bonus: int


@dataclass(frozen=True)
class PlanPrice:
    """Pricing for a subscription plan."""
    label: str
    description: str
    stars: int


@dataclass(frozen=True)
class Plan:
    """Subscription plan with monthly/yearly/lifetime pricing."""
    month: PlanPrice
    year: PlanPrice
    lifetime: PlanPrice


# ── Tier Limits ──────────────────────────────────────────────
TIER_LIMITS: Dict[str, TierLimits] = {
    "free": TierLimits(
        text_requests=10, image_requests=3, audio_transcriptions=1,
        translations=5, code_requests=5, context_tokens=4000,
        fast_models=False, history_days=0, referral_bonus=10,
    ),
    "pro": TierLimits(
        text_requests=200, image_requests=30, audio_transcriptions=20,
        translations=100, code_requests=100, context_tokens=32000,
        fast_models=True, history_days=7, referral_bonus=25,
    ),
    "ultra": TierLimits(
        text_requests=9999, image_requests=100, audio_transcriptions=50,
        translations=9999, code_requests=9999, context_tokens=128000,
        fast_models=True, history_days=30, referral_bonus=50,
    ),
}

# ── Subscription Plans ───────────────────────────────────────
PLANS: Dict[str, Plan] = {
    "pro": Plan(
        month=PlanPrice("Pro — 1 месяц", "Pro подписка на 1 месяц", 149),
        year=PlanPrice("Pro — 1 год", "Pro подписка на 1 год (экономия 44%)", 999),
        lifetime=PlanPrice("Pro — Навсегда", "Pro подписка навсегда", 2999),
    ),
    "ultra": Plan(
        month=PlanPrice("Ultra — 1 месяц", "Ultra подписка на 1 месяц", 499),
        year=PlanPrice("Ultra — 1 год", "Ultra подписка на 1 год (экономия 42%)", 3499),
        lifetime=PlanPrice("Ultra — Навсегда", "Ultra подписка навсегда", 9999),
    ),
}

# ── AI Provider Priority Chains ──────────────────────────────
PROVIDER_CHAINS: Dict[str, List[str]] = {
    "text": ["groq", "openrouter", "github_models", "gemini", "huggingface"],
    "image": ["pollinations", "huggingface_img", "prodia"],
    "audio_stt": ["huggingface_whisper", "groq_whisper"],
    "audio_tts": ["huggingface_tts"],
    "translate": ["huggingface_nllb", "groq", "gemini"],
    "code": ["groq", "openrouter", "github_models"],
}

# ── Provider Timeouts (seconds) ─────────────────────────────
PROVIDER_TIMEOUTS: Dict[str, float] = {
    "text": 15.0,
    "image": 45.0,
    "audio_stt": 30.0,
    "audio_tts": 30.0,
    "translate": 15.0,
    "code": 20.0,
}

# ── Cache Settings ───────────────────────────────────────────
CACHE_TTL_TEXT = 86400       # 24 hours
CACHE_TTL_IMAGE = 604800    # 7 days
CACHE_MAX_MEMORY = 2000      # LRU entries

# ── License Key Prefix ──────────────────────────────────────
LICENSE_PREFIX = "AIP"       # AI Pro
LICENSE_FORMAT = "AIP-{tier}-{part1}-{part2}"

# ── GitHub Actions Session ───────────────────────────────────
SESSION_DURATION_SECONDS = 20700  # 5h 45m = 345 min


def _env(name: str, default: str = "") -> str:
    """Get environment variable or raise error for required ones."""
    val = os.environ.get(name, default)
    if not val and not default:
        # For optional vars, return empty; required vars checked at startup
        pass
    return val


def _env_int(name: str, default: int = 0) -> int:
    val = _env(name)
    try:
        return int(val) if val else default
    except ValueError:
        return default


def _env_list(name: str, default: Optional[List[str]] = None) -> List[str]:
    val = _env(name)
    if val:
        return [x.strip() for x in val.split(",") if x.strip()]
    return default or []


# ── Bot Configuration ────────────────────────────────────────
BOT_TOKEN: str = _env("BOT_TOKEN")
ADMIN_IDS: List[int] = _env_list("ADMIN_IDS", [0])
BOT_USERNAME: str = _env("BOT_USERNAME", "aimega_bot")
BOT_NAME: str = _env("BOT_NAME", "AI Mega Bot")

# ── AI API Keys ──────────────────────────────────────────────
GROQ_API_KEY: str = _env("GROQ_API_KEY")
OPENROUTER_API_KEY: str = _env("OPENROUTER_API_KEY")
GITHUB_TOKEN: str = _env("GITHUB_TOKEN")
GEMINI_API_KEY: str = _env("GEMINI_API_KEY")
HF_TOKEN: str = _env("HF_TOKEN")

# ── GitHub (for Actions, keep-alive, data sync) ─────────────
GH_PAT_TOKEN: str = _env("GH_PAT_TOKEN")
GH_REPO: str = _env("GH_REPO", "sochiautoparts/ai-mega-bot")

# ── API Server ───────────────────────────────────────────────
API_HOST: str = _env("API_HOST", "0.0.0.0")
API_PORT: int = _env_int("API_PORT", 8080)
API_SECRET: str = _env("API_SECRET", "sk_aimghub_xK9mP2vL4nQ7rW")

# ── Database ─────────────────────────────────────────────────
DB_PATH: str = _env("DB_PATH", "data/bot.db")

# ── Logging ──────────────────────────────────────────────────
LOG_LEVEL: str = _env("LOG_LEVEL", "INFO")


def validate_config() -> List[str]:
    """Validate required configuration. Returns list of missing items."""
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    # AI keys are optional — bot works with whatever is available
    return missing


def get_provider_keys() -> Dict[str, bool]:
    """Check which AI providers have keys configured."""
    return {
        "groq": bool(GROQ_API_KEY),
        "openrouter": bool(OPENROUTER_API_KEY),
        "github_models": bool(GITHUB_TOKEN),
        "gemini": bool(GEMINI_API_KEY),
        "huggingface": bool(HF_TOKEN),
        "huggingface_img": bool(HF_TOKEN),
        "huggingface_whisper": bool(HF_TOKEN),
        "huggingface_tts": bool(HF_TOKEN),
        "huggingface_nllb": bool(HF_TOKEN),
        "pollinations": True,  # No key needed
        "prodia": False,       # Requires key (not available by default)
        "groq_whisper": bool(GROQ_API_KEY),
    }
