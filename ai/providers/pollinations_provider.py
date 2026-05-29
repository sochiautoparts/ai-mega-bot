"""Pollinations.ai Provider — FREE, no API key needed!

Supports:
  - Text generation via OpenAI-compatible POST API
  - Image generation via GET request (returns image bytes)
  - Translation via text generation with system prompt
  - Code assistance via text generation with system prompt

Pollinations is the ultimate fallback — always available, no key, no limits.
"""
import logging
from typing import Any, Dict, List
from urllib.parse import quote

import httpx

from ai.providers.base import AIResponse, BaseProvider, ProviderError

logger = logging.getLogger(__name__)

IMAGE_BASE = "https://image.pollinations.ai/prompt"
TEXT_BASE = "https://text.pollinations.ai"

# Models available via Pollinations (free, no key)
TEXT_MODELS = {
    "default": "openai",      # GPT-4o-mini
    "fast": "mistral",        # Mistral Small
    "reasoning": "deepseek",  # DeepSeek V3
    "code": "deepseek",       # DeepSeek for code
}

IMAGE_MODELS = {
    "default": "flux",
    "realism": "flux-realism",
    "anime": "flux-anime",
    "3d": "flux-3d",
    "cablyai": "cablyai",
    "turbo": "flux",
}


class PollinationsProvider(BaseProvider):
    """Pollinations.ai provider — free, no API key required, always available."""

    name: str = "pollinations"
    supports_streaming: bool = False

    def __init__(self, api_key: str = "", timeout: float = 60.0):
        # Pollinations doesn't need an API key
        super().__init__(api_key="", timeout=timeout)

    async def init(self) -> None:
        """Initialize httpx async client with connection pooling."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=True,
        )

    def is_available(self) -> bool:
        """Pollinations is always available — no key needed."""
        return True

    async def generate(self, prompt: str, **kwargs) -> AIResponse:
        """Generate text via Pollinations OpenAI-compatible POST API."""
        if not self._client:
            await self.init()

        model_key: str = kwargs.get("model_key", "default")
        model: str = kwargs.get("model", TEXT_MODELS.get(model_key, TEXT_MODELS["default"]))
        system_prompt: str = kwargs.get("system_prompt", "")
        temperature: float = kwargs.get("temperature", 0.7)
        max_tokens: int = kwargs.get("max_tokens", 4096)

        # Use POST endpoint (OpenAI-compatible) for better results
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        try:
            response = await self._client.post(
                f"{TEXT_BASE}/",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()

            text = response.text

            if not text:
                raise ProviderError(
                    self.name,
                    "Empty text response from Pollinations",
                    retryable=True,
                )

            return AIResponse(
                text=text,
                provider=self.name,
                model=f"pollinations:{model}",
                tokens_used=0,  # Pollinations doesn't report tokens
                metadata={"endpoint": "text_post"},
            )

        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, f"Text generation timed out: {exc}", retryable=True)
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

    async def generate_image(self, prompt: str, **kwargs) -> AIResponse:
        """Generate image via Pollinations image endpoint."""
        if not self._client:
            await self.init()

        width: int = kwargs.get("width", 1024)
        height: int = kwargs.get("height", 1024)
        seed: int = kwargs.get("seed", 42)
        nologo: bool = kwargs.get("nologo", True)
        model_key: str = kwargs.get("model_key", "default")
        model: str = kwargs.get("model", IMAGE_MODELS.get(model_key, IMAGE_MODELS["default"]))

        encoded_prompt = quote(prompt, safe="")

        url = (
            f"{IMAGE_BASE}/{encoded_prompt}"
            f"?width={width}&height={height}"
            f"&seed={seed}&nologo={str(nologo).lower()}"
            f"&model={model}"
        )

        # Also store a direct URL for reference
        image_url = url

        try:
            response = await self._client.get(url)
            response.raise_for_status()

            image_bytes = response.content
            content_type = response.headers.get("content-type", "")

            if not image_bytes:
                raise ProviderError(
                    self.name,
                    "Empty image response",
                    retryable=True,
                )

            return AIResponse(
                image_url=image_url,
                image_bytes=image_bytes,
                provider=self.name,
                model=f"pollinations:{model}",
                metadata={
                    "content_type": content_type,
                    "width": width,
                    "height": height,
                    "endpoint": "image",
                },
            )

        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, f"Image generation timed out: {exc}", retryable=True)
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
            raise ProviderError(self.name, f"Image generation error: {exc}", retryable=True)

    async def translate(
        self,
        text: str,
        source_lang: str = "auto",
        target_lang: str = "ru",
        **kwargs,
    ) -> AIResponse:
        """Translate text using Pollinations text generation with translation prompt."""
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

        return await self.generate(text, system_prompt=system_prompt, model_key="default")
