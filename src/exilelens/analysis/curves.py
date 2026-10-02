"""R1.5 response curves: does a top stat keep paying off when the build gets more of it?

One sensitivity probe (baseline B -> B + D) cannot say that. For a small, bounded set of the build's strongest measured
stats this module asks the existing `ProbeEngine` for one more point, B + 2D, and compares the two STEPS:

    first step   f(B + D)  - f(B)
    second step  f(B + 2D) - f(B + D)

Both are expressed in percent of the baseline value, so they are directly comparable; the raw 2D response is never
presented as a marginal value. The probe is the same catalog probe at twice its canonical increment, run through the same
`run_probe` (same restore verification, same `ProbeCache` key: baseline fingerprint, generation, context, probe,
magnitude), so a repeat analysis of the same baseline costs nothing.

Runs only inside an explicit Analyze Build. Resistances are excluded on purpose: they have real caps and are described by
the explicit breakpoint facts in `analysis.actionable`, never by curve language.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from exilelens.analysis.fingerprint import MEASURED, _PROBE_STATUS
from exilelens.analysis.priorities import MEANINGFUL_PERCENT

SCHEMA_VERSION = 1
#: Hard budget of follow-up probes per analysis (cold). Everything else in R1.5 is pure derivation.
MAX_CURVES = 3

# Player-facing states.
GROWS = "GROWS"
HOLDS = "HOLDS"
WEAKENS = "WEAKENS"
DROPS = "DROPS"
NO_FURTHER_VALUE = "NO_FURTHER_VALUE"
COULD_NOT_ESTABLISH = "COULD_NOT_ESTABLISH"

STATE_LABELS = {
    GROWS: "Response grows",
    HOLDS: "Response remains similar",
    WEAKENS: "Response weakens",
    DROPS: "Response drops sharply",
    NO_FURTHER_VALUE: "No further measured value",
    COULD_NOT_ESTABLISH: "Could not establish",
}

# Bands on ratio = second step / first step, set after looking at real PoB results (docs/R1-5-...md): flat and
# "increased" stats measured 1.00, attack/cast speed 0.88-1.00, skill levels 1.09-1.26, and stats that visibly taper
# (Strength, Poison Duration) 0.74-0.79. So +-15% around 1 is "about the same", below half is a real collapse, and under
# 5% of the first step is indistinguishable from nothing. The bands are not tuned per build.
GROWS_ABOVE = 1.15
HOLDS_FROM = 0.85
WEAKENS_FROM = 0.50
NO_VALUE_BELOW = 0.05

#: Lane -> (metric_profile key, player label). Movement is not curved: it is one stat with one obvious use.
_AXES = {"offense": ("primary_offense", "Damage"), "max_hit": ("worst_max_hit", "Max Hit"), "ehp": ("ehp", "EHP")}
#: Order in which lanes offer a target: the strongest damage stat, the strongest of each defensive axis, then the
#: runner-up damage stat. Three distinct stats at most.
_TARGET_ORDER = (("offense", 0), ("max_hit", 0), ("ehp", 0), ("offense", 1))
_INELIGIBLE_FAMILIES = frozenset({"resistance"})


def classify(first: float, second: float) -> str:
    """State of the second step relative to the first. `first` must be a meaningful positive response."""
    if first <= 0:
        return COULD_NOT_ESTABLISH
    ratio = second / first
    if ratio < NO_VALUE_BELOW:
        return NO_FURTHER_VALUE
    if ratio < WEAKENS_FROM:
        return DROPS
    if ratio < HOLDS_FROM:
        return WEAKENS
    if ratio <= GROWS_ABOVE:
        return HOLDS
    return GROWS


def curve_targets(priorities: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(stat label, lane) for the stats worth a second measurement, strongest first. At most `MAX_CURVES`."""
    targets: list[tuple[str, str]] = []
    for lane, position in _TARGET_ORDER:
        if lane == "offense" and priorities.get("offense_limited_confidence"):
            continue  # a low-confidence damage number is not worth a second measurement
        rows = priorities.get(lane) or []
        if position >= len(rows):
            continue
        row = rows[position]
        label = str(row.get("label") or "")
        if float(row.get("response_percent") or 0.0) < MEANINGFUL_PERCENT:
            continue
        if label and label not in [name for name, _lane in targets]:
            targets.append((label, lane))
    return targets[:MAX_CURVES]


def _percent(probe: Mapping[str, Any], key: str) -> float | None:
    entry = (probe.get("metric_profile") or {}).get(key) or {}
    if entry.get("availability") != "available" or entry.get("percent_delta") is None:
        return None
    return float(entry["percent_delta"])


def _not_established(label: str, lane: str, reason: str, first: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "label": label,
        "axis": lane,
        "axis_label": _AXES[lane][1],
        "tested_change": str((first or {}).get("line") or ""),
        "status": COULD_NOT_ESTABLISH,
        "state": COULD_NOT_ESTABLISH,
        "reason": reason,
    }


def measure_response_curves(
    probes: Any,
    catalog: Any,
    global_probes: list[Mapping[str, Any]],
    priorities: Mapping[str, Any],
    *,
    run_probe: Callable[[str, float], dict[str, Any]],
    before_probe: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Measure B + 2D for the target stats. `run_probe(probe_id, magnitude)` is the analysis' own probe runner."""
    recalcs_before = probes.pob_recalcs
    by_label = {
        str(p.get("display_name")): p
        for p in global_probes
        if p.get("status") == "ok" and not p.get("nonlinear_sample") and not p.get("breakpoint_exact")
    }
    curves: list[dict[str, Any]] = []
    for label, lane in curve_targets(priorities):
        first = by_label.get(label)
        definition = catalog.get(str((first or {}).get("probe_id") or ""))
        key = _AXES[lane][0]
        if first is None or definition is None:
            curves.append(_not_established(label, lane, "first measurement not available"))
            continue
        if definition.family in _INELIGIBLE_FAMILIES:
            continue  # explicit breakpoint mechanics; never a curve
        step = float(first.get("magnitude") or 0.0)
        first_percent = _percent(first, key)
        if step <= 0 or first_percent is None or first_percent < MEANINGFUL_PERCENT:
            curves.append(_not_established(label, lane, "first measurement has no response on this axis", first))
            continue
        if before_probe is not None:
            before_probe()
        second = run_probe(str(first["probe_id"]), step * 2)
        total_percent = _percent(second, key) if _PROBE_STATUS.get(str(second.get("status"))) == MEASURED else None
        if total_percent is None:
            curves.append(_not_established(label, lane, "the doubled change could not be measured", first))
            continue
        second_percent = total_percent - first_percent
        curves.append(
            {
                "label": label,
                "axis": lane,
                "axis_label": _AXES[lane][1],
                "tested_change": str(first.get("line") or ""),
                "doubled_change": str(second.get("line") or ""),
                "step": step,
                "first_percent": round(first_percent, 2),
                "total_percent": round(total_percent, 2),
                "second_percent": round(second_percent, 2),
                "ratio": round(second_percent / first_percent, 3),
                "status": MEASURED,
                "state": classify(first_percent, second_percent),
                "confidence": str(first.get("confidence") or ""),
                "reused": bool(second.get("cache_hit")),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "budget": MAX_CURVES,
        "new_recalcs": probes.pob_recalcs - recalcs_before,
        "curves": curves,
    }
