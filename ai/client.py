"""
AI client for AI Mega Bot — routes all AI requests through the OpenClaw Gateway.

OpenClaw runs locally (in GitHub Actions) and serves an OpenAI-compatible
POST /v1/chat/completions endpoint. The bot sends model="openclaw" and OpenClaw
handles provider selection, failover, key rotation and retries internally.

This means the bot "works in the OpenClaw environment": every AI response is
produced by OpenClaw's agent runtime, not by a direct provider call.

Resilience layers (in order):
  1. OpenClaw Gateway (/v1/chat/completions, model="openclaw") — primary path.
  2. Direct Pollinations free API (no key, always available) — backup if the
     gateway returns empty / errors. Keeps the bot talking even if OpenClaw's
     agent runtime has an issue.
  3. Context-aware static fallback (male, Russian) — last resort, never silent.

If all three fail, the caller decides what to do (private chat shows a varied
"я завис" message; groups simply skip the reply).
"""

import asyncio
import logging
import random
from typing import List, Optional

import httpx

from bot.config import config

logger = logging.getLogger("mega.ai")

# OpenClaw serves the OpenAI-compatible endpoint on the gateway port.
_ENDPOINT = f"{config.OPENCLAW_URL}/v1/chat/completions"
_MODEL = "openclaw"  # routes to the agent's configured primary + fallbacks

# Direct Pollinations backup (free, no key) — used if OpenClaw returns empty.
_POLLINATIONS_URL = "https://text.pollinations.ai/openai/chat/completions"
_POLLINATIONS_MODEL = "openai"

# Reuse one httpx client (connection pooling) for the whole process.
_client: Optional[httpx.AsyncClient] = None

# Stats for /stats command
_stats = {
    "requests": 0, "success": 0, "fail": 0,
    "openclaw_ok": 0, "pollinations_backup": 0, "static_fallback": 0,
    "last_error": "",
}


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


async def _call_openclaw(messages: List[dict], max_tokens: int, temperature: float,
                         timeout: float = 25.0) -> str:
    """Call OpenClaw gateway. Returns content string, or '' on failure.

    timeout: per-attempt HTTP timeout (default 25s). OpenClaw's internal
    failover chain (groq→gemini→...→pollinations) can take long if multiple
    providers fail; a tight timeout here ensures the Pollinations direct
    backup kicks in fast instead of waiting 50s+.
    """
    if _client is None:
        await initialize()
    payload = {
        "model": _MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    for attempt in range(2):
        try:
            r = await _client.post(_ENDPOINT, json=payload, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                choices = data.get("choices") or []
                if choices:
                    content = choices[0].get("message", {}).get("content", "") or ""
                    if content.strip():
                        return content.strip()
                logger.warning(f"OpenClaw 200 but empty content. body={r.text[:300]}")
                return ""
            if r.status_code in (502, 503, 504) and attempt == 0:
                logger.debug(f"gateway warming up ({r.status_code}), retry once...")
                await _wait_for_gateway(timeout=30.0)
                continue
            _stats["last_error"] = f"OpenClaw HTTP {r.status_code}: {r.text[:200]}"
            logger.warning(f"OpenClaw error: {_stats['last_error']}")
            return ""
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            _stats["last_error"] = f"{type(e).__name__}"
            logger.warning(f"OpenClaw timeout ({timeout}s) — failing fast to backup")
            return ""
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as e:
            _stats["last_error"] = f"{type(e).__name__}: {e}"
            logger.debug(f"gateway connect error (attempt {attempt+1}): {e}")
            if attempt == 0:
                await _wait_for_gateway(timeout=30.0)
                continue
            return ""
        except Exception as e:
            _stats["last_error"] = f"{type(e).__name__}: {e}"
            logger.warning(f"AI chat error: {e}")
            return ""
    return ""


async def _call_pollinations_direct(messages: List[dict], max_tokens: int,
                                    timeout: float = 15.0) -> str:
    """Call Pollinations free API directly (no key needed, always available).

    Pollinations accepts OpenAI-format requests. Fast (~1-3s) and reliable.
    Used as: (a) primary fast path for group comments, (b) backup when
    OpenClaw returns empty/error.
    """
    if _client is None:
        await initialize()
    payload = {
        "model": _POLLINATIONS_MODEL,
        "messages": messages,
        "temperature": 0.9,
        "max_tokens": max_tokens,
        "stream": False,
    }
    try:
        r = await _client.post(_POLLINATIONS_URL, json=payload, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            choices = data.get("choices") or []
            if choices:
                content = choices[0].get("message", {}).get("content", "") or ""
                if content.strip():
                    return content.strip()
        logger.debug(f"pollinations direct HTTP {r.status_code}: {r.text[:200]}")
    except (httpx.ReadTimeout, httpx.ConnectTimeout):
        logger.debug(f"pollinations direct timeout ({timeout}s)")
    except Exception as e:
        logger.debug(f"pollinations direct error: {e}")
    return ""


# Context-aware static fallback (male, Russian). Used as an absolute last resort
# in private chat so the user never gets silence. Group handlers skip replies on
# empty AI output (better silent than robotic).
_STATIC_FALLBACKS = {
    "greeting": [
        "Привет! Я Василий. Чем могу помочь?",
        "Здарова! Я Вася. Что хотел?",
        "Привет-привет. Я тут. Рассказывай.",
    ],
    "howareyou": [
        "Да норм, спасибо. Сам как?",
        "Бывало и лучше, но в целом норм. У тебя как?",
        "Жив-здоров. Слушаю тебя.",
    ],
    "default": [
        "Хм, давай по-другому спроси, не уловил.",
        "Интересно. Расскажи подробнее?",
        "Понял тебя. И что дальше?",
        "Окей, я с тобой. Продолжай.",
        "Так, давай разберёмся. Что конкретно?",
    ],
}


def _static_fallback(prompt: str) -> str:
    """Pick a context-aware static fallback (male, Russian)."""
    t = (prompt or "").lower()
    if any(w in t for w in ["привет", "здаров", "хай", "ку ", "ку.", "доброе утро", "добрый день", "добрый вечер"]):
        return random.choice(_STATIC_FALLBACKS["greeting"])
    if any(w in t for w in ["как дела", "как ты", "как жизнь", "чё как", "что нового", "как сам"]):
        return random.choice(_STATIC_FALLBACKS["howareyou"])
    return random.choice(_STATIC_FALLBACKS["default"])


async def chat(
    prompt: str,
    system: str = "",
    extra_context: str = "",
    dialog_history: Optional[List[dict]] = None,
    max_tokens: int = 600,
    temperature: float = 0.9,
    allow_static_fallback: bool = True,
    fast: bool = False,
) -> str:
    """Single-turn chat completion.

    dialog_history: optional list of {role, content} prior turns.
    allow_static_fallback: if True (default), return a static Russian fallback
        when all AI providers fail. If False, return "".
    fast: if True, try Pollinations direct FIRST (fast ~1-3s, free, no key),
        then OpenClaw as backup. Used for group comments where speed matters
        more than model quality. If False (default), OpenClaw first (best
        model), Pollinations backup — used for directed/private/event messages.
    Returns the assistant message text.
    """
    global _stats
    _stats["requests"] += 1
    import time as _t
    t0 = _t.time()

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

    if fast:
        # Fast path: Pollinations direct first (~1-3s), OpenClaw backup
        out = await _call_pollinations_direct(messages, max_tokens, timeout=15.0)
        if out:
            _stats["success"] += 1
            _stats["pollinations_backup"] += 1  # reusing counter for "pollinations direct"
            logger.info(f"AI fast=pollinations ({_t.time()-t0:.1f}s) len={len(out)}")
            return out
        # OpenClaw backup (shorter timeout — we already spent up to 15s)
        out = await _call_openclaw(messages, max_tokens, temperature, timeout=20.0)
        if out:
            _stats["success"] += 1
            _stats["openclaw_ok"] += 1
            logger.info(f"AI fast=openclaw-backup ({_t.time()-t0:.1f}s) len={len(out)}")
            return out
    else:
        # Quality path: OpenClaw first (best model), Pollinations backup
        out = await _call_openclaw(messages, max_tokens, temperature, timeout=25.0)
        if out:
            _stats["success"] += 1
            _stats["openclaw_ok"] += 1
            logger.info(f"AI openclaw ({_t.time()-t0:.1f}s) len={len(out)}")
            return out
        # Pollinations direct backup
        logger.info("OpenClaw empty → trying Pollinations direct backup")
        out = await _call_pollinations_direct(messages, max_tokens, timeout=15.0)
        if out:
            _stats["success"] += 1
            _stats["pollinations_backup"] += 1
            logger.info(f"AI pollinations-backup ({_t.time()-t0:.1f}s) len={len(out)}")
            return out

    # Static fallback (only if allowed)
    _stats["fail"] += 1
    if allow_static_fallback:
        fb = _static_fallback(prompt)
        _stats["static_fallback"] += 1
        logger.info(f"AI static-fallback ({_t.time()-t0:.1f}s)")
        return fb
    logger.warning(f"AI ALL FAILED ({_t.time()-t0:.1f}s) — returning empty")
    return ""


async def comment(prompt: str, extra_context: str = "", mood: str = "",
                  dialog_history: Optional[List[dict]] = None) -> str:
    """Generate a group comment through OpenClaw (shorter, livelier).

    Groups use allow_static_fallback=False — if AI is silent, skip the reply
    rather than post a robotic static phrase. Better silent than spammy.
    """
    from bot.persona import COMMENT_PROMPT
    system = COMMENT_PROMPT
    if mood:
        system += f"\n\nТвоё текущее настроение: {mood}."
    out = await chat(
        prompt, system=system, extra_context=extra_context,
        dialog_history=dialog_history, max_tokens=400, temperature=0.95,
        allow_static_fallback=False,
    )
    if not out:
        return ""
    return out


def stats() -> dict:
    return dict(_stats)
