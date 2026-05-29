"""
Git operations — diff reading, commit creation, repo analysis
"""

import subprocess
import os
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RepoInfo:
    """Basic repository information"""
    name: str
    root: str
    current_branch: str
    is_git_repo: bool
    has_staged_changes: bool
    has_unstaged_changes: bool
    total_commits: int


def get_repo_info(path: str = ".") -> RepoInfo:
    """Get basic repository information"""
    try:
        root = run_git(["rev-parse", "--show-toplevel"], path)
        name = Path(root).name
        branch = run_git(["branch", "--show-current"], path)
        total = int(run_git(["rev-list", "--count", "HEAD"], path))

        staged = run_git(["diff", "--cached", "--quiet"], path, check=False)
        unstaged = run_git(["diff", "--quiet"], path, check=False)

        return RepoInfo(
            name=name,
            root=root,
            current_branch=branch,
            is_git_repo=True,
            has_staged_changes=staged != 0,
            has_unstaged_changes=unstaged != 0,
            total_commits=total,
        )
    except Exception:
        return RepoInfo(
            name="", root="", current_branch="",
            is_git_repo=False, has_staged_changes=False,
            has_unstaged_changes=False, total_commits=0,
        )


def get_staged_diff(path: str = ".") -> str:
    """Get the staged diff (for commit message generation)"""
    return run_git(["diff", "--cached"], path, check=False, default="")


def get_unstaged_diff(path: str = ".") -> str:
    """Get the unstaged diff"""
    return run_git(["diff"], path, check=False, default="")


def get_diff_against_branch(branch: str = "main", path: str = ".") -> str:
    """Get diff against a specific branch"""
    return run_git(["diff", f"{branch}...HEAD"], path, check=False, default="")


def get_recent_commits(count: int = 50, path: str = ".") -> list[dict]:
    """Get recent commits with full info"""
    format_str = "%H|||%s|||%an|||%ae|||%aI|||%b|||END"
    output = run_git(
        ["log", f"-{count}", f"--format={format_str}", "--no-merges"],
        path, check=False, default=""
    )

    commits = []
    for block in output.split("END"):
        block = block.strip()
        if not block:
            continue
        parts = block.split("|||")
        if len(parts) >= 5:
            commits.append({
                "hash": parts[0].strip(),
                "subject": parts[1].strip(),
                "author": parts[2].strip(),
                "email": parts[3].strip(),
                "date": parts[4].strip(),
                "body": parts[5].strip() if len(parts) > 5 else "",
            })

    return commits


def get_commit_tags(path: str = ".") -> dict[str, str]:
    """Get commit hash → tag mapping"""
    output = run_git(["tag", "--list"], path, check=False, default="")
    tags = {}
    for tag in output.strip().split("\n"):
        tag = tag.strip()
        if tag:
            commit_hash = run_git(["rev-list", "-1", tag], path, check=False, default="")
            if commit_hash:
                tags[commit_hash.strip()] = tag
    return tags


def stage_all(path: str = ".") -> bool:
    """Stage all changes"""
    result = run_git(["add", "-A"], path, check=False)
    return result == 0


def create_commit(message: str, path: str = ".", sign: bool = False) -> bool:
    """Create a commit with the given message"""
    args = ["commit", "-m", message]
    if sign:
        args.append("-S")
    result = run_git(args, path, check=False)
    return result == 0


def run_git(
    args: list[str],
    cwd: str = ".",
    check: bool = True,
    default: str = "",
) -> str | int:
    """Run a git command and return output"""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if check and result.returncode != 0:
            logger.warning(f"Git command failed: git {' '.join(args)} — {result.stderr.strip()}")
            return default
        if check:
            return result.stdout.strip()
        return result.returncode
    except subprocess.TimeoutExpired:
        logger.error("Git command timed out")
        return default
    except FileNotFoundError:
        logger.error("Git not found. Is git installed?")
        return default
