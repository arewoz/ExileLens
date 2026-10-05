"""1.0-A: the package must carry LICENSE and the third-party notices, and the shipped/public copy must not repeat known stale claims."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from exilelens import __version__
from exilelens.ops.models import GateVerdict
from exilelens.ops.release_gate import (
    DISTRIBUTION_FILES,
    SHIPPING_COPY_FILES,
    THIRD_PARTY_LICENSE_FILES,
    _distribution_files,
    _shipping_copy,
    evaluate_release_gate,
)
from tests.test_release_gate import ROOT, _result, _valid_root

pytestmark = pytest.mark.itemcheck


def test_the_repository_passes_both_new_checks():
    assert _distribution_files(ROOT).status is GateVerdict.PASS
    assert _shipping_copy(ROOT).status is GateVerdict.PASS


def test_the_new_checks_run_inside_the_release_gate(tmp_path: Path):
    report = evaluate_release_gate(root=_valid_root(tmp_path), allow_dirty=True)
    assert _result(report, "distribution_files").status is GateVerdict.PASS
    assert _result(report, "shipping_copy").status is GateVerdict.PASS


@pytest.mark.parametrize("missing", ["LICENSE", "packaging/THIRD_PARTY_NOTICES.txt", *THIRD_PARTY_LICENSE_FILES[:3]])
def test_a_missing_source_file_blocks_the_release(tmp_path: Path, missing: str):
    root = _valid_root(tmp_path)
    (root / missing).unlink()
    report = evaluate_release_gate(root=root, allow_dirty=True)
    assert report.verdict is GateVerdict.BLOCKED
    assert _result(report, "packaging_files").status is GateVerdict.BLOCKED


def test_the_build_script_must_copy_the_license_and_notices(tmp_path: Path):
    root = _valid_root(tmp_path)
    script = root / "scripts" / "build_exe.ps1"
    script.write_text(script.read_text(encoding="utf-8").replace('"LICENSE"', '"LICENCE"'), encoding="utf-8")
    result = _distribution_files(root)
    assert result.status is GateVerdict.BLOCKED and "LICENSE" in result.detail


def test_the_notices_must_point_at_every_shipped_license_text(tmp_path: Path):
    root = _valid_root(tmp_path)
    notices = root / "packaging" / "THIRD_PARTY_NOTICES.txt"
    notices.write_text(notices.read_text(encoding="utf-8").replace("third_party_licenses\\cffi\\LICENSE", "x"), encoding="utf-8")
    assert _distribution_files(root).status is GateVerdict.BLOCKED


def _fake_dist(root: Path) -> Path:
    dist = root / "dist" / "ExileLens"
    (dist / "third_party_licenses").mkdir(parents=True)
    for name in DISTRIBUTION_FILES:
        source = root / ("packaging/" + name if name != "LICENSE" else "LICENSE")
        shutil.copyfile(source, dist / name)
    for rel in THIRD_PARTY_LICENSE_FILES:
        target = dist / "third_party_licenses" / rel.split("third_party_licenses/", 1)[1]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / rel, target)
    return dist


def test_a_built_package_without_the_license_is_blocked_and_with_it_passes(tmp_path: Path):
    root = _valid_root(tmp_path)
    assert _distribution_files(root, required=True).status is GateVerdict.BLOCKED  # nothing built yet
    dist = _fake_dist(root)
    assert _distribution_files(root, required=True).status is GateVerdict.PASS
    (dist / "LICENSE").unlink()
    result = _distribution_files(root, required=True)
    assert result.status is GateVerdict.BLOCKED and "LICENSE" in result.detail
    (dist / "LICENSE").write_text("not the project license", encoding="utf-8")
    assert "differs" in _distribution_files(root, required=True).detail


def test_a_package_missing_a_third_party_text_is_blocked(tmp_path: Path):
    root = _valid_root(tmp_path)
    dist = _fake_dist(root)
    (dist / "third_party_licenses" / "cryptography" / "LICENSE.APACHE").unlink()
    assert _distribution_files(root, required=True).status is GateVerdict.BLOCKED


def test_third_party_texts_are_byte_identical_copies_not_rewrites():
    """They must be upstream files. Sizes are pinned so an accidental edit is noticed."""
    sizes = {rel: (ROOT / rel).stat().st_size for rel in THIRD_PARTY_LICENSE_FILES[1:]}
    assert sizes["packaging/third_party_licenses/cryptography/LICENSE.APACHE"] == 11360
    assert sizes["packaging/third_party_licenses/pyinstaller/COPYING.txt"] == 32138
    assert all(size > 100 for size in sizes.values())
    for rel in THIRD_PARTY_LICENSE_FILES[1:]:
        assert b"
" not in (ROOT / rel).read_bytes(), f"{rel}: line endings were rewritten (.gitattributes pins them)"
    assert "third_party_licenses/** -text" in (ROOT / ".gitattributes").read_text(encoding="utf-8")


# ----------------------------------------------------------------------------------------------- stale-copy guard


def _copy_root(tmp_path: Path) -> Path:
    for rel in SHIPPING_COPY_FILES:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    return tmp_path


@pytest.mark.parametrize(
    "stale",
    [
        "Value for My Build",
        "VALUE / COST    +3.0 Build Value / Ex",
        "Power / Cost    GOOD",
        "ExileLens currently has no analytics / telemetry system.",
        "Optional functionality (live market pricing) may contact the trade site.",
        "This is an early beta.",
    ],
)
def test_known_stale_claims_are_rejected_on_the_shipped_readme(tmp_path: Path, stale: str):
    root = _copy_root(tmp_path)
    readme = root / "packaging" / "README.txt"
    readme.write_text(readme.read_text(encoding="utf-8") + "\n" + stale + "\n", encoding="utf-8")
    result = _shipping_copy(root)
    assert result.status is GateVerdict.BLOCKED and "packaging/README.txt" in result.detail


def test_a_negated_live_market_sentence_is_allowed(tmp_path: Path):
    root = _copy_root(tmp_path)
    readme = root / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nLive market pricing is not a feature of this build.\n", encoding="utf-8")
    assert _shipping_copy(root).status is GateVerdict.PASS


def test_historical_docs_may_keep_old_terminology():
    """Scope: only the current shipped/public surfaces are scanned; the plan/changelog history may name the removed system."""
    assert "docs/R5-MARKET-INTELLIGENCE-PLAN.md" not in SHIPPING_COPY_FILES
    assert "docs/1.0-HARDENING-PLAN.md" not in SHIPPING_COPY_FILES
    assert "packaging/CHANGELOG.txt" not in SHIPPING_COPY_FILES
    assert "VALUE / COST" in (ROOT / "docs" / "R5-MARKET-INTELLIGENCE-PLAN.md").read_text(encoding="utf-8")


def test_beta_wording_is_only_stale_in_release_notes_for_a_final_version():
    from exilelens.ops import release_gate

    notes_rel = "packaging/RELEASE_NOTES.md"
    assert notes_rel in SHIPPING_COPY_FILES and notes_rel not in release_gate._BETA_ALWAYS_FILES
    final = "b" not in __version__.rsplit(".", 1)[-1]
    text = (ROOT / notes_rel).read_text(encoding="utf-8").lower()
    if final:
        assert "early beta" not in text  # at a final version the gate blocks it


def test_the_current_public_copy_has_no_ai_marketing_phrases():
    banned = ("unlock", "next-level", "powerful", "seamless experience", "smarter decisions", "supercharge", "enhanced experience",
              "ai-powered", "game-changing", "excited to announce", "insights")
    for rel in ("packaging/README.txt", "README.md", "PRIVACY.md", "packaging/THIRD_PARTY_NOTICES.txt"):
        text = (ROOT / rel).read_text(encoding="utf-8").lower()
        assert not [word for word in banned if word in text], (rel, [word for word in banned if word in text])


def test_the_application_version_is_unchanged_by_1_0_a():
    from exilelens._version import __version__ as version

    assert version == "0.7.0b1"


# ------------------------------------------------------------------------------------------------- 1.0 drafts (not active)

DRAFTS = ROOT / "docs" / "release-1.0"


def _draft_catalog():
    import json

    from exilelens.whats_new.content import parse_document

    document = json.loads((DRAFTS / "WHATS_NEW_DRAFT.json").read_text(encoding="utf-8"))
    document.pop("_draft")
    document["releases"][0]["released"] = "2026-01-01"  # the draft carries an explicit placeholder date
    return parse_document(document)


def test_the_whats_new_draft_is_lint_clean_for_1_0_0_and_describes_0_6_to_1_0():
    from exilelens.app.updates.version import ExileLensVersion
    from exilelens.whats_new.content import lint_catalog

    catalog = _draft_catalog()
    (release,) = catalog.releases
    assert str(release.version) == "1.0.0" and str(release.previous) == "0.6.0"
    assert lint_catalog(catalog, ExileLensVersion.parse("1.0.0")) == []
    raw = (DRAFTS / "WHATS_NEW_DRAFT.json").read_text(encoding="utf-8")
    assert "TBD-AT-RELEASE" in raw, "no final release date is set in the draft"


def test_the_drafts_are_not_active():
    import json

    live = json.loads((ROOT / "src" / "exilelens" / "whats_new" / "whats_new.json").read_text(encoding="utf-8"))
    assert [row["version"] for row in live["releases"]] == ["0.7.0b1"]
    assert (ROOT / "packaging" / "RELEASE_NOTES.md").read_text(encoding="utf-8").splitlines()[0] == "# ExileLens 0.7.0b1"
    assert "1.0.0" not in (ROOT / "packaging" / "CHANGELOG.txt").read_text(encoding="utf-8")


def test_the_drafts_pass_the_same_copy_rules_and_do_not_advertise_the_market():
    import re

    banned = ("unlock", "next-level", "powerful", "seamless experience", "smarter decisions", "supercharge", "enhanced experience",
              "ai-powered", "game-changing", "excited to announce")
    forbidden_features = ("live market", "market price", "price check", "upgrade finder", "character sync", "astra", "engine")
    internal = re.compile(r"\b(R[1-9](\.\d)?|AMMO-\d+|MARKET-\d+|EL-[A-Z]+-\d+)\b")
    for path in DRAFTS.iterdir():
        text = path.read_text(encoding="utf-8").lower()
        assert not [word for word in banned if word in text], path.name
        assert not internal.search(path.read_text(encoding="utf-8")), (path.name, internal.search(path.read_text(encoding="utf-8")))
        if path.suffix != ".md":
            assert not [word for word in forbidden_features if word in text], (path.name, [w for w in forbidden_features if w in text])
    notes = (DRAFTS / "RELEASE_NOTES_DRAFT.md").read_text(encoding="utf-8").lower()
    assert "does not show prices" in notes and "does not contact the path of exile trade service" in notes  # absence, never a feature
    assert "early beta" not in notes and "beta" not in notes.replace("0.7.x", "")


def test_the_release_notes_draft_follows_the_release_gate_heading_contract():
    lines = (DRAFTS / "RELEASE_NOTES_DRAFT.md").read_text(encoding="utf-8").splitlines()
    assert lines[1] == "# ExileLens 1.0.0" and lines[0].startswith("<!-- DRAFT, NOT ACTIVE")
