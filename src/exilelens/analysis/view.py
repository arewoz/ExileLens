"""R1 player-facing view of one `analyze_build()` result.

Presentation only: it reads `build_priorities` / `strongest_responses` / the fingerprint identity and turns them into
the words and grouping the Analyze Build page shows. It measures nothing, ranks nothing and reads no value profile.
Internal vocabulary (probe ids, status enums, cache counters, hashes) never leaves this module; the status words are the
ones in `strongest.STATUS_LABELS`.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from exilelens.analysis.priorities import MEANINGFUL_PERCENT
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


_SHORT_FORMS = (
    (re.compile(r"^\+1 to Level of all (.+) Skills$"), r"+1 \1 Skill Level"),
    (re.compile(r"^\+(\d+) to Level of all (.+) Skills$"), r"+\1 \2 Skill Levels"),
    (re.compile(r"^Minions have (\d+)% increased (.+)$"), r"\1% Minion \2"),
    (re.compile(r"^(\d+(?:\.\d+)?)% increased (.+)$"), r"\1% \2"),
    (re.compile(r"^\+(\d+) to maximum (.+)$"), r"+\1 \2"),
    (re.compile(r"^\+(\d+)(%?) to (.+)$"), r"+\1\2 \3"),
)


def short_change(tested_change: Any) -> str:
    """The tested change in card length: same stat, same increment, fewer words (`+1 Spell Skill Level`)."""
    text = str(tested_change or "").strip()
    for pattern, form in _SHORT_FORMS:
        if pattern.match(text):
            return pattern.sub(form, text)
    return text


def display_name(name: Any) -> str:
    """A build name fit for a header: a file path collapses to its file name without the extension."""
    text = str(name or "").strip()
    if "\\" in text or "/" in text or text.lower().endswith(".xml"):
        text = re.split(r"[\\/]", text)[-1]
        text = re.sub(r"\.xml$", "", text, flags=re.I)
    return text


def _tile(key: str, caption: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    if entry.get("status") != MEASURED:
        # An axis nothing moved is a finding, not a failure; a multi-impact stat simply may not exist for a build.
        if key == "multi_impact" and entry.get("status") == "NO_MEASURABLE_RESPONSE":
            return {"key": key, "caption": caption, "value": "", "change": "No multi-impact stat measured", "measured": False}
        return {"key": key, "caption": caption, "value": "—", "change": STATUS_LABELS.get(str(entry.get("status")), ""), "measured": False}
    if "responses" in entry:
        value = " · ".join(f"{name} {percent(amount)}" for name, amount in entry["responses"].items())
    else:
        value = percent(entry["response_percent"])
    note = ""
    if entry.get("limited_confidence"):
        note = "Limited confidence"
    elif entry.get("tied_with"):
        note = "Tied: " + ", ".join(short_change(name) for name in entry["tied_with"])
    full = str(entry.get("tested_change") or "")
    return {"key": key, "caption": caption, "value": value, "change": short_change(full), "tested_change": full, "note": note, "measured": True}


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
            "name": display_name(baseline.get("build_name")) or display_name(baseline.get("build_path")) or "Loaded build",
            "source_path": str(baseline.get("build_path") or ""),
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


# ----------------------------------------------------------------------- slot view
#
# The slot ordering and its 0-100 number are the existing opportunity heuristic (`analysis.opportunity`): a sum of
# need bumps, the best profile-scored test on the slot and how little the current item contributes. It is an ordering
# aid, not a measurement and not a claim that the slot is the best upgrade, so the page shows its band in words and
# keeps the number, Build Value, reason codes and the Search Intent tiers for the measurement details.

_ELEMENTS = {"fire": "Fire", "cold": "Cold", "lightning": "Lightning", "chaos": "Chaos"}
_BAND_WORDS = {"VERY HIGH": "Very high opportunity", "HIGH": "High opportunity", "MEDIUM": "Medium opportunity", "LOW": "Low opportunity"}
_LIMITED = "Weapon analysis is currently limited."
_MAX_SLOT_STATS = 6
_REPAIR = re.compile(r"missing (\w+) res(?: \+([\d.]+) to cap)?")
_AXIS_WORDS = (("offense", "damage"), ("ehp", "EHP"), ("max_hit", "Max Hit"), ("mobility", "movement"))


def slot_label(product_slot: Any) -> str:
    return str(product_slot or "").replace("_", " ").title()


def slot_row_text(slot: Mapping[str, Any]) -> str:
    """One row of the UPGRADE OPPORTUNITIES list: the slot and its band in words. Never the internal number."""
    opportunity = slot.get("opportunity") or {}
    if slot.get("analysis_limited") or opportunity.get("analysis_limited"):
        return f"{slot_label(slot.get('product_slot'))} — Limited analysis"
    band = _BAND_WORDS.get(str(opportunity.get("band") or "").upper(), "")
    return f"{slot_label(slot.get('product_slot'))} — {band}" if band else slot_label(slot.get("product_slot"))


def _strong_axes(priorities: Mapping[str, Any], label: str) -> list[str]:
    return [
        word for lane, word in _AXIS_WORDS
        if any(row.get("label") == label and float(row.get("response_percent") or 0.0) >= MEANINGFUL_PERCENT for row in priorities.get(lane) or [])
        and not (lane == "offense" and priorities.get("offense_limited_confidence"))
    ]


def _driver_text(driver: Mapping[str, Any], priorities: Mapping[str, Any]) -> str:
    """One opportunity driver in player words. Only what the driver itself establishes is said."""
    kind, text = str(driver.get("kind") or ""), str(driver.get("text") or "")
    if kind == "critical":
        match = _REPAIR.search(text)
        if match:
            needed = f" (+{float(match.group(2)):g}% needed)" if match.group(2) else ""
            return f"Can cap {_ELEMENTS.get(match.group(1), match.group(1).title())} Resistance{needed}"
        return "Can fix an urgent build problem"
    if kind == "high":
        return "Can help cap Chaos Resistance" if driver.get("code") == "LOW_CHAOS_RES" else "Can help with a build problem"
    if kind == "marginal":
        label = text.replace(" has high marginal value", "")
        axes = _strong_axes(priorities, label)
        if axes:
            return f"{label} is among this build's strongest measured {' / '.join(axes)} responses"
        return f"{label} is valuable for this build"
    if kind == "breakpoint":
        return f"More {text.replace(' crosses a breakpoint', '')} reaches its cap"
    if kind == "contribution":
        return "Your current item adds little damage" if "little" in text else "Your current item adds only modest damage"
    if kind == "note":
        return "This slot already performs well"
    return ""


def _intent_stat(row: Mapping[str, Any]) -> str:
    name = str(row.get("display_name") or "")
    if name:
        return name
    stat = str(row.get("stat") or "")
    if stat.endswith("_res"):
        return f"{_ELEMENTS.get(stat[:-4], stat[:-4].title())} Resistance"
    return stat.replace("_", " ").title()


def _measured_line(probe: Mapping[str, Any]) -> str:
    """A tested stat worth showing by default: it moved damage or EHP meaningfully, or it reaches a cap."""
    change = short_change(probe.get("line") or probe.get("display_name"))
    parts = [
        f"{name} {percent(value)}"
        for name, value in (("Damage", probe.get("offense_percent")), ("EHP", probe.get("ehp_percent")))
        if value is not None and abs(float(value)) >= MEANINGFUL_PERCENT
    ]
    if any(event.get("code") == "CAP_REACHED" for event in probe.get("breakpoints") or []):
        parts.append("reaches the resistance cap")
    return f"{change} → {' · '.join(parts)}" if parts else ""


def _slot_details(result: Mapping[str, Any], slot: Mapping[str, Any]) -> list[str]:
    """Everything technical about one slot, for the measurement details toggle. Nothing here is removed, only moved."""
    opportunity = slot.get("opportunity") or {}
    intent = slot.get("search_intent") or {}
    lines = [f"Opportunity ordering: {opportunity.get('band')} {opportunity.get('score') if opportunity.get('score') is not None else '—'} "
             "(internal 0-100 heuristic used to order slots; not a measurement)"]
    lines += [f"Driver: {driver.get('text')}" for driver in opportunity.get("drivers") or []]
    for probe in slot.get("probes") or []:
        if probe.get("status") in {"ok", "NO_SIGNAL"} and probe.get("slot_compatible"):
            lines.append(
                f"{probe.get('line') or probe.get('display_name')} → Damage {float(probe.get('offense_percent') or 0):+.1f}%"
                f" · EHP {float(probe.get('ehp_percent') or 0):+.1f}% · Build Value {float(probe.get('score_delta') or 0):+.1f}"
            )
    for tier in ("required", "high_value", "useful", "low_value", "avoid"):
        names = ", ".join(str(row.get("display_name") or row.get("stat") or "?") for row in intent.get(tier) or []) or "—"
        lines.append(f"Search Intent {tier}: {names}")
    source = str((result.get("baseline") or {}).get("build_path") or "")
    if source:
        lines.append(f"Build file: {source}")
    return lines


def build_slot_view(result: Mapping[str, Any], slot: Mapping[str, Any]) -> dict[str, Any]:
    """Product guidance for one equipped slot from the existing analysis data. Pure; invents no reason."""
    priorities = result.get("build_priorities") or {}
    opportunity = slot.get("opportunity") or {}
    intent = slot.get("search_intent") or {}
    item = slot.get("current_item") or {}
    limited = bool(slot.get("analysis_limited") or opportunity.get("analysis_limited"))
    why: list[str] = []
    for driver in opportunity.get("drivers") or []:
        text = "" if limited else _driver_text(driver, priorities)
        if text and text not in why:
            why.append(text)
    useful: list[str] = []
    for tier in ("required", "high_value", "useful"):
        for row in intent.get(tier) or []:
            name = _intent_stat(row)
            if name and name not in useful:
                useful.append(name)
    measured = [line for line in (_measured_line(p) for p in slot.get("probes") or [] if p.get("status") == "ok" and p.get("slot_compatible")) if line]
    return {
        "slot": slot_label(slot.get("product_slot")),
        "item_name": str(item.get("name") or "") or "Unnamed item",
        "item_base": str(item.get("base_name") or ""),
        "summary": "Limited analysis" if limited else _BAND_WORDS.get(str(opportunity.get("band") or "").upper(), ""),
        "why": why,
        "useful_stats": useful[:_MAX_SLOT_STATS],
        "measured": measured[:_MAX_SLOT_STATS],
        "limitations": [_LIMITED] if limited else [],
        "details": _slot_details(result, slot),
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
