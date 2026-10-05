"""R4: the machine-checkable 1.0 Reliability / Coverage Gate.

Pure functions over a `CoverageReport` (and, separately, the Build Intelligence measurement JSON written by
`scripts/r4_gate_measure.py`). No subprocess and no engine, so the rules are unit-tested without PoB.

The gate does not ask for "100% of everything". It BLOCKS on evidence of an unsafe or unmeasured foundation and ALLOWS
documented limitations. A refusal that is correct and explained is not a failure; a confident answer nothing
established, a corrupted state, an unmeasured archetype, or an unexplained refusal is.

Thresholds are ratchets taken from the evidence at the time they were set (see `MIN_*`): they exist so coverage can
only grow, not so that a round number is reached. Raise them when the corpus grows; never lower them to pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from tests.corpus_coverage.report import CoverageReport
from tests.corpus_coverage.taxonomy import (
    Archetype,
    CaseRole,
    CoverageResult,
    EvaluationDepth,
    ExpectedResult,
    FunctionalMeasurement,
    UncertaintyAudit,
)

BLOCK = "BLOCK"
INFO = "INFO"

# Ratchets (R4 evidence, installed PoB 0.23.1): executed registered cases and passing FULLY_MEASURED verdict cases.
MIN_EXECUTED_CASES = 190
MIN_FULLY_MEASURED_CASES = 92

# Archetypes the corpus represents but does not (yet) functionally measure, each with the documented reason. An archetype
# not listed here must be FUNCTIONALLY_MEASURED to pass the gate.
DOCUMENTED_NOT_FUNCTIONALLY_MEASURED: Mapping[Archetype, str] = {
    Archetype.UNUSUAL_SKILL_PART: (
        "Only the Flameblast channel-release stage context is represented; its ignite verdict is PARTIAL because "
        "ignite/bleed-dominant outputs have no stack/stage scope proof (audited FIXABLE_MEASUREMENT_GAP)."
    ),
}


@dataclass(frozen=True)
class GateCheck:
    name: str
    passed: bool
    severity: str
    detail: str


@dataclass(frozen=True)
class GateResult:
    checks: tuple[GateCheck, ...]
    evaluable: bool

    @property
    def blockers(self) -> tuple[GateCheck, ...]:
        return tuple(c for c in self.checks if c.severity == BLOCK and not c.passed)

    @property
    def passed(self) -> bool:
        return self.evaluable and not self.blockers

    @property
    def verdict(self) -> str:
        if not self.evaluable:
            return "NOT_EVALUABLE"
        return "PASS" if not self.blockers else "BLOCKED"


def _names(grades: list[Any]) -> str:
    return ", ".join(sorted(g.case.id for g in grades)) or "none"


def evaluate_gate(report: CoverageReport) -> GateResult:
    executed = [g for g in report.grades if g.result is not CoverageResult.NOT_RUN]
    evaluable = bool(executed)
    checks: list[GateCheck] = []

    wrong = [g for g in report.grades if g.result in (CoverageResult.WRONG_RESULT, CoverageResult.WRONG_UNCERTAIN)]
    checks.append(GateCheck("NO_WRONG_RESULT", not wrong, BLOCK,
                            f"WRONG_RESULT/WRONG_UNCERTAIN cases: {_names(wrong)}"))

    integrity = [g for g in report.grades if g.case.role is CaseRole.STATE_INTEGRITY]
    # A state-integrity case proves the state was right: only a plain PASS counts. A refusal, a skip or a failure is not proof.
    integrity_bad = [g for g in integrity if g.result is not CoverageResult.PASS]
    checks.append(GateCheck("RESTORE_AND_STATE_INTEGRITY", bool(integrity) and not integrity_bad, BLOCK,
                            f"{len(integrity) - len(integrity_bad)}/{len(integrity)} integrity cases pass; failing/not run: {_names(integrity_bad)}"))

    not_run = [g for g in report.grades if g.result is CoverageResult.NOT_RUN]
    checks.append(GateCheck("EVERY_REGISTERED_CASE_EXECUTED", not not_run, BLOCK,
                            f"registered cases that did not execute: {_names(not_run)}"))

    unmapped = report.unmapped_failures
    checks.append(GateCheck("NO_FAILING_TEST_OUTSIDE_THE_REGISTRY", not unmapped, BLOCK,
                            "failing tests no registered case accounts for: "
                            + (", ".join(sorted(f"{o.classname.split('.')[-1]}::{o.name}" for o in unmapped)) or "none")))

    unclassified = [g for g in report.grades if g.case.depth is EvaluationDepth.VERDICT
                    and g.case.role is CaseRole.MECHANIC and g.case.functional is None]
    checks.append(GateCheck("EVERY_VERDICT_CASE_CLASSIFIED", not unclassified, BLOCK,
                            f"verdict cases with neither a functional classification nor an integrity role: {_names(unclassified)}"))

    needs_audit = [g for g in report.grades if g.case.audit is None and (
        g.case.expected is not ExpectedResult.CONFIDENT or g.case.functional is FunctionalMeasurement.PARTIALLY_MEASURED)]
    checks.append(GateCheck("EVERY_REFUSAL_AUDITED", not needs_audit, BLOCK,
                            f"refusal/partial cases without an audit: {_names(needs_audit)}"))

    blockers = [g for g in report.grades if g.case.blocks_1_0]
    checks.append(GateCheck("NO_UNRESOLVED_RELEASE_BLOCKER", not blockers, BLOCK,
                            f"cases flagged blocks_1_0: {_names(blockers)}"))

    uncovered = report.uncovered_archetypes()
    checks.append(GateCheck("EVERY_ARCHETYPE_REPRESENTED", not uncovered, BLOCK,
                            "archetypes with no corpus case: " + (", ".join(a.value for a in uncovered) or "none")))

    statuses = report.archetype_status()
    short = [a for a, s in statuses.items()
             if s.status != "FUNCTIONALLY MEASURED" and a not in DOCUMENTED_NOT_FUNCTIONALLY_MEASURED and a not in uncovered]
    checks.append(GateCheck("EVERY_ARCHETYPE_FUNCTIONALLY_MEASURED_OR_DOCUMENTED", not short, BLOCK,
                            "not functionally measured and not documented: " + (", ".join(a.value for a in short) or "none")))

    checks.append(GateCheck("EXECUTED_CASE_RATCHET", len(executed) >= MIN_EXECUTED_CASES, BLOCK,
                            f"executed {len(executed)} (minimum {MIN_EXECUTED_CASES})"))
    checks.append(GateCheck("FULLY_MEASURED_RATCHET", report.functional_count >= MIN_FULLY_MEASURED_CASES, BLOCK,
                            f"fully measured {report.functional_count} (minimum {MIN_FULLY_MEASURED_CASES})"))

    fixable = [g for g in report.grades if g.case.audit is UncertaintyAudit.FIXABLE_MEASUREMENT_GAP]
    checks.append(GateCheck("DOCUMENTED_FIXABLE_GAPS", True, INFO,
                            f"{len(fixable)} audited FIXABLE_MEASUREMENT_GAP refusals (allowed, documented): {_names(fixable)}"))
    for archetype, reason in DOCUMENTED_NOT_FUNCTIONALLY_MEASURED.items():
        checks.append(GateCheck(f"DOCUMENTED_LIMITATION:{archetype.value}", True, INFO, reason))
    return GateResult(tuple(checks), evaluable)


def render_gate(result: GateResult) -> str:
    lines = [f"R4 1.0 RELIABILITY GATE (coverage): {result.verdict}"]
    for check in result.checks:
        mark = "ok  " if check.passed else ("FAIL" if check.severity == BLOCK else "info")
        lines.append(f"  [{mark}] {check.name}: {check.detail}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- Build Intelligence gate

#: Every per-build invariant `scripts/r4_gate_measure.py` records; all must hold for every build.
BUILD_INTEL_INVARIANTS = (
    "restore_fingerprint_unchanged",
    "lanes_sorted_and_labelled",
    "rescore_priorities_identical",
    "rescore_made_no_pob_call",
    "not_stale_on_same_baseline",
    "stale_after_generation_change",
    "no_per_point_or_normalised_fields",
    "repeat_priorities_identical",
)
#: A lane that exists must never report a response it did not measure: a build with measured responses elsewhere may have
#: an empty lane, but a build where EVERY lane is empty must say so through `strongest_status`, never through silence.
EMPTY_STATES = {"NO_MEASURABLE_RESPONSE", "COULD_NOT_ESTABLISH", "NOT_SUPPORTED"}


def evaluate_build_intel_gate(measure: Mapping[str, Any]) -> GateResult:
    """Check the JSON written by `scripts/r4_gate_measure.py` (Parts A and B)."""
    builds = list(measure.get("builds") or [])
    checks: list[GateCheck] = []
    failed = [b["id"] for b in builds if not b.get("ok")]
    checks.append(GateCheck("EVERY_BUILD_ANALYSED", bool(builds) and not failed, BLOCK, f"builds whose analysis failed: {failed or 'none'}"))
    for invariant in BUILD_INTEL_INVARIANTS:
        bad = [b["id"] for b in builds if b.get("ok") and not (b.get("invariants") or {}).get(invariant)]
        checks.append(GateCheck(f"BI:{invariant}", not bad, BLOCK, f"violating builds: {bad or 'none'}"))
    silent = []
    for b in builds:
        if not b.get("ok"):
            continue
        counts = b.get("lane_row_counts") or {}
        status = b.get("strongest_status") or {}
        if sum(counts.values()) == 0 and not any(status.get(k) in EMPTY_STATES for k in ("damage", "ehp", "max_hit", "movement")):
            silent.append(b["id"])
    checks.append(GateCheck("BI:INSUFFICIENT_EVIDENCE_IS_EXPLICIT", not silent, BLOCK, f"builds with no lane rows and no explicit state: {silent or 'none'}"))
    not_established = [b["id"] for b in builds if b.get("ok") and b.get("not_established")]
    checks.append(GateCheck("BI:NOT_ESTABLISHED_PROBES", True, INFO, f"builds with probes the engine could not establish (reported, never zeros): {not_established or 'none'}"))
    cache = list(measure.get("cache") or [])
    for key in ("fingerprint_changed_by_equip", "analysis_changed_by_equip", "fingerprint_restored_after_reload", "analysis_reproduced_after_reload"):
        bad = [c["id"] for c in cache if not c.get("ok") or not c.get(key)]
        checks.append(GateCheck(f"BI_CACHE:{key}", bool(cache) and not bad, BLOCK, f"violating builds: {bad or 'none'}"))
    return GateResult(tuple(checks), bool(builds))
