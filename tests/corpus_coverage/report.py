"""Builds the Corpus Coverage Matrix/Report from the registry + JUnit outcomes.

Pure functions only (no subprocess/pytest invocation here — see
scripts/generate_corpus_coverage_report.py for the CLI that runs the targeted
suites and calls into this module). Keeping this side-effect-free is what makes
`tests/test_corpus_coverage_report.py` able to exercise the grading logic without
a local PoB2 install.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from tests.corpus_coverage.junit import JUnitOutcome
from tests.corpus_coverage.registry import ALL_CASES, CoverageCase
from tests.corpus_coverage.taxonomy import (
    SUPPORTED_RESULTS,
    Archetype,
    CoverageResult,
    ExpectedResult,
)

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


@dataclass
class CoverageReport:
    grades: list[CaseGrade] = field(default_factory=list)

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


def build_report(outcomes: list[JUnitOutcome], cases: tuple[CoverageCase, ...] = ALL_CASES) -> CoverageReport:
    return CoverageReport(grades=[grade_case(case, outcomes) for case in cases])


def render_markdown(report: CoverageReport) -> str:
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
            "corpus is currently 4 build fixtures plus deterministic policy unit tests, not a "
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


def to_json_dict(report: CoverageReport) -> dict:
    """Deterministic, diff-friendly machine-readable form (sorted keys, no timestamps)."""
    return {
        "result_counts": report.result_counts,
        "supported_count": report.supported_count,
        "total_count": report.total_count,
        "uncovered_archetypes": sorted(a.value for a in report.uncovered_archetypes()),
        "cases": [
            {
                "id": grade.case.id,
                "test_file": grade.case.test_file,
                "depth": grade.case.depth.value,
                "expected": grade.case.expected.value,
                "archetypes": sorted(a.value for a in grade.case.archetypes),
                "manifest_id": grade.case.manifest_id,
                "result": grade.result.value,
                "passed_variants": grade.passed_variants,
                "total_variants": grade.total_variants,
                "failure_messages": list(grade.failure_messages),
            }
            for grade in sorted(report.grades, key=lambda g: g.case.id)
        ],
    }
