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
import os
import random
from typing import List, Optional

import httpx

from bot.config import config
from ai.local_model import call_local

logger = logging.getLogger("mega.ai")

# OpenClaw serves the OpenAI-compatible endpoint on the gateway port.
_ENDPOINT = f"{config.OPENCLAW_URL}/v1/chat/completions"
_MODEL = "openclaw"  # routes to the agent's configured primary + fallbacks

# Direct Pollinations backup (free, no key) — used if OpenClaw returns empty.
_POLLINATIONS_URL = "https://text.pollinations.ai/openai/chat/completions"
_POLLINATIONS_MODEL = "openai"

# Cloudflare Workers AI (reliable tier — real content in 2026-09)
_CF_MODEL = "@cf/meta/llama-4-scout-17b-16e-instruct"
_CF_ACCOUNTS = []
for _i in range(1, 3):
    _aid = os.getenv(f"CF_ACCOUNT_ID_{_i}", "")
    _tok = os.getenv(f"CF_API_TOKEN_{_i}", "")
    if _aid and _tok:
        _CF_ACCOUNTS.append((_aid, _tok))
_CF_ACCOUNT_IDX = 0

def _get_cf_account():
    """Get next Cloudflare account (round-robin). Returns (account_id, token) or None."""
    global _CF_ACCOUNT_IDX
    if not _CF_ACCOUNTS:
        return None
    acct = _CF_ACCOUNTS[_CF_ACCOUNT_IDX % len(_CF_ACCOUNTS)]
    _CF_ACCOUNT_IDX += 1
    return acct

# ─── Garbage detection: static placeholders / ads / quota notices ───
# 2026-09-11: Pollinations began returning a static ~344-char notice with HTTP 200
# on exhausted keys. Filter it out so garbage never reaches chat/posts.
_GARBAGE_MARKERS = [
    "pollinations.ai/keys", "api key is required", "invalid api key",
    "rate limit", "rate_limit", "too many requests", "payment required",
    "quota exceeded", "unauthorized", "support pollinations", "get one at",
    "out of pollen", "need pollen", "subscribe to", "access denied",
]
_recent_resp_hashes: list = []

def _looks_garbage(text, expect_russian=True):
    """Reject static placeholder/ad/quota responses that are not real content."""
    import hashlib as _hl
    if not text: return True
    t = text.strip()
    if len(t) < 3: return True
    tl = t.lower()
    for m in _GARBAGE_MARKERS:
        if m in tl: return True
    # Identical response repeated across different prompts → static placeholder
    h = _hl.md5(t.encode()).hexdigest()
    if h in _recent_resp_hashes: return True
    _recent_resp_hashes.append(h)
    if len(_recent_resp_hashes) > 6: _recent_resp_hashes.pop(0)
    # Bot replies in Russian — reject mostly-Latin garbage
    if expect_russian:
        letters = [c for c in t if c.isalpha()]
        if letters:
            cyr = sum(1 for c in letters if ('а' <= c.lower() <= 'я') or c.lower() == 'ё')
            if cyr / len(letters) < 0.2: return True
    return False

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

    Uses POST /openai/chat/completions (OpenAI-compatible). The model is
    openai-fast (GPT-OSS 20B, reasoning). Returns the content field, stripping
    any 'reasoning' field the model may emit separately.

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
        "referrer": "aimega-bot",
    }
    try:
        r = await _client.post(_POLLINATIONS_URL, json=payload, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            choices = data.get("choices") or []
            if choices:
                msg = choices[0].get("message", {}) or {}
                content = msg.get("content", "") or ""
                # Model may emit a separate 'reasoning' field — ignore it,
                # we only want the final answer in 'content'.
                if content.strip():
                    clean = content.strip()
                    return clean if not _looks_garbage(clean) else ""
                # Sometimes content is empty but reasoning has the answer —
                # fall back to it (stripped) as last resort.
                reasoning = msg.get("reasoning", "") or ""
                if reasoning.strip() and not content.strip():
                    # reasoning often ends with the answer; take last 2 sentences
                    parts = reasoning.strip().split(".")
                    cand = ".".join(parts[-3:]).strip()[:500] if parts else ""
                    return cand if not _looks_garbage(cand) else ""
        elif r.status_code == 429:
            logger.debug(f"pollinations 429 rate-limited")
        else:
            logger.debug(f"pollinations direct HTTP {r.status_code}: {r.text[:200]}")
    except (httpx.ReadTimeout, httpx.ConnectTimeout):
        logger.debug(f"pollinations direct timeout ({timeout}s)")
    except Exception as e:
        logger.debug(f"pollinations direct error: {e}")
    return ""


async def _call_pollinations_get(prompt: str, timeout: float = 12.0) -> str:
    """Fast GET endpoint for short prompts (~3-6s vs 15-20s for POST).

    Pollinations GET endpoint: https://text.pollinations.ai/{prompt}
    No system role support — embed persona instructions into the prompt text.
    Used for short group comments where speed matters most.
    Returns the plain-text response.
    """
    if _client is None:
        await initialize()
    from urllib.parse import quote
    url = f"https://text.pollinations.ai/{quote(prompt)}"
    try:
        r = await _client.get(url, timeout=timeout, headers={"Accept": "text/plain"})
        if r.status_code == 200:
            text = r.text.strip()
            if text and len(text) > 2:
                clean = text[:2000]
                return clean if not _looks_garbage(clean) else ""
        logger.debug(f"pollinations GET HTTP {r.status_code}")
    except (httpx.ReadTimeout, httpx.ConnectTimeout):
        logger.debug(f"pollinations GET timeout ({timeout}s)")
    except Exception as e:
        logger.debug(f"pollinations GET error: {e}")
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
    prefer_local: bool = False,
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

    # Локальная 7B первой — только при явном prefer_local (LOCAL_MODEL_PRIMARY=1)
    if prefer_local:
        out = await call_local(messages, max_tokens, None, mode="post")
        if out:
            _stats["success"] += 1
            logger.info(f"AI primary=local-7B ({_t.time()-t0:.1f}s) len={len(out)}")
            return _strip_name_prefix(out)
        logger.info("Local 7B unavailable/empty — falling back to cloud cascade")

    if fast:
        # Ultra-fast path: for short prompts without heavy context, use GET
        # endpoint (~0.6-6s). For longer prompts (events with research context),
        # use POST. Both are Pollinations direct (no key, anonymous).
        use_get = (not extra_context) and (not dialog_history) and len(prompt) < 400
        if use_get:
            # GET has no system role — embed a SHORT persona instruction.
            # Using the full system prompt would make the URL too long.
            # The short instruction preserves gender + tone + brevity.
            short_persona = (
                "Ты Василий, парень из Сочи. Мужской род всегда. "
                "Отвечай живо, кратко (1-3 предложения), как знакомый в переписке. "
                "По-русски. Без выдуманных фактов. Не начинай с имени."
            )
            embedded = f"{short_persona}\n\nВопрос: {prompt}\n\nОтвет:"
            out = await _call_pollinations_get(embedded, timeout=12.0)
            if out:
                _stats["success"] += 1
                _stats["pollinations_backup"] += 1
                logger.info(f"AI fast=pollinations-GET ({_t.time()-t0:.1f}s) len={len(out)}")
                return _strip_name_prefix(out)
        # POST path (handles system role, dialog history, long prompts)
        out = await _call_pollinations_direct(messages, max_tokens, timeout=30.0)
        if out:
            _stats["success"] += 1
            _stats["pollinations_backup"] += 1
            logger.info(f"AI fast=pollinations-POST ({_t.time()-t0:.1f}s) len={len(out)}")
            return _strip_name_prefix(out)
        # OpenClaw backup (shorter timeout — we already spent up to 30s)
        out = await _call_openclaw(messages, max_tokens, temperature, timeout=15.0)
        if out:
            _stats["success"] += 1
            _stats["openclaw_ok"] += 1
            logger.info(f"AI fast=openclaw-backup ({_t.time()-t0:.1f}s) len={len(out)}")
            return _strip_name_prefix(out)
        # Cloudflare backup (reliable, real content)
        out = await _call_cloudflare(messages, max_tokens, timeout=45.0)
        if out:
            _stats["success"] += 1
            logger.info(f"AI fast=cloudflare-backup ({_t.time()-t0:.1f}s) len={len(out)}")
            return _strip_name_prefix(out)
    else:
        # Quality path: OpenClaw first (best model), Pollinations backup
        out = await _call_openclaw(messages, max_tokens, temperature, timeout=25.0)
        if out:
            _stats["success"] += 1
            _stats["openclaw_ok"] += 1
            logger.info(f"AI openclaw ({_t.time()-t0:.1f}s) len={len(out)}")
            return _strip_name_prefix(out)
        # Pollinations direct backup
        logger.info("OpenClaw empty → trying Pollinations direct backup")
        out = await _call_pollinations_direct(messages, max_tokens, timeout=20.0)
        if out:
            _stats["success"] += 1
            _stats["pollinations_backup"] += 1
            logger.info(f"AI pollinations-backup ({_t.time()-t0:.1f}s) len={len(out)}")
            return _strip_name_prefix(out)
        # Cloudflare backup (reliable, real content, both accounts)
        out = await _call_cloudflare(messages, max_tokens, timeout=60.0)
        if out:
            _stats["success"] += 1
            logger.info(f"AI cloudflare-backup ({_t.time()-t0:.1f}s) len={len(out)}")
            return _strip_name_prefix(out)

    # LOCAL 7B last-resort: автономная модель без сети/ключей/лимитов
    out = await call_local(messages, max_tokens, temperature)
    if out:
        _stats["success"] += 1
        logger.info(f"AI fallback=local-7B ({_t.time()-t0:.1f}s) len={len(out)}")
        return _strip_name_prefix(out)

    # Static fallback (only if allowed)
    _stats["fail"] += 1
    if allow_static_fallback:
        fb = _static_fallback(prompt)
        _stats["static_fallback"] += 1
        logger.info(f"AI static-fallback ({_t.time()-t0:.1f}s)")
        return fb
    logger.warning(f"AI ALL FAILED ({_t.time()-t0:.1f}s) — returning empty")
    return ""


async def _call_cloudflare(messages: List[dict], max_tokens: int, timeout: float = 60.0) -> str:
    """Call Cloudflare Workers AI (reliable). Tries BOTH accounts before giving up."""
    if _client is None:
        await initialize()
    for _ in range(2):
        acct = _get_cf_account()
        if not acct:
            return ""
        account_id, token = acct
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions"
        payload = {
            "model": _CF_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.85,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            r = await _client.post(url, json=payload, timeout=timeout, headers=headers)
            if r.status_code == 200:
                data = r.json()
                # Cloudflare returns either OpenAI format or {result: {response: ...}}
                choices = data.get("choices") or []
                if choices:
                    content = (choices[0].get("message", {}).get("content", "") or "").strip()
                    if content and not _looks_garbage(content):
                        return content
                result = data.get("result", {})
                if isinstance(result, dict):
                    content = (result.get("response", "") or "").strip()
                    if content and not _looks_garbage(content):
                        return content
        except Exception as e:
            _stats["last_error"] = f"Cloudflare: {type(e).__name__}: {e}"
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
    return _strip_name_prefix(out)


def _strip_name_prefix(text: str) -> str:
    """Remove 'Василий:' or 'Ответ:' prefix from AI responses."""
    if not text:
        return text
    import re
    stripped = re.sub(r'^\s*Василий\s*[:,\-—]\s*', '', text, flags=re.IGNORECASE)
    stripped = re.sub(r'^\s*Ответ\s*[:,\-—]\s*', '', stripped, flags=re.IGNORECASE)
    return stripped


async def vision(prompt: str, image_data_uri: str, system: str = "",
                 max_tokens: int = 300) -> str:
    """Describe/understand an image. Uses OpenClaw (routes to vision-capable
    models like Gemini/GPT-4o when keys present). Pollinations has no vision.

    image_data_uri: base64 data URI from media_handler.download_photo_as_base64()
    Returns the assistant text, or '' on failure.
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
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data_uri}},
        ],
    })
    payload = {
        "model": _MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": False,
    }
    try:
        r = await _client.post(_ENDPOINT, json=payload, timeout=30.0)
        if r.status_code == 200:
            data = r.json()
            choices = data.get("choices") or []
            if choices:
                content = choices[0].get("message", {}).get("content", "") or ""
                if content.strip():
                    _stats["success"] += 1
                    _stats["openclaw_ok"] += 1
                    logger.info(f"AI vision ({_t.time()-t0:.1f}s) len={len(content)}")
                    return content.strip()
        _stats["fail"] += 1
        _stats["last_error"] = f"vision HTTP {r.status_code}: {r.text[:200]}"
        logger.warning(f"vision error: {_stats['last_error']}")
    except Exception as e:
        _stats["fail"] += 1
        _stats["last_error"] = f"vision: {type(e).__name__}: {e}"
        logger.warning(f"vision exception: {e}")
    return ""


async def transcribe_audio(audio_data_uri: str, timeout: float = 30.0) -> str:
    """Transcribe a voice message via OpenClaw (routes to Whisper via Groq/HF).

    audio_data_uri: base64 data URI of the audio (data:audio/ogg;base64,...)
    Returns the transcribed text, or '' on failure.
    """
    global _stats
    _stats["requests"] += 1
    import time as _t
    t0 = _t.time()

    if _client is None:
        await initialize()

    # OpenClaw doesn't have a direct audio transcription endpoint, but we can
    # use Groq's Whisper API directly if GROQ_API_KEY is set.
    groq_key = config.GROQ_API_KEY
    if not groq_key:
        _stats["fail"] += 1
        _stats["last_error"] = "transcribe: no GROQ_API_KEY"
        logger.debug("transcribe: no GROQ_API_KEY, skipping")
        return ""

    try:
        import base64 as _b64
        # Extract raw base64 from data URI
        if "," in audio_data_uri:
            raw_b64 = audio_data_uri.split(",", 1)[1]
        else:
            raw_b64 = audio_data_uri
        audio_bytes = _b64.b64decode(raw_b64)

        # Use Groq Whisper API directly
        files = {
            "file": ("voice.ogg", audio_bytes, "audio/ogg"),
            "model": (None, "whisper-large-v3"),
            "language": (None, "ru"),
        }
        r = await _client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {groq_key}"},
            files=files,
            timeout=timeout,
        )
        if r.status_code == 200:
            data = r.json()
            text = data.get("text", "") or ""
            if text.strip():
                _stats["success"] += 1
                logger.info(f"AI transcribe ({_t.time()-t0:.1f}s) len={len(text)}")
                return text.strip()
        _stats["fail"] += 1
        _stats["last_error"] = f"transcribe HTTP {r.status_code}: {r.text[:200]}"
        logger.warning(f"transcribe error: {_stats['last_error']}")
    except Exception as e:
        _stats["fail"] += 1
        _stats["last_error"] = f"transcribe: {type(e).__name__}: {e}"
        logger.warning(f"transcribe exception: {e}")
    return ""


def stats() -> dict:
    s = dict(_stats)
    try:
        from ai.local_model import stats as _local_stats
        s["local"] = _local_stats()
    except Exception:
        pass
    return s
