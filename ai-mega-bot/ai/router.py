"""AI Router — routes requests to optimal AI providers with fallback chains."""
import logging
from typing import Any, Dict, List, Optional

from ai.providers.base import BaseProvider, AIResponse, ProviderError
from ai.providers import ALL_PROVIDERS
from ai.rate_limiter import RateLimiter
from ai.cache import AICache
from bot.config import PROVIDER_CHAINS, PROVIDER_TIMEOUTS, get_provider_keys

logger = logging.getLogger(__name__)


class AllProvidersExhaustedError(Exception):
    """All providers in chain failed."""

    def __init__(self, task_type: str):
        self.task_type = task_type
        super().__init__(f"All providers exhausted for task: {task_type}")


class AIRouter:
    """Central AI request router with fallback chains and caching."""

    def __init__(self, db):
        self.db = db
        self.limiter = RateLimiter(db)
        self.cache = AICache(db)
        self.providers: Dict[str, BaseProvider] = {}
        self._chains: Dict[str, List[str]] = {}

    async def init(self) -> None:
        """Initialize all available providers."""
        available_keys = get_provider_keys()

        for name, provider_cls in ALL_PROVIDERS.items():
            try:
                if name.startswith("huggingface"):
                    sub_type = name.replace("huggingface", "").lstrip("_") or "text"
                    from bot.config import HF_TOKEN
                    provider = provider_cls(
                        api_key=HF_TOKEN,
                        sub_type=sub_type,
                        timeout=PROVIDER_TIMEOUTS.get("text", 15.0),
                    )
                    provider.name = name
                elif name == "groq_whisper":
                    from bot.config import GROQ_API_KEY
                    provider = provider_cls(
                        api_key=GROQ_API_KEY,
                        timeout=PROVIDER_TIMEOUTS.get("audio_stt", 30.0),
                    )
                    provider.name = name
                elif name == "groq":
                    from bot.config import GROQ_API_KEY
                    provider = provider_cls(
                        api_key=GROQ_API_KEY,
                        timeout=PROVIDER_TIMEOUTS.get("text", 15.0),
                    )
                elif name == "openrouter":
                    from bot.config import OPENROUTER_API_KEY
                    provider = provider_cls(
                        api_key=OPENROUTER_API_KEY,
                        timeout=PROVIDER_TIMEOUTS.get("text", 30.0),
                    )
                elif name == "github_models":
                    from bot.config import GITHUB_TOKEN
                    provider = provider_cls(
                        api_key=GITHUB_TOKEN,
                        timeout=PROVIDER_TIMEOUTS.get("code", 20.0),
                    )
                elif name == "gemini":
                    from bot.config import GEMINI_API_KEY
                    provider = provider_cls(
                        api_key=GEMINI_API_KEY,
                        timeout=PROVIDER_TIMEOUTS.get("text", 15.0),
                    )
                elif name == "pollinations":
                    provider = provider_cls(timeout=PROVIDER_TIMEOUTS.get("text", 30.0))
                elif name == "prodia":
                    provider = provider_cls(timeout=PROVIDER_TIMEOUTS.get("image", 45.0))
                elif name == "cerebras":
                    from bot.config import CEREBRAS_API_KEY
                    provider = provider_cls(
                        api_key=CEREBRAS_API_KEY,
                        timeout=PROVIDER_TIMEOUTS.get("text", 15.0),
                    )
                elif name == "grok":
                    from bot.config import GROK_API_KEY
                    provider = provider_cls(
                        api_key=GROK_API_KEY,
                        timeout=PROVIDER_TIMEOUTS.get("text", 30.0),
                    )
                else:
                    continue

                if provider.is_available():
                    await provider.init()
                    self.providers[name] = provider
                    logger.info(f"Provider initialized: {name}")
                else:
                    logger.warning(f"Provider not available (no key): {name}")

            except Exception as exc:
                logger.error(f"Failed to initialize provider {name}: {exc}")

        # Build chains with only available providers
        for task_type, chain in PROVIDER_CHAINS.items():
            self._chains[task_type] = [p for p in chain if p in self.providers]
            if not self._chains[task_type]:
                logger.warning(f"No providers available for task: {task_type}")
            else:
                logger.info(f"Provider chain for {task_type}: {self._chains[task_type]}")

    async def close(self) -> None:
        """Shutdown all providers."""
        for provider in self.providers.values():
            try:
                await provider.close()
            except Exception as exc:
                logger.error(f"Error closing provider {provider.name}: {exc}")

    async def route(
        self,
        task_type: str,
        prompt: str,
        user_id: int,
        tier: str = "free",
        **kwargs,
    ) -> AIResponse:
        """Route a request to the best available provider."""
        # Check cache first (unless skip_cache is set)
        skip_cache = kwargs.get("skip_cache", False)
        if not skip_cache:
            cached = await self.cache.get(prompt, task_type, **kwargs)
            if cached:
                return AIResponse(
                    text=cached.get("text", ""),
                    image_url=cached.get("image_url", ""),
                    image_bytes=cached.get("image_bytes", b"")
                    if isinstance(cached.get("image_bytes"), bytes)
                    else b"",
                    provider=cached.get("provider", "cache"),
                    model=cached.get("model", ""),
                    tokens_used=0,
                    metadata={"from_cache": True},
                )

        chain = self._chains.get(task_type, [])
        if not chain:
            raise AllProvidersExhaustedError(task_type)

        last_error: Optional[Exception] = None
        for provider_name in chain:
            provider = self.providers.get(provider_name)
            if not provider:
                continue

            # Check rate limits
            if not await self.limiter.can_use(provider_name, user_id, tier):
                logger.info(f"Rate limit hit for {provider_name}, trying next")
                continue

            try:
                if task_type == "image":
                    result = await provider.generate_image(prompt, **kwargs)
                elif task_type == "audio_stt":
                    audio_data = kwargs.get("audio_data", b"")
                    result = await provider.transcribe(audio_data, **kwargs)
                elif task_type == "audio_tts":
                    result = await provider.text_to_speech(prompt, **kwargs)
                elif task_type == "translate":
                    _kw = dict(kwargs)
                    src = _kw.pop("source_lang", "auto")
                    tgt = _kw.pop("target_lang", "ru")
                    _kw.pop("history", None)  # Not needed for translate
                    _kw.pop("skip_cache", None)
                    result = await provider.translate(
                        prompt,
                        source_lang=src,
                        target_lang=tgt,
                        **_kw,
                    )
                else:
                    # text, code — pass history for context
                    result = await provider.generate(prompt, **kwargs)

                # Validate result has content
                has_content = bool(result.text or result.image_bytes or result.image_url or result.audio_bytes)
                if not has_content:
                    logger.warning(f"Provider {provider_name} returned empty result, trying next")
                    continue

                # Record usage
                await self.limiter.record_usage(
                    provider_name, user_id, task_type, result.tokens_used
                )

                # Cache the result (only if not skip_cache)
                if not skip_cache:
                    cache_data = {
                        "text": result.text,
                        "image_url": result.image_url,
                        "provider": result.provider,
                        "model": result.model,
                    }
                    await self.cache.put(prompt, task_type, cache_data, **kwargs)

                return result

            except ProviderError as e:
                last_error = e
                logger.warning(f"Provider {provider_name} failed: {e}")
                if not e.retryable:
                    break
                continue
            except Exception as e:
                last_error = e
                logger.error(f"Unexpected error from {provider_name}: {e}")
                continue

        logger.error(f"All providers exhausted for {task_type}. Last error: {last_error}")
        raise AllProvidersExhaustedError(task_type)

    async def get_status(self) -> Dict[str, Any]:
        """Get status of all providers."""
        status: Dict[str, Any] = {}
        for name, provider in self.providers.items():
            try:
                used, limit = await self.limiter.get_provider_remaining(name)
                status[name] = {
                    "available": True,
                    "used_today": used,
                    "daily_limit": limit,
                    "remaining": max(0, limit - used),
                }
            except Exception as exc:
                status[name] = {
                    "available": False,
                    "error": str(exc),
                }
        return status
