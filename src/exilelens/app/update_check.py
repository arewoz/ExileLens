"""Small, privacy-preserving GitHub Releases update availability checker."""

from __future__ import annotations

from exilelens._version import __version__, is_packaged
from exilelens.app.updates.constants import (
    CHECK_COOLDOWN_SECONDS,
    DISCORD_INVITE_URL,
    GITHUB_ISSUES_URL,
    GITHUB_LATEST_RELEASE_API,
    GITHUB_RELEASES_API,
    GITHUB_RELEASES_URL,
    NETWORK_TIMEOUT_SECONDS as TIMEOUT_SECONDS,
)
from exilelens.app.updates.github import GitHubReleaseClient
from exilelens.app.updates.service import UpdateCheckService, UpdateService
from exilelens.app.updates.version import ExileLensVersion, Release, parse_release_payload


def parse_latest_release(payload: object) -> Release | None:
    """Validate GitHub's one authoritative, normal latest release response."""
    parsed = parse_release_payload(payload)
    if parsed is None or parsed.prerelease:
        return None
    return parsed


__all__ = [
    "CHECK_COOLDOWN_SECONDS",
    "DISCORD_INVITE_URL",
    "ExileLensVersion",
    "GITHUB_ISSUES_URL",
    "GITHUB_LATEST_RELEASE_API",
    "GITHUB_RELEASES_API",
    "GITHUB_RELEASES_URL",
    "GitHubReleaseClient",
    "Release",
    "TIMEOUT_SECONDS",
    "UpdateCheckService",
    "UpdateService",
    "__version__",
    "is_packaged",
    "parse_latest_release",
]
