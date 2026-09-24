"""Focused release-gate contracts for source checkouts and workflow ordering."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from poe2value.ops.models import GateVerdict
from poe2value.ops.release_gate import REQUIRED_PACKAGING, evaluate_release_gate


ROOT = Path(__file__).resolve().parents[1]


def _valid_root(tmp_path: Path) -> Path:
    for relative in (*REQUIRED_PACKAGING, "pyproject.toml"):
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for name in ("compatibility.json", "regression_registry.json"):
        source = ROOT / "ops" / name
        target = tmp_path / "ops" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return tmp_path


def _result(report, name: str):
    return next(item for item in (*report.blockers, *report.warnings, *report.passed) if item.name == name)


def test_missing_compatibility_manifest_is_structured_blocker(tmp_path: Path) -> None:
    root = _valid_root(tmp_path)
    (root / "ops" / "compatibility.json").unlink()

    report = evaluate_release_gate(root=root)

    result = _result(report, "compatibility_manifest")
    assert report.verdict is GateVerdict.BLOCKED
    assert result.status is GateVerdict.BLOCKED
    assert "compatibility manifest missing" in result.detail


def test_missing_regression_registry_is_structured_blocker(tmp_path: Path) -> None:
    root = _valid_root(tmp_path)
    (root / "ops" / "regression_registry.json").unlink()

    report = evaluate_release_gate(root=root)

    result = _result(report, "known_p0")
    assert report.verdict is GateVerdict.BLOCKED
    assert result.status is GateVerdict.BLOCKED
    assert "regression registry unavailable" in result.detail


def test_invalid_required_manifests_are_structured_blockers(tmp_path: Path) -> None:
    root = _valid_root(tmp_path)
    (root / "ops" / "compatibility.json").write_text("{", encoding="utf-8")
    (root / "ops" / "regression_registry.json").write_text("{", encoding="utf-8")

    report = evaluate_release_gate(root=root)

    assert report.verdict is GateVerdict.BLOCKED
    assert _result(report, "compatibility_manifest").status is GateVerdict.BLOCKED
    assert _result(report, "known_p0").status is GateVerdict.BLOCKED


def test_semantically_invalid_manifests_are_structured_blockers(tmp_path: Path) -> None:
    root = _valid_root(tmp_path)
    (root / "ops" / "compatibility.json").write_text('{"game": {}}', encoding="utf-8")
    (root / "ops" / "regression_registry.json").write_text('{"entries": [{}]}', encoding="utf-8")

    report = evaluate_release_gate(root=root)

    assert report.verdict is GateVerdict.BLOCKED
    assert _result(report, "compatibility_manifest").status is GateVerdict.BLOCKED
    assert _result(report, "known_p0").status is GateVerdict.BLOCKED


def test_valid_required_inputs_pass_prebuild_and_require_artifact_postbuild(tmp_path: Path) -> None:
    root = _valid_root(tmp_path)

    prebuild = evaluate_release_gate(root=root)
    postbuild = evaluate_release_gate(root=root, require_artifact=True)

    assert prebuild.verdict is GateVerdict.PASS
    assert _result(prebuild, "compatibility_manifest").status is GateVerdict.PASS
    assert _result(prebuild, "known_p0").status is GateVerdict.PASS
    assert postbuild.verdict is GateVerdict.BLOCKED
    assert _result(postbuild, "release_artifact").status is GateVerdict.BLOCKED


def test_release_workflow_gates_before_build_and_before_publication() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    source_gate = workflow.index("Run source release gate")
    build = workflow.index("Build the official Windows onedir distribution")
    artifact_gate = workflow.index("Run packaged-artifact release gate")
    package = workflow.index("Package and verify release assets")
    publish = workflow.index("Create published release")
    assert source_gate < build < artifact_gate < package < publish
    assert "python -m poe2value.ops.cli release-gate" in workflow
    assert "python -m poe2value.ops.cli release-gate --require-artifact" in workflow
    assert "continue-on-error" not in workflow


def test_committed_manifest_is_json_and_matches_current_source_version() -> None:
    manifest = json.loads((ROOT / "ops" / "compatibility.json").read_text(encoding="utf-8"))
    assert manifest["exilelens_version"] == "0.3.0b2"
