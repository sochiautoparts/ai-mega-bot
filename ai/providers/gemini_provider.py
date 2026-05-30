"""Google Gemini Provider — Gemini 2.0 Flash via REST API.

Supports:
  - Text generation with conversation history
  - Vision (image understanding) via Gemini 2.0 Flash
  - Translation via prompt engineering
"""
import base64
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from ai.providers.base import AIResponse, BaseProvider, ProviderError

logger = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

DEFAULT_MODEL = "gemini-2.0-flash"
VISION_MODEL = "gemini-2.0-flash"


class GeminiProvider(BaseProvider):
    """Google Gemini provider using httpx for REST API."""

    name: str = "gemini"
    supports_streaming: bool = False
    supports_vision: bool = True

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
        """Generate text via Gemini generateContent endpoint with conversation history."""
        if not self._client:
            await self.init()

        model: str = kwargs.get("model", DEFAULT_MODEL)
        system_prompt: str = kwargs.get("system_prompt", "")
        temperature: float = kwargs.get("temperature", 0.7)
        max_tokens: int = kwargs.get("max_tokens", 4096)
        messages_history: Optional[List[Dict[str, Any]]] = kwargs.get("messages")

        contents: List[Dict[str, Any]] = []

        # Add system prompt as first exchange
        if system_prompt:
            contents.append({
                "role": "user",
                "parts": [{"text": system_prompt}],
            })
            contents.append({
                "role": "model",
                "parts": [{"text": "Understood. I will follow these instructions."}],
            })

        # Add conversation history
        if messages_history:
            for msg in messages_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if isinstance(content, str):
                    gemini_role = "user" if role in ("user", "system") else "model"
                    contents.append({
                        "role": gemini_role,
                        "parts": [{"text": content}],
                    })

        # Add current user message
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

            candidates = data.get("candidates", [])
            if not candidates:
                raise ProviderError(self.name, "No candidates in response", retryable=True)

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if not parts:
                raise ProviderError(self.name, "No parts in response", retryable=True)

            text = parts[0].get("text", "")
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

    async def generate_with_vision(
        self,
        prompt: str,
        image_data: bytes = b"",
        image_url: str = "",
        **kwargs,
    ) -> AIResponse:
        """Generate response with image understanding via Gemini."""
        if not self._client:
            await self.init()

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

        # Build user message with image
        user_parts: List[Dict[str, Any]] = []
        if image_data:
            b64 = base64.b64encode(image_data).decode("utf-8")
            user_parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": b64,
                }
            })
        user_parts.append({"text": prompt})

        contents.append({
            "role": "user",
            "parts": user_parts,
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
                self._build_url(VISION_MODEL, "generateContent"),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            candidates = data.get("candidates", [])
            if not candidates:
                raise ProviderError(self.name, "No candidates in vision response", retryable=True)

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            text = parts[0].get("text", "") if parts else ""

            usage = data.get("usageMetadata", {})

            return AIResponse(
                text=text,
                provider=self.name,
                model=VISION_MODEL,
                tokens_used=usage.get("totalTokenCount", 0),
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
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(self.name, f"Vision error: {exc}", retryable=True)

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
