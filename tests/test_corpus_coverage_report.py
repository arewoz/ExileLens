"""Regression tests for the M1.1 Corpus Coverage Matrix grading logic.

These are engine-free and fixture-free: they exercise `tests/corpus_coverage/report.py`
against synthetic JUnit outcomes, and separately guard the registry against drift from
the real manifest/test files it describes.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from tests.corpus_coverage.junit import JUnitOutcome
from tests.corpus_coverage.registry import ALL_CASES, CoverageCase
from tests.corpus_coverage.report import build_report, grade_case, render_markdown, to_json_dict
from tests.corpus_coverage.taxonomy import (
    Archetype,
    CoverageResult,
    EvaluationDepth,
    ExpectedResult,
    FunctionalMeasurement,
)

pytestmark = pytest.mark.itemcheck

ROOT = Path(__file__).resolve().parents[1]


def _case(**overrides) -> CoverageCase:
    defaults = dict(
        id="TEST-CASE",
        test_file="tests/example_module.py",
        node_name="test_something",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="synthetic case for grading tests",
    )
    defaults.update(overrides)
    return CoverageCase(**defaults)


def _outcome(**overrides) -> JUnitOutcome:
    defaults = dict(name="test_something", classname="tests.example_module", status="passed", message="")
    defaults.update(overrides)
    return JUnitOutcome(**defaults)


def test_confident_case_that_passes_is_graded_pass() -> None:
    grade = grade_case(_case(expected=ExpectedResult.CONFIDENT), [_outcome(status="passed")])
    assert grade.result is CoverageResult.PASS


def test_uncertain_case_that_passes_is_graded_expected_uncertain() -> None:
    grade = grade_case(_case(expected=ExpectedResult.UNCERTAIN), [_outcome(status="passed")])
    assert grade.result is CoverageResult.EXPECTED_UNCERTAIN


def test_unsupported_case_that_passes_is_graded_unsupported() -> None:
    grade = grade_case(_case(expected=ExpectedResult.UNSUPPORTED), [_outcome(status="passed")])
    assert grade.result is CoverageResult.UNSUPPORTED


def test_confident_case_that_fails_with_no_safe_degradation_marker_is_wrong_result() -> None:
    grade = grade_case(
        _case(expected=ExpectedResult.CONFIDENT),
        [_outcome(status="failed", message="assert 'MEANINGFUL_UPGRADE' == 'MEANINGFUL_DOWNGRADE'")],
    )
    assert grade.result is CoverageResult.WRONG_RESULT


def test_confident_case_that_fails_and_looks_like_safe_degradation_is_wrong_uncertain() -> None:
    grade = grade_case(
        _case(expected=ExpectedResult.CONFIDENT),
        [_outcome(status="failed", message="assert 'MEANINGFUL_UPGRADE' == 'UNCERTAIN'")],
    )
    assert grade.result is CoverageResult.WRONG_UNCERTAIN


def test_uncertain_case_that_fails_fails_closed_to_wrong_result() -> None:
    # The truthfulness invariant: a case whose author declared a safe non-answer as
    # correct, that then fails, must never be graded as anything less severe.
    grade = grade_case(
        _case(expected=ExpectedResult.UNCERTAIN),
        [_outcome(status="failed", message="assert 'UNCERTAIN' == 'MEANINGFUL_UPGRADE'")],
    )
    assert grade.result is CoverageResult.WRONG_RESULT


def test_case_with_no_matching_outcome_is_not_run() -> None:
    grade = grade_case(_case(), [])
    assert grade.result is CoverageResult.NOT_RUN
    assert grade.total_variants == 0


def test_case_where_every_variant_was_skipped_is_not_run() -> None:
    grade = grade_case(_case(), [_outcome(status="skipped")])
    assert grade.result is CoverageResult.NOT_RUN


def test_prefix_case_groups_all_parametrized_variants() -> None:
    case = _case(node_name="test_parametrized", node_name_is_prefix=True)
    outcomes = [
        _outcome(name="test_parametrized[a]", status="passed"),
        _outcome(name="test_parametrized[b]", status="passed"),
        _outcome(name="test_parametrized[c]", status="failed", message="boom"),
    ]
    grade = grade_case(case, outcomes)
    assert grade.total_variants == 3
    assert grade.passed_variants == 2
    assert grade.result is CoverageResult.WRONG_RESULT


def test_prefix_case_does_not_match_an_unrelated_longer_name() -> None:
    case = _case(node_name="test_short", node_name_is_prefix=True)
    outcomes = [_outcome(name="test_short_but_actually_different", status="passed")]
    grade = grade_case(case, outcomes)
    assert grade.result is CoverageResult.NOT_RUN


def test_wrong_classname_never_matches() -> None:
    case = _case(test_file="tests/example_module.py")
    outcomes = [_outcome(classname="tests.a_different_module")]
    grade = grade_case(case, outcomes)
    assert grade.result is CoverageResult.NOT_RUN


def test_high_risk_grades_surfaces_only_wrong_result() -> None:
    cases = (
        _case(id="A", expected=ExpectedResult.CONFIDENT),
        _case(id="B", node_name="test_b", expected=ExpectedResult.CONFIDENT),
    )
    outcomes = [
        _outcome(name="test_something", status="failed", message="no marker here"),
        _outcome(name="test_b", status="failed", message="actual was UNCERTAIN"),
    ]
    report = build_report(outcomes, cases=cases)
    high_risk_ids = {g.case.id for g in report.high_risk_grades}
    assert high_risk_ids == {"A"}


def test_uncovered_archetypes_lists_every_archetype_with_zero_cases() -> None:
    cases = (_case(archetypes=(Archetype.MELEE,)),)
    report = build_report([_outcome(status="passed")], cases=cases)
    uncovered = report.uncovered_archetypes()
    assert Archetype.MELEE not in uncovered
    assert Archetype.TRIGGER in uncovered
    assert len(uncovered) == len(list(Archetype)) - 1


def test_supported_count_excludes_not_run_and_wrong_results() -> None:
    cases = (
        _case(id="PASS-CASE", expected=ExpectedResult.CONFIDENT),
        _case(id="UNCERTAIN-CASE", node_name="test_uncertain", expected=ExpectedResult.UNCERTAIN),
        _case(id="NOT-RUN-CASE", node_name="test_missing"),
        _case(id="WRONG-CASE", node_name="test_wrong", expected=ExpectedResult.CONFIDENT),
    )
    outcomes = [
        _outcome(name="test_something", status="passed"),
        _outcome(name="test_uncertain", status="passed"),
        _outcome(name="test_wrong", status="failed", message="nope"),
    ]
    report = build_report(outcomes, cases=cases)
    assert report.supported_count == 2
    assert report.total_count == 3  # NOT_RUN excluded from total too


def test_render_markdown_does_not_crash_and_mentions_every_archetype() -> None:
    report = build_report([_outcome(status="passed")], cases=(_case(archetypes=(Archetype.MELEE,)),))
    markdown = render_markdown(report)
    for archetype in Archetype:
        assert archetype.value in markdown


def test_to_json_dict_is_json_serializable_and_deterministic() -> None:
    report = build_report([_outcome(status="passed")], cases=(_case(),))
    payload = to_json_dict(report)
    first = json.dumps(payload, sort_keys=True)
    second = json.dumps(to_json_dict(report), sort_keys=True)
    assert first == second


# ---------------------------------------------------------------------------
# Registry drift guards: the registry must describe real, currently-existing
# fixtures and test files, never invented ones.
# ---------------------------------------------------------------------------


def test_report_prose_derives_the_fixture_count_from_the_manifest() -> None:
    """The header used to hard-code 13 fixtures while the manifest held 19."""
    from tests.corpus_coverage.report import manifest_fixture_count

    manifest = json.loads((ROOT / "fixtures" / "builds" / "public_corpus" / "manifest.json").read_text(encoding="utf-8"))
    count = manifest_fixture_count()
    assert count == len(manifest["fixtures"])
    markdown = render_markdown(build_report([_outcome()], cases=(_case(),)))
    assert f"the corpus is currently {count} build fixtures" in markdown
    assert "13 build fixtures" not in markdown or count == 13


def test_every_registered_case_test_file_exists() -> None:
    for case in ALL_CASES:
        assert (ROOT / case.test_file).is_file(), f"{case.id} references a missing test file"


def test_every_registered_manifest_id_exists_in_the_real_manifest() -> None:
    manifest = json.loads((ROOT / "fixtures" / "builds" / "public_corpus" / "manifest.json").read_text())
    known_ids = {entry["id"] for entry in manifest["fixtures"]}
    for case in ALL_CASES:
        if case.manifest_id is not None:
            assert case.manifest_id in known_ids, f"{case.id} references unknown manifest id {case.manifest_id}"


def test_every_manifest_fixture_has_at_least_one_registered_case() -> None:
    manifest = json.loads((ROOT / "fixtures" / "builds" / "public_corpus" / "manifest.json").read_text())
    known_ids = {entry["id"] for entry in manifest["fixtures"]}
    registered_ids = {case.manifest_id for case in ALL_CASES if case.manifest_id is not None}
    assert known_ids <= registered_ids


def test_case_ids_are_unique() -> None:
    ids = [case.id for case in ALL_CASES]
    assert len(ids) == len(set(ids))


# --------------------------------------------------------------- CORPUS-02D1 functional coverage


def test_functional_coverage_counts_only_passing_fully_measured_cases() -> None:
    cases = (
        _case(id="FULL", node_name="test_full", functional=FunctionalMeasurement.FULLY_MEASURED,
              archetypes=(Archetype.AILMENT,)),
        _case(id="REFUSAL", node_name="test_refusal", expected=ExpectedResult.UNCERTAIN,
              functional=FunctionalMeasurement.EXPECTED_UNCERTAINTY, archetypes=(Archetype.AILMENT,)),
        _case(id="PARTIAL", node_name="test_partial", expected=ExpectedResult.UNCERTAIN,
              functional=FunctionalMeasurement.PARTIALLY_MEASURED),
        _case(id="BROKEN", node_name="test_broken", functional=FunctionalMeasurement.FULLY_MEASURED,
              archetypes=(Archetype.AILMENT,)),
        _case(id="UNCLASSIFIED", node_name="test_unclassified"),
        _case(id="IDENTITY", node_name="test_identity", depth=EvaluationDepth.IDENTITY_ONLY),
    )
    outcomes = [
        _outcome(name="test_full"), _outcome(name="test_refusal"), _outcome(name="test_partial"),
        _outcome(name="test_broken", status="failed", message="assert 'PARTIAL' == 'FULL'"),
        _outcome(name="test_unclassified"), _outcome(name="test_identity"),
    ]
    report = build_report(outcomes, cases)

    # The historical headline still counts the correct refusals as supported.
    assert report.supported_count == 5
    assert report.functional_count == 1
    counts = report.functional_counts()
    assert counts["FULLY_MEASURED"] == 1
    assert counts["EXPECTED_UNCERTAINTY"] == 1
    assert counts["PARTIALLY_MEASURED"] == 1
    assert counts["NOT_ESTABLISHED"] == 1
    assert report.unclassified_verdict_count() == 1
    ailment = report.functional_by_archetype()[Archetype.AILMENT]
    assert ailment["FULLY_MEASURED"] == 1 and ailment["EXPECTED_UNCERTAINTY"] == 1 and ailment["NOT_ESTABLISHED"] == 1
    markdown = render_markdown(report)
    assert "Functional coverage (separate from the headline metric)" in markdown
    assert "Fully measured (of executed classified cases): 1/4 (25%)" in markdown
    assert to_json_dict(report)["functional"]["fully_measured"] == 1


_DIRECTIONAL_VERDICTS = (
    '"MEANINGFUL_UPGRADE"', '"MINOR_UPGRADE"', '"SIDEGRADE"', '"MINOR_DOWNGRADE"', '"MEANINGFUL_DOWNGRADE"',
)
_ASSERTED_QUALITY = {
    # A score-derived verdict can only be produced at FULL quality (see
    # test_score_derived_verdicts_require_full_quality), so asserting one is asserting FULL.
    FunctionalMeasurement.FULLY_MEASURED: ('"FULL"',) + _DIRECTIONAL_VERDICTS,
    FunctionalMeasurement.PARTIALLY_MEASURED: ('"PARTIAL"', '"UNCERTAIN"'),
    FunctionalMeasurement.EXPECTED_UNCERTAINTY: ('"PARTIAL"', '"UNCERTAIN"'),
    FunctionalMeasurement.UNSUPPORTED_MECHANIC: ('"UNSUPPORTED"',),
}


def test_score_derived_verdicts_require_full_quality() -> None:
    """R4: the policy fact that lets a test asserting only a directional verdict count as FULL evidence."""
    from exilelens.items.evaluation_outcome import EvaluationQuality, PublicVerdict, decide_verdict

    score_derived = {
        PublicVerdict.MEANINGFUL_UPGRADE, PublicVerdict.MINOR_UPGRADE, PublicVerdict.SIDEGRADE,
        PublicVerdict.MINOR_DOWNGRADE, PublicVerdict.MEANINGFUL_DOWNGRADE,
    }
    reasons = [{"code": "TEST", "detail": "reduced evidence"}]
    for quality in EvaluationQuality:
        for raw in (-95.0, -40.0, -8.0, -1.0, 0.0, 1.0, 8.0, 40.0, 95.0):
            verdict = decide_verdict(raw, (), quality, reasons).verdict
            if quality is not EvaluationQuality.FULL:
                assert verdict not in score_derived, (quality, raw, verdict)
    full_verdicts = {decide_verdict(raw, (), EvaluationQuality.FULL, []).verdict for raw in (-95.0, -8.0, 0.0, 8.0, 95.0)}
    assert full_verdicts <= score_derived


def test_declared_functional_measurement_matches_what_the_test_asserts() -> None:
    """A case may only claim what its own test body asserts about quality."""
    sources: dict[str, dict[str, str]] = {}
    for case in ALL_CASES:
        if case.functional is None:
            continue
        assert case.depth is EvaluationDepth.VERDICT, case.id
        if case.test_file not in sources:
            text = (ROOT / case.test_file).read_text(encoding="utf-8")
            sources[case.test_file] = {
                node.name: ast.get_source_segment(text, node) or ""
                for node in ast.walk(ast.parse(text))
                if isinstance(node, ast.FunctionDef)
            }
        body = sources[case.test_file][case.node_name.split("[", 1)[0]]
        if case.functional is FunctionalMeasurement.NOT_ESTABLISHED:
            # Declared gap: the body must really lack the evidence, and the gap must be named.
            assert case.evidence_gap, case.id
            assert not any(marker in body for marker in _ASSERTED_QUALITY[FunctionalMeasurement.FULLY_MEASURED]), (
                f"{case.id} now asserts quality/verdict: reclassify it"
            )
            continue
        assert case.evidence_gap is None, case.id
        grounded_refusal = (
            case.functional is FunctionalMeasurement.FULLY_MEASURED
            and '"NOT_VIABLE"' in body
            and ("_fresh(" in body or "_fresh_metrics(" in body)
        )
        assert grounded_refusal or any(marker in body for marker in _ASSERTED_QUALITY[case.functional]), case.id
        if case.functional is FunctionalMeasurement.FULLY_MEASURED:
            assert case.expected is ExpectedResult.CONFIDENT, case.id


# --------------------------------------------------------------- R4 gate hygiene


def _generator_suites() -> set[str]:
    import importlib.util

    spec = importlib.util.spec_from_file_location("generate_corpus_coverage_report", ROOT / "scripts" / "generate_corpus_coverage_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {test_file for test_file, _marker in module.SUITES}


def test_every_registered_test_file_is_run_by_the_report_generator() -> None:
    """R4: LIFE-01 was registered but its suite was never run, so it could only ever report NOT_RUN."""
    suites = _generator_suites()
    missing = sorted({case.test_file for case in ALL_CASES} - suites)
    assert not missing, f"registered but never run by scripts/generate_corpus_coverage_report.py: {missing}"


def test_every_verdict_case_declares_what_it_measures() -> None:
    unclassified = [c.id for c in ALL_CASES if c.depth is EvaluationDepth.VERDICT and c.functional is None]
    assert not unclassified, unclassified


def test_committed_report_describes_the_current_registry() -> None:
    """The committed JSON may carry old results, but never an old registry: ids, depth, declaration."""
    committed = json.loads((ROOT / "docs" / "corpus_coverage" / "coverage_report.json").read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in committed["cases"]}
    assert set(by_id) == {c.id for c in ALL_CASES}
    for case in ALL_CASES:
        row = by_id[case.id]
        assert row["depth"] == case.depth.value, case.id
        assert row["functional"] == (case.functional.value if case.functional else None), case.id
        assert row["expected"] == case.expected.value, case.id
        assert sorted(row["archetypes"]) == sorted(a.value for a in case.archetypes), case.id


def test_committed_report_never_fails_the_gate() -> None:
    """INCONCLUSIVE (no current engine results) is allowed to be committed; FAIL is not."""
    from tests.corpus_coverage.gate import evaluate_gate

    committed = json.loads((ROOT / "docs" / "corpus_coverage" / "coverage_report.json").read_text(encoding="utf-8"))
    result = evaluate_gate(committed)
    assert result.verdict != "FAIL", [c for c in result.criteria if not c.ok]


def _gate_payload(**overrides):
    base_case = {
        "id": "X", "depth": "VERDICT", "functional": "FULLY_MEASURED", "result": "PASS", "archetypes": list(MAJOR),
        "carried": False,
    }
    state_case = {"id": "S", "depth": "STATE_INTEGRITY", "functional": None, "result": "PASS", "archetypes": [], "carried": False}
    payload = {
        "provenance": {"mode": "executed"},
        "cases": [base_case, state_case],
        "uncovered_archetypes": [],
        "functional": {"fully_measured": 10_000},
    }
    payload.update(overrides)
    return payload


from tests.corpus_coverage.gate import MAJOR_ARCHETYPES as MAJOR  # noqa: E402
from tests.corpus_coverage.gate import evaluate_gate as _evaluate_gate  # noqa: E402


def test_gate_passes_clean_executed_data() -> None:
    assert _evaluate_gate(_gate_payload()).verdict == "PASS"


def test_gate_fails_on_a_wrong_result() -> None:
    payload = _gate_payload()
    payload["cases"][0]["result"] = "WRONG_RESULT"
    assert _evaluate_gate(payload).verdict == "FAIL"


def test_gate_fails_when_an_archetype_is_unrepresented() -> None:
    assert _evaluate_gate(_gate_payload(uncovered_archetypes=["spell"])).verdict == "FAIL"


def test_gate_is_conditional_when_a_verdict_case_does_not_establish_its_measurement() -> None:
    payload = _gate_payload()
    payload["cases"].append({"id": "G", "depth": "VERDICT", "functional": "NOT_ESTABLISHED", "result": "PASS",
                             "archetypes": [], "carried": False})
    assert _evaluate_gate(payload).verdict == "CONDITIONAL"


def test_gate_is_inconclusive_on_carried_or_missing_results_but_still_fails_on_structure() -> None:
    payload = _gate_payload()
    payload["cases"][0]["carried"] = True
    payload["provenance"] = {"mode": "carried_forward", "results_from": "abc"}
    assert _evaluate_gate(payload).verdict == "INCONCLUSIVE"
    payload["cases"].append({"id": "U", "depth": "VERDICT", "functional": None, "result": "NOT_RUN",
                             "archetypes": [], "carried": False})
    assert _evaluate_gate(payload).verdict == "FAIL"  # an unclassified verdict case is structural


def test_gate_fails_when_a_state_integrity_case_fails() -> None:
    payload = _gate_payload()
    payload["cases"][1]["result"] = "WRONG_RESULT"
    assert _evaluate_gate(payload).verdict == "FAIL"
