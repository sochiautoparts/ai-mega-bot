"""
Dynamic mood for AI Mega Bot.

Mood drifts with time of day and the sentiment of recent messages. The current
mood descriptor is injected into AI prompts so responses feel alive.
"""

import asyncio
import logging
import random
import time

logger = logging.getLogger("mega.mood")

_MOODS_BY_TIME = {
    "night":   ["сонная", "тихая", "спокойная"],
    "morning": ["бодрая", "свежая", "весёлая"],
    "day":     ["активная", "деятельная", "бодрая"],
    "evening": ["расслабленная", "уютная", "задумчивая"],
}

_POSITIVE = ["радостная", "воодушевлённая", "тёплая"]
_NEGATIVE = ["грустная", "озабоченная", "сдержанная"]

_current: str = "бодрая"


def _time_of_day() -> str:
    # Moscow time (UTC+3)
    h = (time.gmtime().tm_hour + 3) % 24
    if 0 <= h < 6:
        return "night"
    if 6 <= h < 12:
        return "morning"
    if 12 <= h < 18:
        return "day"
    return "evening"


async def mood_loop() -> None:
    """Periodically drift mood based on time of day."""
    global _current
    while True:
        await asyncio.sleep(900)  # 15 min
        try:
            tod = _time_of_day()
            _current = random.choice(_MOODS_BY_TIME[tod])
        except Exception:
            pass


def update_mood_from_message(text: str) -> None:
    """Light sentiment nudge — does not override time-of-day base."""
    global _current
    t = (text or "").lower()
    if any(w in t for w in ["спасибо", "класс", "супер", "обожаю", "❤", "🔥"]):
        _current = random.choice(_POSITIVE)
    elif any(w in t for w in ["грустно", "плохо", "ужас", "печаль", "устал"]):
        _current = random.choice(_NEGATIVE)


async def current_mood_descriptor() -> str:
    return _current
