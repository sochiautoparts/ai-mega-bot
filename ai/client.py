"""
AI client for AI Mega Bot — routes all AI requests through the OpenClaw Gateway.

OpenClaw runs locally (in GitHub Actions) and serves an OpenAI-compatible
POST /v1/chat/completions endpoint. The bot sends model="openclaw" and OpenClaw
handles provider selection, failover, key rotation and retries internally.

This means the bot "works in the OpenClaw environment": every AI response is
produced by OpenClaw's agent runtime, not by a direct provider call.

If the OpenClaw gateway is unreachable (cold start, crash), the client retries
with backoff and finally returns an empty string — the caller decides what to
do (skip the reply, or for private chat use a static fallback).
"""

import asyncio
import logging
from typing import List, Optional

import httpx

from bot.config import config

logger = logging.getLogger("mega.ai")

# OpenClaw serves the OpenAI-compatible endpoint on the gateway port.
_ENDPOINT = f"{config.OPENCLAW_URL}/v1/chat/completions"
_MODEL = "openclaw"  # routes to the agent's configured primary + fallbacks

# Reuse one httpx client (connection pooling) for the whole process.
_client: Optional[httpx.AsyncClient] = None

# Stats for /stats command
_stats = {"requests": 0, "success": 0, "fail": 0, "last_error": ""}


async def initialize() -> None:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    logger.info(f"AI client → OpenClaw @ {_ENDPOINT} (providers: {config.providers_status()})")


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _wait_for_gateway(timeout: float = 90.0) -> bool:
    """Poll the gateway until it responds (cold start can take ~15s)."""
    if _client is None:
        await initialize()
    deadline = asyncio.get_event_loop().time() + timeout
    url = f"{config.OPENCLAW_URL}/v1/models"
    while asyncio.get_event_loop().time() < deadline:
        try:
            r = await _client.get(url, timeout=5.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        await asyncio.sleep(2.0)
    return False


async def chat(
    prompt: str,
    system: str = "",
    extra_context: str = "",
    dialog_history: Optional[List[dict]] = None,
    max_tokens: int = 600,
    temperature: float = 0.9,
) -> str:
    """Single-turn chat completion through OpenClaw.

    dialog_history: optional list of {role, content} prior turns.
    Returns the assistant message text, or "" on failure.
    """
    global _stats
    _stats["requests"] += 1

    if _client is None:
        await initialize()

    messages: List[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    if dialog_history:
        messages.extend(dialog_history)
    user_content = prompt
    if extra_context:
        user_content = f"{extra_context}\n\n---\n\n{prompt}"
    messages.append({"role": "user", "content": user_content})

    payload = {
        "model": _MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    # Wait for gateway if it's not up yet (cold start).
    for attempt in range(3):
        try:
            r = await _client.post(_ENDPOINT, json=payload, timeout=60.0)
            if r.status_code == 200:
                data = r.json()
                choices = data.get("choices") or []
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    if content and content.strip():
                        _stats["success"] += 1
                        return content.strip()
            # Gateway not ready yet (starting up) → wait + retry
            if r.status_code in (502, 503, 504):
                logger.debug(f"gateway warming up ({r.status_code}), retry...")
                await _wait_for_gateway(timeout=60.0)
                continue
            # Other error → log + return empty
            _stats["fail"] += 1
            _stats["last_error"] = f"HTTP {r.status_code}: {r.text[:200]}"
            logger.warning(f"OpenClaw error: {_stats['last_error']}")
            return ""
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as e:
            _stats["last_error"] = f"{type(e).__name__}: {e}"
            logger.debug(f"gateway connect error (attempt {attempt+1}): {e}")
            if attempt < 2:
                ok = await _wait_for_gateway(timeout=60.0)
                if not ok:
                    _stats["fail"] += 1
                    return ""
        except Exception as e:
            _stats["fail"] += 1
            _stats["last_error"] = f"{type(e).__name__}: {e}"
            logger.warning(f"AI chat error: {e}")
            return ""
    _stats["fail"] += 1
    return ""


async def comment(prompt: str, extra_context: str = "", mood: str = "",
                  dialog_history: Optional[List[dict]] = None) -> str:
    """Generate a group comment through OpenClaw (shorter, livelier)."""
    from bot.persona import COMMENT_PROMPT
    system = COMMENT_PROMPT
    if mood:
        system += f"\n\nТвоё текущее настроение: {mood}."
    return await chat(
        prompt, system=system, extra_context=extra_context,
        dialog_history=dialog_history, max_tokens=400, temperature=0.95,
    )


def stats() -> dict:
    return dict(_stats)
