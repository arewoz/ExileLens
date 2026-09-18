"""Offline contract tests for the Discord release announcement payload."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("discord_release_announcement", ROOT / "scripts" / "discord_release_announcement.py")
assert SPEC and SPEC.loader
announcement = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(announcement)


def _fields(payload: dict[str, object]) -> dict[str, str]:
    return {field["name"]: field["value"] for field in payload["embeds"][0]["fields"]}


def test_one_highlight_has_a_complete_release_layout(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.txt"
    changelog.write_text("0.2.1b3\n-------\n- One real change.\n", encoding="utf-8")
    payload = announcement.build_payload("v0.2.1b3", changelog)
    embed = payload["embeds"][0]
    fields = _fields(payload)
    assert embed["title"] == "🚀 ExileLens 0.2.1b3 is out!"
    assert embed["description"] == "A new ExileLens beta is available."
    assert fields["What's new"] == "• One real change."
    assert fields["Download"].endswith("/releases/tag/v0.2.1b3)")
    assert announcement.CHANGELOG_URL in fields["Full changelog"]
    assert embed["footer"]["text"] == "ExileLens · Free & Open Source"


def test_highlights_are_bounded_ordered_and_mentions_are_neutralized(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.txt"
    changelog.write_text(
        "1.2.3\n-----\n- @everyone first\n- @here second\n- <@123> third\n- <@&123> fourth\n- fifth\n\n1.2.2\n-----\n- old\n",
        encoding="utf-8",
    )
    fields = _fields(announcement.build_payload("1.2.3", changelog))
    highlights = fields["What's new"].splitlines()
    assert len(highlights) == 4
    assert "first" in highlights[0] and "fourth" in highlights[3]
    assert "old" not in fields["What's new"]
    assert all(token not in fields["What's new"] for token in ("@everyone", "@here", "<@123>", "<@&123>"))


def test_no_highlights_has_a_useful_neutral_fallback(tmp_path: Path) -> None:
    payload = announcement.build_payload("1.2.3", tmp_path / "missing.txt")
    fields = _fields(payload)
    assert fields["What's new"] == "See the full changelog for release details."
    assert "/releases/tag/v1.2.3" in fields["Download"]
    assert announcement.CHANGELOG_URL in fields["Full changelog"]


def test_payload_uses_only_safe_github_links_and_disables_mentions() -> None:
    payload = announcement.build_payload("0.2.1b3", ROOT / "packaging" / "CHANGELOG.txt")
    assert payload["allowed_mentions"] == {"parse": []}
    for value in _fields(payload).values():
        for url in re.findall(r"https://[^)]+", value):
            assert url.startswith(announcement.REPOSITORY_URL + "/")


def test_workflow_posts_after_release_and_treats_discord_as_best_effort() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert workflow.index("Create published release") < workflow.index("Announce published release on Discord")
    assert "${{ secrets.DISCORD_RELEASE_WEBHOOK }}" in workflow
    assert "DISCORD_RELEASE_WEBHOOK is not configured" in workflow
    assert "catch {" in workflow
    assert "the release remains published" in workflow
