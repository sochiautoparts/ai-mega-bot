"""Google Gemini Provider — Gemini 2.0 Flash via REST API."""
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from ai.providers.base import AIResponse, BaseProvider, ProviderError

logger = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiProvider(BaseProvider):
    """Google Gemini provider using httpx for REST API."""

    name: str = "gemini"
    supports_streaming: bool = False

    def __init__(self, api_key: str = "", timeout: float = 15.0):
        super().__init__(api_key=api_key, timeout=timeout)

    async def init(self) -> None:
        """Initialize httpx async client with connection pooling."""
        self._client = httpx.AsyncClient(
            base_url="https://generativelanguage.googleapis.com",
            timeout=httpx.Timeout(self.timeout, connect=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    def _build_url(self, model: str, method: str = "generateContent") -> str:
        """Build the full Gemini API URL with key parameter."""
        return f"/v1beta/models/{model}:{method}?key={self.api_key}"

    async def generate(self, prompt: str, **kwargs) -> AIResponse:
        """Generate text via Gemini generateContent endpoint."""
        if not self._client:
            await self.init()

        model: str = kwargs.get("model", DEFAULT_MODEL)
        system_prompt: str = kwargs.get("system_prompt", "")
        temperature: float = kwargs.get("temperature", 0.7)
        max_tokens: int = kwargs.get("max_tokens", 4096)

        contents: List[Dict[str, Any]] = []
        if system_prompt:
            contents.append({
                "role": "user",
                "parts": [{"text": system_prompt}],
            })
            contents.append({
                "role": "model",
                "parts": [{"text": "Understood."}],
            })
        contents.append({
            "role": "user",
            "parts": [{"text": prompt}],
        })

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        try:
            response = await self._client.post(
                self._build_url(model, "generateContent"),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            # Parse response: candidates[0].content.parts[0].text
            candidates = data.get("candidates", [])
            if not candidates:
                raise ProviderError(self.name, "No candidates in response", retryable=True)

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if not parts:
                raise ProviderError(self.name, "No parts in response", retryable=True)

            text = parts[0].get("text", "")

            # Token usage from usageMetadata
            usage = data.get("usageMetadata", {})

            return AIResponse(
                text=text,
                provider=self.name,
                model=model,
                tokens_used=usage.get("totalTokenCount", 0),
                finish_reason=candidates[0].get("finishReason", ""),
                metadata={
                    "prompt_tokens": usage.get("promptTokenCount", 0),
                    "completion_tokens": usage.get("candidatesTokenCount", 0),
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
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(self.name, f"Unexpected error: {exc}", retryable=True)

    async def translate(
        self,
        text: str,
        source_lang: str = "auto",
        target_lang: str = "ru",
        **kwargs,
    ) -> AIResponse:
        """Translate text using Gemini's language capabilities."""
        model: str = kwargs.get("model", DEFAULT_MODEL)

        prompt = (
            f"Translate the following text to {target_lang}. "
            f"Output only the translation, nothing else.\n\n{text}"
        )

        if source_lang and source_lang != "auto":
            prompt = (
                f"Translate the following text from {source_lang} to {target_lang}. "
                f"Output only the translation, nothing else.\n\n{text}"
            )

        return await self.generate(prompt, model=model, **kwargs)
