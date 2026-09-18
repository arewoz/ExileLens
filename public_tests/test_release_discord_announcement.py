"""Offline contract tests for the Discord release announcement payload."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "discord_release_announcement", ROOT / "scripts" / "discord_release_announcement.py"
)
assert SPEC and SPEC.loader
announcement = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(announcement)


def test_payload_uses_canonical_version_and_official_links() -> None:
    payload = announcement.build_payload("0.2.1b3", ROOT / "packaging" / "CHANGELOG.txt")
    embed = payload["embeds"][0]
    assert embed["title"] == "🚀 ExileLens 0.2.1b3 is out!"
    assert announcement.RELEASES_URL in embed["description"]
    assert announcement.CHANGELOG_URL in embed["description"]
    assert payload["allowed_mentions"] == {"parse": []}
    assert len(embed["description"].splitlines()) <= 7


def test_highlights_are_bounded_and_mentions_are_neutralized(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.txt"
    changelog.write_text(
        "1.2.3\n-----\n- @everyone first\n- @here second\n- <@&123> third\n- fourth\n- fifth\n\n1.2.2\n-----\n- old\n",
        encoding="utf-8",
    )
    highlights = announcement.extract_highlights(changelog, "1.2.3")
    assert len(highlights) == 4
    assert all("@everyone" not in item and "@here" not in item and "<@&123>" not in item for item in highlights)
    assert "@\u200beveryone" in highlights[0]


def test_missing_changelog_falls_back_to_link_only_announcement(tmp_path: Path) -> None:
    payload = announcement.build_payload("1.2.3", tmp_path / "missing.txt")
    description = payload["embeds"][0]["description"]
    assert description == f"[Download]({announcement.RELEASES_URL}) · [Full changelog]({announcement.CHANGELOG_URL})"


def test_workflow_posts_after_release_and_treats_discord_as_best_effort() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert workflow.index("Create published release") < workflow.index("Announce published release on Discord")
    assert "${{ secrets.DISCORD_RELEASE_WEBHOOK }}" in workflow
    assert "DISCORD_RELEASE_WEBHOOK is not configured" in workflow
    assert "catch {" in workflow
    assert "the release remains published" in workflow
    assert "http" not in workflow.split("DISCORD_RELEASE_WEBHOOK", 1)[1].splitlines()[0]
