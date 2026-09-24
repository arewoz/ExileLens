"""Focused release-gate, registry-integrity, and workflow-enforcement contracts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from poe2value.ops import release_regressions
from poe2value.ops.models import GateVerdict
from poe2value.ops.regression import REQUIRED_P0_IDS, load_registry
from poe2value.ops.release_gate import REQUIRED_PACKAGING, evaluate_release_gate


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = "tests/test_pob_import_load_reliability.py"
EVIDENCE_NODEID = f"{EVIDENCE_PATH}::test_ensure_source_ready_skips_reload_until_save"


def _entry(entry_id: str, *, severity: str = "P0", status: str = "covered", tests=None, gap: str = "") -> dict:
    payload = {
        "id": entry_id,
        "title": entry_id,
        "subsystem": "pob_import",
        "trigger": "test trigger",
        "tests": [{"path": EVIDENCE_PATH, "nodeid": EVIDENCE_NODEID}] if tests is None else tests,
        "status": status,
        "severity": severity,
    }
    if status != "covered":
        payload["coverage_gap"] = gap or "explicit test gap"
    return payload


def _valid_registry() -> dict:
    return {"version": 2, "entries": [_entry(entry_id) for entry_id in sorted(REQUIRED_P0_IDS)]}


def _write_registry(root: Path, payload: dict) -> None:
    target = root / "ops" / "regression_registry.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")


def _valid_root(tmp_path: Path) -> Path:
    for relative in (*REQUIRED_PACKAGING, "pyproject.toml"):
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    ops = tmp_path / "ops"
    ops.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "ops" / "compatibility.json", ops / "compatibility.json")
    target_test = tmp_path / EVIDENCE_PATH
    target_test.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / EVIDENCE_PATH, target_test)
    _write_registry(tmp_path, _valid_registry())
    return tmp_path


def _result(report, name: str):
    return next(item for item in (*report.blockers, *report.warnings, *report.passed) if item.name == name)


def test_missing_compatibility_manifest_is_structured_blocker(tmp_path: Path) -> None:
    root = _valid_root(tmp_path)
    (root / "ops" / "compatibility.json").unlink()

    report = evaluate_release_gate(root=root)

    assert report.verdict is GateVerdict.BLOCKED
    assert _result(report, "compatibility_manifest").status is GateVerdict.BLOCKED


def test_empty_registry_is_structured_blocker(tmp_path: Path) -> None:
    root = _valid_root(tmp_path)
    _write_registry(root, {})

    report = evaluate_release_gate(root=root)

    assert report.verdict is GateVerdict.BLOCKED
    assert "version must be 2" in _result(report, "known_p0").detail


def test_missing_required_p0_entries_are_structured_blockers(tmp_path: Path) -> None:
    root = _valid_root(tmp_path)
    _write_registry(root, {"version": 2, "entries": [_entry("stale-pob-build")]})

    report = evaluate_release_gate(root=root)

    assert report.verdict is GateVerdict.BLOCKED
    assert "missing required P0 entries" in _result(report, "known_p0").detail


@pytest.mark.parametrize(
    ("test_ref", "expected"),
    [
        ({"path": "tests/does_not_exist.py", "nodeid": "tests/does_not_exist.py::test_missing"}, "missing test file"),
        ({"path": EVIDENCE_PATH, "nodeid": f"{EVIDENCE_PATH}::not_a_test"}, "nodeid must exactly identify"),
        ({"path": EVIDENCE_PATH, "nodeid": f"{EVIDENCE_PATH}::test_not_present"}, "missing test identity"),
    ],
)
def test_invalid_test_references_are_structured_blockers(tmp_path: Path, test_ref: dict, expected: str) -> None:
    root = _valid_root(tmp_path)
    payload = _valid_registry()
    payload["entries"][0]["tests"] = [test_ref]
    _write_registry(root, payload)

    report = evaluate_release_gate(root=root)

    assert report.verdict is GateVerdict.BLOCKED
    assert expected in _result(report, "known_p0").detail


def test_p0_falsely_marked_covered_without_evidence_is_blocked(tmp_path: Path) -> None:
    root = _valid_root(tmp_path)
    payload = _valid_registry()
    payload["entries"][0]["tests"] = []
    _write_registry(root, payload)

    report = evaluate_release_gate(root=root)

    assert report.verdict is GateVerdict.BLOCKED
    assert "marked covered but has no verified test evidence" in _result(report, "known_p0").detail


def test_valid_registry_with_real_references_passes_prebuild_and_requires_artifact_postbuild(tmp_path: Path) -> None:
    root = _valid_root(tmp_path)

    prebuild = evaluate_release_gate(root=root)
    postbuild = evaluate_release_gate(root=root, require_artifact=True)

    assert prebuild.verdict is GateVerdict.PASS
    assert _result(prebuild, "known_p0").status is GateVerdict.PASS
    assert "execution is required separately" in _result(prebuild, "known_p0").detail
    assert postbuild.verdict is GateVerdict.BLOCKED
    assert _result(postbuild, "release_artifact").status is GateVerdict.BLOCKED


def test_committed_registry_has_complete_executable_mandatory_p0_evidence() -> None:
    entries = load_registry(ROOT / "ops" / "regression_registry.json", root=ROOT)
    mandatory = {entry.id: entry for entry in entries if entry.id in REQUIRED_P0_IDS}

    assert set(mandatory) == REQUIRED_P0_IDS
    assert all(entry.severity == "P0" for entry in mandatory.values())
    covered = [entry for entry in mandatory.values() if entry.status == "covered"]
    assert all(entry.tests for entry in covered)
    # `load_registry` has already parsed each file and AST-verified each exact
    # node ID. Keep this assertion explicit so the committed manifest cannot
    # regress to path-only or declaration-only P0 evidence.
    assert all(test.nodeid.startswith(f"{test.path}::test_") for entry in covered for test in entry.tests)


def test_mandatory_runner_executes_declared_p0_tests_and_reports_failures(tmp_path: Path, monkeypatch) -> None:
    root = _valid_root(tmp_path)
    calls: list[list[str]] = []

    def succeeded(targets, *, root):
        calls.append(targets)
        return {"ok": True, "returncode": 0, "stdout": "1 passed", "stderr": ""}

    monkeypatch.setattr(release_regressions, "run_pytest", succeeded)
    passed = release_regressions.run_mandatory_release_regressions(root=root)
    assert passed["status"] == "PASS"
    assert calls == [passed["tests"]]
    assert calls[0] == [EVIDENCE_NODEID]

    monkeypatch.setattr(
        release_regressions,
        "run_pytest",
        lambda targets, *, root: {"ok": False, "returncode": 1, "stdout": "failed", "stderr": ""},
    )
    failed = release_regressions.run_mandatory_release_regressions(root=root)
    assert failed["status"] == "BLOCKED"
    assert failed["test_run"]["returncode"] == 1


def test_mandatory_runner_blocks_declared_p0_coverage_gaps(tmp_path: Path) -> None:
    root = _valid_root(tmp_path)
    payload = _valid_registry()
    payload["entries"][0]["status"] = "uncovered"
    payload["entries"][0]["coverage_gap"] = "missing real regression"
    _write_registry(root, payload)

    result = release_regressions.run_mandatory_release_regressions(root=root)

    assert result["status"] == "BLOCKED"
    assert "not covered" in result["detail"]
    assert result["test_run"] is None


def test_release_workflow_executes_mandatory_regressions_before_build_and_publication() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    source_gate = workflow.index("Run source release gate")
    dependencies = workflow.index("Install mandatory release-test dependencies")
    regressions = workflow.index("Run mandatory release regressions")
    build = workflow.index("Build the official Windows onedir distribution")
    artifact_gate = workflow.index("Run packaged-artifact release gate")
    package = workflow.index("Package and verify release assets")
    publish = workflow.index("Create published release")
    assert source_gate < dependencies < regressions < build < artifact_gate < package < publish
    assert "python -m poe2value.ops.cli release-regressions" in workflow
    assert "python -m pip install --disable-pip-version-check pytest PySide6" in workflow
    assert "continue-on-error" not in workflow


def test_committed_compatibility_manifest_matches_current_source_version() -> None:
    manifest = json.loads((ROOT / "ops" / "compatibility.json").read_text(encoding="utf-8"))
    assert manifest["exilelens_version"] == "0.4.0b1"
