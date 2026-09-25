from __future__ import annotations

GITHUB_OWNER = "arewoz"
GITHUB_REPO = "ExileLens"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
GITHUB_LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
GITHUB_ISSUES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/issues"
DISCORD_INVITE_URL = "https://discord.gg/4jrhBbSwEn"

CHECK_COOLDOWN_SECONDS = 24 * 60 * 60
NETWORK_TIMEOUT_SECONDS = 15
DOWNLOAD_CHUNK_BYTES = 256 * 1024
DOWNLOAD_STALL_SECONDS = 120

MANIFEST_SCHEMA = 1
UPDATE_MANIFEST_SUFFIX = ".update.json"
