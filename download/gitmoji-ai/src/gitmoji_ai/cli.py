"""
CLI interface — main entry point using Typer + Rich
"""

import asyncio
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Confirm, Prompt
from rich.text import Text

from gitmoji_ai import __version__
from gitmoji_ai.config import get_settings
from gitmoji_ai.git_ops import (
    get_repo_info, get_staged_diff, get_unstaged_diff,
    stage_all, create_commit,
)
from gitmoji_ai.ai_engine import generate_commit_messages, analyze_diff
from gitmoji_ai.changelog import generate_changelog, update_changelog_file
from gitmoji_ai.usage import track_usage, check_limit, get_usage_stats, activate_license

console = Console()
app = typer.Typer(
    name="gitmoji-ai",
    help="🤖 AI-powered commit messages & changelog generator",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def version_callback(value: bool):
    if value:
        console.print(f"[bold green]gitmoji-ai[/] v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True,
        help="Show version",
    ),
):
    """🤖 AI-powered commit messages & changelog generator"""


@app.command()
def commit(
    style: str = typer.Option("conventional", "--style", "-s", help="Commit style: conventional, emoji, plain"),
    language: str = typer.Option("en", "--lang", "-l", help="Language: en, ru, es, de, fr"),
    stage: bool = typer.Option(False, "--stage", "-a", help="Stage all changes before committing"),
    sign: bool = typer.Option(False, "--sign", "-S", help="GPG-sign the commit"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    path: str = typer.Option(".", "--path", "-p", help="Repository path"),
):
    """🤖 Generate AI commit message and commit"""

    # Check limits (also checks GitHub Sponsors)
    from gitmoji_ai.sponsors import is_pro_via_sponsor
    is_sponsor, _ = is_pro_via_sponsor()
    if is_sponsor:
        settings = get_settings()
        if not settings.is_pro:
            settings.pro_license_key = "sponsor"

    allowed, remaining = check_limit("commit")
    if not allowed:
        settings = get_settings()
        console.print(Panel(
            f"[red]Monthly limit reached![/red] ({settings.free_commits_per_month} commits/month)\n\n"
            f"Upgrade to [bold green]Pro[/bold green]:\n\n"
            f"  💜 [bold]GitHub Sponsors[/bold] (recommended):\n"
            f"  [link]https://github.com/sponsors/sochiautoparts[/link]\n"
            f"  Then: [cyan]gmai pro login[/cyan]\n\n"
            f"  🔑 Or use a license key:\n"
            f"  [cyan]gmai pro activate YOUR_KEY[/cyan]",
            title="⚠️ Free Tier Limit",
            border_style="red",
        ))
        raise typer.Exit(1)

    # Get repo info
    repo = get_repo_info(path)
    if not repo.is_git_repo:
        console.print("[red]❌ Not a git repository![/red]")
        raise typer.Exit(1)

    # Stage if requested
    if stage:
        console.print("[dim]📦 Staging all changes...[/dim]")
        stage_all(path)

    # Get diff
    diff = get_staged_diff(path)
    if not diff:
        diff = get_unstaged_diff(path)
        if diff:
            console.print("[yellow]⚠️ No staged changes. Showing suggestions for unstaged changes.[/yellow]")
            console.print("[dim]Use --stage flag to auto-stage, or run: git add -A[/dim]")
        else:
            console.print("[red]❌ No changes to commit![/red]")
            raise typer.Exit(1)

    # Analyze diff
    analysis = analyze_diff(diff)
    console.print(Panel(
        f"[bold]📊 Diff Analysis[/bold]\n\n"
        f"  Files changed: [cyan]{analysis.files_changed}[/cyan]\n"
        f"  Lines added: [green]+{analysis.lines_added}[/green]\n"
        f"  Lines removed: [red]-{analysis.lines_removed}[/red]\n"
        f"  Summary: [dim]{analysis.summary}[/dim]",
        border_style="blue",
    ))

    # Generate AI suggestions
    console.print("[dim]🤖 Generating AI commit suggestions...[/dim]")
    suggestions = asyncio.run(generate_commit_messages(diff, language, style))

    if not suggestions:
        console.print("[red]❌ Could not generate suggestions[/red]")
        raise typer.Exit(1)

    # Display suggestions
    table = Table(title="💡 Commit Suggestions", show_lines=True)
    table.add_column("#", style="bold", width=3)
    table.add_column("Message", style="green")
    table.add_column("Confidence", width=10)

    for i, s in enumerate(suggestions, 1):
        conf_color = "green" if s.confidence > 0.8 else "yellow" if s.confidence > 0.6 else "red"
        table.add_row(
            str(i),
            s.message,
            f"[{conf_color}]{s.confidence:.0%}[/{conf_color}]",
        )

    console.print(table)

    # If body exists, show it
    if suggestions[0].body:
        console.print(Panel(
            suggestions[0].body,
            title="📝 Commit Body",
            border_style="dim",
        ))

    # Select
    if yes:
        selected = suggestions[0]
    else:
        choice = Prompt.ask(
            "Select commit",
            choices=[str(i) for i in range(1, len(suggestions) + 1)] + ["e", "q"],
            default="1",
        )
        if choice == "q":
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit()
        if choice == "e":
            custom = Prompt.ask("Enter commit message")
            selected = type(suggestions[0])(
                message=custom, type="chore", scope="",
                description=custom, body="", emoji="🔧", confidence=0.5,
            )
        else:
            selected = suggestions[int(choice) - 1]

    # Confirm and commit
    console.print(f"\n[bold]Selected:[/bold] {selected.message}")

    if yes or Confirm.ask("Create this commit?"):
        full_message = selected.message
        if selected.body:
            full_message += f"\n\n{selected.body}"

        # Add watermark for free tier
        settings = get_settings()
        if not settings.is_pro:
            full_message += "\n\n🤖 Generated by gitmoji-ai (free)"

        success = create_commit(full_message, path, sign)
        if success:
            track_usage("commit")
            console.print(f"[bold green]✅ Committed![/bold green] {selected.message}")
            console.print(f"[dim]Remaining this month: {remaining - 1}[/dim]")
        else:
            console.print("[red]❌ Commit failed![/red]")
    else:
        console.print("[dim]Cancelled.[/dim]")


@app.command()
def changelog(
    version: str = typer.Option("Unreleased", "--version", "-v", help="Version tag"),
    format: str = typer.Option("keepachangelog", "--format", "-f", help="Format: keepachangelog, angular"),
    language: str = typer.Option("en", "--lang", "-l", help="Language: en, ru"),
    since: Optional[str] = typer.Option(None, "--since", help="Generate changes since tag"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path"),
    no_ai: bool = typer.Option(False, "--no-ai", help="Disable AI, use manual grouping"),
    path: str = typer.Option(".", "--path", "-p", help="Repository path"),
):
    """📝 Generate AI-powered changelog"""

    # Check limits
    allowed, remaining = check_limit("changelog")
    if not allowed:
        console.print(Panel(
            "[red]Monthly changelog limit reached![/red]\n\n"
            "Upgrade to Pro for unlimited changelogs:\n"
            "  [cyan]gmai pro activate YOUR_KEY[/cyan]",
            title="⚠️ Free Tier Limit",
            border_style="red",
        ))
        raise typer.Exit(1)

    # Get repo info
    repo = get_repo_info(path)
    if not repo.is_git_repo:
        console.print("[red]❌ Not a git repository![/red]")
        raise typer.Exit(1)

    console.print(f"[dim]📝 Generating changelog v{version}...[/dim]")

    # Generate
    content = asyncio.run(generate_changelog(
        version=version,
        repo_path=path,
        language=language,
        format_style=format,
        since_tag=since,
        use_ai=not no_ai,
    ))

    # Output
    if output:
        from gitmoji_ai.changelog import update_changelog_file
        update_changelog_file(content, output, format)
        console.print(f"[green]✅ Changelog updated in {output}[/green]")
    else:
        console.print(content)

    track_usage("changelog")


@app.command()
def info(
    path: str = typer.Option(".", "--path", "-p", help="Repository path"),
):
    """📊 Show repository info and usage stats"""

    repo = get_repo_info(path)
    stats = get_usage_stats()
    settings = get_settings()

    # Repo info panel
    if repo.is_git_repo:
        repo_panel = Panel(
            f"  [bold]Name:[/bold] {repo.name}\n"
            f"  [bold]Branch:[/bold] {repo.current_branch}\n"
            f"  [bold]Commits:[/bold] {repo.total_commits}\n"
            f"  [bold]Staged:[/bold] {'✅' if repo.has_staged_changes else '❌'}\n"
            f"  [bold]Unstaged:[/bold] {'✅' if repo.has_unstaged_changes else '❌'}",
            title="📁 Repository",
            border_style="blue",
        )
    else:
        repo_panel = Panel("  [red]Not a git repository[/red]", title="📁 Repository", border_style="red")

    # Usage panel — check all Pro sources
    from gitmoji_ai.sponsors import is_pro_via_sponsor
    is_sponsor, sponsor_tier = is_pro_via_sponsor()
    if is_sponsor:
        plan = f"⭐ Pro ({sponsor_tier})"
    elif stats["is_pro"]:
        plan = "⭐ Pro (License Key)"
    else:
        plan = "🆓 Free"
    usage_panel = Panel(
        f"  [bold]Plan:[/bold] {plan}\n"
        f"  [bold]Commits this month:[/bold] {stats['commits_this_month']}/{stats['commit_limit']}\n"
        f"  [bold]Changelogs this month:[/bold] {stats['changelogs_this_month']}/{stats['changelog_limit']}",
        title="📊 Usage",
        border_style="green",
    )

    console.print(repo_panel)
    console.print(usage_panel)

    # API key status
    if settings.openai_api_key:
        console.print("[green]✅ OpenAI API key configured[/green]")
    else:
        console.print("[yellow]⚠️ No OpenAI API key — using fallback mode[/yellow]")
        console.print("[dim]Set GMAI_OPENAI_API_KEY env var for AI-powered suggestions[/dim]")


@app.command()
def pro(
    action: str = typer.Argument(..., help="login | activate | status | purchase | logout"),
    key: Optional[str] = typer.Argument(None, help="License key or GitHub PAT"),
    email: str = typer.Option("", "--email", "-e", help="Email for license"),
):
    """⭐ Manage Pro license (GitHub Sponsors or license key)"""

    if action == "login":
        # GitHub Sponsors flow
        if key:
            # User provided GitHub PAT
            console.print("[dim]🔍 Checking GitHub sponsor status...[/dim]")
            from gitmoji_ai.sponsors import validate_sponsor_token
            is_pro, info = validate_sponsor_token(key)
            if is_pro and info:
                console.print(Panel(
                    f"[bold green]✅ Pro activated via GitHub Sponsors![/bold green]\n\n"
                    f"  Account: [cyan]@{info.github_login}[/cyan]\n"
                    f"  Tier: [bold]{info.tier_name}[/bold] (${info.tier_amount}/month)\n\n"
                    f"Your sponsorship is your Pro license.\n"
                    f"Cancel sponsorship = Pro expires at end of billing period.",
                    title="⭐ Pro Active",
                    border_style="green",
                ))
            else:
                console.print(Panel(
                    "[yellow]⚠️ Not a sponsor yet[/yellow]\n\n"
                    "To get Pro via GitHub Sponsors:\n\n"
                    "  [bold]Step 1:[/bold] Sponsor the project:\n"
                    "  [link]https://github.com/sponsors/sochiautoparts[/link]\n\n"
                    "  [bold]Step 2:[/bold] Choose a tier:\n"
                    "  • $5/month → Pro (unlimited commits + changelogs)\n"
                    "  • $20/month → Team (Pro + team features)\n\n"
                    "  [bold]Step 3:[/bold] Run again:\n"
                    "  [cyan]gmai pro login <your-github-pat>[/cyan]\n\n"
                    "  [dim]Create PAT: github.com/settings/tokens/new?scopes=read:user[/dim]",
                    title="💡 Become a Sponsor",
                    border_style="gold",
                ))
        else:
            # Interactive flow
            from gitmoji_ai.sponsors import device_flow_login
            device_flow_login()

    elif action == "activate":
        # Legacy license key flow
        if not key:
            key = Prompt.ask("Enter your license key")
        if activate_license(key, email):
            console.print("[green]✅ Pro license activated![/green]")
            console.print("[dim]Set GMAI_PRO_LICENSE_KEY env var to persist.[/dim]")
        else:
            console.print("[red]❌ Invalid license key[/red]")

    elif action == "status":
        # Check all Pro sources
        from gitmoji_ai.sponsors import is_pro_via_sponsor
        from gitmoji_ai.usage import check_license_valid

        # Check GitHub Sponsors first
        is_sponsor, tier = is_pro_via_sponsor()
        if is_sponsor:
            console.print(Panel(
                f"[bold green]⭐ Pro is active![/bold green]\n\n"
                f"  Via: {tier}\n\n"
                f"  ✅ Unlimited AI commits\n"
                f"  ✅ Unlimited changelogs\n"
                f"  ✅ No watermarks",
                title="Pro Status",
                border_style="green",
            ))
        elif check_license_valid():
            console.print("[green]⭐ Pro license key is active[/green]")
        else:
            stats = get_usage_stats()
            console.print(Panel(
                f"[yellow]🆓 Using free tier[/yellow]\n\n"
                f"  Commits: {stats['commits_this_month']}/{stats['commit_limit']} this month\n"
                f"  Changelogs: {stats['changelogs_this_month']}/{stats['changelog_limit']} this month\n\n"
                f"[bold]Upgrade to Pro:[/bold]\n"
                f"  💜 GitHub Sponsors: [link]https://github.com/sponsors/sochiautoparts[/link]\n"
                f"  🔑 License key: [cyan]gmai pro activate KEY[/cyan]",
                title="Free Tier",
                border_style="yellow",
            ))

    elif action == "purchase":
        console.print(Panel(
            "⭐ [bold]GitMoji AI Pro[/bold]\n\n"
            "🚀 Unlimited AI commits & changelogs\n"
            "🚀 No watermarks in commit messages\n"
            "🚀 Priority support\n"
            "🚀 Team features\n\n"
            "[bold]💜 Via GitHub Sponsors (recommended):[/bold]\n"
            "  Pro: $5/month\n"
            "  Team: $20/month\n"
            "  [link]https://github.com/sponsors/sochiautoparts[/link]\n\n"
            "[bold]🔑 Via License Key:[/bold]\n"
            "  Coming soon at gitmoji-ai.dev\n\n"
            "[dim]Your sponsorship = your Pro license. Cancel anytime.[/dim]",
            border_style="gold",
        ))

    elif action == "logout":
        from gitmoji_ai.sponsors import clear_github_token
        clear_github_token()
        console.print("[green]🔓 GitHub sponsor token removed[/green]")
        console.print("[dim]Run 'gmai pro login' to re-link your sponsorship[/dim]")

    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        console.print("[dim]Use: login, activate, status, purchase, or logout[/dim]")


@app.command()
def init():
    """🔧 Initialize GitMoji AI in current repository"""

    repo = get_repo_info()
    if not repo.is_git_repo:
        console.print("[red]❌ Not a git repository. Run 'git init' first.[/red]")
        raise typer.Exit(1)

    # Create .env template
    env_path = ".env"
    if not Path(env_path).exists():
        Path(env_path).write_text(
            "# GitMoji AI Configuration\n"
            "GMAI_OPENAI_API_KEY=your-key-here\n"
            "GMAI_DEFAULT_LANGUAGE=en\n"
            "GMAI_COMMIT_STYLE=conventional\n"
            "# GMAI_PRO_LICENSE_KEY=\n",
            encoding="utf-8",
        )
        console.print(f"[green]✅ Created {env_path}[/green]")
    else:
        console.print(f"[yellow]{env_path} already exists[/yellow]")

    # Install git hook
    hooks_dir = Path(repo.root) / ".git" / "hooks"
    hook_path = hooks_dir / "prepare-commit-msg"

    if not hook_path.exists():
        hook_content = """#!/bin/sh
# GitMoji AI — prepare-commit-msg hook
# This hook suggests AI commit messages when you run 'git commit'
# Install: gmai init

COMMIT_MSG_FILE=$1
COMMIT_SOURCE=$2

# Only suggest for regular commits (not merges, etc.)
if [ -z "$COMMIT_SOURCE" ]; then
    # Check if gmai is available
    if command -v gmai &> /dev/null; then
        # Get the staged diff and generate suggestion
        SUGGESTION=$(gmai suggest --quiet 2>/dev/null)
        if [ -n "$SUGGESTION" ]; then
            echo "" >> "$COMMIT_MSG_FILE"
            echo "# 🤖 GitMoji AI Suggestion:" >> "$COMMIT_MSG_FILE"
            echo "# $SUGGESTION" >> "$COMMIT_MSG_FILE"
        fi
    fi
fi
"""
        hook_path.write_text(hook_content, encoding="utf-8")
        hook_path.chmod(0o755)
        console.print("[green]✅ Installed prepare-commit-msg hook[/green]")
    else:
        console.print("[yellow]prepare-commit-msg hook already exists[/yellow]")

    # Add to .gitignore
    gitignore_path = Path(repo.root) / ".gitignore"
    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding="utf-8")
        if ".env" not in content:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write("\n# GitMoji AI\n.env\n")
            console.print("[green]✅ Added .env to .gitignore[/green]")

    console.print(Panel(
        "[bold green]🎉 GitMoji AI initialized![/bold green]\n\n"
        "Next steps:\n"
        "1. Add your OpenAI key to .env\n"
        "2. Make some changes\n"
        "3. Run: [cyan]gmai commit[/cyan]\n\n"
        "Or use the git hook — just run [cyan]git commit[/cyan]!",
        border_style="green",
    ))


if __name__ == "__main__":
    app()
