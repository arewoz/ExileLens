"""M5.3 Build Priorities: the strongest MEASURED responses among the stats ExileLens tested.

Build Priorities are measured responses to a bounded probe catalog, not a claim that all possible PoE2 stats were tested.

Consumes `result["build_sensitivity"]` (M5.2) plus the existing audit `needs` and M5.1 requirement facts. It runs no probe
and makes no PoB call. There is deliberately NO universal score: each lane is ordered by one native measured axis at the
exact tested increment, which is always shown beside the response. Nothing here reads `profile_dependent`, `score_delta`,
Build Value, a value profile or SearchIntent tiers, so the payload is identical for every scoring profile.
"""

from __future__ import annotations

from typing import Any, Mapping

from exilelens.analysis.fingerprint import MEASURED
from exilelens.analysis.identity import AnalysisBaseline
from exilelens.analysis.sensitivity import is_sensitivity_stale

SCHEMA_VERSION = 1
MAX_ROWS_PER_LANE = 3
RESPONSE_EPSILON = 0.05  # percent; below this a response is not shown as a priority
MEANINGFUL_PERCENT = 1.0  # percent; an axis counts toward a multi-axis row at or above this

# Native response axes, grouped so "multi-axis" means different KINDS of effect (offense / defence / resource / mobility),
# not merely a defence probe raising several defence numbers.
_GROUPS = {
    "offense": "offense",
    "ehp": "defence", "max_hit": "defence", "life": "defence", "energy_shield": "defence", "armour": "defence", "evasion": "defence",
    "mana": "resource",
    "movement": "mobility",
}
_AXIS_LABELS = {
    "offense": "Damage", "ehp": "EHP", "max_hit": "Max Hit", "life": "Life", "energy_shield": "ES", "armour": "Armour",
    "evasion": "Evasion", "mana": "Mana", "movement": "Movement",
}
_DEFENCE_DETAILS = ("life", "energy_shield", "armour", "evasion")
_ELEMENT_NAMES = {"fire": "Fire", "cold": "Cold", "lightning": "Lightning", "chaos": "Chaos"}
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
# Baseline facts that are breakpoints/deficits. Probe-derived needs (OFFENSE_/MOVEMENT_OPPORTUNITY) are score based: excluded.
# RESOURCE_PRESSURE is deliberately NOT here: PoB's cost-per-second assumes uninterrupted use at full speed against passive
# regeneration, which most working builds exceed (M5.4: 12/18). It stays in the audit/SearchIntent untouched and is reported
# as `resource_context`; FIX FIRST only states a hard fact (the pool cannot pay for one use).
_NEED_CODES = ("RES_CAP_MISSING", "LOW_CHAOS_RES")


def _percent(signal: Mapping[str, Any], axis: str) -> float | None:
    value = ((signal.get("response") or {}).get(axis) or {}).get("percent")
    return None if value is None else float(value)


def _tested_change(signal: Mapping[str, Any]) -> str:
    probe = signal.get("probe") or {}
    line = str(probe.get("line") or "").strip()
    if line:
        return line
    magnitude = probe.get("magnitude")
    return f"+{magnitude:g} {signal.get('label')}" if isinstance(magnitude, (int, float)) else str(signal.get("label") or "")


def _is_resistance_signal(signal: Mapping[str, Any]) -> bool:
    return bool(signal.get("breakpoints")) or str(signal.get("probe_id") or "").endswith("_RES")


def _row(signal: Mapping[str, Any], axis: str, *, also: tuple[str, ...] = ()) -> dict[str, Any]:
    details = {
        _AXIS_LABELS[name]: round(_percent(signal, name), 2)
        for name in also
        if (_percent(signal, name) or 0.0) > RESPONSE_EPSILON
    }
    axis_row = (signal.get("response") or {}).get(axis) or {}
    row: dict[str, Any] = {
        "label": signal.get("label"),
        "tested_change": _tested_change(signal),
        "axis": axis,
        "response_percent": round(float(_percent(signal, axis)), 2),
        # Confidence follows the axis' own evidence (M5.2 sets it per axis where it can differ).
        "confidence": axis_row.get("confidence") or signal.get("confidence"),
        "evidence": MEASURED,
    }
    if details:
        row["also"] = details
    return row


def _lane(signals: list[Mapping[str, Any]], axis: str, *, also: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    candidates = [s for s in signals if (_percent(s, axis) or 0.0) > RESPONSE_EPSILON and not _is_resistance_signal(s)]
    # Stable sort: ties keep sensitivity (catalog) order. One native axis at the tested increment; no secondary scalar.
    candidates.sort(key=lambda s: -float(_percent(s, axis)))
    return [_row(s, axis, also=also) for s in candidates[:MAX_ROWS_PER_LANE]]


def _multi_axis(signals: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for signal in signals:
        if _is_resistance_signal(signal):
            continue
        meaningful = [a for a in _GROUPS if (_percent(signal, a) or 0.0) >= MEANINGFUL_PERCENT]
        if len({_GROUPS[a] for a in meaningful}) < 2:
            continue
        shown = {_AXIS_LABELS[a]: round(float(_percent(signal, a)), 2) for a in _GROUPS if (_percent(signal, a) or 0.0) > RESPONSE_EPSILON}
        rows.append(
            {
                "label": signal.get("label"),
                "tested_change": _tested_change(signal),
                "responses": shown,
                "confidence": signal.get("confidence"),
                "evidence": MEASURED,
            }
        )
    return rows[:MAX_ROWS_PER_LANE]


def _pinned_resistances(signals_all: list[Mapping[str, Any]], needs: Any) -> set[str]:
    """Below-cap elements whose resistance PoB demonstrably did not move when the probe was applied (pinned/overridden).

    A capped resistance also shows no response to more resistance, so only an element the audit reports below cap counts."""
    below_cap = {str(n.get("metric") or "").replace("_res", "") for n in needs or [] if n.get("code") in _NEED_CODES}
    pinned: set[str] = set()
    for signal in signals_all:
        probe_id = str(signal.get("probe_id") or "")
        if probe_id.endswith("_RES") and signal.get("status") == "NO_SIGNAL" and signal.get("applied") and signal.get("own_resistance_delta") == 0:
            element = probe_id.replace("_RES", "").lower()
            if element in below_cap:
                pinned.add(element)
    return pinned


def _resource_rows(result: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mana = ((result.get("build_fingerprint") or {}).get("resources") or {}).get("mana") or {}

    def value(key: str) -> float | None:
        v = (mana.get(key) or {}).get("value")
        return None if v is None else float(v)

    pool, per_use = value("unreserved"), value("cost_per_use")
    rows: list[dict[str, Any]] = []
    if pool is not None and per_use and per_use > 0 and pool < per_use:
        rows.append({"kind": "RESOURCE", "title": "Mana pool", "detail": "Unreserved mana is smaller than the cost of one use of the main skill", "severity": "critical", "source": "fingerprint"})
    context: dict[str, Any] = {}
    deficit = value("continuous_use_deficit_per_second")
    if deficit and pool:
        context["mana"] = {
            "continuous_use_deficit_per_second": deficit,
            "seconds_to_empty_unreserved_pool": round(pool / deficit, 1),
            "recovery_includes_leech": value("leech_gain_per_second") is not None,
            "assumption": "PoB assumes uninterrupted use at full speed; flasks and burst/idle patterns are not modelled",
        }
    return rows, context


def _fix_first(result: Mapping[str, Any], signals_all: list[Mapping[str, Any]], pinned: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    exact: dict[str, float] = {}
    for signal in signals_all:
        for bp in signal.get("breakpoints") or []:
            if bp.get("required_increment") is not None and bp.get("element") and bp.get("status") == MEASURED:
                exact.setdefault(str(bp["element"]), float(bp["required_increment"]))
    for need in result.get("needs") or []:
        code = need.get("code")
        if code not in _NEED_CODES:
            continue
        severity = str(need.get("severity") or "medium")
        element = str(need.get("metric") or "").replace("_res", "")
        if element in pinned:
            continue  # raising it is impossible by gear (pinned/overridden); reported in coverage, not as an actionable fix
        increment = exact.get(element, need.get("deficit"))
        if increment is None:
            continue
        rows.append(
            {
                "kind": "RESISTANCE_CAP",
                "title": f"{_ELEMENT_NAMES.get(element, element.title())} Resistance",
                "detail": f"+{float(increment):g}% reaches cap",
                "severity": severity,
                "source": "sensitivity" if element in exact else "audit",
            }
        )
    for name, state in ((((result.get("build_fingerprint") or {}).get("requirements")) or {}).items()):
        if (state.get("state") or {}).get("value") == "DEFICIT":
            margin = abs(float((state.get("margin") or {}).get("value") or 0.0))
            rows.append({"kind": "ATTRIBUTE_REQUIREMENT", "title": name.title(), "detail": f"{margin:g} short of the highest requirement", "severity": "critical", "source": "fingerprint"})
    rows.extend(_resource_rows(result)[0])
    # Existing severity first, then deterministic source order (sort is stable). No numeric priority.
    rows.sort(key=lambda r: _SEVERITY_ORDER.get(r["severity"], 9))
    return rows


def build_priorities(result: Mapping[str, Any]) -> dict[str, Any]:
    """Build Priorities from one analysis result (needs `build_sensitivity`). Zero PoB work, profile independent."""
    sensitivity = result.get("build_sensitivity") or {}
    signals_all = list(sensitivity.get("signals") or [])
    measured = [s for s in signals_all if s.get("status") == MEASURED]
    context = dict(sensitivity.get("offense_context") or {})
    limited = str(context.get("confidence") or "").upper() == "LOW"

    lanes = {
        "offense": _lane(measured, "offense"),
        "ehp": _lane(measured, "ehp", also=_DEFENCE_DETAILS),
        "max_hit": _lane(measured, "max_hit", also=_DEFENCE_DETAILS),
        "mobility": _lane(measured, "movement"),
    }
    counts = dict((sensitivity.get("coverage") or {}).get("counts") or {})
    pinned = _pinned_resistances(signals_all, result.get("needs"))
    resource_context = _resource_rows(result)[1]
    return {
        "schema_version": SCHEMA_VERSION,
        "identity": dict(sensitivity.get("identity") or {}),
        "offense_context": context,
        "offense_limited_confidence": limited,
        "fix_first": _fix_first(result, signals_all, pinned),
        "resource_context": resource_context,
        **lanes,
        "multi_axis": _multi_axis(measured),
        "coverage": {
            "signals_considered": len(measured),
            "counts": counts,
            "no_signal": [s.get("label") for s in signals_all if s.get("status") == "NO_SIGNAL"],
            "not_established": [s.get("label") for s in signals_all if s.get("status") in {"REJECTED", "UNSUPPORTED", "RESTORE_FAILED", "INVALID"}],
            "lanes_without_response": [name for name, rows in lanes.items() if not rows],
            "resistance_pinned": sorted(pinned),
            "axes_not_captured": list((sensitivity.get("coverage") or {}).get("axes_not_captured") or []),
            "basis": "Based on stats ExileLens tested against this PoB build.",
        },
    }


def is_priorities_stale(priorities: Mapping[str, Any], current: AnalysisBaseline) -> bool:
    """Same baseline binding as the fingerprint and sensitivity; a value-profile-only change is never stale."""
    return is_sensitivity_stale(priorities, current)


def format_priorities(priorities: Mapping[str, Any]) -> str:
    """Player-facing text. Shows the tested change next to each response; never probe ids, hashes or Build Value."""
    lines = ["BUILD PRIORITIES", "Strongest measured responses among tested stats.", ""]
    if priorities.get("fix_first"):
        lines.append("FIX FIRST")
        for row in priorities["fix_first"]:
            lines.append(f"  {row['title']}")
            lines.append(f"    {row['detail']}")
        lines.append("")

    def lane(title: str, key: str, limited: bool = False) -> None:
        rows = priorities.get(key) or []
        if not rows:
            return
        lines.append(f"{title} — limited confidence" if limited else title)
        for row in rows:
            extra = ""
            if row.get("also"):
                extra = "   (" + " · ".join(f"{name} {value:+g}%" for name, value in row["also"].items()) + ")"
            lines.append(f"  {row['tested_change']:<34}{row['response_percent']:+.1f}%{extra}")
        lines.append("")

    lane("DAMAGE", "offense", bool(priorities.get("offense_limited_confidence")))
    lane("EHP", "ehp")
    lane("MAX HIT", "max_hit")
    lane("MOVEMENT", "mobility")
    multi = priorities.get("multi_axis") or []
    if multi:
        lines.append("MULTI-IMPACT")
        for row in multi:
            lines.append(f"  {row['tested_change']}")
            lines.append("    " + " · ".join(f"{name} {value:+g}%" for name, value in row["responses"].items()))
        lines.append("")
    if len(lines) <= 4:
        lines.append("No measured response among the tested stats.")
        lines.append("")
    lines.append(str((priorities.get("coverage") or {}).get("basis") or "Based on stats ExileLens tested against this PoB build."))
    return "\n".join(lines)
