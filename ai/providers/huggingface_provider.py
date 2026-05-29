"""HuggingFace Provider — multiple sub-providers via Inference API.

Sub-types:
  - text:   Mistral-7B-Instruct text generation
  - image:  Stable Diffusion XL image generation
  - whisper: Whisper-large-v3 audio transcription
  - tts:    Bark text-to-speech
  - nllb:   NLLB-200 translation
"""
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from ai.providers.base import AIResponse, BaseProvider, ProviderError

logger = logging.getLogger(__name__)

BASE_URL = "https://api-inference.huggingface.co/models"

MODELS = {
    "text": "mistralai/Mistral-7B-Instruct-v0.3",
    "image": "stabilityai/stable-diffusion-xl-base-1.0",
    "whisper": "openai/whisper-large-v3",
    "tts": "suno/bark",
    "nllb": "facebook/nllb-200-distilled-600M",
}

NAME_MAP = {
    "text": "huggingface",
    "image": "huggingface_img",
    "whisper": "huggingface_whisper",
    "tts": "huggingface_tts",
    "nllb": "huggingface_nllb",
}


class HuggingFaceProvider(BaseProvider):
    """HuggingFace Inference API provider with multiple sub-types."""

    supports_streaming: bool = False

    def __init__(
        self,
        api_key: str = "",
        timeout: float = 15.0,
        sub_type: str = "text",
    ):
        super().__init__(api_key=api_key, timeout=timeout)
        self._sub_type = sub_type
        self._model = MODELS.get(sub_type, MODELS["text"])
        self.name = NAME_MAP.get(sub_type, "huggingface")

    async def init(self) -> None:
        """Initialize httpx async client with connection pooling."""
        timeout = self.timeout
        # Image generation and TTS need longer timeouts
        if self._sub_type in ("image", "tts"):
            timeout = max(timeout, 60.0)

        self._client = httpx.AsyncClient(
            base_url="https://api-inference.huggingface.co",
            headers={
                "Authorization": f"Bearer {self.api_key}",
            },
            timeout=httpx.Timeout(timeout, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    async def generate(self, prompt: str, **kwargs) -> AIResponse:
        """Generate text via HuggingFace Inference API."""
        if not self._client:
            await self.init()

        model: str = kwargs.get("model", self._model)

        payload: Dict[str, Any] = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": kwargs.get("max_tokens", 1024),
                "temperature": kwargs.get("temperature", 0.7),
                "return_full_text": False,
            },
        }

        try:
            response = await self._client.post(
                f"/models/{model}",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            # Response format: [{"generated_text": "..."}]
            if isinstance(data, list) and data:
                text = data[0].get("generated_text", "")
            elif isinstance(data, dict) and "generated_text" in data:
                text = data["generated_text"]
            else:
                text = str(data)

            return AIResponse(
                text=text,
                provider=self.name,
                model=model,
                metadata={"sub_type": self._sub_type},
            )

        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, f"Request timed out: {exc}", retryable=True)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status in (429, 500, 502, 503, 504)
            # HF returns 503 when model is loading
            if status == 503:
                retryable = True
            raise ProviderError(
                self.name,
                f"HTTP {status}: {exc.response.text[:200]}",
                retryable=retryable,
            )
        except Exception as exc:
            raise ProviderError(self.name, f"Unexpected error: {exc}", retryable=True)

    async def generate_image(self, prompt: str, **kwargs) -> AIResponse:
        """Generate image via HuggingFace Inference API (Stable Diffusion)."""
        if not self._client:
            await self.init()

        model: str = kwargs.get("model", self._model)

        payload: Dict[str, Any] = {
            "inputs": prompt,
        }

        try:
            response = await self._client.post(
                f"/models/{model}",
                json=payload,
            )
            response.raise_for_status()

            # Response is raw image bytes (content-type: image/png)
            image_bytes = response.content
            content_type = response.headers.get("content-type", "")

            if not image_bytes or "image" not in content_type:
                raise ProviderError(
                    self.name,
                    f"Expected image response, got content-type: {content_type}",
                    retryable=True,
                )

            return AIResponse(
                image_bytes=image_bytes,
                provider=self.name,
                model=model,
                metadata={"content_type": content_type, "sub_type": self._sub_type},
            )

        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, f"Image generation timed out: {exc}", retryable=True)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status in (429, 500, 502, 503, 504)
            if status == 503:
                retryable = True
            raise ProviderError(
                self.name,
                f"HTTP {status}: {exc.response.text[:200]}",
                retryable=retryable,
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(self.name, f"Image generation error: {exc}", retryable=True)

    async def transcribe(self, audio_data: bytes, **kwargs) -> AIResponse:
        """Transcribe audio via HuggingFace Whisper."""
        if not self._client:
            await self.init()

        model: str = kwargs.get("model", self._model)

        try:
            response = await self._client.post(
                f"/models/{model}",
                content=audio_data,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "audio/wav",
                },
            )
            response.raise_for_status()
            data = response.json()

            # Response format: {"text": "..."}
            text = data.get("text", "")

            return AIResponse(
                text=text,
                provider=self.name,
                model=model,
                metadata={"sub_type": self._sub_type},
            )

        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, f"Transcription timed out: {exc}", retryable=True)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status in (429, 500, 502, 503, 504)
            if status == 503:
                retryable = True
            raise ProviderError(
                self.name,
                f"HTTP {status}: {exc.response.text[:200]}",
                retryable=retryable,
            )
        except Exception as exc:
            raise ProviderError(self.name, f"Transcription error: {exc}", retryable=True)

    async def text_to_speech(self, text: str, **kwargs) -> AIResponse:
        """Convert text to speech via HuggingFace Bark."""
        if not self._client:
            await self.init()

        model: str = kwargs.get("model", self._model)

        payload: Dict[str, Any] = {
            "inputs": text,
        }

        try:
            response = await self._client.post(
                f"/models/{model}",
                json=payload,
            )
            response.raise_for_status()

            # Response is raw audio bytes
            audio_bytes = response.content
            content_type = response.headers.get("content-type", "")

            return AIResponse(
                audio_bytes=audio_bytes,
                provider=self.name,
                model=model,
                metadata={"content_type": content_type, "sub_type": self._sub_type},
            )

        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, f"TTS timed out: {exc}", retryable=True)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status in (429, 500, 502, 503, 504)
            if status == 503:
                retryable = True
            raise ProviderError(
                self.name,
                f"HTTP {status}: {exc.response.text[:200]}",
                retryable=retryable,
            )
        except Exception as exc:
            raise ProviderError(self.name, f"TTS error: {exc}", retryable=True)

    async def translate(
        self,
        text: str,
        source_lang: str = "auto",
        target_lang: str = "ru",
        **kwargs,
    ) -> AIResponse:
        """Translate text via HuggingFace NLLB-200."""
        if not self._client:
            await self.init()

        model: str = kwargs.get("model", self._model)

        # NLLB language code mapping for common languages
        lang_codes: Dict[str, str] = {
            "en": "eng_Latn",
            "ru": "rus_Cyrl",
            "es": "spa_Latn",
            "fr": "fra_Latn",
            "de": "deu_Latn",
            "zh": "zho_Hans",
            "ja": "jpn_Jpan",
            "ko": "kor_Hang",
            "ar": "arb_Arab",
            "pt": "por_Latn",
            "it": "ita_Latn",
            "hi": "hin_Deva",
            "tr": "tur_Latn",
            "uk": "ukr_Cyrl",
            "auto": "eng_Latn",  # default assumption
        }

        src_code = lang_codes.get(source_lang, source_lang)
        tgt_code = lang_codes.get(target_lang, target_lang)

        params = {
            "src_lang": src_code,
            "tgt_lang": tgt_code,
        }

        payload: Dict[str, Any] = {
            "inputs": text,
            "parameters": params,
        }

        try:
            response = await self._client.post(
                f"/models/{model}",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            # Response format: [{"translation_text": "..."}]
            if isinstance(data, list) and data:
                translated = data[0].get("translation_text", "")
            elif isinstance(data, dict) and "translation_text" in data:
                translated = data["translation_text"]
            else:
                translated = str(data)

            return AIResponse(
                text=translated,
                provider=self.name,
                model=model,
                metadata={
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "sub_type": self._sub_type,
                },
            )

        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, f"Translation timed out: {exc}", retryable=True)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status in (429, 500, 502, 503, 504)
            if status == 503:
                retryable = True
            raise ProviderError(
                self.name,
                f"HTTP {status}: {exc.response.text[:200]}",
                retryable=retryable,
            )
        except Exception as exc:
            raise ProviderError(self.name, f"Translation error: {exc}", retryable=True)
