"""Base AI Provider."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
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
    supports_vision: bool = False  # Whether provider can handle images

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
        """Generate text response.

        Args:
            prompt: The user's current message text
            **kwargs: Additional options including:
                messages: List[Dict] - conversation history with role/content
                system_prompt: str - system instructions
                model: str - model override
                temperature: float
                max_tokens: int
        """
        raise NotImplementedError

    async def generate_with_vision(
        self,
        prompt: str,
        image_data: bytes = b"",
        image_url: str = "",
        **kwargs,
    ) -> AIResponse:
        """Generate response with image understanding (vision).

        Args:
            prompt: User's text about the image
            image_data: Raw image bytes (will be base64-encoded)
            image_url: URL of the image (alternative to image_data)
            **kwargs: Same as generate()
        """
        # Default: fall back to text-only if provider doesn't support vision
        if not self.supports_vision:
            return await self.generate(prompt, **kwargs)
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

    # Providers that work without API keys
    NO_KEY_PROVIDERS = {"pollinations", "prodia"}

    def is_available(self) -> bool:
        """Check if provider has required credentials."""
        if self.name in self.NO_KEY_PROVIDERS:
            return True
        return bool(self.api_key)

    @staticmethod
    def _build_messages(
        prompt: str,
        system_prompt: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Build OpenAI-compatible messages array with history.

        Args:
            prompt: Current user message
            system_prompt: System instructions
            messages: Conversation history (list of {role, content} dicts)

        Returns:
            Complete messages array for API call
        """
        result: List[Dict[str, Any]] = []
        if system_prompt:
            result.append({"role": "system", "content": system_prompt})
        # Add conversation history (previous messages)
        if messages:
            result.extend(messages)
        # Add current user message
        result.append({"role": "user", "content": prompt})
        return result
