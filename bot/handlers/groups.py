"""
Group / Supergroup handler — ACTIVE participation.

Behaviour (requires Privacy Mode DISABLED via @BotFather so the bot receives
ALL group messages, not just mentions):

For every group message:
  1. Log it to group_messages (context window, last N per group).
  2. Update mood from sentiment.
  3. Set a reaction (like) on some messages the bot reads — feels alive.
  4. Decide whether to respond:
     - ALWAYS if directed at the bot (mention / reply / name).
     - With probability GROUP_PROACTIVE_PROB otherwise (be "very active").
     - Other bots' messages: high proactive chance (the bot chats with bots).
  5. Respect rate limiting (safe_send handles RetryAfter).
  6. Build rich context: who, where, recent messages, long-term memory.
  7. For news/events: web-search to supplement the answer with real info.
  8. Generate a comment via OpenClaw and reply.

The bot remembers per-(chat,user) facts and recent topics per chat.
"""

import asyncio
import hashlib
import logging
import random
import re
import time
from typing import List

from aiogram import Router, F
from aiogram.types import Message
from aiogram.enums import ChatAction

from bot.config import config
from bot import database as db
from bot.context import (
    user_descriptor, chat_descriptor, is_directed_at_bot,
    strip_mention, recent_messages_to_text, build_group_context,
    build_user_profile, extract_and_store_facts,
)
from bot.mood import update_mood_from_message, current_mood_descriptor
from bot.reactions import maybe_react
from bot.safe_send import safe_reply
from bot.web_search import verify_claim, research_topic, first_url, all_urls
from bot.media_handler import extract_caption
from ai import client as ai_client
from bot.persona import COMMENT_PROMPT, EVENT_PROMPT, DIRECT_PROMPT

logger = logging.getLogger("mega.groups")

group_router = Router()

# ── Heuristics: when to web-search to supplement the answer ──
_VERIFY_HINTS = [
    "новост", "правда ли", "это правда", "что случилось", "говорят что", "по данным",
    "сегодня", "вчера", "слышал", "прочитал", "вот пишут", "источник", "статья",
    "появился", "вышла", "анонс", "запустили", "анонсировал", "выпустил",
    "сколько стоит", "цена", "когда выйдет", "узнал что", "оказывается",
    "прошёл", "прошла", "состоялся", "состоялась", "открыли", "закрыли",
    "обновил", "обновление", "патч", "версия", "релиз",
    "тренд", "вирусный", "популярн", "обсуждают", "хайп",
]

_EVENT_HINTS = [
    "новост", "событие", "случил", "произош", "прошёл", "прошла",
    "состоялся", "открыли", "закрыли", "запустили", "анонс", "вышла",
    "выпустил", "обновлен", "релиз", "появился", "анонсировал",
    "сегодня", "вчера", "только что", "прямо сейчас",
    "факт", "жесть факт", "знали что", "прикинь", "ого",
    "самый", "крупнейший", "первый в", "единственный",
    "открыла для себя", "узнала", "только что узнала", "не знала",
    "оказывает", "опрос дня", "опрос:", "как вы считаете", "что думаете",
    "кто тоже", "а вы",
]


def _needs_verification(text: str) -> bool:
    t = (text or "").lower()
    if len(t) < 15:
        return False
    return any(h in t for h in _VERIFY_HINTS)


def _is_event_or_news(text: str) -> bool:
    t = (text or "").lower()
    if len(t) < 10:
        return False
    return any(h in t for h in _EVENT_HINTS)


def _is_politics_or_war(text: str) -> bool:
    t = (text or "").lower()
    triggers = ["путин", "кремль", "госдума", "санкци", "сво", "мобилиз",
                "война", "зеленск", "байден", "трамп", "выборы", "парламент",
                "оранжев", "наци", "террор", "обеднен", "обстрел"]
    return any(w in t for w in triggers)


# ── Content dedup: one channel-post forwarded to 5 groups → reply in 1st only ──
_recent_content_hashes: dict = {}
_DEDUP_TTL = 300


def _content_hash(text: str) -> str:
    clean = re.sub(r"^\[[^\]]+\]\s*", "", text or "")
    clean = clean[:100].strip().lower()
    return hashlib.md5(clean.encode()).hexdigest()


def _should_skip_duplicate(text: str, chat_id: int) -> bool:
    now = time.time()
    global _recent_content_hashes
    _recent_content_hashes = {
        k: v for k, v in _recent_content_hashes.items() if now - v[1] < _DEDUP_TTL
    }
    h = _content_hash(text)
    if h in _recent_content_hashes:
        first_chat, _ = _recent_content_hashes[h]
        if first_chat != chat_id:
            return True
        return False
    _recent_content_hashes[h] = (chat_id, now)
    return False


async def _log_group_message(message: Message, content: str = "", is_media: bool = False,
                              media_caption: str = "", is_bot: bool = False):
    u = message.from_user
    if not is_bot and u and (u.id == config.BOT_ID or u.is_bot):
        is_bot = True
    await db.add_group_message(
        chat_id=message.chat.id,
        user_id=u.id if u else 0,
        username=(u.username or "") if u else "",
        first_name=(u.first_name or "") if u else "",
        content=content or (message.text or ""),
        is_media=is_media,
        media_caption=media_caption,
        is_bot=is_bot,
    )


async def _should_respond(message: Message) -> bool:
    u = message.from_user
    if u and u.id == config.BOT_ID:
        return False  # never reply to self

    directed = is_directed_at_bot(message)
    if directed:
        return True

    # Channel auto-forwards: dedup + probability
    is_channel_forward = (
        (u and u.id == 777000)
        or (message.sender_chat and message.sender_chat.type == "channel")
        or (message.forward_from_chat is not None)
    )
    if is_channel_forward:
        if _should_skip_duplicate(message.text or "", message.chat.id):
            return False
        return random.random() < 0.40

    # Reply in an existing discussion thread → more likely to join
    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.id != config.BOT_ID:
            return random.random() < (config.GROUP_PROACTIVE_PROB + 0.2)

    # Other bots' messages: high proactive chance (bot chats with bots)
    if u and u.is_bot:
        return random.random() < 0.65

    return random.random() < config.GROUP_PROACTIVE_PROB


async def _generate_group_response(message: Message, text: str, directed: bool) -> str:
    """Generate the bot's group response via OpenClaw. Returns text or ''."""
    recent = await db.get_recent_group_messages(message.chat.id, limit=12)
    recent_text = recent_messages_to_text(recent, limit=8)
    memory_facts_rows = await db.get_group_memory(message.chat.id, limit=8)
    memory_facts = [r["fact"] for r in memory_facts_rows]

    # ── Author profile: who is writing? (global user knowledge) ──
    author_profile = ""
    u = message.from_user
    if u and not u.is_bot and u.id != config.BOT_ID:
        try:
            await db.upsert_user(u.id, username=u.username or "", first_name=u.first_name or "",
                                 last_name=u.last_name or "", is_bot=u.is_bot, in_group=True)
            author_profile = await build_user_profile(u.id)
        except Exception as e:
            logger.debug(f"author profile error: {e}")

    mood = await current_mood_descriptor()
    extra_ctx = build_group_context(message, recent_text, memory_facts, author_profile)

    # ── Web research: supplement news/events with DETAILED info ──
    is_event = _is_event_or_news(text)
    needs_verify = _needs_verification(text)
    web_context = ""
    web_urls: list = []
    if is_event:
        # News/event → DEEP research: multiple queries + article content fetch
        try:
            web_context = await asyncio.wait_for(
                research_topic(text[:400], max_queries=2), timeout=20.0
            )
            if web_context:
                extra_ctx += "\n\n" + web_context
                web_urls = all_urls(web_context)
                logger.info(f"GROUP RESEARCH (event) found {len(web_context)} chars, {len(web_urls)} urls")
        except (asyncio.TimeoutError, Exception) as e:
            logger.debug(f"research_topic failed: {e}")
    elif needs_verify and random.random() < config.WEB_VERIFY_PROB:
        # Fact claim → quick verify (5s)
        try:
            web_context = await asyncio.wait_for(verify_claim(text[:400]), timeout=6.0)
            if web_context:
                extra_ctx += (
                    "\n\nРезультаты веб-поиска (используй для дополнения ответа, "
                    "упомяни источник если уместно):\n" + web_context
                )
                web_urls = [first_url(web_context)]
                logger.info(f"GROUP VERIFY found context ({len(web_context)} chars)")
        except (asyncio.TimeoutError, Exception) as e:
            logger.debug(f"web verify failed: {e}")

    # Build dialog history from recent messages (role-tagged)
    dialog_history = []
    for m in recent:
        who = m.get("first_name") or m.get("username") or "кто-то"
        if m.get("user_id") == config.BOT_ID:
            role = "assistant"
            content = m.get("content", "")
        else:
            role = "user"
            content = f"{who}: {m.get('content', '')}"
            if m.get("is_media"):
                cap = m.get("media_caption", "")
                content = f"{who}: [фото{': ' + cap if cap else ''}]"
        if content.strip():
            dialog_history.append({"role": role, "content": content})

    # Choose prompt persona based on message type
    if is_event:
        system = EVENT_PROMPT
    elif directed:
        system = DIRECT_PROMPT
    else:
        system = COMMENT_PROMPT
    if mood:
        system += f"\n\nТвоё текущее настроение: {mood}."

    prompt = strip_mention(text) if directed else text
    if not prompt:
        prompt = "(сообщение без текста — прокомментируй контекст чата, вступи в беседу)"

    # Events/news get a longer reply budget (detailed supplementation)
    max_tokens = 700 if is_event else 450
    try:
        out = await asyncio.wait_for(
            ai_client.chat(
                prompt, system=system, extra_context=extra_ctx,
                dialog_history=dialog_history, max_tokens=max_tokens, temperature=0.95,
                allow_static_fallback=False,
            ),
            timeout=50.0,
        )
    except asyncio.TimeoutError:
        logger.warning(f"GROUP AI timeout (50s) chat={message.chat.id}")
        return ""

    out = (out or "").strip()
    if not out:
        return ""

    # Events allow longer detailed answers; regular comments stay compact
    limit = (config.GROUP_MAX_CHARS + 300) if is_event else (
        config.GROUP_MAX_CHARS if directed else config.COMMENT_MAX_CHARS
    )
    out = out[:limit]

    # Append source URLs if web research found them and AI didn't mention them
    if web_urls:
        missing = [u for u in web_urls[:2] if u not in out]
        if missing:
            out += "\n\nИсточник: " + " · ".join(missing)

    return out


@group_router.message(F.new_chat_members)
async def handle_new_members(message: Message):
    """Greet when the bot is added to a group — short, warm, natural.

    No Privacy Mode lecture: that was a leftover from when the real bug
    (chat_router consuming group messages) was still unfixed. Now that the
    router bug is fixed, the bot just says hi and gets to work.
    """
    if message.chat.type not in ("group", "supergroup"):
        return
    newcomers = message.new_chat_members or []
    bot_added = any(m and m.id == config.BOT_ID for m in newcomers)
    if not bot_added:
        return  # someone else was added; stay quiet
    # Bot was just added → pick a varied greeting
    greetings = [
        "Василий на связи 👋 Буду вписываться в беседу, ставить реакции и "
        "дополнять новости из интернета. Кидайте темы!",
        "Здарова! Я Василий 🤖 Готов общаться, реагировать и копать инфу по "
        "новостям. Упомяните (@) или ответьте на сообщение — точно отвечу.",
        "Привет всем! Это Василий 🙂 Буду активно участвовать в чате: "
        "комментарии, реакции, факты из сети. Погнали.",
        "Василий в здании 👋 Готов болтать, лайкать посты и раскапывать "
        "подробности по любым новостям. Чем займёмся?",
    ]
    try:
        import random as _r
        await message.reply(_r.choice(greetings))
        logger.info(f"BOT ADDED to chat {message.chat.id} ({message.chat.title})")
    except Exception as e:
        logger.debug(f"greet on add failed: {e}")


@group_router.message(F.photo)
async def handle_group_photo(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    if message.from_user is None:
        return
    u = message.from_user
    if u.id == config.BOT_ID:
        return
    caption = extract_caption(message)
    await _log_group_message(message, content=caption, is_media=True, media_caption=caption)
    update_mood_from_message(caption)

    if _is_politics_or_war(caption):
        return

    directed = is_directed_at_bot(message)

    # Albums: only react to first photo (skip duplicates), unless directed
    if message.media_group_id:
        if not directed:
            if caption and random.random() < 0.15:
                asyncio.create_task(maybe_react(
                    message.bot, message.chat.id, message.message_id, caption, prob=1.0))
            return

    # Non-directed photo: just a reaction, no text
    if not directed:
        if caption and random.random() < 0.25:
            asyncio.create_task(maybe_react(
                message.bot, message.chat.id, message.message_id, caption, prob=1.0))
        elif not caption and random.random() < 0.10:
            asyncio.create_task(maybe_react(
                message.bot, message.chat.id, message.message_id, "", prob=1.0))
        return

    # Directed photo: respond
    photo_prompt = caption or "(тебе прислали фото — коротко отреагируй живо)"
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        out = await _generate_group_response(message, photo_prompt, directed)
    except Exception as e:
        logger.error(f"group photo response error: {e}")
        return
    if not out:
        return
    await safe_reply(message.bot, message, out, always_reply=True, priority=directed)
    await _log_group_message(message, content=out, is_media=False, is_bot=True)


@group_router.message(F.text)
async def handle_group_text(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    if message.from_user is None:
        return
    u = message.from_user
    if u.id == config.BOT_ID:
        return
    text = (message.text or "").strip()
    if not text:
        return

    directed_early = is_directed_at_bot(message)
    logger.info(
        f"GROUP MSG chat={message.chat.id} ({message.chat.title or '?'}) "
        f"user={u.first_name} ({u.id}) bot={u.is_bot} directed={directed_early} "
        f"text={text[:60]!r}"
    )

    await _log_group_message(message, content=text, is_media=False, is_bot=False)
    update_mood_from_message(text)

    # Set a reaction on some messages the bot reads (alive engagement)
    asyncio.create_task(maybe_react(message.bot, message.chat.id, message.message_id, text))

    if text.startswith("/") and not directed_early:
        return
    if _is_politics_or_war(text) and not directed_early:
        return

    if not await _should_respond(message):
        logger.info(f"GROUP SKIP chat={message.chat.id}")
        return

    directed = directed_early
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        out = await _generate_group_response(message, text, directed)
    except Exception as e:
        logger.error(f"group text response error: {e}")
        return
    if not out:
        logger.warning(f"GROUP NO RESPONSE chat={message.chat.id}")
        return
    logger.info(f"GROUP REPLY chat={message.chat.id} len={len(out)}")
    await safe_reply(message.bot, message, out, always_reply=True, priority=directed)
    await _log_group_message(message, content=out, is_media=False, is_bot=True)

    # Extract & store long-term facts about the user (globally + per-group)
    try:
        await _extract_and_store_memory(message, text)
    except Exception as e:
        logger.debug(f"memory extraction error: {e}")


async def _extract_and_store_memory(message: Message, text: str):
    """Extract personal facts from a user message → store globally + per-group.

    Uses the shared extract_and_store_facts() (global user_facts table) AND
    also mirrors into group_memory so per-group context still shows it.
    """
    if not text or not message.from_user:
        return
    u = message.from_user
    if u.id == 777000 or u.is_bot or u.id == config.BOT_ID:
        return
    if (message.sender_chat and message.sender_chat.type == "channel") or \
       message.forward_from_chat is not None:
        return

    name = u.first_name or u.username or ""
    chat_id = message.chat.id
    # Global storage (used in BOTH private & group context)
    new_facts = await extract_and_store_facts(u.id, name, text, source_chat=chat_id)
    # Mirror into per-group memory for group-context display
    for fact in new_facts:
        await db.add_group_memory(chat_id, u.id, fact)
        logger.info(f"MEMORY STORED (group): {fact}")
