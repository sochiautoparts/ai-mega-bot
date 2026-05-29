"""Rate Limiter — tracks per-user and per-provider usage."""
import logging
import time
from typing import Dict, Optional, Tuple

from bot.config import TIER_LIMITS

logger = logging.getLogger(__name__)

# Provider daily limits (free tier)
PROVIDER_DAILY_LIMITS = {
    "groq": 14400,
    "openrouter": 10000,
    "github_models": 200,
    "gemini": 1500,
    "huggingface": 5000,
    "huggingface_img": 1000,
    "huggingface_whisper": 500,
    "huggingface_tts": 500,
    "huggingface_nllb": 1000,
    "pollinations": 99999,
    "prodia": 99999,
    "groq_whisper": 500,
    "cerebras": 10000,
}


class RateLimiter:
    """Multi-level rate limiter."""

    def __init__(self, db):
        self.db = db

    async def can_use(self, provider: str, user_id: int, tier: str) -> bool:
        """Check if request is allowed for user and provider."""
        # Check provider's daily limit
        provider_limit = PROVIDER_DAILY_LIMITS.get(provider, 9999)
        provider_used = await self.db.get_provider_usage(provider)
        if provider_used >= provider_limit:
            logger.warning(
                f"Provider {provider} daily limit reached: {provider_used}/{provider_limit}"
            )
            return False

        return True

    async def record_usage(
        self,
        provider: str,
        user_id: int,
        task_type: str,
        tokens: int = 0,
    ) -> None:
        """Record usage for both user and provider."""
        await self.db.record_usage(user_id, task_type, provider, tokens)
        await self.db.increment_provider_usage(provider)

    async def get_user_remaining(
        self, user_id: int, task_type: str, tier: str
    ) -> Tuple[int, int]:
        """Get (used, limit) for user's task type."""
        limit_map = {
            "text": "text_requests",
            "image": "image_requests",
            "audio_stt": "audio_transcriptions",
            "translate": "translations",
            "code": "code_requests",
        }
        limit_key = limit_map.get(task_type, "text_requests")
        limit = getattr(TIER_LIMITS.get(tier, TIER_LIMITS["free"]), limit_key, 10)
        used = await self.db.get_daily_usage(user_id, task_type)
        return used, limit

    async def get_provider_remaining(self, provider: str) -> Tuple[int, int]:
        """Get (used, limit) for provider."""
        limit = PROVIDER_DAILY_LIMITS.get(provider, 9999)
        used = await self.db.get_provider_usage(provider)
        return used, limit
