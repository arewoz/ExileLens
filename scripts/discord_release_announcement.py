"""Build a safe, compact Discord announcement for an ExileLens release.

This helper intentionally has no network or secret handling.  GitHub Actions owns
the webhook secret and uses this script only to create a JSON payload file.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPOSITORY_URL = "https://github.com/arewoz/ExileLens"
CHANGELOG_URL = f"{REPOSITORY_URL}/blob/main/packaging/CHANGELOG.txt"
_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:b\d+)?$")
_HEADING = re.compile(r"^(\d+\.\d+\.\d+(?:b\d+)?)\s*$")
_BULLET = re.compile(r"^\s*-\s+(.+?)\s*$")
_MENTION = re.compile(r"@(everyone|here|[!&]?\d+)", re.IGNORECASE)


def _safe_text(value: str) -> str:
    """Keep changelog prose readable without allowing Discord mentions."""
    return _MENTION.sub(lambda match: "@\u200b" + match.group(1), value.replace("\r", " ").strip())


def extract_highlights(changelog: Path, version: str, *, limit: int = 4) -> list[str]:
    """Extract up to ``limit`` deterministic bullets from a plain-text section."""
    try:
        lines = changelog.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    active = False
    highlights: list[str] = []
    for line in lines:
        heading = _HEADING.match(line)
        if heading:
            if active:
                break
            active = heading.group(1) == version
            continue
        if not active:
            continue
        bullet = _BULLET.match(line)
        if bullet:
            text = _safe_text(bullet.group(1))
            if text:
                highlights.append(text[:220])
        if len(highlights) >= limit:
            break
    return highlights


def build_payload(version: str, changelog: Path) -> dict[str, object]:
    """Return a webhook payload containing only fixed official links and safe text."""
    version = version.removeprefix("v")
    if not _VERSION.fullmatch(version):
        raise ValueError("version must use the canonical ExileLens format")
    highlights = extract_highlights(changelog, version)
    release_url = f"{REPOSITORY_URL}/releases/tag/v{version}"
    whats_new = "\n".join(f"• {item}" for item in highlights) or "See the full changelog for release details."
    return {
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": f"🚀 ExileLens {version} is out!",
                "description": "A new ExileLens beta is available.",
                "color": 0x5865F2,
                "fields": [
                    {"name": "What's new", "value": whats_new, "inline": False},
                    {"name": "Download", "value": f"[Download from GitHub Releases]({release_url})", "inline": True},
                    {"name": "Full changelog", "value": f"[View the full changelog]({CHANGELOG_URL})", "inline": True},
                ],
                "footer": {"text": "ExileLens · Free & Open Source"},
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--changelog", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = build_payload(args.version.removeprefix("v"), args.changelog)
    args.output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
