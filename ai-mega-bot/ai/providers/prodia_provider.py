"""Prodia Provider — backup image generator.

Since Prodia requires a paid API key, this provider acts as a simple
fallback that delegates to Pollinations under the hood with slightly
different default parameters (different model/seed).
"""
import logging
from typing import Any, Dict
from urllib.parse import quote

import httpx

from ai.providers.base import AIResponse, BaseProvider, ProviderError

logger = logging.getLogger(__name__)

# Prodia's paid API endpoint (not used currently)
PRODIA_API_URL = "https://api.prodia.com/v1/sd/generate"

# Fallback: use Pollinations with different defaults
POLLINATIONS_IMAGE_BASE = "https://image.pollinations.ai/prompt"


class ProdiaProvider(BaseProvider):
    """Prodia provider — fallback image generation via Pollinations.

    When a Prodia API key becomes available, this can be upgraded to
    use the real Prodia API. For now, it delegates to Pollinations
    with different model/seed parameters as a distinct fallback.
    """

    name: str = "prodia"
    supports_streaming: bool = False

    def __init__(self, api_key: str = "", timeout: float = 45.0):
        super().__init__(api_key=api_key, timeout=timeout)

    async def init(self) -> None:
        """Initialize httpx async client with connection pooling."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            follow_redirects=True,
        )

    def is_available(self) -> bool:
        """Prodia is available as a Pollinations fallback even without a key."""
        # Available as Pollinations fallback even without a Prodia API key
        return True

    async def generate_image(self, prompt: str, **kwargs) -> AIResponse:
        """Generate image — delegates to Pollinations with Prodia-style params."""
        if not self._client:
            await self.init()

        width: int = kwargs.get("width", 1024)
        height: int = kwargs.get("height", 1024)
        seed: int = kwargs.get("seed", 1337)  # Different default seed from Pollinations
        nologo: bool = kwargs.get("nologo", True)
        model: str = kwargs.get("model", "flux-realism")  # Different model for variety

        encoded_prompt = quote(prompt, safe="")

        url = (
            f"{POLLINATIONS_IMAGE_BASE}/{encoded_prompt}"
            f"?width={width}&height={height}"
            f"&seed={seed}&nologo={str(nologo).lower()}"
            f"&model={model}"
        )

        image_url = url

        try:
            response = await self._client.get(url)
            response.raise_for_status()

            image_bytes = response.content
            content_type = response.headers.get("content-type", "")

            if not image_bytes:
                raise ProviderError(
                    self.name,
                    "Empty image response from fallback",
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
                    "fallback": True,
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
