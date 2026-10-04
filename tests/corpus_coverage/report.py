"""Builds the Corpus Coverage Matrix/Report from the registry + JUnit outcomes.

Pure functions only (no subprocess/pytest invocation here — see
scripts/generate_corpus_coverage_report.py for the CLI that runs the targeted
suites and calls into this module). Keeping this side-effect-free is what makes
`tests/test_corpus_coverage_report.py` able to exercise the grading logic without
a local PoB2 install.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from tests.corpus_coverage.junit import JUnitOutcome
from tests.corpus_coverage.registry import ALL_CASES, CoverageCase
from tests.corpus_coverage.taxonomy import (
    FUNCTIONAL_RESULTS,
    SUPPORTED_RESULTS,
    Archetype,
    CaseRole,
    CoverageResult,
    EvaluationDepth,
    ExpectedResult,
    FunctionalMeasurement,
    UncertaintyAudit,
)

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "builds" / "public_corpus" / "manifest.json"


def manifest_fixture_count(path: Path = MANIFEST_PATH) -> int:
    """Number of build fixtures in the public corpus manifest (the one source of truth for report prose)."""
    return len(json.loads(path.read_text(encoding="utf-8"))["fixtures"])


# Failure-message substrings that indicate the product safely under-answered
# (degraded to an explicit non-answer) rather than confidently returning a wrong
# directional result. Matched case-sensitively against enum member names, which is
# how these values actually appear in assertion/repr text.
_SAFE_DEGRADATION_MARKERS = ("UNCERTAIN", "UNSUPPORTED", "PARTIAL", "NOT_EVALUATED", "FAILED")


@dataclass(frozen=True)
class CaseGrade:
    case: CoverageCase
    result: CoverageResult
    passed_variants: int
    total_variants: int
    failure_messages: tuple[str, ...] = ()


def _classname_for(test_file: str) -> str:
    return test_file[: -len(".py")].replace("/", ".").replace("\\", ".")


def _matches(case: CoverageCase, outcomes: list[JUnitOutcome]) -> list[JUnitOutcome]:
    classname = _classname_for(case.test_file)
    result = []
    for outcome in outcomes:
        if outcome.classname != classname:
            continue
        if case.node_name_is_prefix:
            if outcome.name == case.node_name or outcome.name.startswith(case.node_name + "["):
                result.append(outcome)
        elif outcome.name == case.node_name:
            result.append(outcome)
    return result


def _grade_for_expected_pass(expected: ExpectedResult) -> CoverageResult:
    return {
        ExpectedResult.CONFIDENT: CoverageResult.PASS,
        ExpectedResult.UNCERTAIN: CoverageResult.EXPECTED_UNCERTAIN,
        ExpectedResult.UNSUPPORTED: CoverageResult.UNSUPPORTED,
    }[expected]


def _grade_for_failure(expected: ExpectedResult, failed: list[JUnitOutcome]) -> CoverageResult:
    if expected is not ExpectedResult.CONFIDENT:
        # The author declared a safe non-answer as the *correct* outcome and the
        # product didn't reliably produce it. Fail closed to the worse bucket.
        return CoverageResult.WRONG_RESULT
    looks_like_safe_degradation = any(
        marker in failure.message for failure in failed for marker in _SAFE_DEGRADATION_MARKERS
    )
    return CoverageResult.WRONG_UNCERTAIN if looks_like_safe_degradation else CoverageResult.WRONG_RESULT


def grade_case(case: CoverageCase, outcomes: list[JUnitOutcome]) -> CaseGrade:
    matched = _matches(case, outcomes)
    if not matched:
        return CaseGrade(case, CoverageResult.NOT_RUN, 0, 0)

    executed = [o for o in matched if o.status != "skipped"]
    if not executed:
        return CaseGrade(case, CoverageResult.NOT_RUN, 0, len(matched))

    failed = [o for o in executed if o.status in ("failed", "error")]
    passed = len(executed) - len(failed)

    if failed:
        grade = _grade_for_failure(case.expected, failed)
        return CaseGrade(case, grade, passed, len(executed), tuple(f.message[:200] for f in failed))

    grade = _grade_for_expected_pass(case.expected)
    return CaseGrade(case, grade, passed, len(executed))


@dataclass(frozen=True)
class ArchetypeStatus:
    """R4: what the corpus actually establishes for one archetype. Derived from the cases, never from their count."""

    status: str
    fully_measured: int
    partially_measured: int
    refusals: int
    integrity_or_identity: int
    failing: int


@dataclass
class CoverageReport:
    grades: list[CaseGrade] = field(default_factory=list)
    # R4: failing tests in the executed suites that no registered case accounts for. The headline metric only sees
    # registered cases, so without this a failing corpus-gate test could sit beside "100%".
    unmapped_failures: list[JUnitOutcome] = field(default_factory=list)
    # R4: the PoB runtime the report was measured on (version/layout only, no paths): results are runtime-specific.
    runtime: dict[str, str] = field(default_factory=dict)
    # R4: tests skipped in the executed suites. A skip is not evidence of anything and is listed so it cannot hide.
    skipped: list[JUnitOutcome] = field(default_factory=list)

    @property
    def result_counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for grade in self.grades:
            counts[grade.result.value] += 1
        return dict(sorted(counts.items()))

    @property
    def supported_count(self) -> int:
        return sum(1 for g in self.grades if g.result in SUPPORTED_RESULTS)

    @property
    def total_count(self) -> int:
        return sum(1 for g in self.grades if g.result is not CoverageResult.NOT_RUN)

    @property
    def high_risk_grades(self) -> list[CaseGrade]:
        return [g for g in self.grades if g.result is CoverageResult.WRONG_RESULT]

    def archetype_counts(self) -> dict[Archetype, list[CaseGrade]]:
        by_archetype: dict[Archetype, list[CaseGrade]] = defaultdict(list)
        for grade in self.grades:
            for archetype in grade.case.archetypes:
                by_archetype[archetype].append(grade)
        return dict(by_archetype)

    def uncovered_archetypes(self) -> list[Archetype]:
        covered = set(self.archetype_counts())
        return [a for a in Archetype if a not in covered]

    # CORPUS-02D1 functional coverage: separate from, and never mixed into, the
    # headline supported-coverage metric above.
    def classified_grades(self) -> list[CaseGrade]:
        """Executed VERDICT cases that declare what they measure."""
        return [
            g for g in self.grades
            if g.case.depth is EvaluationDepth.VERDICT
            and g.case.functional is not None
            and g.result is not CoverageResult.NOT_RUN
        ]

    def functional_counts(self) -> dict[str, int]:
        """Declared measurement of each classified case whose test passed; a failed
        case establishes nothing and is counted as NOT_ESTABLISHED."""
        counts = {m.value: 0 for m in FunctionalMeasurement}
        counts["NOT_ESTABLISHED"] = 0
        for grade in self.classified_grades():
            if grade.result in SUPPORTED_RESULTS:
                counts[grade.case.functional.value] += 1
            else:
                counts["NOT_ESTABLISHED"] += 1
        return counts

    @property
    def functional_count(self) -> int:
        return sum(
            1 for g in self.classified_grades()
            if g.result in SUPPORTED_RESULTS and g.case.functional in FUNCTIONAL_RESULTS
        )

    def unclassified_verdict_count(self) -> int:
        """Executed MECHANIC verdict cases with no functional classification (STATE_INTEGRITY cases are accounted for)."""
        return sum(
            1 for g in self.grades
            if g.case.depth is EvaluationDepth.VERDICT and g.case.functional is None
            and g.case.role is CaseRole.MECHANIC and g.result is not CoverageResult.NOT_RUN
        )

    def integrity_grades(self) -> list[CaseGrade]:
        """Executed VERDICT cases that prove state/loadout/restore integrity rather than measure a mechanic."""
        return [
            g for g in self.grades
            if g.case.depth is EvaluationDepth.VERDICT and g.case.role is CaseRole.STATE_INTEGRITY
            and g.result is not CoverageResult.NOT_RUN
        ]

    def archetype_status(self) -> dict[Archetype, ArchetypeStatus]:
        """Per-archetype status from what the cases establish: FUNCTIONALLY MEASURED needs a passing FULLY_MEASURED verdict
        case; PARTIAL/EXPECTED UNCERTAINTY describe only refusals; REPRESENTED means identity/policy/integrity cases only."""
        by_archetype = self.archetype_counts()
        table: dict[Archetype, ArchetypeStatus] = {}
        for archetype in Archetype:
            grades = [g for g in by_archetype.get(archetype, []) if g.result is not CoverageResult.NOT_RUN]
            if not by_archetype.get(archetype):
                table[archetype] = ArchetypeStatus("RELEASE GAP", 0, 0, 0, 0, 0)
                continue
            failing = sum(1 for g in grades if g.result not in SUPPORTED_RESULTS)
            passing = [g for g in grades if g.result in SUPPORTED_RESULTS]
            fully = sum(1 for g in passing if g.case.functional is FunctionalMeasurement.FULLY_MEASURED)
            partial = sum(1 for g in passing if g.case.functional is FunctionalMeasurement.PARTIALLY_MEASURED)
            refusals = sum(1 for g in passing if g.case.functional in (
                FunctionalMeasurement.EXPECTED_UNCERTAINTY, FunctionalMeasurement.UNSUPPORTED_MECHANIC))
            other = len(passing) - fully - partial - refusals
            if fully:
                status = "FUNCTIONALLY MEASURED"
            elif partial:
                status = "PARTIAL"
            elif refusals:
                status = "EXPECTED UNCERTAINTY"
            else:
                status = "REPRESENTED"
            table[archetype] = ArchetypeStatus(status, fully, partial, refusals, other, failing)
        return table

    def audited_refusals(self) -> list[CaseGrade]:
        """Every case whose correct answer is a refusal or that is only partially measured (the R4 uncertainty audit)."""
        return [
            g for g in self.grades
            if g.case.expected is not ExpectedResult.CONFIDENT
            or g.case.functional is FunctionalMeasurement.PARTIALLY_MEASURED
        ]

    def functional_by_archetype(self) -> dict[Archetype, dict[str, int]]:
        table: dict[Archetype, dict[str, int]] = {}
        for grade in self.classified_grades():
            key = grade.case.functional.value if grade.result in SUPPORTED_RESULTS else "NOT_ESTABLISHED"
            for archetype in grade.case.archetypes:
                row = table.setdefault(archetype, {m.value: 0 for m in FunctionalMeasurement} | {"NOT_ESTABLISHED": 0})
                row[key] += 1
        return table


def _unmapped_failures(outcomes: list[JUnitOutcome], cases: tuple[CoverageCase, ...]) -> list[JUnitOutcome]:
    accounted: set[int] = set()
    for case in cases:
        for matched in _matches(case, outcomes):
            accounted.add(id(matched))
    return [o for o in outcomes if o.status in ("failed", "error") and id(o) not in accounted]


def build_report(
    outcomes: list[JUnitOutcome],
    cases: tuple[CoverageCase, ...] = ALL_CASES,
    *,
    runtime: dict[str, str] | None = None,
) -> CoverageReport:
    return CoverageReport(
        grades=[grade_case(case, outcomes) for case in cases],
        unmapped_failures=_unmapped_failures(outcomes, cases),
        runtime=dict(runtime or {}),
        skipped=[o for o in outcomes if o.status == "skipped"],
    )


def render_markdown(report: CoverageReport, gate_text: str | None = None) -> str:
    lines: list[str] = []
    lines.append("# Corpus Coverage Report")
    lines.append("")
    lines.append(
        "Generated by `scripts/generate_corpus_coverage_report.py` from the existing "
        "Build Corpus (`fixtures/builds/public_corpus/manifest.json`) and the existing "
        "regression suites. See `docs/CORPUS_COVERAGE_METHODOLOGY.md` for how cases are "
        "graded and how to extend this report. This file is generated — do not hand-edit."
    )
    lines.append("")

    total = report.total_count
    supported = report.supported_count
    if report.runtime:
        lines.append(
            "**PoB runtime this report was measured on:** "
            + ", ".join(f"{key} {value}" for key, value in sorted(report.runtime.items()))
            + ". Results are specific to this runtime: another PoB revision can legitimately change a measured value."
        )
        lines.append("")
    if gate_text:
        lines.append("## R4 1.0 reliability gate (coverage half)")
        lines.append("")
        lines.append("```")
        lines.append(gate_text)
        lines.append("```")
        lines.append("")
    lines.append("## Headline metric")
    lines.append("")
    if total == 0:
        lines.append(
            "**Supported real-build coverage: not computable.** No coverage case executed "
            "(engine unavailable, or the targeted suites were not run). Rerun with a local "
            "PoB2 install detectable via `POB2_PATH` or auto-detection."
        )
    else:
        pct = 100.0 * supported / total
        lines.append(
            f"**Supported real-build coverage (of executed cases): {supported}/{total} "
            f"({pct:.0f}%).**"
        )
        lines.append("")
        lines.append(
            "This measures *executed coverage cases*, not real-build population share — the "
            f"corpus is currently {manifest_fixture_count()} build fixtures (from the corpus manifest) plus "
            "deterministic policy unit tests, not a "
            "statistically representative sample of live PoE2 builds. Treat the percentage as "
            "\"how much of what we've encoded so far behaves correctly\", not \"what fraction "
            "of real builds ExileLens can evaluate\". See Known limitations."
        )
    lines.append("")

    lines.append("## Result distribution")
    lines.append("")
    lines.append("| Result | Count |")
    lines.append("| --- | --- |")
    for result, count in report.result_counts.items():
        lines.append(f"| {result} | {count} |")
    lines.append("")

    lines.extend(_render_functional(report))
    lines.extend(_render_archetype_status(report))
    lines.extend(_render_integrity(report))
    lines.extend(_render_audit(report))

    lines.append("## Archetype / mechanic coverage matrix")
    lines.append("")
    lines.append("| Archetype | Cases | Results |")
    lines.append("| --- | --- | --- |")
    by_archetype = report.archetype_counts()
    for archetype in Archetype:
        grades = by_archetype.get(archetype, [])
        if not grades:
            lines.append(f"| {archetype.value} | 0 | **NO COVERAGE** |")
            continue
        summary = ", ".join(f"{g.case.id}={g.result.value}" for g in grades)
        lines.append(f"| {archetype.value} | {len(grades)} | {summary} |")
    lines.append("")

    uncovered = report.uncovered_archetypes()
    lines.append(f"**{len(uncovered)}/{len(list(Archetype))} archetype categories have zero corpus representation:**")
    lines.append("")
    for archetype in uncovered:
        lines.append(f"- {archetype.value}")
    lines.append("")

    lines.append("## Build/verdict-level cases (archetype matrix detail)")
    lines.append("")
    lines.append("| Case | Depth | Archetypes | Expected | Result | Variants |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for grade in report.grades:
        case = grade.case
        if case.depth.value == "POLICY_UNIT":
            continue
        archetypes = ", ".join(a.value for a in case.archetypes) or "(none — cross-cutting)"
        lines.append(
            f"| {case.id} | {case.depth.value} | {archetypes} | {case.expected.value} | "
            f"{grade.result.value} | {grade.passed_variants}/{grade.total_variants} |"
        )
    lines.append("")

    lines.append("## Policy safety-net (adversarial unit coverage, not archetype-specific)")
    lines.append("")
    lines.append(
        "These are deterministic, worker-shaped unit tests of the verdict/quality contract "
        "itself (guardrails, resistance-cap state machine, malformed-metric handling, slot "
        "selection, identity). They do not exercise a real build archetype and are not part "
        "of the archetype matrix above; see `docs/CORE_04_ITEM_CHECK_COVERAGE_MATRIX.md` for "
        "the full policy-boundary catalogue this suite implements."
    )
    lines.append("")
    lines.append("| Case | Expected | Result | Variants |")
    lines.append("| --- | --- | --- | --- |")
    for grade in report.grades:
        case = grade.case
        if case.depth.value != "POLICY_UNIT":
            continue
        lines.append(
            f"| {case.id} | {case.expected.value} | {grade.result.value} | "
            f"{grade.passed_variants}/{grade.total_variants} |"
        )
    lines.append("")

    lines.append("## Failing tests outside the registry")
    lines.append("")
    if not report.unmapped_failures:
        lines.append("None in this run: every failing test in the executed suites belongs to a registered case.")
    else:
        lines.append(
            "The headline metric only sees registered cases. These tests failed in the executed suites and no registered "
            "case accounts for them; the R4 gate blocks on any of them."
        )
        for outcome in report.unmapped_failures:
            lines.append(f"- `{outcome.classname.split('.')[-1]}::{outcome.name}`: {outcome.message[:160]}")
    lines.append("")

    lines.append("## Skipped tests in the executed suites")
    lines.append("")
    if not report.skipped:
        lines.append("None: every collected test in the executed suites ran.")
    else:
        lines.append("A skipped test is not evidence of anything. Listed so a skip cannot hide a gap.")
        for outcome in report.skipped:
            lines.append(f"- `{outcome.classname.split('.')[-1]}::{outcome.name}`: {outcome.message[:160]}")
    lines.append("")

    high_risk = report.high_risk_grades
    lines.append("## High-risk failures (confident but incorrect)")
    lines.append("")
    if not high_risk:
        lines.append("None in this run.")
    else:
        for grade in high_risk:
            lines.append(f"- **{grade.case.id}** ({grade.case.test_file}): {grade.case.description}")
            for message in grade.failure_messages:
                lines.append(f"  - `{message}`")
    lines.append("")

    return "\n".join(lines) + "\n"


def _render_functional(report: CoverageReport) -> list[str]:
    lines = ["## Functional coverage (separate from the headline metric)", ""]
    lines.append(
        "The headline metric above counts a correct refusal as supported. This section does "
        "not: it counts what each classified verdict-level case's own assertions establish "
        "about the mechanic (see `FunctionalMeasurement` in `tests/corpus_coverage/taxonomy.py`). "
        "Only FULLY_MEASURED is functional coverage. Every verdict-level case is either a MECHANIC case (classified "
        "here) or a STATE_INTEGRITY case (loadout, restore and enumeration plumbing, listed separately below: it is "
        "neither counted as nor against functional coverage). Identity and policy cases are not verdict-level."
    )
    lines.append("")
    classified = report.classified_grades()
    if not classified:
        lines.append("**Functional coverage: not computable.** No classified case executed.")
        lines.append("")
        return lines
    lines.append(
        f"**Fully measured (of executed classified cases): {report.functional_count}/{len(classified)} "
        f"({100.0 * report.functional_count / len(classified):.0f}%).** "
        f"Executed mechanic cases not yet classified: {report.unclassified_verdict_count()}. "
        f"State-integrity cases: {len(report.integrity_grades())}."
    )
    lines.append("")
    lines.append("| Measurement | Cases |")
    lines.append("| --- | --- |")
    for name, count in report.functional_counts().items():
        lines.append(f"| {name} | {count} |")
    lines.append("")
    columns = [m.value for m in FunctionalMeasurement] + ["NOT_ESTABLISHED"]
    lines.append("| Archetype | " + " | ".join(columns) + " |")
    lines.append("| --- |" + " --- |" * len(columns))
    by_archetype = report.functional_by_archetype()
    for archetype in Archetype:
        row = by_archetype.get(archetype)
        if row:
            lines.append(f"| {archetype.value} | " + " | ".join(str(row[c]) for c in columns) + " |")
    lines.append("")
    lines.append("| Case | Measurement | Result |")
    lines.append("| --- | --- | --- |")
    for grade in classified:
        lines.append(f"| {grade.case.id} | {grade.case.functional.value} | {grade.result.value} |")
    lines.append("")
    return lines


def _render_archetype_status(report: CoverageReport) -> list[str]:
    lines = ["## Archetype status (what the cases establish, not how many there are)", ""]
    lines.append(
        "FUNCTIONALLY MEASURED = at least one passing FULLY_MEASURED verdict case. PARTIAL / EXPECTED UNCERTAINTY = only "
        "partially measured or correctly refused. REPRESENTED = identity, policy or integrity cases only. RELEASE GAP = no case."
    )
    lines.append("")
    lines.append("| Archetype | Status | Fully measured | Partial | Refusals | Other (identity/policy/integrity) | Failing |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for archetype, status in report.archetype_status().items():
        lines.append(
            f"| {archetype.value} | {status.status} | {status.fully_measured} | {status.partially_measured} | "
            f"{status.refusals} | {status.integrity_or_identity} | {status.failing} |"
        )
    lines.append("")
    return lines


def _render_integrity(report: CoverageReport) -> list[str]:
    grades = report.integrity_grades()
    lines = ["## State-integrity cases", ""]
    lines.append(
        "Verdict-level cases that prove the right loadout/state was evaluated, isolated, enumerated or restored. They assert no "
        "mechanic measurement, so they are not functional coverage; a failure here is a restore/state-corruption failure and "
        "blocks the R4 gate."
    )
    lines.append("")
    lines.append("| Case | Result |")
    lines.append("| --- | --- |")
    for grade in grades:
        lines.append(f"| {grade.case.id} | {grade.result.value} |")
    lines.append("")
    return lines


def _render_audit(report: CoverageReport) -> list[str]:
    grades = report.audited_refusals()
    lines = ["## Refusal / uncertainty audit", ""]
    lines.append(
        "Every case whose correct answer is a refusal (expected UNCERTAIN or UNSUPPORTED) or that is only partially measured, "
        "with the audited reason. CORRECT_UNCERTAINTY stays; FIXABLE_MEASUREMENT_GAP is a documented product limitation with "
        "its effort; COPY_OR_DIAGNOSTIC is a wording problem."
    )
    lines.append("")
    counts: dict[str, int] = defaultdict(int)
    for grade in grades:
        counts[grade.case.audit.value if grade.case.audit else "UNAUDITED"] += 1
    lines.append("Audit counts: " + ", ".join(f"{name}={count}" for name, count in sorted(counts.items())) + ".")
    lines.append("")
    lines.append("| Case | Answer | Audit | Note |")
    lines.append("| --- | --- | --- | --- |")
    for grade in grades:
        case = grade.case
        note = case.audit_note.replace("|", "/")
        lines.append(f"| {case.id} | {case.expected.value} | {case.audit.value if case.audit else 'UNAUDITED'} | {note} |")
    lines.append("")
    return lines


def to_json_dict(report: CoverageReport) -> dict:
    """Deterministic, diff-friendly machine-readable form (sorted keys, no timestamps)."""
    return {
        "result_counts": report.result_counts,
        "supported_count": report.supported_count,
        "total_count": report.total_count,
        "uncovered_archetypes": sorted(a.value for a in report.uncovered_archetypes()),
        "runtime": dict(sorted(report.runtime.items())),
        "unmapped_failures": sorted(f"{o.classname}::{o.name}" for o in report.unmapped_failures),
        "skipped_tests": sorted(f"{o.classname}::{o.name}" for o in report.skipped),
        "state_integrity_cases": len(report.integrity_grades()),
        "archetype_status": {
            a.value: {"status": s.status, "fully_measured": s.fully_measured, "partially_measured": s.partially_measured,
                      "refusals": s.refusals, "other": s.integrity_or_identity, "failing": s.failing}
            for a, s in report.archetype_status().items()
        },
        "functional": {
            "counts": report.functional_counts(),
            "fully_measured": report.functional_count,
            "classified_executed": len(report.classified_grades()),
            "unclassified_verdict_executed": report.unclassified_verdict_count(),
        },
        "cases": [
            {
                "id": grade.case.id,
                "test_file": grade.case.test_file,
                "depth": grade.case.depth.value,
                "expected": grade.case.expected.value,
                "archetypes": sorted(a.value for a in grade.case.archetypes),
                "manifest_id": grade.case.manifest_id,
                "functional": grade.case.functional.value if grade.case.functional else None,
                "role": grade.case.role.value,
                "audit": grade.case.audit.value if grade.case.audit else None,
                "audit_note": grade.case.audit_note,
                "blocks_1_0": grade.case.blocks_1_0,
                "result": grade.result.value,
                "passed_variants": grade.passed_variants,
                "total_variants": grade.total_variants,
                "failure_messages": list(grade.failure_messages),
            }
            for grade in sorted(report.grades, key=lambda g: g.case.id)
        ],
    }
