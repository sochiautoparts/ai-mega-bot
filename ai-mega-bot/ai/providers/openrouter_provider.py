"""OpenRouter AI Provider — access to multiple free models with conversation context."""
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


class OpenRouterProvider(BaseProvider):
    """OpenRouter provider using httpx for access to free models."""

    name: str = "openrouter"
    supports_streaming: bool = False

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
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    def _build_messages(
        self,
        prompt: str,
        system_prompt: str = "",
        history: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        """Build messages array with system prompt, history, and current prompt."""
        messages: List[Dict[str, str]] = []

        # System prompt first
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Add conversation history for context memory
        if history:
            for msg in history:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        # Current user message (if not already in history)
        # Check if the last history entry is already this prompt
        last_is_current = (
            history
            and len(history) > 0
            and history[-1].get("role") == "user"
            and history[-1].get("content") == prompt
        )
        if not last_is_current:
            messages.append({"role": "user", "content": prompt})

        return messages

    async def generate(self, prompt: str, **kwargs) -> AIResponse:
        """Generate text via OpenRouter chat completions with context memory."""
        if not self._client:
            await self.init()

        model_key: str = kwargs.get("model_key", "default")
        model: str = kwargs.get("model", FREE_MODELS.get(model_key, FREE_MODELS["default"]))
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
