"""
Context builder for AI Mega Bot — assembles "who/where/recent/memory" context
for AI prompts, so the model understands the conversation and the people.

Василий remembers:
  - Global user profiles (name, how many times we talked, first seen)
  - Global facts about each user (learned across ALL chats — private + groups)
  - Per-group recent message transcript
  - Per-group memory facts
"""

import re
import time
from typing import List, Optional

from aiogram.types import Message

from bot.config import config
from bot import database as db


def user_descriptor(message: Message) -> str:
    u = message.from_user
    if not u:
        return "кто-то"
    name = u.first_name or u.username or "кто-то"
    if u.is_bot:
        return f"{name} (бот)"
    return name


def chat_descriptor(message: Message) -> str:
    c = message.chat
    return c.title or c.username or ("личка" if c.type == "private" else "чат")


def is_directed_at_bot(message: Message) -> bool:
    """True if the message is addressed to the bot (mention / reply / name)."""
    text = (message.text or "").lower()
    handle = config.BOT_HANDLE.lower()
    if not handle:
        return False
    if f"@{handle}" in text:
        return True
    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.id == config.BOT_ID:
            return True
    if text.startswith(handle):
        return True
    return False


def strip_mention(text: str) -> str:
    """Remove the bot @mention/handle from text."""
    if not text:
        return ""
    handle = config.BOT_HANDLE
    out = re.sub(rf"(?i)\s*@{re.escape(handle)}\b", "", text)
    out = re.sub(rf"(?i)^{re.escape(handle)}[,\s:]*", "", out)
    return out.strip()


def recent_messages_to_text(recent: List[dict], limit: int = 8) -> str:
    """Render recent group messages as a compact transcript."""
    lines = []
    for m in recent[-limit:]:
        who = m.get("first_name") or m.get("username") or "кто-то"
        if m.get("user_id") == config.BOT_ID:
            who = "Василий"
        content = m.get("content") or ""
        if m.get("is_media"):
            cap = m.get("media_caption") or ""
            content = f"[фото{': ' + cap if cap else ''}]"
        if content.strip():
            lines.append(f"{who}: {content}")
    return "\n".join(lines)


async def build_user_profile(user_id: int) -> str:
    """Build a human-readable profile of a user: name, history, known facts.

    Used in BOTH private chat and groups, so Василий knows who he's talking to.
    Returns '' if the user is unknown.
    """
    user = await db.get_user(user_id)
    if not user:
        return ""
    parts = []
    name = user.get("first_name") or user.get("username") or f"пользователь {user_id}"
    if user.get("username"):
        name += f" (@{user['username']})"
    parts.append(name)
    # Acquaintance level
    total = user.get("msg_count", 0) or 0
    priv = user.get("private_msgs", 0) or 0
    grp = user.get("group_msgs", 0) or 0
    if total > 0:
        if total < 3:
            parts.append("(общались мало)")
        elif total < 20:
            parts.append(f"(виделись {total} раз, личка: {priv}, группы: {grp})")
        else:
            parts.append(f"(давние знакомые, ~{total} сообщений)")
    # Known facts about this person
    facts_rows = await db.get_user_facts(user_id, limit=10)
    if facts_rows:
        facts = [r["fact"] for r in facts_rows]
        parts.append("что знаю о нём:\n- " + "\n- ".join(facts))
    return "\n".join(parts) if len(parts) > 1 else ""


def build_group_context(message: Message, recent_text: str, memory_facts: List[str],
                        author_profile: str = "") -> str:
    """Assemble full context for a group AI prompt.

    author_profile: output of build_user_profile() for the message author
                    (passed in so we don't re-fetch).
    """
    who = user_descriptor(message)
    where = chat_descriptor(message)
    now = _now_moscow()
    parts = [
        f"Контекст: чат «{where}», сейчас {now}.",
    ]
    # Author profile — who is writing, what we know about them
    if author_profile:
        parts.append(f"Кто пишет:\n{author_profile}")
    else:
        parts.append(f"Пишет: {who}.")
    if recent_text:
        parts.append("Недавняя беседа:\n" + recent_text)
    if memory_facts:
        parts.append("Что помнишь об участниках чата:\n- " + "\n- ".join(memory_facts))
    return "\n\n".join(parts)


def build_private_context(user_profile: str) -> str:
    """Context for private chat prompt: time + what we know about the user."""
    now = _now_moscow()
    parts = [f"Сейчас {now}."]
    if user_profile:
        parts.append(f"С кем общаешься:\n{user_profile}")
    return "\n\n".join(parts)


def _now_moscow() -> str:
    t = time.gmtime()
    h = (t.tm_hour + 3) % 24
    tod = "ночь" if 0 <= h < 6 else "утро" if h < 12 else "день" if h < 18 else "вечер"
    days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    return f"{h:02d}:{t.tm_min:02d}, {tod}, {days[t.tm_wday]}"


# ── Fact extraction ─────────────────────────────────────────────────────────
# Patterns that reveal personal info. Matches are turned into third-person
# facts ("Павел живёт в Москве") and stored globally in user_facts.
_FACT_PATTERNS = [
    ("я живу в ", "живёт в"),
    ("я из ", "родом из"),
    ("я работаю в ", "работает в"),
    ("я работаю ", "работает"),
    ("я учусь ", "учится"),
    ("я учусь в ", "учится в"),
    ("у меня собака", "есть собака"),
    ("у меня кот", "есть кот"),
    ("у меня кошка", "есть кошка"),
    ("у меня ребенок", "есть ребенок"),
    ("у меня дети", "есть дети"),
    ("у меня сын", "есть сын"),
    ("у меня дочь", "есть дочь"),
    ("я люблю ", "любит"),
    ("мне нравится ", "нравится"),
    ("я обожаю ", "обожает"),
    ("я ненавижу ", "не любит"),
    ("я фрилансер", "фрилансер"),
    ("я программист", "программист"),
    ("я дизайнер", "дизайнер"),
    ("я маркетолог", "маркетолог"),
    ("я инженер", "инженер"),
    ("я студент", "студент"),
    ("я езжу на ", "ездит на"),
    ("у меня ", "имеет"),
    ("я был в ", "был в"),
    ("я была в ", "был в"),
    ("мне ", "упоминает что ему"),
]


async def extract_and_store_facts(user_id: int, name: str, text: str,
                                  source_chat: int = 0) -> List[str]:
    """Extract personal facts from a user message and store them globally.

    Returns the list of new facts actually stored (for logging).
    """
    if not text or not name:
        return []
    t = text.lower().strip()
    stored = []
    for pattern, label in _FACT_PATTERNS:
        if pattern in t:
            idx = t.index(pattern) + len(pattern)
            rest = text[idx:idx + 80].split(".")[0].split("!")[0].split("?")[0].strip()
            if rest and 2 < len(rest) < 80:
                fact = f"{name} {label} {rest}".strip()
                if not await db.has_user_fact(user_id, fact):
                    await db.add_user_fact(user_id, fact, source_chat)
                    stored.append(fact)
                break  # one fact per message
    return stored
