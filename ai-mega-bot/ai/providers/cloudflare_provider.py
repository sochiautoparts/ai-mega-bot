"""Cloudflare Workers AI Provider — 50+ models via OpenAI-compatible API.

Cloudflare Workers AI offers 10,000 neurons/day free tier with 50+ models.
Edge inference in 200+ cities worldwide.
Requires Cloudflare Account ID in the URL path.
"""
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from ai.providers.base import AIResponse, BaseProvider, ProviderError

logger = logging.getLogger(__name__)

TEXT_MODELS = {
    "default": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "fast": "@cf/meta/llama-3.1-8b-instruct",
    "reasoning": "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
    "code": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
}


class CloudflareProvider(BaseProvider):
    """Cloudflare Workers AI provider — edge inference, OpenAI-compatible API."""

    name: str = "cloudflare"
    supports_streaming: bool = False

    def __init__(self, api_key: str = "", timeout: float = 30.0, account_id: str = ""):
        super().__init__(api_key=api_key, timeout=timeout)
        self._account_id = account_id or os.environ.get("CF_ACCOUNT_ID", "")

    async def init(self) -> None:
        if not self._account_id:
            logger.warning("Cloudflare: no account ID set, provider will not work")
            return
        self._client = httpx.AsyncClient(
            base_url=f"https://api.cloudflare.com/client/v4/accounts/{self._account_id}/ai",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    def is_available(self) -> bool:
        return bool(self.api_key and self._account_id)

    def _build_messages(self, prompt: str, system_prompt: str = "", history: Optional[List[Dict[str, str]]] = None) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            for msg in history:
                role, content = msg.get("role", ""), msg.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
        last_is_current = history and len(history) > 0 and history[-1].get("role") == "user" and history[-1].get("content") == prompt
        if not last_is_current:
            messages.append({"role": "user", "content": prompt})
        return messages

    async def generate(self, prompt: str, **kwargs) -> AIResponse:
        if not self._client:
            await self.init()
        if not self._client:
            raise ProviderError(self.name, "Not initialized (missing account ID or API key)", retryable=False)
        model_key = kwargs.get("model_key", "default")
        model = kwargs.get("model", TEXT_MODELS.get(model_key, TEXT_MODELS["default"]))
        system_prompt = kwargs.get("system_prompt", "")
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 4096)
        history = kwargs.get("history")
        messages = self._build_messages(prompt, system_prompt, history)
        payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        try:
            response = await self._client.post("/v1/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            choice = data["choices"][0]
            usage = data.get("usage", {})
            return AIResponse(text=choice["message"]["content"], provider=self.name, model=model, tokens_used=usage.get("total_tokens", 0), finish_reason=choice.get("finish_reason", ""), metadata={"prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0), "context_messages": len(messages)})
        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, f"Request timed out: {exc}", retryable=True)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise ProviderError(self.name, f"HTTP {status}: {exc.response.text[:200]}", retryable=status in (429, 500, 502, 503, 504))
        except Exception as exc:
            raise ProviderError(self.name, f"Unexpected error: {exc}", retryable=True)

    async def translate(self, text: str, source_lang: str = "auto", target_lang: str = "ru", **kwargs) -> AIResponse:
        lang_names = {"ru": "Russian", "en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "pt": "Portuguese", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "ar": "Arabic", "hi": "Hindi", "tr": "Turkish", "uk": "Ukrainian", "pl": "Polish"}
        src_name, tgt_name = lang_names.get(source_lang, source_lang), lang_names.get(target_lang, target_lang)
        if source_lang and source_lang != "auto":
            system_prompt = f"You are a professional translator. Translate the following text from {src_name} to {tgt_name}. Output only the translation, nothing else. Maintain the original tone and style."
        else:
            system_prompt = f"You are a professional translator. Translate the following text to {tgt_name}. Output only the translation, nothing else. Maintain the original tone and style."
        return await self.generate(text, system_prompt=system_prompt, model_key="fast")
