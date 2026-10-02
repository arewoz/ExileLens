"""R1 strongest measured responses ("Highest-Return Stat"): the head of each Build Priorities lane.

Pure derivation from `build_priorities` (M5.3). No probe is run, no PoB call is made, no ranking is recomputed: a lane's
first row is already the strongest measured response on that lane's one native axis.

There is deliberately NO per-point value. The tested changes are not equal sized (+1 Skill Level, 10% Cast Speed,
+20 Intelligence, +50 Energy Shield), so every entry keeps its tested change and the wording is always "strongest
measured response among the tested stat changes", never "best stat". Profile independent because priorities are.
"""

from __future__ import annotations

from typing import Any, Mapping

from exilelens.analysis.priorities import _AXIS_LABELS, _GROUPS, MEANINGFUL_PERCENT

SCHEMA_VERSION = 1

MEASURED = "MEASURED"
NO_MEASURABLE_RESPONSE = "NO_MEASURABLE_RESPONSE"
COULD_NOT_ESTABLISH = "COULD_NOT_ESTABLISH"

#: Player-facing words for every state this module or the coverage summary can report.
STATUS_LABELS = {
    MEASURED: "Measured",
    NO_MEASURABLE_RESPONSE: "No measurable response",
    COULD_NOT_ESTABLISH: "Could not establish",
    "NOT_SUPPORTED": "Not currently supported",
}

BASIS = "Strongest measured response among the tested stat changes."
NOT_PER_POINT = "Tested amounts differ between stats, so this is not a per-point comparison."

#: (entry key, priorities lane, player label). Order is the display order.
LANES = (
    ("damage", "offense", "Damage"),
    ("ehp", "ehp", "EHP"),
    ("max_hit", "max_hit", "Max Hit"),
    ("movement", "mobility", "Movement"),
)

_LABEL_KIND = {_AXIS_LABELS[axis]: kind for axis, kind in _GROUPS.items()}


def _shown(value: Any) -> str:
    """The precision a response is displayed at; two responses that display alike are reported as tied."""
    return f"{float(value):+.1f}"


def _empty(priorities: Mapping[str, Any]) -> str:
    coverage = priorities.get("coverage") or {}
    applied = int(coverage.get("signals_considered") or 0) + len(coverage.get("no_signal") or [])
    return NO_MEASURABLE_RESPONSE if applied else COULD_NOT_ESTABLISH


def _lane_entry(priorities: Mapping[str, Any], lane: str, label: str) -> dict[str, Any]:
    rows = list(priorities.get(lane) or [])
    if not rows:
        return {"status": _empty(priorities), "axis_label": label}
    top = rows[0]
    entry: dict[str, Any] = {
        "status": MEASURED,
        "axis_label": label,
        "label": top.get("label"),
        "tested_change": top.get("tested_change"),
        "response_percent": top.get("response_percent"),
        "confidence": top.get("confidence"),
    }
    if top.get("also"):
        entry["also"] = dict(top["also"])
    # Lane order is the M5.3 one (measured response, exact ties in catalog order). A runner-up that displays the same
    # response is named instead of being silently beaten by a rounding-level difference.
    tied = [row.get("tested_change") for row in rows[1:] if _shown(row.get("response_percent")) == _shown(top.get("response_percent"))]
    if tied:
        entry["tied_with"] = tied
    if lane == "offense" and priorities.get("offense_limited_confidence"):
        entry["limited_confidence"] = True
    return entry


def _kinds(responses: Mapping[str, Any]) -> int:
    return len({_LABEL_KIND[name] for name, value in responses.items() if name in _LABEL_KIND and float(value) >= MEANINGFUL_PERCENT})


def _multi_impact(priorities: Mapping[str, Any]) -> dict[str, Any]:
    rows = list(priorities.get("multi_axis") or [])
    if not rows:
        return {"status": _empty(priorities), "axis_label": "Multi-impact"}
    # Breadth (how many kinds of effect respond), never a sum across axes: adding Damage % to EHP % would be exactly the
    # universal score M5 refuses to invent. Ties keep the M5.3 (catalog) order; `max` returns the first maximum.
    top = max(rows, key=lambda row: _kinds(row.get("responses") or {}))
    return {
        "status": MEASURED,
        "axis_label": "Multi-impact",
        "label": top.get("label"),
        "tested_change": top.get("tested_change"),
        "responses": dict(top.get("responses") or {}),
        "confidence": top.get("confidence"),
        "others": [row.get("tested_change") for row in rows if row is not top],
    }


def strongest_responses(priorities: Mapping[str, Any] | None) -> dict[str, Any]:
    """Strongest measured response per axis from one `build_priorities` payload. Zero PoB work."""
    priorities = priorities or {}
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "identity": dict(priorities.get("identity") or {}),
        "basis": BASIS,
        "caveat": NOT_PER_POINT,
    }
    for key, lane, label in LANES:
        out[key] = _lane_entry(priorities, lane, label)
    out["multi_impact"] = _multi_impact(priorities)
    return out


def entry_keys() -> tuple[str, ...]:
    return tuple(key for key, _lane, _label in LANES) + ("multi_impact",)


def format_entry(entry: Mapping[str, Any]) -> str:
    """One player line: the tested change, then what it measured. `+1 to Level of all Spell Skills → Damage +18.4%`."""
    if entry.get("status") != MEASURED:
        return STATUS_LABELS.get(str(entry.get("status")), STATUS_LABELS[COULD_NOT_ESTABLISH])
    if "responses" in entry:
        measured = " · ".join(f"{name} {_shown(value)}%" for name, value in entry["responses"].items())
    else:
        measured = f"{entry.get('axis_label')} {_shown(entry.get('response_percent'))}%"
    return f"{entry.get('tested_change')} → {measured}"
