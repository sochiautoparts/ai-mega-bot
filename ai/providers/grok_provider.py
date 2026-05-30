"""xAI Grok Provider — Grok models via xAI API (OpenAI-compatible).

Supports:
  - Text generation with conversation history
  - Translation via system prompt
  - Vision not currently available via free tier
"""
import logging
from typing import Any, Dict, List, Optional

import httpx

from ai.providers.base import AIResponse, BaseProvider, ProviderError

logger = logging.getLogger(__name__)

# ── Model registry ───────────────────────────────────────────
TEXT_MODELS = {
    "default": "grok-3-mini-fast",
    "reasoning": "grok-3-mini",
}

CHAT_URL = "https://api.x.ai/v1/chat/completions"


class GrokProvider(BaseProvider):
    """xAI Grok provider using httpx for OpenAI-compatible API."""

    name: str = "grok"
    supports_streaming: bool = False
    supports_vision: bool = False

    def __init__(self, api_key: str = "", timeout: float = 30.0):
        super().__init__(api_key=api_key, timeout=timeout)

    async def init(self) -> None:
        """Initialize httpx async client with connection pooling."""
        self._client = httpx.AsyncClient(
            base_url="https://api.x.ai",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(self.timeout, connect=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    async def generate(self, prompt: str, **kwargs) -> AIResponse:
        """Generate text via Grok chat completions with conversation history."""
        if not self._client:
            await self.init()

        model_key: str = kwargs.get("model_key", "default")
        model: str = kwargs.get("model", TEXT_MODELS.get(model_key, TEXT_MODELS["default"]))
        system_prompt: str = kwargs.get("system_prompt", "")
        temperature: float = kwargs.get("temperature", 0.7)
        max_tokens: int = kwargs.get("max_tokens", 4096)
        messages_history: Optional[List[Dict[str, Any]]] = kwargs.get("messages")

        # Build messages with history support
        messages = self._build_messages(prompt, system_prompt, messages_history)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response = await self._client.post(
                "/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            choice = data["choices"][0]
            usage = data.get("usage", {})

            return AIResponse(
                text=choice["message"]["content"],
                provider=self.name,
                model=model,
                tokens_used=usage.get("total_tokens", 0),
                finish_reason=choice.get("finish_reason", ""),
                metadata={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                },
            )

        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, f"Request timed out: {exc}", retryable=True)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status in (429, 500, 502, 503, 504)
            raise ProviderError(
                self.name,
                f"HTTP {status}: {exc.response.text[:200]}",
                retryable=retryable,
            )
        except Exception as exc:
            raise ProviderError(self.name, f"Unexpected error: {exc}", retryable=True)

    async def translate(
        self,
        text: str,
        source_lang: str = "auto",
        target_lang: str = "ru",
        **kwargs,
    ) -> AIResponse:
        """Translate text using Grok with translation system prompt."""
        lang_names = {
            "ru": "Russian", "en": "English", "de": "German",
            "fr": "French", "es": "Spanish", "it": "Italian",
            "pt": "Portuguese", "zh": "Chinese", "ja": "Japanese",
            "ko": "Korean", "ar": "Arabic", "hi": "Hindi",
            "tr": "Turkish", "uk": "Ukrainian", "pl": "Polish",
        }

        src_name = lang_names.get(source_lang, source_lang)
        tgt_name = lang_names.get(target_lang, target_lang)

        if source_lang and source_lang != "auto":
            system_prompt = (
                f"You are a professional translator. Translate the following text "
                f"from {src_name} to {tgt_name}. Output only the translation, "
                f"nothing else. Maintain the original tone and style."
            )
        else:
            system_prompt = (
                f"You are a professional translator. Translate the following text "
                f"to {tgt_name}. Output only the translation, nothing else. "
                f"Maintain the original tone and style."
            )

        return await self.generate(text, system_prompt=system_prompt, **kwargs)
