"""Regression tests for the M1.1 Corpus Coverage Matrix grading logic.

These are engine-free and fixture-free: they exercise `tests/corpus_coverage/report.py`
against synthetic JUnit outcomes, and separately guard the registry against drift from
the real manifest/test files it describes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.corpus_coverage.junit import JUnitOutcome
from tests.corpus_coverage.registry import ALL_CASES, CoverageCase
from tests.corpus_coverage.report import build_report, grade_case, render_markdown, to_json_dict
from tests.corpus_coverage.taxonomy import Archetype, CoverageResult, EvaluationDepth, ExpectedResult

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
