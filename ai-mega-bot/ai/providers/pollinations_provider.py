"""Pollinations.ai Provider — FREE, no API key needed!

Supports:
  - Text generation via GET request
  - Image generation via GET request (returns image bytes)
"""
import logging
from typing import Any, Dict
from urllib.parse import quote

import httpx

from ai.providers.base import AIResponse, BaseProvider, ProviderError

logger = logging.getLogger(__name__)

IMAGE_BASE = "https://image.pollinations.ai/prompt"
TEXT_BASE = "https://text.pollinations.ai"


class PollinationsProvider(BaseProvider):
    """Pollinations.ai provider — free, no API key required."""

    name: str = "pollinations"
    supports_streaming: bool = False

    def __init__(self, api_key: str = "", timeout: float = 45.0):
        # Pollinations doesn't need an API key
        super().__init__(api_key="", timeout=timeout)

    async def init(self) -> None:
        """Initialize httpx async client with connection pooling."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            follow_redirects=True,
        )

    def is_available(self) -> bool:
        """Pollinations is always available — no key needed."""
        return True

    async def generate(self, prompt: str, **kwargs) -> AIResponse:
        """Generate text via Pollinations text endpoint."""
        if not self._client:
            await self.init()

        model: str = kwargs.get("model", "openai")
        encoded_prompt = quote(prompt, safe="")

        url = f"{TEXT_BASE}/{encoded_prompt}?model={model}"

        try:
            response = await self._client.get(url)
            response.raise_for_status()

            text = response.text

            return AIResponse(
                text=text,
                provider=self.name,
                model=model,
                metadata={"endpoint": "text"},
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
        model: str = kwargs.get("model", "flux")

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
                model=model,
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
