"""R1 build-aware Item Check context: why this item matters for THIS build.

Explanation only. The verdict, the score and every measured delta come from the direct candidate-vs-equipped PoB
evaluation and are read here, never recomputed or changed. This module adds two kinds of structured notes:

* ``source == "direct"`` -- consequences already present in the direct comparison (a resistance cap with its actual
  values, an attribute requirement, the main skill no longer affordable for one use, an EHP / Max Hit split).
* ``source == "build_intelligence"`` -- context from a previously run, still-current Analyze Build result: the item
  gains or loses a stat that was one of the build's strongest measured responses, or resolves a FIX FIRST issue.

It runs no PoB calculation and never starts an analysis: `snapshot` is whatever the controller already holds, or None.
Sensitivity never decides item value -- the wording says "one of your strongest measured responses", and the note
always sits below the measured result.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, replace
from typing import Any, Iterable, Mapping

from exilelens.analysis.identity import AnalysisBaseline
from exilelens.analysis.priorities import is_priorities_stale
from exilelens.analysis.strongest import strongest_responses
from exilelens.items.item_impact import IMPACT_THRESHOLDS
from exilelens.items.requirement_gates import attribute_requirement_warnings

SCHEMA_VERSION = 1

# Whether cached Build Intelligence backs this result.
AVAILABLE = "AVAILABLE"
NOT_ANALYZED = "NOT_ANALYZED"
STALE = "STALE"
NO_SIGNAL = "NO_SIGNAL"

SOURCE_DIRECT = "direct"
SOURCE_INTELLIGENCE = "build_intelligence"

# Note codes. Presentation may change freely; these and `kind` are the stable semantics.
HIGH_RESPONSE_GAIN = "HIGH_RESPONSE_GAIN"
HIGH_RESPONSE_LOSS = "HIGH_RESPONSE_LOSS"
MULTI_AXIS_GAIN = "MULTI_AXIS_GAIN"
MULTI_AXIS_LOSS = "MULTI_AXIS_LOSS"
FIX_FIRST_RESOLVED = "FIX_FIRST_RESOLVED"
FIX_FIRST_PROGRESS = "FIX_FIRST_PROGRESS"
RESISTANCE_CAP_BROKEN = "RESISTANCE_CAP_BROKEN"
RESISTANCE_CAP_RESTORED = "RESISTANCE_CAP_RESTORED"
ATTRIBUTE_REQUIREMENT_BROKEN = "ATTRIBUTE_REQUIREMENT_BROKEN"
ATTRIBUTE_REQUIREMENT_RESTORED = "ATTRIBUTE_REQUIREMENT_RESTORED"
RESOURCE_USE_BLOCKED = "RESOURCE_USE_BLOCKED"
RESOURCE_USE_RESTORED = "RESOURCE_USE_RESTORED"
MAX_HIT_TRADEOFF = "MAX_HIT_TRADEOFF"

KIND_GAIN, KIND_LOSS, KIND_FIX, KIND_BREAKAGE, KIND_TRADEOFF = "gain", "loss", "fix", "breakage", "tradeoff"

BASIS = "Build context comes from your last Analyze Build. The verdict comes from testing this exact item in Path of Building."
HINT_NOT_ANALYZED = "Run Analyze Build to see how items match your build's strongest measured stats."

MAX_RESPONSE_NOTES = 2  # per direction (gained / lost stats)
MAX_COMPACT_LINES = 2
MAX_DETAIL_LINES = 6

# Reading order inside the context block: Build Intelligence context, then breakages, then the trade-off reading.
_ORDER = (
    HIGH_RESPONSE_GAIN, MULTI_AXIS_GAIN, FIX_FIRST_RESOLVED, RESISTANCE_CAP_RESTORED, ATTRIBUTE_REQUIREMENT_RESTORED,
    RESOURCE_USE_RESTORED, FIX_FIRST_PROGRESS, HIGH_RESPONSE_LOSS, MULTI_AXIS_LOSS, RESISTANCE_CAP_BROKEN,
    ATTRIBUTE_REQUIREMENT_BROKEN, RESOURCE_USE_BLOCKED, MAX_HIT_TRADEOFF,
)
# The compact tooltip already states cap breaks and requirement blockers itself (notes / blocker reasons).
_COMPACT_DIRECT = frozenset({RESOURCE_USE_BLOCKED, RESOURCE_USE_RESTORED, MAX_HIT_TRADEOFF})


@dataclass(frozen=True)
class ContextNote:
    code: str
    kind: str
    source: str
    text: str
    #: Stat label or metric the note is about ("Cast Speed", "fire_res", "strength").
    subject: str = ""
    #: Evidence shown in More Info only (tested change and measured response, actual values).
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------- intelligence


def snapshot_intelligence(analysis: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The part of a finished Analyze Build result Item Check may read later. None when it carries no priorities."""
    priorities = (analysis or {}).get("build_priorities")
    if not priorities:
        return None
    return {
        "priorities": priorities,
        "strongest": (analysis or {}).get("strongest_responses") or strongest_responses(priorities),
    }


def _norm_path(path: Any) -> str:
    text = str(path or "")
    return os.path.normcase(os.path.normpath(text)) if text else ""


def intelligence_status(snapshot: Mapping[str, Any] | None, current: AnalysisBaseline) -> str:
    """AVAILABLE only for an analysis of exactly this baseline (M5 identity: hash, generation, build, loadout, item
    set, context). A value-profile-only change is never stale, as in M5.1-M5.3."""
    priorities = (snapshot or {}).get("priorities")
    if not priorities:
        return NOT_ANALYZED
    identity = dict(priorities.get("identity") or {})
    # Same M5 staleness rule; the two sides may only spell the same file differently (slashes, case).
    bound = {"identity": {**identity, "build_path": _norm_path(identity.get("build_path"))}}
    if is_priorities_stale(bound, replace(current, build_path=_norm_path(current.build_path))):
        return STALE
    measured = int((priorities.get("coverage") or {}).get("signals_considered") or 0)
    return AVAILABLE if measured or priorities.get("fix_first") else NO_SIGNAL


# --------------------------------------------------------------------- item stats

_NUM = r"(\d+(?:\.\d+)?)"
_ATTR = r"(strength|dexterity|intelligence)"


def _one(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern) for pattern in patterns)


# Sensitivity label (the catalog's player label) -> the item lines of the same stat. Deliberately strict: a line counts
# only when it is the same kind of stat the analysis tested, never a merely related one.
_STAT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "Cast Speed": _one(rf"^{_NUM}% increased cast speed$"),
    "Spell Damage": _one(rf"^{_NUM}% increased spell damage$"),
    "Attack Damage": _one(rf"^{_NUM}% increased attack damage$"),
    "Attack Speed": _one(rf"^{_NUM}% increased attack speed$"),
    "Critical Hit Chance": _one(rf"^{_NUM}% increased critical hit chance$"),
    "Critical Damage Bonus": _one(rf"^{_NUM}% increased critical damage bonus$"),
    "Spell Skill Levels": _one(rf"^\+{_NUM} to level of all spell skills$"),
    "Projectile Skill Levels": _one(rf"^\+{_NUM} to level of all projectile skills$"),
    "Minion Skill Levels": _one(rf"^\+{_NUM} to level of all minion skills$"),
    "Minion Damage": _one(rf"^minions deal {_NUM}% increased damage$", rf"^{_NUM}% increased minion damage$"),
    "Minion Attack Speed": _one(rf"^minions have {_NUM}% increased attack speed$", rf"^minions have {_NUM}% increased attack and cast speed$"),
    "Minion Cast Speed": _one(rf"^minions have {_NUM}% increased cast speed$", rf"^minions have {_NUM}% increased attack and cast speed$"),
    "Ignite Magnitude": _one(rf"^{_NUM}% increased ignite magnitude$", rf"^{_NUM}% increased magnitude of ignite you inflict$"),
    "Poison Magnitude": _one(rf"^{_NUM}% increased poison magnitude$", rf"^{_NUM}% increased magnitude of poison you inflict$"),
    "Poison Duration": _one(rf"^{_NUM}% increased poison duration$", rf"^{_NUM}% increased duration of poison you inflict$"),
    "Life": _one(rf"^\+{_NUM} to maximum life$"),
    "Energy Shield": _one(rf"^\+{_NUM} to maximum energy shield$"),
    "Mana": _one(rf"^\+{_NUM} to maximum mana$"),
    "Armour": _one(rf"^\+{_NUM} to armour$"),
    "Evasion": _one(rf"^\+{_NUM} to evasion(?: rating)?$"),
    "Movement Speed": _one(rf"^{_NUM}% increased movement speed$"),
}
_ATTRIBUTES = re.compile(rf"^\+{_NUM} to (?:{_ATTR}(?: and {_ATTR})?|(all attributes))$")
_LEVEL_STATS = frozenset({"Spell Skill Levels", "Projectile Skill Levels", "Minion Skill Levels"})
_FLAT_STATS = frozenset({"Life", "Energy Shield", "Mana", "Armour", "Evasion", "Strength", "Dexterity", "Intelligence"})

_TAG_PREFIX = re.compile(r"^(?:\{[^}]*\})+")
_TRAILING_NOTE = re.compile(r"\s*\((?:implicit|rune|enchant|crafted|fractured|desecrated|augmented)\)\s*$", re.I)
_ROLL_AFTER_VALUE = re.compile(r"(?<=\d)\s*\(\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?\)")
_BARE_RANGE = re.compile(r"\((\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\)")
_RANGE_TAG = re.compile(r"\{range:(\d+(?:\.\d+)?)\}")


def _clean_line(line: str) -> str:
    """One item line as the plain stat text (PoB tag prefixes, roll ranges and source suffixes removed)."""
    text = str(line or "").strip()
    roll = _RANGE_TAG.search(text)
    text = _TAG_PREFIX.sub("", text).strip()
    text = _TRAILING_NOTE.sub("", text)
    text = _ROLL_AFTER_VALUE.sub("", text)  # in-game advanced copy: "85(80-91)"
    if "(" in text:  # PoB template line: "+(70-80) to maximum Life" with a {range:} roll
        share = float(roll.group(1)) if roll else 0.5
        text = _BARE_RANGE.sub(lambda m: f"{float(m.group(1)) + (float(m.group(2)) - float(m.group(1))) * share:g}", text)
    return text.lower()


def item_stat_totals(raw_text: str | None) -> dict[str, float]:
    """Total of each tested-stat family written on one item (in-game clipboard text or PoB item text)."""
    totals: dict[str, float] = {}
    for raw_line in str(raw_text or "").replace("\r", "").split("\n"):
        line = _clean_line(raw_line)
        if not line:
            continue
        for label, patterns in _STAT_PATTERNS.items():
            for pattern in patterns:
                match = pattern.match(line)
                if match:
                    totals[label] = totals.get(label, 0.0) + float(match.group(1))
                    break
        attributes = _ATTRIBUTES.match(line)
        if attributes:
            named = [name for name in attributes.groups()[1:3] if name]
            for name in named or ["strength", "dexterity", "intelligence"]:
                totals[name.title()] = totals.get(name.title(), 0.0) + float(attributes.group(1))
    return totals


def _amount(label: str, value: float) -> str:
    if label in _LEVEL_STATS or label in _FLAT_STATS:
        return f"+{value:g}"
    return f"{value:g}%"


# ------------------------------------------------------------------ response notes

_LANE_WORDS = (("offense", "damage"), ("ehp", "EHP"), ("max_hit", "Max Hit"), ("mobility", "movement"))


def _response_index(priorities: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Stat label -> where it sits among the strongest measured responses (lane rows are already the top ones)."""
    index: dict[str, dict[str, Any]] = {}
    for lane, word in _LANE_WORDS:
        if lane == "offense" and priorities.get("offense_limited_confidence"):
            continue  # a low-confidence damage number is not used to characterise an item
        for position, row in enumerate(priorities.get(lane) or []):
            entry = index.setdefault(str(row.get("label")), {"lanes": [], "tested": str(row.get("tested_change") or ""), "measured": []})
            entry["lanes"].append((word, position))
            entry["measured"].append(f"{word[:1].upper()}{word[1:]} {float(row['response_percent']):+.1f}%")
    for row in priorities.get("multi_axis") or []:
        entry = index.setdefault(str(row.get("label")), {"lanes": [], "tested": str(row.get("tested_change") or ""), "measured": []})
        entry["multi"] = " · ".join(f"{name} {float(value):+.1f}%" for name, value in (row.get("responses") or {}).items())
    return index


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _response_phrase(entry: Mapping[str, Any]) -> str:
    lanes = entry.get("lanes") or []
    if not lanes:
        return "a multi-impact stat for your build"
    axes = _join([word for word, _position in lanes])
    if all(position == 0 for _word, position in lanes):
        return f"your build's strongest measured {axes} response"
    return f"one of your build's strongest measured {axes} responses"


def _response_notes(candidate: Mapping[str, float], replaced: Mapping[str, float], priorities: Mapping[str, Any]) -> list[ContextNote]:
    index = _response_index(priorities)
    gains: list[ContextNote] = []
    losses: list[ContextNote] = []
    for label, entry in index.items():  # priorities order: lane by lane, strongest first
        new, old = float(candidate.get(label) or 0.0), float(replaced.get(label) or 0.0)
        if abs(new - old) < 1e-9:
            continue
        gained = new > old
        multi = not entry.get("lanes")
        phrase = _response_phrase(entry)
        if gained:
            lead = f"Adds {label} ({_amount(label, new)})" if old == 0 else f"More {label} than your current item ({_amount(label, new)} vs {_amount(label, old)})"
        else:
            lead = f"Loses {label} ({_amount(label, old)})" if new == 0 else f"Less {label} than your current item ({_amount(label, new)} vs {_amount(label, old)})"
        measured = entry.get("multi") if multi else " · ".join(entry.get("measured") or [])
        note = ContextNote(
            code=(MULTI_AXIS_GAIN if gained else MULTI_AXIS_LOSS) if multi else (HIGH_RESPONSE_GAIN if gained else HIGH_RESPONSE_LOSS),
            kind=KIND_GAIN if gained else KIND_LOSS,
            source=SOURCE_INTELLIGENCE,
            text=f"{lead} — {phrase}.",
            subject=label,
            detail=f"Tested {entry['tested']} → {measured}." if measured else "",
        )
        (gains if gained else losses).append(note)
    return gains[:MAX_RESPONSE_NOTES] + losses[:MAX_RESPONSE_NOTES]


# -------------------------------------------------------------------- direct notes


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _fix_first(priorities: Mapping[str, Any] | None, kind: str) -> set[str]:
    return {str(row.get("title") or "") for row in (priorities or {}).get("fix_first") or [] if row.get("kind") == kind}


def _resistance_notes(outcome: Mapping[str, Any], priorities: Mapping[str, Any] | None) -> list[ContextNote]:
    listed = _fix_first(priorities, "RESISTANCE_CAP")
    notes: list[ContextNote] = []
    for row in outcome.get("resistances") or []:
        element = str(row.get("element") or "").lower()
        state = str(row.get("state") or "")
        if not element:
            continue
        name = f"{element.title()} Resistance"
        before, after = _num(row.get("current")), _num(row.get("candidate"))
        cap = _num(row.get("cap_candidate")) if row.get("cap_candidate") is not None else _num(row.get("cap_current"))
        values = f"{before:g}% → {after:g}%" if before is not None and after is not None else ""
        in_fix_first = name in listed
        if state == "CAP_LOST":
            if values and cap is not None:
                text = f"{name} falls from {before:g}% to {after:g}%, below the {cap:g}% cap."
            else:
                text = f"{name} falls below the cap."
            notes.append(ContextNote(RESISTANCE_CAP_BROKEN, KIND_BREAKAGE, SOURCE_DIRECT, text, f"{element}_res"))
        elif state == "CAP_REACHED":
            reach = f"{name} reaches the cap" + (f" ({values})" if values else "")
            if in_fix_first:
                notes.append(ContextNote(FIX_FIRST_RESOLVED, KIND_FIX, SOURCE_INTELLIGENCE, f"Fixes a Fix First issue: {reach}.", f"{element}_res"))
            else:
                notes.append(ContextNote(RESISTANCE_CAP_RESTORED, KIND_FIX, SOURCE_DIRECT, f"{reach}.", f"{element}_res"))
        elif state == "BELOW_CAP_IMPROVED" and in_fix_first:
            deficit_before, deficit_after = _num(row.get("deficit_current")), _num(row.get("deficit_candidate"))
            moved = abs((deficit_before or 0.0) - (deficit_after or 0.0))
            if moved >= IMPACT_THRESHOLDS.resistance_deficit_points:
                closer = f"Moves {name} closer to the cap" + (f" ({values})" if values else "")
                notes.append(ContextNote(FIX_FIRST_PROGRESS, KIND_FIX, SOURCE_INTELLIGENCE, f"{closer} — a Fix First issue for your build.", f"{element}_res"))
    return notes


def _attribute_notes(outcome: Mapping[str, Any], priorities: Mapping[str, Any] | None) -> list[ContextNote]:
    """Requirement facts PoB reports for the build after the swap. Never a guess about future gems or gear."""
    listed = _fix_first(priorities, "ATTRIBUTE_REQUIREMENT")
    baseline, candidate = outcome.get("baseline_metrics") or {}, outcome.get("candidate_metrics") or {}
    notes: list[ContextNote] = []
    for warning in attribute_requirement_warnings(dict(baseline), dict(candidate)):
        metric = str(warning.get("metric") or "")
        name = metric.title()
        if warning.get("code") == "ATTRIBUTE_REQUIREMENT_LOST":
            detail = str(warning.get("detail") or "").replace(" — ", ", ")
            text = f"{name} no longer meets what your gear and gems need ({detail[:1].lower()}{detail[1:]})." if detail else f"{name} no longer meets your requirements."
            notes.append(ContextNote(ATTRIBUTE_REQUIREMENT_BROKEN, KIND_BREAKAGE, SOURCE_DIRECT, text, metric))
        elif warning.get("code") == "ATTRIBUTE_REQUIREMENT_REACHED":
            if name in listed:
                notes.append(ContextNote(FIX_FIRST_RESOLVED, KIND_FIX, SOURCE_INTELLIGENCE, f"Fixes a Fix First issue: your {name} requirement is met.", metric))
            else:
                notes.append(ContextNote(ATTRIBUTE_REQUIREMENT_RESTORED, KIND_FIX, SOURCE_DIRECT, f"Your {name} requirement is met again.", metric))
    return notes


def _one_use(metrics: Mapping[str, Any]) -> tuple[bool | None, float | None, float | None]:
    """(affordable, unreserved pool, cost of one use). M5.5 semantics: one use against the unreserved pool, no sustain."""
    pool, cost = _num(metrics.get("ManaUnreserved")), _num(metrics.get("ManaCost"))
    if pool is None or cost is None or cost <= 0:
        return None, pool, cost
    return pool >= cost, pool, cost


def _resource_notes(outcome: Mapping[str, Any], priorities: Mapping[str, Any] | None) -> list[ContextNote]:
    before, _pool_before, _cost_before = _one_use(outcome.get("baseline_metrics") or {})
    after, pool, cost = _one_use(outcome.get("candidate_metrics") or {})
    if before is None or after is None or before == after:
        return []
    if not after:
        text = f"Unreserved Mana ({pool:.0f}) no longer covers one use of your main skill ({cost:.0f})."
        return [ContextNote(RESOURCE_USE_BLOCKED, KIND_BREAKAGE, SOURCE_DIRECT, text, "mana")]
    text = f"Unreserved Mana ({pool:.0f}) now covers one use of your main skill ({cost:.0f})."
    if _fix_first(priorities, "RESOURCE"):
        return [ContextNote(FIX_FIRST_RESOLVED, KIND_FIX, SOURCE_INTELLIGENCE, f"Fixes a Fix First issue: {text[:1].lower()}{text[1:]}", "mana")]
    return [ContextNote(RESOURCE_USE_RESTORED, KIND_FIX, SOURCE_DIRECT, text, "mana")]


def _tradeoff_notes(outcome: Mapping[str, Any]) -> list[ContextNote]:
    """At most one split, and only when both sides pass the existing materiality thresholds."""
    deltas = {str(row.get("key") or ""): row for row in outcome.get("all_deltas") or outcome.get("primary_deltas") or []}

    def pct(key: str) -> float | None:
        row = deltas.get(key) or {}
        if key == "primary_offense" and str(row.get("delta_kind") or "MEASURED") not in {"MEASURED", "MEASURED_ZERO"}:
            return None
        return _num(row.get("percent_delta"))

    damage, ehp, max_hit = pct("primary_offense"), pct("ehp"), pct("worst_max_hit")
    defence, offense = IMPACT_THRESHOLDS.defense_pct, IMPACT_THRESHOLDS.offense_pct
    text = ""
    if ehp is not None and max_hit is not None and ehp >= defence and max_hit <= -defence:
        text = f"EHP rises {ehp:.1f}% but Max Hit falls {abs(max_hit):.1f}%: tougher against sustained damage, weaker against one big hit."
    elif ehp is not None and max_hit is not None and max_hit >= defence and ehp <= -defence:
        text = f"Max Hit rises {max_hit:.1f}% but EHP falls {abs(ehp):.1f}%: safer against one big hit, weaker against sustained damage."
    elif damage is not None and max_hit is not None and damage >= offense and max_hit <= -defence:
        text = f"Damage rises {damage:.1f}% but Max Hit falls {abs(max_hit):.1f}%: more damage for a smaller safety margin against one big hit."
    return [ContextNote(MAX_HIT_TRADEOFF, KIND_TRADEOFF, SOURCE_DIRECT, text, "worst_max_hit")] if text else []


# ---------------------------------------------------------------------- public API


def _outcome_of(comparison: Mapping[str, Any]) -> Mapping[str, Any]:
    outcome = comparison.get("evaluation_outcome") or {}
    return outcome.to_dict() if hasattr(outcome, "to_dict") else outcome


def _slot_notes(comparison: Mapping[str, Any], candidate_stats: Mapping[str, float], priorities: Mapping[str, Any] | None) -> list[ContextNote]:
    outcome = _outcome_of(comparison)
    if not outcome or outcome.get("final_score") is None:
        return []  # a failed evaluation has no measured consequences to explain
    notes: list[ContextNote] = []
    if priorities:
        replaced = item_stat_totals((comparison.get("baseline_item") or {}).get("raw"))
        notes.extend(_response_notes(candidate_stats, replaced, priorities))
    notes.extend(_resistance_notes(outcome, priorities))
    notes.extend(_attribute_notes(outcome, priorities))
    notes.extend(_resource_notes(outcome, priorities))
    notes.extend(_tradeoff_notes(outcome))
    return sorted(notes, key=lambda note: _ORDER.index(note.code))  # stable: equal codes keep measurement order


def build_item_context(result: Mapping[str, Any], snapshot: Mapping[str, Any] | None, *, status: str) -> dict[str, Any]:
    """Structured build context for one Item Check result, per legal slot. Pure: no engine, no mutation of `result`."""
    priorities = (snapshot or {}).get("priorities") if status == AVAILABLE else None
    candidate_stats = item_stat_totals((result.get("raw_input") or {}).get("raw_text")) if priorities else {}
    slots: dict[str, list[dict[str, Any]]] = {}
    for comparison in result.get("slot_comparisons") or []:
        slot = str(comparison.get("pob_slot") or "")
        if slot:
            slots[slot] = [note.to_dict() for note in _slot_notes(comparison, candidate_stats, priorities)]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "uses_build_intelligence": status == AVAILABLE,
        "basis": BASIS if status == AVAILABLE else "",
        "hint": HINT_NOT_ANALYZED if status in {NOT_ANALYZED, STALE} else "",
        "slots": slots,
    }


def _notes_for(context: Mapping[str, Any] | None, slot: str) -> list[Mapping[str, Any]]:
    slots = (context or {}).get("slots") or {}
    if slot in slots:
        return list(slots[slot])
    return list(next(iter(slots.values()))) if len(slots) == 1 else []


def compact_lines(context: Mapping[str, Any] | None, slot: str, claimed: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Up to two short context lines for the compact tooltip.

    `claimed` are the metrics the measured Why already explains; a fact the tooltip states is not said a second time."""
    stated = {str(metric) for metric in claimed if metric}
    notes = [
        note for note in _notes_for(context, slot)
        if (note.get("source") == SOURCE_INTELLIGENCE or note.get("code") in _COMPACT_DIRECT) and note.get("subject") not in stated
    ]
    return [{"text": note["text"], "kind": note["kind"], "code": note["code"]} for note in notes[:MAX_COMPACT_LINES]]


def detail_lines(context: Mapping[str, Any] | None, slot: str) -> list[str]:
    """More Info lines: every note with its evidence, then where the context comes from."""
    notes = _notes_for(context, slot)[:MAX_DETAIL_LINES]
    lines = [f"{note['text']} {note['detail']}".strip() for note in notes]
    context = context or {}
    if lines and context.get("basis") and any(note.get("source") == SOURCE_INTELLIGENCE for note in notes):
        lines.append(str(context["basis"]))
    if context.get("hint"):
        lines.append(str(context["hint"]))
    return lines


def note_codes(notes: Iterable[Mapping[str, Any]]) -> list[str]:
    return [str(note.get("code")) for note in notes]
