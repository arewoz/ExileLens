"""Game-update audit orchestration. Never rewrites product code from patch notes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from exilelens.ops.compatibility import load_manifest
from exilelens.ops.patch_impact import classify_notes, parse_notes_text
from exilelens.ops.smoke import run_pytest


def run_game_update(
    *,
    notes_path: Path | None = None,
    notes_text: str | None = None,
    game_version: str | None = None,
    run_tests: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    manifest = load_manifest()
    text = notes_text or ""
    source = "inline"
    if notes_path:
        text = Path(notes_path).read_text(encoding="utf-8")
        source = str(notes_path)
    entries = parse_notes_text(text)
    report = classify_notes(
        entries,
        game_version=game_version,
        previous_verified_version=manifest.game_version,
        patch_source=source,
        root=root,
    )
    if run_tests and report.selected_tests:
        report.test_results = run_pytest(report.selected_tests, root=root)
        passed = report.test_results.get("ok")
        if passed and report.counts()["HIGH"] == 0:
            report.compatibility_decision = "PARTIALLY_SUPPORTED"
            report.notes.append(
                "Selected tests passed. Status is PARTIALLY_SUPPORTED until manual client verification."
            )
        elif passed:
            report.compatibility_decision = "UNVERIFIED"
            report.notes.append("Tests passed but HIGH-impact items still require manual verification.")
        else:
            report.compatibility_decision = "BROKEN"
            report.notes.append("Selected tests failed. Do not mark SUPPORTED. Fix from failing tests, not patch wording.")
    elif report.relevant_entries:
        report.compatibility_decision = "UNVERIFIED"
    payload = report.to_dict()
    payload["forbidden"] = [
        "Do not change scoring, parsers, or overlay behavior solely because a patch note exists.",
        "Do not write SUPPORTED into the compatibility manifest without passing tests plus required manual checks.",
    ]
    return payload
