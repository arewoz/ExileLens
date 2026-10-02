"""R1 player-facing view of one `analyze_build()` result.

Presentation only: it reads `build_priorities` / `strongest_responses` / the fingerprint identity and turns them into
the words and grouping the Analyze Build page shows. It measures nothing, ranks nothing and reads no value profile.
Internal vocabulary (probe ids, status enums, cache counters, hashes) never leaves this module; the status words are the
ones in `strongest.STATUS_LABELS`.
"""

from __future__ import annotations

from typing import Any, Mapping

from exilelens.analysis.strongest import MEASURED, NOT_PER_POINT, STATUS_LABELS, strongest_responses

_MAX_LISTED = 8
_URGENCY = {"critical": "Critical", "high": "Important", "medium": "Worth fixing", "low": "Minor"}
_NOT_SUPPORTED = {
    "life_regen": "Life regeneration",
    "energy_shield_regen": "Energy Shield regeneration",
    "mana_sustain_numbers": "Mana sustain",
}
_LANES = (("offense", "DAMAGE", "Damage"), ("ehp", "EHP", "EHP"), ("max_hit", "MAX HIT", "Max Hit"), ("mobility", "MOVEMENT", "Movement"))
_STAGES = {"audit": "Reading your build", "starting": "Starting"}


def percent(value: Any) -> str:
    return f"{float(value):+.1f}%"


def _names(labels: list[Any]) -> str:
    names = [str(label) for label in labels if label]
    shown = ", ".join(names[:_MAX_LISTED])
    return f"{shown} and {len(names) - _MAX_LISTED} more" if len(names) > _MAX_LISTED else shown


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _tile(key: str, caption: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    if entry.get("status") != MEASURED:
        return {"key": key, "caption": caption, "value": "—", "change": STATUS_LABELS.get(str(entry.get("status")), ""), "measured": False}
    if "responses" in entry:
        value = " · ".join(f"{name} {percent(amount)}" for name, amount in entry["responses"].items())
    else:
        value = percent(entry["response_percent"])
    note = ""
    if entry.get("limited_confidence"):
        note = "Limited confidence"
    elif entry.get("tied_with"):
        note = "Tied with " + _join([str(name) for name in entry["tied_with"]])
    return {"key": key, "caption": caption, "value": value, "change": str(entry.get("tested_change") or ""), "note": note, "measured": True}


def _tiles(strongest: Mapping[str, Any]) -> list[dict[str, Any]]:
    damage, ehp, max_hit = strongest.get("damage") or {}, strongest.get("ehp") or {}, strongest.get("max_hit") or {}
    tiles = [_tile("damage", "DAMAGE", damage)]
    same_change = ehp.get("status") == MEASURED == max_hit.get("status") and ehp.get("tested_change") == max_hit.get("tested_change")
    if same_change:
        # One stat is the strongest response on both defensive axes: say it once, with both measured numbers.
        merged = _tile("ehp_max_hit", "EHP · MAX HIT", ehp)
        merged["value"] = f"{percent(ehp['response_percent'])} · {percent(max_hit['response_percent'])}"
        tiles.append(merged)
    else:
        tiles.append(_tile("ehp", "EHP", ehp))
        tiles.append(_tile("max_hit", "MAX HIT", max_hit))
    tiles.append(_tile("movement", "MOVEMENT", strongest.get("movement") or {}))
    tiles.append(_tile("multi_impact", "MULTI-IMPACT", strongest.get("multi_impact") or {}))
    return tiles


def _lanes(priorities: Mapping[str, Any]) -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    for key, title, _label in _LANES:
        rows = priorities.get(key) or []
        if not rows:
            continue  # an empty lane is reported once, in coverage; it never renders as an empty section
        lanes.append({
            "key": key,
            "title": title,
            "note": "Limited confidence in this build's damage number" if key == "offense" and priorities.get("offense_limited_confidence") else "",
            "rows": [
                {
                    "change": str(row.get("tested_change") or ""),
                    "response": percent(row["response_percent"]),
                    "also": " · ".join(f"{name} {percent(amount)}" for name, amount in (row.get("also") or {}).items()),
                }
                for row in rows
            ],
        })
    multi = priorities.get("multi_axis") or []
    if multi:
        lanes.append({
            "key": "multi_axis",
            "title": "MULTI-IMPACT",
            "note": "One tested stat that moves more than one kind of result",
            "rows": [
                {"change": str(row.get("tested_change") or ""), "response": "",
                 "also": " · ".join(f"{name} {percent(amount)}" for name, amount in (row.get("responses") or {}).items())}
                for row in multi
            ],
        })
    return lanes


def _coverage(result: Mapping[str, Any], priorities: Mapping[str, Any]) -> list[str]:
    coverage = priorities.get("coverage") or {}
    lines: list[str] = []
    measured = int(coverage.get("signals_considered") or 0)
    lines.append(f"{STATUS_LABELS[MEASURED]}: {measured} tested stat change{'s' if measured != 1 else ''} moved this build.")
    # A capped resistance shows no response to more of it. That is a different message from "this stat does nothing".
    resistances = ((result.get("build_fingerprint") or {}).get("defense") or {}).get("resistances") or {}
    capped = {
        f"{str(element).title()} Resistance"
        for element, row in resistances.items()
        if ((row or {}).get("state") or {}).get("value") in {"CAPPED", "OVER_CAPPED"}
    }
    pinned_names = [str(name).title() for name in coverage.get("resistance_pinned") or []]
    pinned_labels = {f"{name} Resistance" for name in pinned_names}
    at_cap = [label for label in coverage.get("no_signal") or [] if label in capped]
    flat = [label for label in coverage.get("no_signal") or [] if label not in capped and label not in pinned_labels]
    if flat:
        lines.append(f"{STATUS_LABELS['NO_MEASURABLE_RESPONSE']}: {_names(flat)}.")
    if at_cap:
        lines.append(f"Already at cap, so more does nothing: {_join([str(label) for label in at_cap])}.")
    if coverage.get("not_established"):
        reasons = {str(row.get("reason")) for row in result.get("skipped") or [] if isinstance(row, Mapping)}
        why = " Path of Building does not apply test stats added to this build's equipped items." if "carrier_ignores_probe_mods" in reasons else ""
        lines.append(f"{STATUS_LABELS['COULD_NOT_ESTABLISH']}: {_names(coverage['not_established'])}.{why}")
    elif not measured and not coverage.get("no_signal"):
        lines.append(f"{STATUS_LABELS['COULD_NOT_ESTABLISH']}: no equipped ring, amulet, belt or armour piece could carry the test stats.")
    if pinned_names:
        verb, it = ("are", "them") if len(pinned_names) > 1 else ("is", "it")
        lines.append(f"{_join(pinned_names)} Resistance {verb} fixed by an equipped item, so gear cannot raise {it}.")
    unsupported = [_NOT_SUPPORTED.get(str(name), str(name).replace("_", " ")) for name in coverage.get("axes_not_captured") or []]
    if unsupported:
        lines.append(f"{STATUS_LABELS['NOT_SUPPORTED']}: {_join(unsupported)} responses.")
    return lines


def _details(result: Mapping[str, Any], priorities: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    owner = str((priorities.get("offense_context") or {}).get("owner") or "")
    if owner:
        lines.append("Damage is measured on " + ("your minions' main skill." if owner == "MINION" else "your main skill."))
    mana = (priorities.get("resource_context") or {}).get("mana") or {}
    if mana:
        lines.append(
            f"Mana at nonstop full-speed use lasts about {float(mana['seconds_to_empty_unreserved_pool']):g} s. "
            "Path of Building assumes uninterrupted use; flasks and pauses are not modelled, so this is context, not a problem."
        )
    perf = result.get("performance") or {}
    if perf:
        lines.append(f"Tested in {float(perf.get('elapsed_ms') or 0) / 1000:.1f} s with {int(perf.get('pob_recalcs') or 0)} Path of Building calculations.")
    lines.append("Each stat was tested once at the amount shown. Results are measured responses, not a claim that every possible stat was tested.")
    return lines


def build_analysis_view(result: Mapping[str, Any]) -> dict[str, Any]:
    """Everything the Analyze Build page renders for one result. Pure; safe on partial results."""
    priorities = result.get("build_priorities") or {}
    strongest = result.get("strongest_responses") or strongest_responses(priorities)
    baseline = result.get("baseline") or {}
    skill = ((result.get("build_fingerprint") or {}).get("identity") or {}).get("primary_skill")
    return {
        "has_priorities": bool(priorities),
        "build": {
            "name": str(baseline.get("build_name") or "") or "Loaded build",
            "main_skill": str(skill or ""),
            "loadout": str(baseline.get("loadout") or ""),
            "context": str(baseline.get("context") or ""),
        },
        "basis": str(strongest.get("basis") or ""),
        "caveat": NOT_PER_POINT,
        "tiles": _tiles(strongest) if priorities else [],
        "fix_first": [
            {"title": str(row.get("title") or ""), "detail": str(row.get("detail") or ""), "urgency": _URGENCY.get(str(row.get("severity")), "")}
            for row in priorities.get("fix_first") or []
        ],
        "lanes": _lanes(priorities),
        "coverage": _coverage(result, priorities) if priorities else [],
        "coverage_basis": str((priorities.get("coverage") or {}).get("basis") or ""),
        "details": _details(result, priorities) if priorities else [],
    }


def progress_text(payload: Mapping[str, Any], labels: Mapping[str, str] | None = None) -> str:
    """One player line for a running analysis (never a probe id or an internal stage name)."""
    stage = str(payload.get("stage") or "")
    if stage == "probe":
        name = (labels or {}).get(str(payload.get("probe_id") or ""), "")
        return f"Testing {name}" if name else "Testing stats"
    if stage == "slot":
        slot = str(payload.get("slot") or "").replace("_", " ").title()
        return f"Checking {slot}" if slot else "Checking equipped items"
    return _STAGES.get(stage, "Working")
