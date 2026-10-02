"""R1 player-facing view of one `analyze_build()` result.

Presentation only: it reads `build_priorities` / `strongest_responses` / the fingerprint identity and turns them into
the words and grouping the Analyze Build page shows. It measures nothing, ranks nothing and reads no value profile.
Internal vocabulary (probe ids, status enums, cache counters, hashes) never leaves this module; the status words are the
ones in `strongest.STATUS_LABELS`.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from exilelens.analysis.actionable import HEALTH_LABELS, build_actionable
from exilelens.analysis.curves import STATE_LABELS as CURVE_STATE_LABELS
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
_STAGES = {"audit": "Reading your build", "starting": "Starting", "curves": "Checking how your top stats scale"}


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


# ------------------------------------------------------------------ R1.5 overview
#
# Wording for the actionable layer (`analysis.actionable`). Nothing is decided here: order, states and limits all come
# from that layer; this only chooses the words and the short forms.

_LADDER_TITLES = (("damage", "DAMAGE"), ("ehp", "EHP"), ("max_hit", "MAX HIT"), ("movement", "MOVEMENT"))
_HEALTH_TONE = {"NEEDS_ATTENTION": "warn", "NEARLY_CAPPED": "neutral", "OPPORTUNITY": "ok", "NO_URGENT_ISSUE": "neutral", "LIMITED": "muted"}


def _action_summary(action: Mapping[str, Any], ladders: Mapping[str, Any]) -> str:
    if action.get("kind") != "IMPROVE":
        return str(action.get("detail") or "")
    row = next(iter(ladders.get(str(action.get("axis"))) or []), None)
    if row is None:
        return str(action.get("detail") or "")
    return f"{row['label']} · {short_change(row['tested_change'])} → {percent(row['response_percent'])}"


def _curve_note(curve: Mapping[str, Any] | None) -> str:
    """`next step +9.6% · Response remains similar`: the second step in the same unit as the first, then its state."""
    if curve is None:
        return ""
    if curve.get("status") != MEASURED:
        return "more of it: could not establish"
    return f"next step {percent(curve['second_percent'])} · {CURVE_STATE_LABELS[str(curve['state'])]}"


def _curve_detail(curve: Mapping[str, Any]) -> str:
    if curve.get("status") != MEASURED:
        return f"{curve.get('label')} ({curve.get('axis_label')}): follow-up not established — {curve.get('reason')}."
    return (f"{curve['label']} ({curve['axis_label']}): {curve['tested_change']} → {percent(curve['first_percent'])}; "
            f"{curve['doubled_change']} → {percent(curve['total_percent'])}; second step {percent(curve['second_percent'])} "
            f"= {float(curve['ratio']):.2f} of the first step.")


def _actionable_view(actionable: Mapping[str, Any]) -> dict[str, Any]:
    if not actionable:
        return {"has_actionable": False}
    ladders = actionable.get("ladders") or {}
    curves = {(str(c.get("label")), str(c.get("axis"))): c for c in actionable.get("response_curves") or []}
    axis_of = {"damage": "offense", "ehp": "ehp", "max_hit": "max_hit"}
    focus = actionable.get("current_focus") or {}
    best = actionable.get("best_response") or {}
    coverage = actionable.get("coverage") or {}
    return {
        "has_actionable": True,
        "focus": {"title": str(focus.get("title") or "CURRENT FOCUS"), "headline": str(focus.get("headline") or ""),
                  "detail": str(focus.get("detail") or ""), "issue": focus.get("kind") == "ISSUE"},
        "actions": [
            {"number": action["number"], "title": str(action["title"]), "summary": _action_summary(action, ladders),
             # Only a critical or material problem is emphasised; a nearly capped resistance reads like any other line.
             "fix": action["kind"] == "FIX" and action.get("severity") != "MINOR"}
            for action in actionable.get("action_plan") or []
        ],
        "best": ({"measured": True, "value": percent(best["response_percent"]), "change": short_change(best["tested_change"]),
                  "tested_change": str(best["tested_change"])}
                 if best.get("status") == MEASURED else {"measured": False, "value": "—", "change": str(best.get("reason") or "Could not establish")}),
        "health": [
            {"title": str(row["title"]), "state": HEALTH_LABELS[str(row["state"])], "tone": _HEALTH_TONE[str(row["state"])], "reason": str(row["reason"])}
            for row in actionable.get("build_health") or []
        ],
        "ladders": [
            {"key": key, "title": title, "rows": [
                {"position": row["position"], "change": str(row["tested_change"]), "response": percent(row["response_percent"]),
                 "curve": _curve_note(curves.get((str(row["label"]), axis_of.get(key, ""))))}
                for row in ladders.get(key) or []]}
            for key, title in _LADDER_TITLES if ladders.get(key)
        ],
        "packages": [
            {"title": str(package["title"]), "stats": [
                {"change": str(stat["tested_change"]),
                 "evidence": str(stat["evidence"]) + (f" · also moves {_join([str(axis) for axis in stat['also']])}" if stat.get("also") else "")}
                for stat in package["stats"]]}
            for package in actionable.get("stat_packages") or [] if package["stats"]  # an emptied Hybrid is not shown
        ],
        "package_details": [
            f"{package['title'].title()} (all multi-impact stats): " + "; ".join(f"{stat['tested_change']} → {stat['evidence']}" for stat in package["all_stats"])
            for package in actionable.get("stat_packages") or [] if package.get("all_stats")
        ],
        "changes": [str(item["text"]) for item in (actionable.get("changes") or {}).get("items") or []],
        "coverage_summary": {"label": str(coverage.get("label") or ""), "summary": str(coverage.get("summary") or ""),
                             "notes": [str(note) for note in coverage.get("notes") or []]},
        "curve_details": [_curve_detail(curve) for curve in actionable.get("response_curves") or []],
        "breakpoint_details": [f"{row['title']}: {row['text']}" for row in actionable.get("breakpoints") or []],
    }


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
        # R1.5: the actionable layer is pure, so a result that predates it (or a test fixture) is completed here.
        **_actionable_view(result.get("actionable") or build_actionable(result)),
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


_STANDOUT_BANDS = ("VERY HIGH", "HIGH")


def slot_row_texts(slots: list[Mapping[str, Any]]) -> list[str]:
    """Rows of the UPGRADE OPPORTUNITIES list, in the given (existing) order. Never the internal number.

    A row is just the slot name. A qualifier appears only when it says something exceptional: the slot could not be
    analysed properly, or it stands out with a high band that most analysed slots do not share. A band every slot has
    ("Medium opportunity" nine times) carries no information and is not shown."""
    def band(slot: Mapping[str, Any]) -> str:
        return str((slot.get("opportunity") or {}).get("band") or "").upper()

    def limited(slot: Mapping[str, Any]) -> bool:
        return bool(slot.get("analysis_limited") or (slot.get("opportunity") or {}).get("analysis_limited"))

    analysed = [slot for slot in slots if not limited(slot)]
    rows: list[str] = []
    for slot in slots:
        label = slot_label(slot.get("product_slot"))
        if limited(slot):
            rows.append(f"{label} — Limited analysis")
        elif band(slot) in _STANDOUT_BANDS and 2 * sum(band(other) == band(slot) for other in analysed) < len(analysed):
            rows.append(f"{label} — {_BAND_WORDS[band(slot)]}")
        else:
            rows.append(label)
    return rows


def slot_row_text(slot: Mapping[str, Any]) -> str:
    return slot_row_texts([slot])[0]


MAX_SLOT_REASONS = 4
# Reading priority of a reason, by the kind of evidence behind it (no number is computed): a build need first, then a
# stat the measured priorities back on damage, then one they back on defence, then what the current item lacks, then
# stats that are only profile-valued, then the "nothing to improve" note.
_REASON_NEED, _REASON_OFFENSE, _REASON_DEFENCE, _REASON_ITEM, _REASON_VALUED, _REASON_NOTE = range(6)


def _reason_rank(driver: Mapping[str, Any], priorities: Mapping[str, Any]) -> tuple[int, int, str]:
    """(priority, position within the measured lane, distinctness group) for one driver."""
    kind = str(driver.get("kind") or "")
    if kind in {"critical", "high", "breakpoint"}:
        return (_REASON_NEED, 0 if kind == "critical" else 1, f"need:{driver.get('text')}")
    if kind == "marginal":
        label = str(driver.get("text") or "").replace(" has high marginal value", "")
        for lanes, priority, group in ((("offense",), _REASON_OFFENSE, "offense"), (("ehp", "max_hit", "mobility"), _REASON_DEFENCE, "defence")):
            for lane in lanes:
                if lane == "offense" and priorities.get("offense_limited_confidence"):
                    continue
                for position, row in enumerate(priorities.get(lane) or []):
                    if row.get("label") == label and float(row.get("response_percent") or 0.0) >= MEANINGFUL_PERCENT:
                        return (priority, position, group)
        return (_REASON_VALUED, 0, "valued")
    if kind == "contribution":
        return (_REASON_ITEM, 0, "item")
    return (_REASON_NOTE, 0, "note")


def _slot_reasons(drivers: list[Mapping[str, Any]], priorities: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """(default reasons, every reason). Default: at most four, the most important first, one per kind of idea before
    a second of the same kind. Ordering uses only existing evidence: driver kind, lane order, then driver order."""
    ranked: list[tuple[tuple[int, int, int], str, str]] = []
    for index, driver in enumerate(drivers):
        text = _driver_text(driver, priorities)
        if text and text not in [row[1] for row in ranked]:
            priority, position, group = _reason_rank(driver, priorities)
            ranked.append(((priority, position, index), text, group))
    ranked.sort(key=lambda row: row[0])
    chosen: list[tuple[tuple[int, int, int], str, str]] = []
    for row in ranked:  # breadth first: one reason per group
        if len(chosen) < MAX_SLOT_REASONS and row[2] not in {picked[2] for picked in chosen}:
            chosen.append(row)
    for row in ranked:  # then fill what is left by importance
        if len(chosen) < MAX_SLOT_REASONS and row not in chosen:
            chosen.append(row)
    chosen.sort(key=lambda row: row[0])
    return [row[1] for row in chosen], [row[1] for row in ranked]


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
    why, why_all = ([], []) if limited else _slot_reasons(list(opportunity.get("drivers") or []), priorities)
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
        # The band is an ordering detail (measurement details); only the exceptional state is said up front.
        "summary": "Limited analysis" if limited else "",
        "why": why,
        "why_more": [text for text in why_all if text not in why],
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
