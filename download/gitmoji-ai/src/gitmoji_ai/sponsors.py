"""
License validation through GitHub Sponsors API

How it works:
1. User sponsors the project on GitHub ($5/month = Pro)
2. gmai pro login — authenticates with GitHub
3. We check if user is an active sponsor via GitHub API
4. If yes → Pro unlocked automatically

No license keys needed — your GitHub sponsorship IS your license!
"""

import time
import logging
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import httpx

from gitmoji_ai.config import get_settings

logger = logging.getLogger(__name__)

# === Configuration ===
SPONSOR_TIER_PRO = 5       # $5/month = Pro
SPONSOR_TIER_TEAM = 20     # $20/month = Team
GITHUB_CLIENT_ID = "Ov23li4G0Vn3TmY9AoFZ"  # Placeholder — replace with real OAuth App

SPONSOR_TARGET = "sochiautoparts"  # GitHub account to sponsor

# === Data ===
@dataclass
class SponsorInfo:
    """Information about a sponsor"""
    github_login: str
    github_id: int
    tier_amount: int       # USD cents per month
    tier_name: str         # "Pro" or "Team"
    is_active: bool
    expires_at: float      # timestamp


# === Local token storage ===
def _get_auth_file() -> Path:
    settings = get_settings()
    settings.ensure_config_dir()
    return settings.config_dir / "auth.json"


def save_github_token(token: str) -> None:
    """Save GitHub OAuth token locally"""
    import json
    auth_file = _get_auth_file()
    auth_file.write_text(json.dumps({
        "github_token": token,
        "saved_at": time.time(),
    }), encoding="utf-8")
    logger.info("GitHub token saved")


def load_github_token() -> Optional[str]:
    """Load saved GitHub token"""
    import json
    auth_file = _get_auth_file()
    if not auth_file.exists():
        return None
    try:
        data = json.loads(auth_file.read_text(encoding="utf-8"))
        return data.get("github_token")
    except Exception:
        return None


def clear_github_token() -> None:
    """Remove saved GitHub token"""
    auth_file = _get_auth_file()
    if auth_file.exists():
        auth_file.unlink()


# === GitHub Sponsors API ===
def check_sponsor_status(github_token: str) -> Optional[SponsorInfo]:
    """
    Check if the GitHub user is an active sponsor.
    
    Uses GitHub GraphQL API to check sponsorships.
    Returns SponsorInfo if active sponsor, None otherwise.
    """
    query = """
    query($login: String!) {
      user(login: $login) {
        sponsorshipsAsSponsor(first: 10, activeOnly: true) {
          nodes {
            sponsorable {
              login
            }
            tier {
              monthlyPriceInCents
              name
            }
            isActive
          }
        }
      }
    }
    """

    # First get the user's login
    user_login = _get_github_login(github_token)
    if not user_login:
        return None

    try:
        response = httpx.post(
            "https://api.github.com/graphql",
            headers={
                "Authorization": f"bearer {github_token}",
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": {"login": user_login}},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        sponsorships = (
            data.get("data", {})
            .get("user", {})
            .get("sponsorshipsAsSponsor", {})
            .get("nodes", [])
        )

        for sponsorship in sponsorships:
            sponsorable = sponsorship.get("sponsorable", {}).get("login", "")
            if sponsorable.lower() == SPONSOR_TARGET.lower():
                tier = sponsorship.get("tier", {})
                amount = tier.get("monthlyPriceInCents", 0) // 100  # cents to dollars
                tier_name = "Team" if amount >= SPONSOR_TIER_TEAM else "Pro"

                return SponsorInfo(
                    github_login=user_login,
                    github_id=0,
                    tier_amount=amount,
                    tier_name=tier_name,
                    is_active=sponsorship.get("isActive", False),
                    expires_at=time.time() + (35 * 86400),  # 35 days (buffer)
                )

        return None  # Not a sponsor

    except Exception as e:
        logger.error(f"Failed to check sponsor status: {e}")
        return None


def _get_github_login(token: str) -> Optional[str]:
    """Get GitHub username from token"""
    try:
        response = httpx.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/json",
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json().get("login")
    except Exception:
        return None


# === Alternative: Device Flow Auth (no OAuth app needed) ===
def device_flow_login() -> Optional[str]:
    """
    GitHub Device Flow authentication.
    No OAuth app required — works with personal access tokens too.
    
    Flow:
    1. Generate device code
    2. User visits github.com/login/device and enters code
    3. Poll for access token
    4. Return token
    """
    # For simplicity, we use a simpler approach:
    # User provides their GitHub PAT with 'read:user' scope
    # We validate it and check sponsor status
    
    print("\n🔗 To link your GitHub sponsorship as your Pro license:")
    print("")
    print("  1. Go to: https://github.com/sponsors/sochiautoparts")
    print("  2. Choose a tier ($5/month = Pro, $20/month = Team)")
    print("  3. Complete sponsorship")
    print("  4. Create a PAT with 'read:user' scope:")
    print("     https://github.com/settings/tokens/new?scopes=read:user")
    print("  5. Run: gmai pro login <your-pat>")
    print("")
    print("  Your sponsorship = your Pro license! 🎉")
    print("  Cancel sponsorship = Pro expires at end of billing period.")
    
    return None


def validate_sponsor_token(token: str) -> tuple[bool, Optional[SponsorInfo]]:
    """
    Validate a GitHub token and check sponsor status.
    Returns (is_pro, sponsor_info)
    """
    # Check if token is valid
    login = _get_github_login(token)
    if not login:
        return False, None

    # Check sponsor status
    info = check_sponsor_status(token)
    if info and info.is_active:
        # Save token for future checks
        save_github_token(token)
        return True, info

    return False, None


def is_pro_via_sponsor() -> tuple[bool, Optional[str]]:
    """
    Check if current user has Pro via GitHub Sponsors.
    Returns (is_pro, tier_name)
    """
    # Check env var first
    settings = get_settings()
    if settings.pro_license_key:
        # Old-style license key — still works
        from gitmoji_ai.usage import check_license_valid
        if check_license_valid():
            return True, "Pro (License Key)"

    # Check saved GitHub token
    github_token = load_github_token()
    if not github_token:
        return False, None

    # Validate
    is_pro, info = validate_sponsor_token(github_token)
    if is_pro and info:
        return True, f"{info.tier_name} (GitHub Sponsor)"

    # Token invalid or not a sponsor anymore
    clear_github_token()
    return False, None
