"""
AI Mega Bot — Configuration.

All settings load from environment variables (GitHub Actions Secrets in prod,
.env file locally). The bot ALWAYS works on at least Pollinations (free, no key)
— every other provider is an optional upgrade.
"""

import os
from dataclasses import dataclass, field
from typing import List


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name, default).strip()
    # treat GitHub "not_configured" placeholder secrets as empty
    if v.lower() in ("not_configured", "none", "null"):
        return ""
    return v


@dataclass
class BotConfig:
    # ── Telegram ──
    BOT_TOKEN: str = field(default_factory=lambda: _env("BOT_TOKEN"))
    BOT_USERNAME: str = field(default_factory=lambda: _env("BOT_USERNAME", "aimega_bot"))
    BOT_ID: int = field(default_factory=lambda: int(_env("BOT_ID", "0") or 0))
    OWNER_ID: int = field(default_factory=lambda: int(_env("OWNER_ID", "0") or 0))
    ADMIN_IDS: List[int] = field(default_factory=lambda: [
        int(x) for x in _env("ADMIN_IDS").replace(",", " ").split() if x.isdigit()
    ])

    # ── GitHub self-dispatch ──
    GH_PAT_TOKEN: str = field(default_factory=lambda: _env("GH_PAT_TOKEN"))
    GH_REPO: str = field(default_factory=lambda: _env("GH_REPO", "sochiautoparts/ai-mega-bot"))

    # ── OpenClaw gateway ──
    OPENCLAW_PORT: int = field(default_factory=lambda: int(_env("OPENCLAW_PORT", "18789")))
    OPENCLAW_BIN: str = field(default_factory=lambda: _env("OPENCLAW_BIN", "openclaw"))

    @property
    def OPENCLAW_URL(self) -> str:
        return f"http://127.0.0.1:{self.OPENCLAW_PORT}"

    # ── AI provider keys (optional; Pollinations always free) ──
    GROQ_API_KEY: str = field(default_factory=lambda: _env("GROQ_API_KEY"))
    GEMINI_API_KEY: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    OPENROUTER_API_KEY: str = field(default_factory=lambda: _env("OPENROUTER_API_KEY"))
    HF_TOKEN: str = field(default_factory=lambda: _env("HF_TOKEN"))
    CEREBRAS_API_KEY: str = field(default_factory=lambda: _env("CEREBRAS_API_KEY"))
    SAMBANOVA_API_KEY: str = field(default_factory=lambda: _env("SAMBANOVA_API_KEY"))
    MISTRAL_API_KEY: str = field(default_factory=lambda: _env("MISTRAL_API_KEY"))
    OPENAI_API_KEY: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    ANTHROPIC_API_KEY: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    XAI_API_KEY: str = field(default_factory=lambda: _env("XAI_API_KEY"))

    # ── Database ──
    DB_PATH: str = field(default_factory=lambda: _env("DB_PATH", "data/bot.db"))

    # ── Behaviour tuning ──
    GROUP_PROACTIVE_PROB: float = field(default_factory=lambda: float(_env("GROUP_PROACTIVE_PROB", "0.90")))
    GROUP_MAX_PER_MINUTE: int = field(default_factory=lambda: int(_env("GROUP_MAX_PER_MINUTE", "20")))
    GROUP_MEMORY_SIZE: int = field(default_factory=lambda: int(_env("GROUP_MEMORY_SIZE", "30")))
    CHANNEL_REACTION_PROB: float = field(default_factory=lambda: float(_env("CHANNEL_REACTION_PROB", "0.80")))
    REACTION_PROB: float = field(default_factory=lambda: float(_env("REACTION_PROB", "0.55")))
    WEB_VERIFY_PROB: float = field(default_factory=lambda: float(_env("WEB_VERIFY_PROB", "1.0")))
    SEARCH_TIMEOUT_SECONDS: int = field(default_factory=lambda: int(_env("SEARCH_TIMEOUT_SECONDS", "8")))

    # ── AI tuning ──
    CHAT_MAX_CHARS: int = 1200
    COMMENT_MAX_CHARS: int = 500
    GROUP_MAX_CHARS: int = 700

    LOG_LEVEL: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    @property
    def BOT_HANDLE(self) -> str:
        return self.BOT_USERNAME.lstrip("@")

    def active_providers(self) -> List[str]:
        """List of configured (keyed) providers, in priority order."""
        provs = []
        if self.GROQ_API_KEY:
            provs.append("groq")
        if self.GEMINI_API_KEY:
            provs.append("gemini")
        if self.CEREBRAS_API_KEY:
            provs.append("cerebras")
        if self.OPENROUTER_API_KEY:
            provs.append("openrouter")
        if self.HF_TOKEN:
            provs.append("huggingface")
        if self.SAMBANOVA_API_KEY:
            provs.append("sambanova")
        if self.MISTRAL_API_KEY:
            provs.append("mistral")
        if self.OPENAI_API_KEY:
            provs.append("openai")
        if self.ANTHROPIC_API_KEY:
            provs.append("anthropic")
        if self.XAI_API_KEY:
            provs.append("xai")
        provs.append("pollinations")  # always available (free)
        return provs

    def providers_status(self) -> str:
        return f"active={self.active_providers()}"


config = BotConfig()
