"""The release workflow's dry-run mode runs the whole signing path but can publish nothing."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8").replace("\r\n", "\n")


def _step(name: str) -> str:
    """The raw text of one workflow step (from its '- name:' line to the next step)."""
    match = re.search(rf"^      - name: {re.escape(name)}\n(.*?)(?=^      - name: |\Z)", TEXT, re.S | re.M)
    assert match, name
    return match.group(1)


def _condition(name: str) -> str | None:
    found = re.search(r"^        if: (.+)$", _step(name), re.M)
    return found.group(1).replace(" ", "") if found else None


def test_dry_run_input_defaults_to_false_so_the_normal_release_path_is_unchanged() -> None:
    block = re.search(r"^      dry_run:\n(.*?)(?=^      \w+:\n)", TEXT, re.S | re.M)
    assert block and "type: boolean" in block.group(1) and "default: false" in block.group(1)


def test_every_publishing_or_announcing_step_is_skipped_in_dry_run() -> None:
    for name in ("Create published release", "Build Discord release announcement", "Announce published release on Discord"):
        assert _condition(name) == "${{!inputs.dry_run}}", name
    assert _condition("Dry run summary (nothing is published)") == "${{inputs.dry_run}}"


def test_signing_and_verification_are_never_skipped_by_dry_run() -> None:
    for name in (
        "Run source release gate",
        "Run packaged-artifact release gate",
        "Materialize production update signing key",
        "Require production update signing key",
        "Package and verify release assets",
        "Validate official release notes",
    ):
        assert _condition(name) is None, name


def test_dry_run_publishes_nothing_and_uploads_no_artifacts() -> None:
    order = [m.group(1) for m in re.finditer(r"^      - name: (.+)$", TEXT, re.M)]
    summary = order.index("Dry run summary (nothing is published)")
    assert order.index("Package and verify release assets") < summary < order.index("Create published release")
    assert "upload-artifact" not in TEXT and "--draft" not in TEXT
    body = _step("Dry run summary (nothing is published)")
    assert "gh release" not in body and "git push" not in body and "curl" not in body
