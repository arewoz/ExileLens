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
from tests.corpus_coverage.gate import (
    BUILD_INTEL_INVARIANTS,
    evaluate_build_intel_gate,
    evaluate_gate,
    render_gate,
)
from tests.corpus_coverage.registry import ALL_CASES, CoverageCase
from tests.corpus_coverage.report import build_report, grade_case, render_markdown, to_json_dict
from tests.corpus_coverage.taxonomy import (
    Archetype,
    CaseRole,
    CoverageResult,
    EvaluationDepth,
    ExpectedResult,
    FunctionalMeasurement,
    UncertaintyAudit,
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


_ASSERTED_QUALITY = {
    FunctionalMeasurement.FULLY_MEASURED: ('"FULL"',),
    FunctionalMeasurement.PARTIALLY_MEASURED: ('"PARTIAL"', '"UNCERTAIN"'),
    FunctionalMeasurement.EXPECTED_UNCERTAINTY: ('"PARTIAL"', '"UNCERTAIN"'),
    FunctionalMeasurement.UNSUPPORTED_MECHANIC: ('"UNSUPPORTED"', '"UNSUPPORTED_EQUIPMENT_LAYOUT"'),
}


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
        assert any(marker in body for marker in _ASSERTED_QUALITY[case.functional]), case.id
        if case.functional is FunctionalMeasurement.FULLY_MEASURED:
            assert case.expected is ExpectedResult.CONFIDENT, case.id


# --------------------------------------------------------------------------- R4 classification + gate


def _all_pass_outcomes(cases: tuple[CoverageCase, ...] = ALL_CASES) -> list[JUnitOutcome]:
    return [
        JUnitOutcome(
            name=case.node_name + ("[param]" if case.node_name_is_prefix else ""),
            classname=case.test_file[: -len(".py")].replace("/", "."),
            status="passed",
        )
        for case in cases
    ]


def test_every_verdict_case_is_classified_or_declared_state_integrity() -> None:
    """R4: "not yet classified" can no longer accumulate. A verdict case measures a mechanic or proves state integrity."""
    for case in ALL_CASES:
        if case.depth is EvaluationDepth.VERDICT:
            assert case.functional is not None or case.role is CaseRole.STATE_INTEGRITY, case.id


def test_state_integrity_cases_are_never_also_functionally_classified() -> None:
    for case in ALL_CASES:
        if case.role is CaseRole.STATE_INTEGRITY:
            assert case.functional is None, case.id
            assert case.depth is EvaluationDepth.VERDICT, case.id


def test_every_refusal_case_carries_an_audit_and_a_note() -> None:
    for case in ALL_CASES:
        refusal = case.expected is not ExpectedResult.CONFIDENT or case.functional is FunctionalMeasurement.PARTIALLY_MEASURED
        if refusal:
            assert isinstance(case.audit, UncertaintyAudit), case.id
            assert len(case.audit_note.strip()) >= 40, f"{case.id}: an audit needs a real note"
        else:
            assert case.audit is None, f"{case.id}: only refusals are audited"


def test_no_registered_case_flags_an_unresolved_release_blocker() -> None:
    assert [case.id for case in ALL_CASES if case.blocks_1_0] == []


def test_stat_stacker_is_represented_by_a_functionally_measured_case() -> None:
    cases = [case for case in ALL_CASES if Archetype.STAT_STACKER in case.archetypes]
    assert any(case.functional is FunctionalMeasurement.FULLY_MEASURED for case in cases)


def test_the_registry_satisfies_the_gate_when_every_case_passes() -> None:
    result = evaluate_gate(build_report(_all_pass_outcomes()))
    assert result.passed, render_gate(result)
    assert result.verdict == "PASS"


def test_gate_is_not_evaluable_without_an_engine_run() -> None:
    result = evaluate_gate(build_report([]))
    assert result.verdict == "NOT_EVALUABLE" and not result.passed


def _blockers(outcomes: list[JUnitOutcome], cases: tuple[CoverageCase, ...] = ALL_CASES) -> set[str]:
    return {check.name for check in evaluate_gate(build_report(outcomes, cases)).blockers}


def test_gate_blocks_on_a_confident_but_wrong_result() -> None:
    outcomes = _all_pass_outcomes()
    victim = next(i for i, case in enumerate(ALL_CASES) if case.id == "MELEE-TWO-HAND-WEAPON-UPGRADE")
    outcomes[victim] = JUnitOutcome(outcomes[victim].name, outcomes[victim].classname, "failed", "assert 'MAJOR_UPGRADE' == 'SIDEGRADE'")
    assert "NO_WRONG_RESULT" in _blockers(outcomes)


def test_gate_blocks_on_a_restore_or_state_integrity_failure() -> None:
    outcomes = _all_pass_outcomes()
    victim = next(i for i, case in enumerate(ALL_CASES) if case.id == "WSCTX-CORRUPT-RESTORE-FAILS-CLOSED")
    outcomes[victim] = JUnitOutcome(outcomes[victim].name, outcomes[victim].classname, "failed", "RestoreFailed not raised")
    assert {"RESTORE_AND_STATE_INTEGRITY", "NO_WRONG_RESULT"} <= _blockers(outcomes)


def test_gate_blocks_when_a_registered_case_did_not_execute() -> None:
    outcomes = _all_pass_outcomes()[1:]
    assert "EVERY_REGISTERED_CASE_EXECUTED" in _blockers(outcomes)


def test_gate_blocks_on_a_failing_test_the_registry_does_not_know() -> None:
    """The headline once read 100% beside two failing corpus-gate tests, because only registered cases were graded."""
    outcomes = _all_pass_outcomes() + [
        JUnitOutcome("test_manifest_is_small_complete_and_repository_relative",
                     "tests.integration.test_public_build_corpus", "failed", "assert 21 == 19")
    ]
    report = build_report(outcomes)
    assert [o.name for o in report.unmapped_failures] == ["test_manifest_is_small_complete_and_repository_relative"]
    assert "NO_FAILING_TEST_OUTSIDE_THE_REGISTRY" in _blockers(outcomes)
    assert "Failing tests outside the registry" in render_markdown(report)


def test_an_unregistered_skip_is_listed_but_not_a_failure() -> None:
    outcomes = _all_pass_outcomes() + [JUnitOutcome("test_something_skipped", "tests.integration.test_jewel_real_pob", "skipped", "no fixture")]
    report = build_report(outcomes)
    assert [o.name for o in report.skipped] == ["test_something_skipped"]
    assert evaluate_gate(report).passed
    assert "test_something_skipped" in render_markdown(report)


def test_gate_blocks_an_unclassified_verdict_case_an_unaudited_refusal_and_a_flagged_blocker() -> None:
    cases = (
        _case(id="UNCLASSIFIED", node_name="test_a"),
        _case(id="UNAUDITED-REFUSAL", node_name="test_b", expected=ExpectedResult.UNCERTAIN,
              functional=FunctionalMeasurement.EXPECTED_UNCERTAINTY),
        _case(id="BLOCKER", node_name="test_c", functional=FunctionalMeasurement.FULLY_MEASURED, blocks_1_0=True),
    )
    outcomes = [_outcome(name="test_a"), _outcome(name="test_b"), _outcome(name="test_c")]
    blockers = _blockers(outcomes, cases)
    assert {"EVERY_VERDICT_CASE_CLASSIFIED", "EVERY_REFUSAL_AUDITED", "NO_UNRESOLVED_RELEASE_BLOCKER",
            "EVERY_ARCHETYPE_REPRESENTED"} <= blockers


def test_gate_blocks_an_archetype_with_no_case_and_one_that_is_only_represented() -> None:
    cases = (_case(id="ONLY-IDENTITY", depth=EvaluationDepth.IDENTITY_ONLY, archetypes=(Archetype.MELEE,)),)
    report = build_report([_outcome()], cases)
    assert report.archetype_status()[Archetype.MELEE].status == "REPRESENTED"
    assert report.archetype_status()[Archetype.TRIGGER].status == "RELEASE GAP"
    blockers = {check.name for check in evaluate_gate(report).blockers}
    assert {"EVERY_ARCHETYPE_REPRESENTED", "EVERY_ARCHETYPE_FUNCTIONALLY_MEASURED_OR_DOCUMENTED"} <= blockers


def test_archetype_status_follows_what_the_cases_establish_not_how_many_there_are() -> None:
    refusal = dict(expected=ExpectedResult.UNCERTAIN, audit=UncertaintyAudit.CORRECT_UNCERTAINTY, audit_note="x" * 50)
    cases = (
        _case(id="A1", node_name="t1", archetypes=(Archetype.SPELL,), functional=FunctionalMeasurement.PARTIALLY_MEASURED, **refusal),
        _case(id="A2", node_name="t2", archetypes=(Archetype.SPELL,), functional=FunctionalMeasurement.EXPECTED_UNCERTAINTY, **refusal),
        _case(id="B1", node_name="t3", archetypes=(Archetype.DOT,), functional=FunctionalMeasurement.EXPECTED_UNCERTAINTY, **refusal),
        _case(id="C1", node_name="t4", archetypes=(Archetype.MINION,), functional=FunctionalMeasurement.FULLY_MEASURED),
        _case(id="C2", node_name="t5", archetypes=(Archetype.MINION,), role=CaseRole.STATE_INTEGRITY),
    )
    outcomes = [_outcome(name=f"t{i}") for i in range(1, 6)]
    status = build_report(outcomes, cases).archetype_status()
    assert status[Archetype.SPELL].status == "PARTIAL"
    assert status[Archetype.DOT].status == "EXPECTED UNCERTAINTY"
    assert status[Archetype.MINION].status == "FUNCTIONALLY MEASURED"
    assert (status[Archetype.MINION].fully_measured, status[Archetype.MINION].integrity_or_identity) == (1, 1)


def test_integrity_cases_are_reported_separately_and_not_counted_as_unclassified() -> None:
    cases = (
        _case(id="MEASURE", node_name="t1", functional=FunctionalMeasurement.FULLY_MEASURED),
        _case(id="PLUMBING", node_name="t2", role=CaseRole.STATE_INTEGRITY),
        _case(id="LOOSE", node_name="t3"),
    )
    report = build_report([_outcome(name="t1"), _outcome(name="t2"), _outcome(name="t3")], cases)
    assert report.unclassified_verdict_count() == 1
    assert [g.case.id for g in report.integrity_grades()] == ["PLUMBING"]
    markdown = render_markdown(report)
    assert "State-integrity cases" in markdown and "| PLUMBING | PASS |" in markdown
    payload = to_json_dict(report)
    assert payload["state_integrity_cases"] == 1
    assert {case["id"]: case["role"] for case in payload["cases"]}["PLUMBING"] == "STATE_INTEGRITY"


def test_the_report_names_the_pob_runtime_it_was_measured_on() -> None:
    report = build_report([_outcome()], cases=(_case(),), runtime={"pob_version": "0.23.1", "pob_layout": "installed"})
    assert "pob_version 0.23.1" in render_markdown(report)
    assert to_json_dict(report)["runtime"] == {"pob_layout": "installed", "pob_version": "0.23.1"}


def test_every_real_pob_integration_file_is_wired_into_the_report_generator() -> None:
    """R4: LIFE-01 was registered but never executed, and the jewel suites were never part of the report, because the
    suite list is hand-maintained. A new real-PoB integration file must be added to it (or excluded here with a reason)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("generate_corpus_coverage_report", ROOT / "scripts" / "generate_corpus_coverage_report.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    wired = {path for path, _marker in module.SUITES}
    excluded: dict[str, str] = {
        # AMMO-01 validation: data-derived contract / audit layers over PoB's own gem data. They guard a failure class
        # (and re-derive their cases from the runtime) rather than adding registry cases, so they deliberately do not
        # move the coverage ratchets; the authoritative corpus case is test_ammo01_permafrost_bolts_weapon.py.
        "tests/integration/test_ammo01_family_contract.py": "AMMO-01 data-derived family contract, not a ratchet case",
        "tests/integration/test_ammo01_state_matrix.py": "AMMO-01 state/normalization matrix and negative controls, not a ratchet case",
        "tests/integration/test_gem_effect_audit.py": "AMMO-01 multi-effect gem audit tripwire, not a ratchet case",
    }
    for path in sorted((ROOT / "tests" / "integration").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT).as_posix()
        if "pytest.mark.real_pob" in text or "pytest.mark.build_corpus" in text:
            assert relative in wired or relative in excluded, f"{relative} is not in the generator's SUITES"
    for relative in wired:
        assert (ROOT / relative).is_file(), relative


def _measure_build(**overrides) -> dict:
    entry = {
        "id": "build", "ok": True, "lane_row_counts": {"offense": 1, "ehp": 1, "max_hit": 0, "mobility": 0},
        "strongest_status": {"damage": "MEASURED", "ehp": "MEASURED", "max_hit": "NO_MEASURABLE_RESPONSE", "movement": "NO_MEASURABLE_RESPONSE"},
        "not_established": [], "invariants": {name: True for name in BUILD_INTEL_INVARIANTS},
    }
    entry.update(overrides)
    return entry


def _measure_cache(**overrides) -> dict:
    entry = {"id": "build", "ok": True, "fingerprint_changed_by_equip": True, "analysis_changed_by_equip": True,
             "fingerprint_restored_after_reload": True, "analysis_reproduced_after_reload": True}
    entry.update(overrides)
    return entry


def test_build_intelligence_gate_passes_clean_measurements() -> None:
    result = evaluate_build_intel_gate({"builds": [_measure_build()], "cache": [_measure_cache()]})
    assert result.passed, render_gate(result)


@pytest.mark.parametrize("invariant", BUILD_INTEL_INVARIANTS)
def test_build_intelligence_gate_blocks_each_violated_invariant(invariant: str) -> None:
    broken = _measure_build(invariants={**{name: True for name in BUILD_INTEL_INVARIANTS}, invariant: False})
    result = evaluate_build_intel_gate({"builds": [broken], "cache": [_measure_cache()]})
    assert f"BI:{invariant}" in {check.name for check in result.blockers}


def test_build_intelligence_gate_blocks_silent_emptiness_failed_analysis_and_stale_cache() -> None:
    silent = _measure_build(id="silent", lane_row_counts={"offense": 0, "ehp": 0, "max_hit": 0, "mobility": 0}, strongest_status={})
    failed = {"id": "failed", "ok": False, "error": "boom"}
    cache = _measure_cache(analysis_reproduced_after_reload=False)
    names = {check.name for check in evaluate_build_intel_gate({"builds": [silent, failed], "cache": [cache]}).blockers}
    assert {"BI:INSUFFICIENT_EVIDENCE_IS_EXPLICIT", "EVERY_BUILD_ANALYSED", "BI_CACHE:analysis_reproduced_after_reload"} <= names


def test_build_intelligence_gate_accepts_an_explicit_no_evidence_state() -> None:
    explicit = _measure_build(lane_row_counts={"offense": 0, "ehp": 0, "max_hit": 0, "mobility": 0},
                              strongest_status={"damage": "COULD_NOT_ESTABLISH", "ehp": "COULD_NOT_ESTABLISH"})
    assert evaluate_build_intel_gate({"builds": [explicit], "cache": [_measure_cache()]}).passed


# --------------------------------------------------------------------------- integrity semantics: only a plain PASS counts


def test_every_state_integrity_case_expects_a_plain_pass() -> None:
    """An integrity case proves state; a declared refusal cannot be proof, so none may expect UNCERTAIN/UNSUPPORTED."""
    assert [c.id for c in ALL_CASES if c.role is CaseRole.STATE_INTEGRITY and c.expected is not ExpectedResult.CONFIDENT] == []


def _integrity_case_outcome(expected: ExpectedResult, status: str, message: str = ""):
    case = _case(id="INTEGRITY", node_name="t_int", expected=expected, role=CaseRole.STATE_INTEGRITY)
    report = build_report([_outcome(name="t_int", status=status, message=message)], (case,))
    return {c.name: c for c in evaluate_gate(report).checks}["RESTORE_AND_STATE_INTEGRITY"]


def test_integrity_pass_satisfies_the_integrity_criterion() -> None:
    assert _integrity_case_outcome(ExpectedResult.CONFIDENT, "passed").passed


@pytest.mark.parametrize("expected, label", [(ExpectedResult.UNCERTAIN, "EXPECTED_UNCERTAIN"), (ExpectedResult.UNSUPPORTED, "UNSUPPORTED")])
def test_integrity_refusal_results_block_the_gate(expected: ExpectedResult, label: str) -> None:
    check = _integrity_case_outcome(expected, "passed")
    assert not check.passed and "INTEGRITY" in check.detail, label


@pytest.mark.parametrize("message", ["assert 'a' == 'b'", "state was UNCERTAIN"])
def test_integrity_failure_blocks_the_gate(message: str) -> None:
    for expected in (ExpectedResult.CONFIDENT, ExpectedResult.UNCERTAIN):
        assert not _integrity_case_outcome(expected, "failed", message).passed


def test_integrity_case_that_did_not_run_blocks_the_gate() -> None:
    case = _case(id="INTEGRITY", node_name="t_int", role=CaseRole.STATE_INTEGRITY)
    report = build_report([], (case,))
    assert not {c.name: c for c in evaluate_gate(report).checks}["RESTORE_AND_STATE_INTEGRITY"].passed
