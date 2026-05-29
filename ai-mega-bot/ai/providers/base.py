"""Base AI Provider."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class ProviderError(Exception):
    """Provider-specific error."""

    def __init__(self, provider: str, message: str, retryable: bool = True):
        self.provider = provider
        self.retryable = retryable
        super().__init__(f"[{provider}] {message}")


@dataclass
class AIResponse:
    """Unified AI response."""
    text: str = ""
    image_url: str = ""
    image_bytes: bytes = b""
    audio_bytes: bytes = b""
    provider: str = ""
    model: str = ""
    tokens_used: int = 0
    finish_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseProvider:
    """Base class for all AI providers."""

    name: str = "base"
    supports_streaming: bool = False

    def __init__(self, api_key: str = "", timeout: float = 15.0):
        self.api_key = api_key
        self.timeout = timeout
        self._client: Optional[Any] = None

    async def init(self) -> None:
        """Initialize async resources (httpx client, etc)."""
        pass

    async def close(self) -> None:
        """Cleanup async resources."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def generate(self, prompt: str, **kwargs) -> AIResponse:
        """Generate text response."""
        raise NotImplementedError

    async def generate_image(self, prompt: str, **kwargs) -> AIResponse:
        """Generate image."""
        raise NotImplementedError

    async def transcribe(self, audio_data: bytes, **kwargs) -> AIResponse:
        """Transcribe audio to text."""
        raise NotImplementedError

    async def text_to_speech(self, text: str, **kwargs) -> AIResponse:
        """Convert text to speech."""
        raise NotImplementedError

    async def translate(
        self,
        text: str,
        source_lang: str = "auto",
        target_lang: str = "ru",
        **kwargs,
    ) -> AIResponse:
        """Translate text."""
        raise NotImplementedError

    def is_available(self) -> bool:
        """Check if provider has required credentials."""
        return bool(self.api_key) or self.name == "pollinations"
