#!/usr/bin/env python3
"""
Generate OpenClaw config (openclaw.json) dynamically based on which API keys
are present in the environment.

OpenClaw fails to start if a provider references an env-var secret that is
missing. To keep the bot resilient, we only add providers whose keys are
actually set. Pollinations is always included (free, no key needed) and is
the ultimate fallback so the bot ALWAYS has at least one working AI provider.

Usage:
    python3 scripts/gen_openclaw_config.py [--out PATH] [--state-dir PATH]

Default output: <state-dir>/openclaw.json  (state-dir defaults to ~/.openclaw)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


# ── Provider catalogue ───────────────────────────────────────────────────────
# Each entry: env_var -> (provider_id, baseUrl, api, models[{id,name}], timeout)
# Pollinations is special: free, no key, always on.
PROVIDERS: list[dict] = [
    {
        "id": "pollinations",
        "baseUrl": "https://text.pollinations.ai/openai",
        "api": "openai-completions",
        "apiKey": "pollinations",  # literal — no real key needed
        "timeoutSeconds": 12,
        "always": True,
        "models": [
            {"id": "openai", "name": "Pollinations GPT-OSS 20B (free, no key)"},
        ],
    },
    {
        "id": "groq",
        "baseUrl": "https://api.groq.com/openai/v1",
        "api": "openai-completions",
        "env": "GROQ_API_KEY",
        "timeoutSeconds": 12,
        "models": [
            {"id": "llama-3.3-70b-versatile", "name": "Groq Llama 3.3 70B"},
            {"id": "llama-3.1-8b-instant", "name": "Groq Llama 3.1 8B (fast)"},
        ],
    },
    {
        "id": "gemini",
        "baseUrl": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api": "openai-completions",
        "env": "GEMINI_API_KEY",
        "timeoutSeconds": 12,
        "models": [
            {"id": "gemini-2.0-flash", "name": "Google Gemini 2.0 Flash"},
            {"id": "gemini-1.5-flash", "name": "Google Gemini 1.5 Flash"},
        ],
    },
    {
        "id": "openrouter",
        "baseUrl": "https://openrouter.ai/api/v1",
        "api": "openai-completions",
        "env": "OPENROUTER_API_KEY",
        "timeoutSeconds": 12,
        "models": [
            {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "OpenRouter Llama 3.3 70B (free)"},
            {"id": "google/gemma-2-9b-it:free", "name": "OpenRouter Gemma 2 9B (free)"},
        ],
    },
    {
        "id": "huggingface",
        "baseUrl": "https://router.huggingface.co/v1",
        "api": "openai-completions",
        "env": "HF_TOKEN",
        "timeoutSeconds": 12,
        "models": [
            {"id": "qwen2.5-7b-instruct", "name": "HF Qwen2.5 7B Instruct"},
        ],
    },
    {
        "id": "cerebras",
        "baseUrl": "https://api.cerebras.ai/v1",
        "api": "openai-completions",
        "env": "CEREBRAS_API_KEY",
        "timeoutSeconds": 12,
        "models": [
            {"id": "llama-3.3-70b", "name": "Cerebras Llama 3.3 70B"},
        ],
    },
    {
        "id": "openai",
        "baseUrl": "https://api.openai.com/v1",
        "api": "openai-completions",
        "env": "OPENAI_API_KEY",
        "timeoutSeconds": 12,
        "models": [
            {"id": "gpt-4o-mini", "name": "OpenAI GPT-4o mini"},
            {"id": "gpt-4o", "name": "OpenAI GPT-4o"},
        ],
    },
    {
        "id": "anthropic",
        "baseUrl": "https://api.anthropic.com/v1",
        "api": "anthropic-messages",
        "env": "ANTHROPIC_API_KEY",
        "timeoutSeconds": 12,
        "models": [
            {"id": "claude-3-5-sonnet-latest", "name": "Anthropic Claude 3.5 Sonnet"},
        ],
    },
    {
        "id": "xai",
        "baseUrl": "https://api.x.ai/v1",
        "api": "openai-completions",
        "env": "XAI_API_KEY",
        "timeoutSeconds": 12,
        "models": [
            {"id": "grok-beta", "name": "xAI Grok Beta"},
        ],
    },
    {
        "id": "mistral",
        "baseUrl": "https://api.mistral.ai/v1",
        "api": "openai-completions",
        "env": "MISTRAL_API_KEY",
        "timeoutSeconds": 12,
        "models": [
            {"id": "mistral-small-latest", "name": "Mistral Small"},
        ],
    },
    {
        "id": "sambanova",
        "baseUrl": "https://api.sambanova.ai/v1",
        "api": "openai-completions",
        "env": "SAMBANOVA_API_KEY",
        "timeoutSeconds": 12,
        "models": [
            {"id": "Meta-Llama-3.1-8B-Instruct", "name": "SambaNova Llama 3.1 8B"},
        ],
    },
]

# Priority order for choosing the primary model (best/fastest free-ish first).
# Pollinations is last-resort fallback (always available).
PRIORITY = [
    "groq", "gemini", "cerebras", "openrouter", "huggingface",
    "sambanova", "mistral", "openai", "anthropic", "xai", "pollinations",
]


def _env_set(name: str) -> bool:
    v = os.getenv(name, "").strip()
    return bool(v) and v.lower() not in ("not_configured", "none", "null")


def build_config() -> dict:
    """Build OpenClaw config based on available env keys."""
    providers_out: dict[str, dict] = {}
    active_ids: list[str] = []

    for p in PROVIDERS:
        always = p.get("always", False)
        env = p.get("env")
        if always or (env and _env_set(env)):
            entry: dict = {
                "baseUrl": p["baseUrl"],
                "api": p["api"],
                "timeoutSeconds": p["timeoutSeconds"],
                "models": p["models"],
            }
            if always:
                # literal key (Pollinations needs no real key)
                entry["apiKey"] = p.get("apiKey", "free")
            else:
                entry["apiKey"] = {
                    "source": "env", "provider": "default", "id": env,
                }
            providers_out[p["id"]] = entry
            active_ids.append(p["id"])

    # Choose primary + fallbacks by priority
    ordered = [pid for pid in PRIORITY if pid in active_ids]
    if not ordered:
        ordered = ["pollinations"]  # safety net
    primary_model = f"{ordered[0]}/{PROVIDERS[_idx(ordered[0])]['models'][0]['id']}"
    fallbacks = [
        f"{pid}/{PROVIDERS[_idx(pid)]['models'][0]['id']}"
        for pid in ordered[1:]
    ]

    return {
        "$schema": "https://docs.openclaw.ai/schema/openclaw.json",
        "gateway": {
            "port": int(os.getenv("OPENCLAW_PORT", "18789")),
            "bind": "loopback",
            "auth": {"mode": "none"},
            "http": {
                "endpoints": {
                    "chatCompletions": {"enabled": True, "maxBodyBytes": 8388608},
                },
            },
            "controlUi": {"enabled": False},
        },
        "agents": {
            "defaults": {
                "model": {"primary": primary_model, "fallbacks": fallbacks},
                "params": {"temperature": 0.9},
                "skipBootstrap": True,
                "workspace": ".",
            },
        },
        "models": {
            "mode": "merge",
            "providers": providers_out,
        },
    }


def _idx(provider_id: str) -> int:
    for i, p in enumerate(PROVIDERS):
        if p["id"] == provider_id:
            return i
    return 0


def main() -> int:
    out_arg = None
    state_dir = os.getenv("OPENCLAW_STATE_DIR") or os.path.expanduser("~/.openclaw")
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ("--out", "-o") and i + 1 < len(args):
            out_arg = args[i + 1]
            i += 2
        elif args[i] in ("--state-dir",) and i + 1 < len(args):
            state_dir = args[i + 1]
            i += 2
        else:
            i += 1

    cfg = build_config()
    out_path = Path(out_arg) if out_arg else Path(state_dir) / "openclaw.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))

    active = [pid for pid in PRIORITY if pid in cfg["models"]["providers"]]
    print(f"[gen_openclaw_config] wrote {out_path}")
    print(f"[gen_openclaw_config] active providers: {active}")
    print(f"[gen_openclaw_config] primary: {cfg['agents']['defaults']['model']['primary']}")
    print(f"[gen_openclaw_config] fallbacks: {cfg['agents']['defaults']['model']['fallbacks']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
