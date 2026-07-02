"""
Context builder for AI Mega Bot — assembles "who/where/recent/memory" context
for AI prompts in groups, so the model understands the conversation.
"""

import re
from typing import List

from aiogram.types import Message

from bot.config import config


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
    # @mention
    if f"@{handle}" in text:
        return True
    # reply to the bot
    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.id == config.BOT_ID:
            return True
    # bare name (no @) at start
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


def build_group_context(message: Message, recent_text: str, memory_facts: List[str]) -> str:
    who = user_descriptor(message)
    where = chat_descriptor(message)
    now = _now_moscow()
    parts = [
        f"Контекст: чат «{where}», сейчас {now}.",
        f"Пишет: {who}.",
    ]
    if recent_text:
        parts.append("Недавняя беседа:\n" + recent_text)
    if memory_facts:
        parts.append("Что помнишь об участниках:\n- " + "\n- ".join(memory_facts))
    return "\n\n".join(parts)


def _now_moscow() -> str:
    import time
    t = time.gmtime()
    h = (t.tm_hour + 3) % 24
    tod = "ночь" if 0 <= h < 6 else "утро" if h < 12 else "день" if h < 18 else "вечер"
    days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    return f"{h:02d}:{t.tm_min:02d}, {tod}, {days[t.tm_wday]}"
