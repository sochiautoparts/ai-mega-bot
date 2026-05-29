"""
AI engine — commit message generation and analysis
"""

import re
import json
import logging
from typing import Optional
from dataclasses import dataclass

from openai import AsyncOpenAI

from gitmoji_ai.config import get_settings

logger = logging.getLogger(__name__)

# === GitMoji definitions ===
GITMOJI_MAP = {
    "feat": "✨",
    "fix": "🐛",
    "docs": "📚",
    "style": "💎",
    "refactor": "♻️",
    "perf": "⚡",
    "test": "✅",
    "build": "📦",
    "ci": "👷",
    "chore": "🔧",
    "revert": "⏪",
    "security": "🔒",
    "i18n": "🌐",
    "accessibility": "♿",
    "analytics": "📈",
    "deps": "➕",
    "remove-deps": "➖",
    "config": "🔧",
    "docker": "🐳",
    "ui": "lipstick",
    "init": "🎉",
    "wip": "🚧",
    "dead-code": "⚰️",
    "licensing": "📝",
    "boom": "💥",
    "mock": "🧪",
    "typo": "✏️",
    "poo": "💩",
    "merge": "🔀",
    "auth": "🛂",
    "api": "🔌",
    "logging": "🔊",
    "database": "🗃️",
    "cleanup": "🧹",
}

CONVENTIONAL_TYPES = [
    "feat", "fix", "docs", "style", "refactor", "perf",
    "test", "build", "ci", "chore", "revert"
]


@dataclass
class CommitSuggestion:
    """A single commit message suggestion"""
    message: str
    type: str
    scope: str
    description: str
    body: str
    emoji: str
    confidence: float


@dataclass
class DiffAnalysis:
    """Analysis of a git diff"""
    files_changed: int
    lines_added: int
    lines_removed: int
    file_types: list[str]
    is_new_feature: bool
    is_bug_fix: bool
    is_refactor: bool
    is_docs: bool
    is_test: bool
    is_config: bool
    summary: str


def analyze_diff(diff_text: str) -> DiffAnalysis:
    """Analyze a git diff to understand what changed"""
    if not diff_text or not diff_text.strip():
        return DiffAnalysis(
            files_changed=0, lines_added=0, lines_removed=0,
            file_types=[], is_new_feature=False, is_bug_fix=False,
            is_refactor=False, is_docs=False, is_test=False,
            is_config=False, summary="No changes detected"
        )

    files_changed = diff_text.count("diff --git")
    lines_added = sum(1 for line in diff_text.split("\n") if line.startswith("+") and not line.startswith("+++"))
    lines_removed = sum(1 for line in diff_text.split("\n") if line.startswith("-") and not line.startswith("---"))

    # Detect file types
    file_types = list(set(
        re.findall(r'\.(\w+)(?:\s|$)', diff_text)
    ))[:10]

    # Detect change type
    diff_lower = diff_text.lower()
    is_new_feature = any(w in diff_lower for w in ["new file", "feat", "add ", "create", "implement"])
    is_bug_fix = any(w in diff_lower for w in ["fix", "bug", "patch", "issue", "resolve"])
    is_refactor = any(w in diff_lower for w in ["refactor", "rename", "move", "reorganize"])
    is_docs = any(w in diff_lower for w in ["readme", "doc", "changelog", ".md"])
    is_test = any(w in diff_lower for w in ["test", "spec", "__test__", ".test.", ".spec."])
    is_config = any(w in diff_lower for w in [".yml", ".yaml", ".json", ".toml", "dockerfile", "makefile"])

    # Quick summary
    parts = []
    if is_new_feature: parts.append("new feature")
    if is_bug_fix: parts.append("bug fix")
    if is_refactor: parts.append("refactoring")
    if is_docs: parts.append("documentation")
    if is_test: parts.append("tests")
    if is_config: parts.append("configuration")
    summary = f"Changed {files_changed} file(s): {', '.join(parts) if parts else 'general changes'}"

    return DiffAnalysis(
        files_changed=files_changed,
        lines_added=lines_added,
        lines_removed=lines_removed,
        file_types=file_types,
        is_new_feature=is_new_feature,
        is_bug_fix=is_bug_fix,
        is_refactor=is_refactor,
        is_docs=is_docs,
        is_test=is_test,
        is_config=is_config,
        summary=summary,
    )


SYSTEM_PROMPT_COMMIT = """You are an expert at writing clear, concise, and conventional git commit messages.

Rules:
1. Follow Conventional Commits format: type(scope): description
2. Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert
3. Scope is optional but recommended (e.g., feat(auth): add login)
4. Description: imperative mood, lowercase, no period, max 72 chars
5. Body: explain WHY, not WHAT (the diff shows what changed)
6. Be specific, not generic ("add email validation" not "update code")
7. If there are multiple logical changes, suggest multiple commits

Output format — JSON array of suggestions:
[
  {
    "message": "type(scope): description",
    "type": "feat",
    "scope": "auth",
    "description": "add email validation to login form",
    "body": "Users were able to submit invalid emails...",
    "emoji": "✨",
    "confidence": 0.95
  }
]

Provide 3 variations: one conventional, one with emoji, one detailed.
"""

SYSTEM_PROMPT_COMMIT_RU = """Ты — эксперт по написанию понятных и лаконичных git commit сообщений.

Правила:
1. Формат Conventional Commits: тип(область): описание
2. Типы: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert
3. Область опциональна, но рекомендуется (например: feat(auth): добавить логин)
4. Описание: повелительное наклонение, строчные буквы, макс 72 символа
5. Body: объясни ПОЧЕМУ, а не ЧТО
6. Будь конкретным ("добавить валидацию email" а не "обновить код")

Формат вывода — JSON массив:
[
  {
    "message": "тип(область): описание",
    "type": "feat",
    "scope": "auth",
    "description": "добавить валидацию email",
    "body": "Пользователи могли отправлять невалидные email...",
    "emoji": "✨",
    "confidence": 0.95
  }
]

Предложи 3 варианта: классический, с эмодзи, подробный.
"""


async def generate_commit_messages(
    diff_text: str,
    language: str = "en",
    style: str = "conventional",
    num_suggestions: int = 3,
) -> list[CommitSuggestion]:
    """Generate AI-powered commit message suggestions from a git diff"""
    settings = get_settings()

    if not settings.openai_api_key:
        return _fallback_commit_messages(diff_text, style)

    # Truncate very large diffs
    max_chars = 12000
    if len(diff_text) > max_chars:
        diff_text = diff_text[:max_chars] + "\n\n... (diff truncated)"

    system_prompt = SYSTEM_PROMPT_COMMIT_RU if language == "ru" else SYSTEM_PROMPT_COMMIT

    user_prompt = f"""Generate commit messages for this diff:

```diff
{diff_text}
```

Style: {style}
Language: {language}
Provide {num_suggestions} variations."""

    try:
        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1500,
            temperature=0.7,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        return _parse_commit_suggestions(content, style)

    except Exception as e:
        logger.error(f"AI generation failed: {e}")
        return _fallback_commit_messages(diff_text, style)


def _parse_commit_suggestions(content: str, style: str) -> list[CommitSuggestion]:
    """Parse AI response into CommitSuggestion objects"""
    try:
        data = json.loads(content)
        suggestions = data.get("suggestions", data.get("commits", []))
        if isinstance(data, list):
            suggestions = data

        results = []
        for s in suggestions[:3]:
            msg_type = s.get("type", "chore")
            emoji = s.get("emoji", GITMOJI_MAP.get(msg_type, "🔧"))
            results.append(CommitSuggestion(
                message=s.get("message", s.get("commit", "chore: update")),
                type=msg_type,
                scope=s.get("scope", ""),
                description=s.get("description", ""),
                body=s.get("body", ""),
                emoji=emoji,
                confidence=s.get("confidence", 0.8),
            ))

        return results if results else _fallback_from_text(content, style)

    except json.JSONDecodeError:
        return _fallback_from_text(content, style)


def _fallback_from_text(content: str, style: str) -> list[CommitSuggestion]:
    """Fallback parsing when JSON fails"""
    lines = [l.strip() for l in content.split("\n") if l.strip() and not l.startswith("#")]
    results = []
    for line in lines[:3]:
        line = line.lstrip("-•*0-9. ")
        msg_type = "chore"
        for t in CONVENTIONAL_TYPES:
            if line.startswith(t):
                msg_type = t
                break
        results.append(CommitSuggestion(
            message=line[:100],
            type=msg_type,
            scope="",
            description=line,
            body="",
            emoji=GITMOJI_MAP.get(msg_type, "🔧"),
            confidence=0.5,
        ))
    return results if results else _fallback_commit_messages("", style)


def _fallback_commit_messages(diff_text: str, style: str) -> list[CommitSuggestion]:
    """Generate basic commit messages without AI (offline fallback)"""
    analysis = analyze_diff(diff_text)

    # Determine primary type
    if analysis.is_new_feature:
        msg_type, emoji = "feat", "✨"
    elif analysis.is_bug_fix:
        msg_type, emoji = "fix", "🐛"
    elif analysis.is_docs:
        msg_type, emoji = "docs", "📚"
    elif analysis.is_test:
        msg_type, emoji = "test", "✅"
    elif analysis.is_refactor:
        msg_type, emoji = "refactor", "♻️"
    elif analysis.is_config:
        msg_type, emoji = "chore", "🔧"
    else:
        msg_type, emoji = "chore", "🔧"

    if style == "emoji":
        message = f"{emoji} {analysis.summary}"
    elif style == "plain":
        message = analysis.summary.capitalize()
    else:
        message = f"{msg_type}: {analysis.summary}"

    return [
        CommitSuggestion(
            message=message,
            type=msg_type,
            scope="",
            description=analysis.summary,
            body="",
            emoji=emoji,
            confidence=0.6,
        ),
    ]
