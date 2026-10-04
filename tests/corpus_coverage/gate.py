"""R4 1.0 reliability gate: machine-checkable criteria over a coverage report.

Pure functions over the JSON form (`report.to_json_dict`), so the committed
`docs/corpus_coverage/coverage_report.json` can be gated without an engine and a fresh engine
run can be gated the same way. The gate never invents a threshold: the one numeric ratchet
(`MIN_FULLY_MEASURED`) is the value measured when the gate was defined, so coverage can grow
but not silently shrink. See docs/R4-1.0-RELIABILITY-GATE.md for what each criterion protects
and which release conditions are not machine-checkable.
"""

from __future__ import annotations

from dataclasses import dataclass

# Archetypes a 1.0 Item Check must have *functional* (FULLY_MEASURED, passing) evidence for.
# Not listed: trigger, unusual_skill_part, unique_interaction and the derived stat_stacker. Those
# are represented but may legitimately rest on refusals (see the gate document).
MAJOR_ARCHETYPES: tuple[str, ...] = (
    "melee",
    "ranged_attack",
    "spell",
    "crit",
    "dot",
    "ailment",
    "minion",
    "proxy_totem",
    "attribute_stacker",
    "mana_scaling",
    "es_scaling",
    "life_scaling",
    "weapon_swap",
    "ascendancy",
)

# Ratchet, taken from the R4 classification pass (FULLY_MEASURED cases passing).
MIN_FULLY_MEASURED = 70

# Criteria whose outcome depends on having current results. When results are missing or carried
# forward these cannot be judged, so they yield INCONCLUSIVE rather than FAIL.
_RESULT_DEPENDENT = frozenset({
    "STATE_INTEGRITY_ALL_PASS", "MAJOR_ARCHETYPES_FUNCTIONALLY_MEASURED", "FUNCTIONAL_COVERAGE_RATCHET",
})

_BAD_RESULTS = ("WRONG_RESULT", "WRONG_UNCERTAIN")
_PASSING = ("PASS", "EXPECTED_UNCERTAIN", "UNSUPPORTED")

BLOCK = "BLOCK"
LIMIT = "LIMIT"


@dataclass(frozen=True)
class Criterion:
    id: str
    severity: str  # BLOCK: failing blocks 1.0. LIMIT: failing is a documented limitation.
    ok: bool
    detail: str


@dataclass(frozen=True)
class GateResult:
    verdict: str  # PASS | CONDITIONAL | FAIL | INCONCLUSIVE
    criteria: tuple[Criterion, ...]

    def failing(self, severity: str | None = None) -> list[Criterion]:
        return [c for c in self.criteria if not c.ok and (severity is None or c.severity == severity)]


def evaluate_gate(report: dict) -> GateResult:
    cases = report["cases"]
    criteria: list[Criterion] = []

    bad = [c["id"] for c in cases if c["result"] in _BAD_RESULTS]
    criteria.append(Criterion(
        "NO_WRONG_RESULT", BLOCK, not bad,
        "no case is WRONG_RESULT / WRONG_UNCERTAIN" if not bad else "failing: " + ", ".join(bad),
    ))

    state = [c for c in cases if c["depth"] == "STATE_INTEGRITY"]
    state_bad = [c["id"] for c in state if c["result"] not in _PASSING]
    criteria.append(Criterion(
        "STATE_INTEGRITY_ALL_PASS", BLOCK, bool(state) and not state_bad,
        f"{len(state) - len(state_bad)}/{len(state)} restore/determinism/isolation cases pass"
        + (f"; not passing: {', '.join(state_bad)}" if state_bad else ""),
    ))

    unclassified = [c["id"] for c in cases if c["depth"] == "VERDICT" and c["functional"] is None]
    criteria.append(Criterion(
        "EVERY_VERDICT_CASE_CLASSIFIED", BLOCK, not unclassified,
        "every verdict-level case declares what it measures" if not unclassified
        else "unclassified: " + ", ".join(unclassified),
    ))

    uncovered = report["uncovered_archetypes"]
    criteria.append(Criterion(
        "NO_UNREPRESENTED_ARCHETYPE", BLOCK, not uncovered,
        "every archetype (derived umbrellas through their constituents) has a case"
        if not uncovered else "no case for: " + ", ".join(uncovered),
    ))

    functional_pass = {
        archetype
        for c in cases
        if c["functional"] == "FULLY_MEASURED" and c["result"] == "PASS"
        for archetype in c["archetypes"]
    }
    missing = [a for a in MAJOR_ARCHETYPES if a not in functional_pass]
    criteria.append(Criterion(
        "MAJOR_ARCHETYPES_FUNCTIONALLY_MEASURED", BLOCK, not missing,
        f"{len(MAJOR_ARCHETYPES) - len(missing)}/{len(MAJOR_ARCHETYPES)} major archetypes have a passing FULLY_MEASURED case"
        + (f"; none for: {', '.join(missing)}" if missing else ""),
    ))

    fully = report["functional"]["fully_measured"]
    criteria.append(Criterion(
        "FUNCTIONAL_COVERAGE_RATCHET", BLOCK, fully >= MIN_FULLY_MEASURED,
        f"{fully} fully measured cases (floor {MIN_FULLY_MEASURED})",
    ))

    not_established = [c["id"] for c in cases if c["functional"] == "NOT_ESTABLISHED" or (
        c["depth"] == "VERDICT" and c["functional"] is not None and c["result"] not in _PASSING + ("NOT_RUN",)
    )]
    criteria.append(Criterion(
        "NO_NOT_ESTABLISHED", LIMIT, not not_established,
        "no verdict case is missing evidence" if not not_established
        else f"{len(not_established)} verdict cases do not establish their measurement: " + ", ".join(not_established),
    ))

    not_run = [c["id"] for c in cases if c["result"] == "NOT_RUN"]
    carried = [c["id"] for c in cases if c.get("carried")]
    stale = report.get("provenance", {}).get("mode") != "executed" or bool(carried)
    if stale:
        criteria.append(Criterion(
            "RESULTS_ARE_CURRENT", BLOCK, False,
            f"{len(carried)} results are carried forward from an earlier engine run "
            f"({report.get('provenance', {}).get('results_from', 'unknown')}); re-run on a PoB2 machine",
        ))

    blocking = [c for c in criteria if not c.ok and c.severity == BLOCK]
    if not_run:
        criteria.append(Criterion(
            "ALL_CASES_EXECUTED", BLOCK, False,
            f"{len(not_run)} registered cases were not executed (no results): " + ", ".join(not_run),
        ))
    if not_run or stale:
        # Nothing was disproved, but nothing current was proven either. Structural failures and any
        # WRONG_* result in the data we do have still fail; the rest cannot be judged.
        structural = [c for c in blocking if c.id not in _RESULT_DEPENDENT
                      and c.id not in ("RESULTS_ARE_CURRENT", "ALL_CASES_EXECUTED")]
        verdict = "FAIL" if structural else "INCONCLUSIVE"
    elif blocking:
        verdict = "FAIL"
    elif any(not c.ok for c in criteria):
        verdict = "CONDITIONAL"
    else:
        verdict = "PASS"
    return GateResult(verdict, tuple(criteria))


def render_gate(result: GateResult) -> str:
    lines = [f"R4 1.0 RELIABILITY GATE (machine-checkable part): {result.verdict}"]
    for c in result.criteria:
        lines.append(f"  [{'ok' if c.ok else 'FAIL' if c.severity == BLOCK else 'limit'}] {c.id}: {c.detail}")
    return "\n".join(lines)
