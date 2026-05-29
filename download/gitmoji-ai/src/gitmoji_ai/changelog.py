"""
Changelog generator — AI-powered release notes and changelogs
"""

import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from openai import AsyncOpenAI

from gitmoji_ai.config import get_settings
from gitmoji_ai.git_ops import get_recent_commits, get_commit_tags

logger = logging.getLogger(__name__)


@dataclass
class ChangelogEntry:
    """A single changelog entry"""
    type: str
    scope: str
    description: str
    hash: str
    author: str
    date: str


SYSTEM_PROMPT_CHANGELOG = """You are an expert at writing beautiful, well-organized changelogs.

Rules:
1. Group changes by type: Features, Bug Fixes, Improvements, Documentation, etc.
2. Write in user-friendly language (not technical jargon)
3. Each entry should start with a verb in imperative mood
4. Include breaking changes prominently
5. Keep it concise but informative
6. Format as Markdown

Output a complete changelog section in Markdown format.
"""

SYSTEM_PROMPT_CHANGELOG_RU = """Ты — эксперт по написанию красивых и понятных списков изменений.

Правила:
1. Группируй изменения по типу: Новые функции, Исправления, Улучшения, Документация и т.д.
2. Пиши понятным языком для пользователей, а не техническим жаргоном
3. Каждый пункт начинай с глагола в повелительном наклонении
4. Критические изменения выдели prominently
5. Будь кратким, но информативным
6. Формат — Markdown

Выведи полный раздел changelog в формате Markdown.
"""

CHANGELOG_TEMPLATE = """# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

{entries}
"""

KEEPACHANGELOG_SECTION = """## [{version}] - {date}

{content}
"""

ANGULAR_SECTION = """## {version} ({date})

{content}
"""


def parse_commit_subject(subject: str) -> ChangelogEntry:
    """Parse a conventional commit subject into a ChangelogEntry"""
    # Pattern: type(scope): description or type: description
    pattern = r'^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(?:\(([^)]+)\))?:\s*(.+)$'
    match = re.match(pattern, subject)

    if match:
        return ChangelogEntry(
            type=match.group(1),
            scope=match.group(2) or "",
            description=match.group(3),
            hash="",
            author="",
            date="",
        )

    return ChangelogEntry(
        type="chore",
        scope="",
        description=subject,
        hash="",
        author="",
        date="",
    )


def group_commits_by_type(commits: list[dict]) -> dict[str, list[ChangelogEntry]]:
    """Group commits by their type for changelog organization"""
    groups: dict[str, list[ChangelogEntry]] = {
        "Features": [],
        "Bug Fixes": [],
        "Improvements": [],
        "Documentation": [],
        "Performance": [],
        "Tests": [],
        "Build & CI": [],
        "Other": [],
    }

    type_map = {
        "feat": "Features",
        "fix": "Bug Fixes",
        "refactor": "Improvements",
        "style": "Improvements",
        "docs": "Documentation",
        "perf": "Performance",
        "test": "Tests",
        "build": "Build & CI",
        "ci": "Build & CI",
        "chore": "Build & CI",
        "revert": "Other",
    }

    for commit in commits:
        entry = parse_commit_subject(commit["subject"])
        entry.hash = commit["hash"][:7]
        entry.author = commit["author"]
        entry.date = commit["date"]

        group = type_map.get(entry.type, "Other")
        groups[group].append(entry)

    return {k: v for k, v in groups.items() if v}


async def generate_changelog(
    version: str = "Unreleased",
    repo_path: str = ".",
    language: str = "en",
    format_style: str = "keepachangelog",
    since_tag: Optional[str] = None,
    use_ai: bool = True,
) -> str:
    """Generate a complete changelog"""
    settings = get_settings()

    # Get commits
    commits = get_recent_commits(100, repo_path)

    # Filter by tag if specified
    if since_tag:
        tag_commits = get_commit_tags(repo_path)
        filtered = []
        for c in commits:
            if c["hash"] in tag_commits and tag_commits[c["hash"]] == since_tag:
                break
            filtered.append(c)
        commits = filtered

    if not commits:
        return "No commits found for changelog."

    # Group by type
    grouped = group_commits_by_type(commits)

    # Generate content
    if use_ai and settings.openai_api_key:
        content = await _ai_changelog(grouped, commits, language)
    else:
        content = _manual_changelog(grouped)

    # Format
    today = datetime.now().strftime("%Y-%m-%d")
    if format_style == "angular":
        section = ANGULAR_SECTION.format(version=version, date=today, content=content)
    else:
        section = KEEPACHANGELOG_SECTION.format(version=version, date=today, content=content)

    return section


def _manual_changelog(grouped: dict[str, list[ChangelogEntry]]) -> str:
    """Generate changelog without AI"""
    sections = []
    emoji_map = {
        "Features": "✨",
        "Bug Fixes": "🐛",
        "Improvements": "♻️",
        "Documentation": "📚",
        "Performance": "⚡",
        "Tests": "✅",
        "Build & CI": "👷",
        "Other": "🔧",
    }

    for group_name, entries in grouped.items():
        emoji = emoji_map.get(group_name, "🔧")
        lines = [f"### {emoji} {group_name}", ""]
        for entry in entries:
            scope = f"**{entry.scope}**: " if entry.scope else ""
            hash_ref = f"({entry.hash})" if entry.hash else ""
            lines.append(f"- {scope}{entry.description.capitalize()} {hash_ref}")
        lines.append("")
        sections.append("\n".join(lines))

    return "\n".join(sections)


async def _ai_changelog(
    grouped: dict[str, list[ChangelogEntry]],
    commits: list[dict],
    language: str,
) -> str:
    """Generate AI-enhanced changelog"""
    settings = get_settings()

    # Prepare commit summary for AI
    commit_summary = "\n".join(
        f"- {c['subject']} ({c['hash'][:7]})" for c in commits[:50]
    )

    system_prompt = SYSTEM_PROMPT_CHANGELOG_RU if language == "ru" else SYSTEM_PROMPT_CHANGELOG

    try:
        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Generate changelog from these commits:\n\n{commit_summary}"},
            ],
            max_tokens=2000,
            temperature=0.5,
        )

        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"AI changelog generation failed: {e}")
        return _manual_changelog(grouped)


def update_changelog_file(
    new_section: str,
    changelog_path: str = "CHANGELOG.md",
    format_style: str = "keepachangelog",
) -> bool:
    """Insert new section into existing CHANGELOG.md"""
    path = Path(changelog_path)

    if not path.exists():
        content = CHANGELOG_TEMPLATE.format(entries=new_section)
        path.write_text(content, encoding="utf-8")
        return True

    existing = path.read_text(encoding="utf-8")

    # Find insertion point (after the header)
    if format_style == "keepachangelog":
        # Insert after "## [Unreleased]" or after the header
        marker = "## [Unreleased]"
        if marker in existing:
            idx = existing.index(marker) + len(marker)
            # Skip to the end of the Unreleased section header
            idx = existing.find("\n", idx) + 1
        else:
            # Insert after the first ## heading or after header
            idx = existing.find("\n\n") + 2 if "\n\n" in existing else len(existing)
    else:
        idx = existing.find("\n\n") + 2 if "\n\n" in existing else len(existing)

    updated = existing[:idx] + "\n" + new_section + "\n" + existing[idx:]
    path.write_text(updated, encoding="utf-8")
    return True
