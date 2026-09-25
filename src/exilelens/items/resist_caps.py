from __future__ import annotations

import math
from enum import Enum
from typing import Any


class CapState(str, Enum):
    CAPPED_STAYS_CAPPED = "CAPPED_STAYS_CAPPED"
    OVER_CAP_REDUCED_BUT_STILL_CAPPED = "OVER_CAP_REDUCED_BUT_STILL_CAPPED"
    CAP_REACHED = "CAP_REACHED"
    CAP_LOST = "CAP_LOST"
    BELOW_CAP_IMPROVED = "BELOW_CAP_IMPROVED"
    BELOW_CAP_UNCHANGED = "BELOW_CAP_UNCHANGED"
    BELOW_CAP_WORSENED = "BELOW_CAP_WORSENED"
    UNKNOWN = "UNKNOWN"

    @property
    def at_effective_cap(self) -> bool:
        return self in {
            CapState.CAPPED_STAYS_CAPPED,
            CapState.OVER_CAP_REDUCED_BUT_STILL_CAPPED,
            CapState.CAP_REACHED,
        }


# Backward-compatible aliases used by older docs/tests.
CAP_MAINTAINED = CapState.CAPPED_STAYS_CAPPED
FURTHER_BELOW_CAP = CapState.BELOW_CAP_WORSENED
STILL_BELOW_CAP = CapState.BELOW_CAP_UNCHANGED
CAP_GAINED = CapState.CAP_REACHED


RESIST_ELEMENTS = ("fire", "cold", "lightning", "chaos")
ELEMENTAL = ("fire", "cold", "lightning")
_ELEMENT_TO_POB = {
    "fire": "Fire",
    "cold": "Cold",
    "lightning": "Lightning",
    "chaos": "Chaos",
}

AT_CAP_EPSILON = 0.05

# Generic utility of resistance *above* the effective cap ("buffer"): flexibility to
# swap other gear or absorb curses/penalties without losing the cap. Marginal utility
# per buffer point diminishes by band and saturates past +30. This is flexibility only:
# downstream effects of uncapped resistance (e.g. ES or damage scaling from uncapped
# res) already reach PoB Life/ES/EHP/Max Hit and are scored there, not here.
OVERCAP_MARGINAL_UTILITY_0_20 = 0.20
OVERCAP_MARGINAL_UTILITY_20_30 = 0.075
OVERCAP_MARGINAL_UTILITY_ABOVE_30 = 0.01
OVERCAP_BAND_LOW_END = 20.0
OVERCAP_BAND_MID_END = 30.0

STATE_SEVERITY = {
    CapState.CAP_LOST: "critical",
    CapState.BELOW_CAP_WORSENED: "high",
    CapState.BELOW_CAP_IMPROVED: "positive",
    CapState.CAP_REACHED: "critical_positive",
    CapState.OVER_CAP_REDUCED_BUT_STILL_CAPPED: "info",
    CapState.CAPPED_STAYS_CAPPED: "info",
    CapState.BELOW_CAP_UNCHANGED: "info",
    CapState.UNKNOWN: "unknown",
}


def _num(raw: dict[str, Any], field: str) -> float | None:
    if field not in raw:
        return None
    value = raw.get(field)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def effective_cap(raw: dict[str, Any], element: str) -> float | None:
    prefix = _ELEMENT_TO_POB[element]
    explicit = _num(raw, f"{prefix}ResistMax")
    if explicit is not None and explicit > 0:
        return explicit
    resist = _num(raw, f"{prefix}Resist")
    missing = _num(raw, f"{prefix}Missing") or _num(raw, f"Missing{prefix}Resist")
    if resist is None:
        return None
    return float(resist) + float(missing or 0.0)


def _deficit(value: float | None, cap: float | None) -> float | None:
    if value is None or cap is None:
        return None
    return max(0.0, cap - value)


def _buffer(overcap: float | None, uncapped: float | None, cap: float | None) -> float | None:
    """Resistance above the effective cap. None when neither PoB field is available.

    The bridge zero-fills fields PoB did not emit, so either source can read 0 while
    the other is real; the larger of the two is the buffer PoB actually computed.
    """
    candidates = []
    if overcap is not None:
        candidates.append(float(overcap))
    if uncapped is not None and cap is not None:
        candidates.append(float(uncapped) - float(cap))
    if not candidates:
        return None
    return max(0.0, *candidates)


def overcap_utility(buffer: float | None) -> float:
    """Cumulative flexibility utility of `buffer` points above cap (diminishing bands)."""
    points = max(0.0, float(buffer or 0.0))
    low = min(points, OVERCAP_BAND_LOW_END)
    mid = min(max(points - OVERCAP_BAND_LOW_END, 0.0), OVERCAP_BAND_MID_END - OVERCAP_BAND_LOW_END)
    high = max(points - OVERCAP_BAND_MID_END, 0.0)
    return (
        low * OVERCAP_MARGINAL_UTILITY_0_20
        + mid * OVERCAP_MARGINAL_UTILITY_20_30
        + high * OVERCAP_MARGINAL_UTILITY_ABOVE_30
    )


def analyze_resistance(raw_current: dict[str, Any], raw_candidate: dict[str, Any], element: str) -> dict[str, Any]:
    prefix = _ELEMENT_TO_POB[element]
    current = _num(raw_current, f"{prefix}Resist")
    candidate = _num(raw_candidate, f"{prefix}Resist")
    availability = "available" if current is not None and candidate is not None else "missing"
    cap_current = effective_cap(raw_current, element)
    cap_candidate = effective_cap(raw_candidate, element)
    over_current = _num(raw_current, f"{prefix}ResistOverCap") or 0.0
    over_candidate = _num(raw_candidate, f"{prefix}ResistOverCap") or 0.0
    uncapped_current = _num(raw_current, f"{prefix}ResistTotal")
    uncapped_candidate = _num(raw_candidate, f"{prefix}ResistTotal")
    if uncapped_current is None and current is not None:
        uncapped_current = current + over_current
    if uncapped_candidate is None and candidate is not None:
        uncapped_candidate = candidate + over_candidate

    buffer_current = _buffer(_num(raw_current, f"{prefix}ResistOverCap"), uncapped_current, cap_current)
    buffer_candidate = _buffer(_num(raw_candidate, f"{prefix}ResistOverCap"), uncapped_candidate, cap_candidate)
    buffer_delta = None
    flexibility_delta = 0.0
    if buffer_current is not None and buffer_candidate is not None:
        buffer_delta = buffer_candidate - buffer_current
        flexibility_delta = overcap_utility(buffer_candidate) - overcap_utility(buffer_current)

    baseline_deficit = _deficit(current, cap_current)
    candidate_deficit = _deficit(candidate, cap_candidate)
    deficit_delta = None
    if baseline_deficit is not None and candidate_deficit is not None:
        deficit_delta = candidate_deficit - baseline_deficit

    state = CapState.UNKNOWN
    if availability == "available" and cap_current is not None and cap_candidate is not None:
        was_capped = current >= cap_current - AT_CAP_EPSILON
        now_capped = candidate >= cap_candidate - AT_CAP_EPSILON
        if was_capped and now_capped:
            if over_current - over_candidate > AT_CAP_EPSILON and candidate >= cap_candidate - AT_CAP_EPSILON:
                state = CapState.OVER_CAP_REDUCED_BUT_STILL_CAPPED
            else:
                state = CapState.CAPPED_STAYS_CAPPED
        elif was_capped and not now_capped:
            state = CapState.CAP_LOST
        elif (not was_capped) and now_capped:
            state = CapState.CAP_REACHED
        elif candidate > current + AT_CAP_EPSILON:
            state = CapState.BELOW_CAP_IMPROVED
        elif candidate < current - AT_CAP_EPSILON:
            state = CapState.BELOW_CAP_WORSENED
        else:
            state = CapState.BELOW_CAP_UNCHANGED

    return {
        "element": element,
        "metric": f"{element}_res",
        "current": current,
        "candidate": candidate,
        "effective_cap": cap_candidate if cap_candidate is not None else cap_current,
        "cap_current": cap_current,
        "cap_candidate": cap_candidate,
        "baseline_deficit": baseline_deficit,
        "candidate_deficit": candidate_deficit,
        "deficit_delta": deficit_delta,
        "overcap_current": over_current,
        "overcap_candidate": over_candidate,
        "uncapped_current": uncapped_current,
        "uncapped_candidate": uncapped_candidate,
        "buffer_current": buffer_current,
        "buffer_candidate": buffer_candidate,
        "buffer_delta": buffer_delta,
        "flexibility_delta": round(flexibility_delta, 4),
        "state": state.value,
        "severity": STATE_SEVERITY[state],
        "effective_cap_lost": state == CapState.CAP_LOST,
        "deficit_worsened": state == CapState.BELOW_CAP_WORSENED,
        "overcap_only_change": state == CapState.OVER_CAP_REDUCED_BUT_STILL_CAPPED,
        "availability": availability,
    }


def analyze_resistances(raw_current: dict[str, Any], raw_candidate: dict[str, Any]) -> dict[str, Any]:
    elements = {element: analyze_resistance(raw_current, raw_candidate, element) for element in RESIST_ELEMENTS}
    lost = [item["element"] for item in elements.values() if item.get("effective_cap_lost")]
    reached = [item["element"] for item in elements.values() if item.get("state") == CapState.CAP_REACHED.value]
    worsened = [item["element"] for item in elements.values() if item.get("deficit_worsened")]
    improved = [item["element"] for item in elements.values() if item.get("state") == CapState.BELOW_CAP_IMPROVED.value]
    elemental_worsened = [element for element in worsened if element in ELEMENTAL]
    return {
        "elements": elements,
        "any_cap_lost": bool(lost),
        "lost_elements": lost,
        "reached_elements": reached,
        "deficit_worsened_elements": worsened,
        "elemental_deficit_worsened": bool(elemental_worsened),
        "below_cap_improved_elements": improved,
        "flexibility_delta": round(sum(float(item.get("flexibility_delta") or 0.0) for item in elements.values()), 4),
    }
