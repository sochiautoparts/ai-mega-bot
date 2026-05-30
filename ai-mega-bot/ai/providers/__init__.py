"""AI Provider Adapters."""
from ai.providers.base import BaseProvider, AIResponse, ProviderError
from ai.providers.groq_provider import GroqProvider
from ai.providers.openrouter_provider import OpenRouterProvider
from ai.providers.github_provider import GitHubModelsProvider
from ai.providers.gemini_provider import GeminiProvider
from ai.providers.huggingface_provider import HuggingFaceProvider
from ai.providers.pollinations_provider import PollinationsProvider
from ai.providers.prodia_provider import ProdiaProvider
from ai.providers.cerebras_provider import CerebrasProvider
from ai.providers.grok_provider import GrokProvider
from ai.providers.sambanova_provider import SambaNovaProvider
from ai.providers.chutes_provider import ChutesProvider
from ai.providers.together_provider import TogetherProvider
from ai.providers.mistral_provider import MistralProvider
from ai.providers.fireworks_provider import FireworksProvider
from ai.providers.cloudflare_provider import CloudflareProvider
from ai.providers.blackbox_provider import BlackboxProvider
from ai.providers.cohere_provider import CohereProvider

ALL_PROVIDERS = {
    # ── Existing providers ────────────────────────────────
    "groq": GroqProvider,
    "openrouter": OpenRouterProvider,
    "github_models": GitHubModelsProvider,
    "gemini": GeminiProvider,
    "huggingface": HuggingFaceProvider,
    "huggingface_img": HuggingFaceProvider,
    "huggingface_whisper": HuggingFaceProvider,
    "huggingface_tts": HuggingFaceProvider,
    "huggingface_nllb": HuggingFaceProvider,
    "pollinations": PollinationsProvider,
    "prodia": ProdiaProvider,
    "groq_whisper": GroqProvider,
    "cerebras": CerebrasProvider,
    "grok": GrokProvider,
    # ── New providers ─────────────────────────────────────
    "sambanova": SambaNovaProvider,
    "chutes": ChutesProvider,
    "together": TogetherProvider,
    "mistral": MistralProvider,
    "fireworks": FireworksProvider,
    "cloudflare": CloudflareProvider,
    "blackbox": BlackboxProvider,
    "cohere": CohereProvider,
}
