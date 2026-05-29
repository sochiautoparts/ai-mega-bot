"""
Quick suggest command — for git hooks integration
Outputs a single commit message without interactive prompts
"""

import asyncio
import sys
from gitmoji_ai.git_ops import get_staged_diff, get_unstaged_diff
from gitmoji_ai.ai_engine import generate_commit_messages
from gitmoji_ai.config import get_settings


def suggest_commit(path: str = ".", language: str = "en", style: str = "conventional") -> str:
    """Generate a single commit suggestion (non-interactive, for hooks)"""
    diff = get_staged_diff(path)
    if not diff:
        diff = get_unstaged_diff(path)
    if not diff:
        return ""

    suggestions = asyncio.run(generate_commit_messages(diff, language, style))
    if suggestions:
        return suggestions[0].message
    return ""
