"""OpenRouter AI Provider — access to multiple free models including vision.

Supports:
  - Text generation with conversation history
  - Vision (image understanding) via free vision models
  - Multiple free model options
"""
import base64
import logging
from typing import Any, Dict, List, Optional

import httpx

from ai.providers.base import AIResponse, BaseProvider, ProviderError

logger = logging.getLogger(__name__)

CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

FREE_MODELS = {
    "default": "google/gemma-4-31b-it:free",
    "fast": "qwen/qwen3-coder:free",
    "reasoning": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "code": "qwen/qwen3-coder:free",
}

# Vision-capable free models on OpenRouter
VISION_MODELS = {
    "default": "google/gemma-4-31b-it:free",  # Gemma 4 supports vision
    "fast": "qwen/qwen2.5-vl-72b-instruct:free",
}


class OpenRouterProvider(BaseProvider):
    """OpenRouter provider using httpx for access to free models."""

    name: str = "openrouter"
    supports_streaming: bool = False
    supports_vision: bool = True

    def __init__(self, api_key: str = "", timeout: float = 15.0):
        super().__init__(api_key=api_key, timeout=timeout)

    async def init(self) -> None:
        """Initialize httpx async client with connection pooling."""
        self._client = httpx.AsyncClient(
            base_url="https://openrouter.ai",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/sochiautoparts/ai-mega-bot",
                "X-Title": "AI Mega Bot",
            },
            timeout=httpx.Timeout(self.timeout, connect=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    async def generate(self, prompt: str, **kwargs) -> AIResponse:
        """Generate text via OpenRouter chat completions with conversation history."""
        if not self._client:
            await self.init()

        model_key: str = kwargs.get("model_key", "default")
        model: str = kwargs.get("model", FREE_MODELS.get(model_key, FREE_MODELS["default"]))
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
                "/api/v1/chat/completions",
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

    async def generate_with_vision(
        self,
        prompt: str,
        image_data: bytes = b"",
        image_url: str = "",
        **kwargs,
    ) -> AIResponse:
        """Generate response with image understanding via vision model."""
        if not self._client:
            await self.init()

        system_prompt: str = kwargs.get("system_prompt", "")
        temperature: float = kwargs.get("temperature", 0.7)
        max_tokens: int = kwargs.get("max_tokens", 4096)

        # Build user message content with image
        content_parts: List[Dict[str, Any]] = []
        if image_data:
            b64 = base64.b64encode(image_data).decode("utf-8")
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}"
                },
            })
        elif image_url:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": image_url},
            })
        content_parts.append({"type": "text", "text": prompt})

        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": content_parts})

        # Use vision model
        model: str = kwargs.get("vision_model", VISION_MODELS["default"])

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response = await self._client.post(
                "/api/v1/chat/completions",
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
                metadata={"vision": True},
            )

        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, f"Vision request timed out: {exc}", retryable=True)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status in (429, 500, 502, 503, 504)
            raise ProviderError(
                self.name,
                f"Vision HTTP {status}: {exc.response.text[:200]}",
                retryable=retryable,
            )
        except Exception as exc:
            raise ProviderError(self.name, f"Vision error: {exc}", retryable=True)
