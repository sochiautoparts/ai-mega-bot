"""Fireworks AI Provider — fast inference via OpenAI-compatible API.

Fireworks AI offers $1 signup credits + 50 free requests/day.
Models: Llama 3.3 70B, Mixtral, Qwen, and more.
Base URL: https://api.fireworks.ai/inference/v1
"""
import logging
from typing import Any, Dict, List, Optional

import httpx

from ai.providers.base import AIResponse, BaseProvider, ProviderError

logger = logging.getLogger(__name__)

TEXT_MODELS = {
    "default": "accounts/fireworks/models/llama-v3p3-70b-instruct",
    "fast": "accounts/fireworks/models/llama-v3p1-8b-instruct",
    "reasoning": "accounts/fireworks/models/deepseek-v3",
    "code": "accounts/fireworks/models/qwen2p5-coder-32b-instruct",
}


class FireworksProvider(BaseProvider):
    """Fireworks AI provider — fast inference, OpenAI-compatible API."""

    name: str = "fireworks"
    supports_streaming: bool = False

    def __init__(self, api_key: str = "", timeout: float = 30.0):
        super().__init__(api_key=api_key, timeout=timeout)

    async def init(self) -> None:
        """Initialize httpx async client with connection pooling."""
        self._client = httpx.AsyncClient(
            base_url="https://api.fireworks.ai",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    def _build_messages(
        self,
        prompt: str,
        system_prompt: str = "",
        history: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        """Build messages array with context memory."""
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            for msg in history:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
        last_is_current = (
            history and len(history) > 0
            and history[-1].get("role") == "user"
            and history[-1].get("content") == prompt
        )
        if not last_is_current:
            messages.append({"role": "user", "content": prompt})
        return messages

    async def generate(self, prompt: str, **kwargs) -> AIResponse:
        """Generate text via Fireworks AI chat completions with context."""
        if not self._client:
            await self.init()

        model_key: str = kwargs.get("model_key", "default")
        model: str = kwargs.get("model", TEXT_MODELS.get(model_key, TEXT_MODELS["default"]))
        system_prompt: str = kwargs.get("system_prompt", "")
        temperature: float = kwargs.get("temperature", 0.7)
        max_tokens: int = kwargs.get("max_tokens", 4096)
        history: Optional[List[Dict[str, str]]] = kwargs.get("history")

        messages = self._build_messages(prompt, system_prompt, history)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response = await self._client.post(
                "/inference/v1/chat/completions",
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
                    "context_messages": len(messages),
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
        """Translate text using Fireworks AI with translation system prompt."""
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
        return await self.generate(text, system_prompt=system_prompt, model_key="fast")
