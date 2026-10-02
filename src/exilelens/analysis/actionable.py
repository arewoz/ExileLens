"""R1.5 actionable Build Intelligence: what to do next, derived from what M5/R1 already measured.

A derived layer, not an engine. Everything here is pure arithmetic and ordering over one `analyze_build()` result:
Build Priorities and the sensitivity profile (M5), the Build Fingerprint facts, the strongest responses (R1) and the
response curves measured in `analysis.curves`. It runs no probe, makes no PoB call and reads no value profile.

Truthfulness rules it holds to:

* a hard problem (cap, requirement, one-use affordability) always outranks an optimisation;
* strong sensitivity means "the build responds to this stat", never "the build is weak here";
* unlike tested increments are never converted to a per-point value, and package percentages are never summed;
* there is no build score -- health is a qualitative state with its reason;
* a claim the coverage cannot support is reported as not established instead of being made.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from exilelens.analysis.curves import COULD_NOT_ESTABLISH as CURVE_NOT_ESTABLISHED
from exilelens.analysis.curves import STATE_LABELS as CURVE_STATE_LABELS
from exilelens.analysis.fingerprint import MEASURED
from exilelens.analysis.priorities import (
    _DEFENCE_DETAILS,
    MAX_ROWS_PER_LANE,
    MEANINGFUL_PERCENT,
    RESPONSE_EPSILON,
    _is_resistance_signal,
    _percent,
    _row,
)

SCHEMA_VERSION = 1

MAX_LADDER_ROWS = 5
MAX_ACTIONS = 3
MAX_PACKAGE_STATS = 2
MAX_CHANGES = 6

# Health states (qualitative; there is deliberately no score).
NEEDS_ATTENTION = "NEEDS_ATTENTION"
OPPORTUNITY = "OPPORTUNITY"
NO_URGENT_ISSUE = "NO_URGENT_ISSUE"
LIMITED = "LIMITED"
HEALTH_LABELS = {
    NEEDS_ATTENTION: "Needs attention",
    OPPORTUNITY: "Opportunity",
    NO_URGENT_ISSUE: "No urgent issue detected",
    LIMITED: "Limited analysis",
}

# Coverage levels: share of the relevant tests PoB actually applied. Distinct from measurement confidence.
COVERAGE_HIGH, COVERAGE_PARTIAL, COVERAGE_LIMITED = "HIGH", "PARTIAL", "LIMITED"
COVERAGE_LABELS = {COVERAGE_HIGH: "High", COVERAGE_PARTIAL: "Partial", COVERAGE_LIMITED: "Limited"}
COVERAGE_HIGH_FROM = 0.90
COVERAGE_PARTIAL_FROM = 0.50

# Current focus kinds.
FOCUS_ISSUE, FOCUS_NO_CRITICAL, FOCUS_NOT_ESTABLISHED = "ISSUE", "NO_CRITICAL_ISSUE", "NOT_ESTABLISHED"

# What Changed: a response has to move by this much (absolute points AND relative share) to be worth a line.
CHANGE_MIN_POINTS = 1.0
CHANGE_MIN_RELATIVE = 0.25
CHANGE_MIN_RANK_MOVE = 2

#: (ladder key, sensitivity axis, player label). Order is the display order.
_LADDERS = (("damage", "offense", "Damage"), ("ehp", "ehp", "EHP"), ("max_hit", "max_hit", "Max Hit"), ("movement", "movement", "Movement"))
_ELEMENTS = ("fire", "cold", "lightning", "chaos")


def _leaf(node: Any) -> Any:
    return (node or {}).get("value") if isinstance(node, Mapping) else None


def _num(value: Any) -> float | None:
    try:
        return None if value is None or isinstance(value, bool) else float(value)
    except (TypeError, ValueError):
        return None


def _pct(value: Any) -> str:
    return f"{float(value):+.1f}%"


# ------------------------------------------------------------------------- ladders


def _ladder(signals: list[Mapping[str, Any]], axis: str, *, limited: bool) -> list[dict[str, Any]]:
    """The Build Priorities lane ordering (M5.3), kept longer. The first rows are exactly the priorities lane; a row
    past it must be a meaningful response to be called useful."""
    if limited:
        return []
    measured = [s for s in signals if s.get("status") == MEASURED and (_percent(s, axis) or 0.0) > RESPONSE_EPSILON and not _is_resistance_signal(s)]
    measured.sort(key=lambda s: -float(_percent(s, axis)))  # stable: ties keep catalog order
    also = _DEFENCE_DETAILS if axis in {"ehp", "max_hit"} else ()
    rows = []
    for position, signal in enumerate(measured[:MAX_LADDER_ROWS]):
        if position >= MAX_ROWS_PER_LANE and float(_percent(signal, axis)) < MEANINGFUL_PERCENT:
            break
        rows.append({**_row(signal, axis, also=also), "position": position + 1})
    return rows


def _ladders(result: Mapping[str, Any], priorities: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    signals = list((result.get("build_sensitivity") or {}).get("signals") or [])
    limited = bool(priorities.get("offense_limited_confidence"))
    return {key: _ladder(signals, axis, limited=limited and axis == "offense") for key, axis, _label in _LADDERS}


# --------------------------------------------------------------------- breakpoints


def _breakpoints(result: Mapping[str, Any], priorities: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Explicit thresholds with their actual values. These are stated as facts and override any curve wording."""
    fingerprint = result.get("build_fingerprint") or {}
    pinned = set((priorities.get("coverage") or {}).get("resistance_pinned") or [])
    exact = {str(row.get("title")): str(row.get("detail") or "") for row in priorities.get("fix_first") or [] if row.get("kind") == "RESISTANCE_CAP"}
    rows: list[dict[str, Any]] = []
    for element in _ELEMENTS:
        info = ((fingerprint.get("defense") or {}).get("resistances") or {}).get(element) or {}
        current, cap, state = _num(_leaf(info.get("current"))), _num(_leaf(info.get("cap"))), _leaf(info.get("state"))
        if current is None or cap is None or state is None:
            continue
        title = f"{element.title()} Resistance"
        if element in pinned:
            status, text = "PINNED", f"{title} is fixed by an equipped item; gear cannot raise it."
        elif state == "BELOW_CAP":
            needed = cap - current
            measured = exact.get(title, "")  # the exact amount measured in sensitivity, when there is one
            if measured.startswith("+") and "%" in measured:
                needed = _num(measured[1:measured.index("%")]) or needed
            status, text = "BELOW_CAP", f"{current:g}% → {cap:g}% · {needed:g}% needed"
        else:
            status, text = "AT_CAP", "At cap — more of it does not improve this measured breakpoint."
        rows.append({"kind": "RESISTANCE_CAP", "key": f"{element}_res", "title": title, "status": status,
                     "current": current, "target": cap, "needed": max(0.0, cap - current), "text": text})
    for name, info in (fingerprint.get("requirements") or {}).items():
        have, need, state = _num(_leaf(info.get("value"))), _num(_leaf(info.get("highest_requirement"))), _leaf(info.get("state"))
        if state == "DEFICIT" and have is not None and need is not None:
            rows.append({"kind": "ATTRIBUTE_REQUIREMENT", "key": name, "title": name.title(), "status": "BELOW_REQUIREMENT",
                         "current": have, "target": need, "needed": need - have, "text": f"{have:g} → {need:g} · {need - have:g} needed"})
    mana = (fingerprint.get("resources") or {}).get("mana") or {}
    pool, cost = _num(_leaf(mana.get("unreserved"))), _num(_leaf(mana.get("cost_per_use")))
    if pool is not None and cost and cost > 0:
        short = pool < cost
        rows.append({"kind": "RESOURCE", "key": "mana_one_use", "title": "Mana for one use", "status": "UNAFFORDABLE" if short else "AFFORDABLE",
                     "current": pool, "target": cost, "needed": max(0.0, cost - pool),
                     "text": f"{pool:.0f} unreserved → {cost:.0f} per use" + (f" · {cost - pool:.0f} needed" if short else "")})
    return rows


# --------------------------------------------------------------------- action plan


def _fix_action(row: Mapping[str, Any], breakpoints: list[Mapping[str, Any]]) -> dict[str, Any]:
    kind, title = str(row.get("kind")), str(row.get("title"))
    fact = next((b for b in breakpoints if b["kind"] == kind and (b["title"] == title or kind == "RESOURCE")), None)
    detail = str(fact["text"]) if fact else str(row.get("detail") or "")
    if kind == "RESISTANCE_CAP":
        headline, issue = f"Cap {title}", f"{title} is below cap."
    elif kind == "ATTRIBUTE_REQUIREMENT":
        headline, issue = f"Meet your {title} requirement", f"{title} is below what your gear and gems require."
    else:
        headline, issue = "Make one use of your main skill affordable", "Unreserved Mana is smaller than one use of your main skill."
    return {"id": f"FIX:{kind}:{title}", "kind": "FIX", "fix_kind": kind, "subject": title, "title": headline,
            "detail": detail, "issue": issue, "urgency": str(row.get("severity") or "")}


def _curve_for(curves: list[Mapping[str, Any]], label: str) -> Mapping[str, Any] | None:
    return next((c for c in curves if c.get("label") == label and c.get("status") == MEASURED), None)


def _improve_action(ladder_key: str, axis_label: str, row: Mapping[str, Any], curves: list[Mapping[str, Any]]) -> dict[str, Any]:
    detail = f"{row['label']} gives the strongest measured {axis_label} response ({row['tested_change']} → {_pct(row['response_percent'])})."
    curve = _curve_for(curves, str(row["label"]))
    return {"id": f"IMPROVE:{ladder_key}", "kind": "IMPROVE", "axis": ladder_key, "subject": str(row["label"]),
            "title": f"Improve {axis_label}", "detail": detail, "curve_state": str(curve["state"]) if curve else ""}


def _action_plan(priorities: Mapping[str, Any], ladders: Mapping[str, list], breakpoints: list, curves: list) -> list[dict[str, Any]]:
    """At most three: hard problems in their existing severity order, then the strongest well-supported directions.

    Two different axes cannot be ranked against each other without a universal score, so the order of the optimisation
    part is fixed: the defensive direction (Max Hit, else EHP), then damage."""
    actions = [_fix_action(row, breakpoints) for row in priorities.get("fix_first") or []]
    improve: list[dict[str, Any]] = []
    for ladder_key, label in (("max_hit", "Max Hit"), ("ehp", "EHP")):
        rows = ladders.get(ladder_key) or []
        if rows and float(rows[0]["response_percent"]) >= MEANINGFUL_PERCENT:
            improve.append(_improve_action(ladder_key, label, rows[0], curves))
            break
    damage = ladders.get("damage") or []
    if damage and float(damage[0]["response_percent"]) >= MEANINGFUL_PERCENT:
        improve.append(_improve_action("damage", "Damage", damage[0], curves))
    actions = (actions + improve)[:MAX_ACTIONS]
    for number, action in enumerate(actions, start=1):
        action["number"] = number
    return actions


def _current_focus(actions: list[Mapping[str, Any]], measured: int) -> dict[str, Any]:
    fixes = [a for a in actions if a["kind"] == "FIX"]
    if fixes:
        top = fixes[0]
        return {"kind": FOCUS_ISSUE, "title": "BIGGEST CURRENT ISSUE", "headline": top["issue"], "detail": top["detail"], "action_id": top["id"]}
    if actions:
        top = actions[0]
        return {"kind": FOCUS_NO_CRITICAL, "title": "CURRENT FOCUS", "headline": "No critical issue detected.",
                "detail": top["detail"], "action_id": top["id"]}
    reason = "No tested stat produced a measured response." if measured == 0 else "No meaningful improvement direction was measured."
    return {"kind": FOCUS_NOT_ESTABLISHED, "title": "CURRENT FOCUS", "headline": "Could not establish a current focus.", "detail": reason, "action_id": ""}


def _best_response(ladders: Mapping[str, list], priorities: Mapping[str, Any]) -> dict[str, Any]:
    """The strongest measured damage response, or an honest "not established". Never ranks across axes."""
    damage = ladders.get("damage") or []
    if damage:
        row = damage[0]
        return {"status": MEASURED, "axis_label": "Damage", "label": row["label"], "tested_change": row["tested_change"],
                "response_percent": row["response_percent"]}
    reason = "Limited confidence in this build's damage number." if priorities.get("offense_limited_confidence") else "No tested stat moved this build's damage."
    return {"status": "COULD_NOT_ESTABLISH", "axis_label": "Damage", "reason": reason}


# ------------------------------------------------------------------------ packages


def _evidence(row: Mapping[str, Any], axis_label: str) -> str:
    return f"{axis_label} {_pct(row['response_percent'])}"


def _packages(ladders: Mapping[str, list], priorities: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Stat directions made of individually measured stats. Each stat keeps its own evidence; nothing is added up."""
    packages: list[dict[str, Any]] = []
    offense = [
        {"label": row["label"], "tested_change": row["tested_change"], "evidence": _evidence(row, "Damage")}
        for row in (ladders.get("damage") or [])[:MAX_PACKAGE_STATS] if float(row["response_percent"]) >= MEANINGFUL_PERCENT
    ]
    if offense:
        packages.append({"key": "offense", "title": "OFFENSE FOCUS", "stats": offense})
    defence: dict[str, dict[str, Any]] = {}
    for ladder_key, label in (("max_hit", "Max Hit"), ("ehp", "EHP")):
        for row in (ladders.get(ladder_key) or [])[:MAX_PACKAGE_STATS]:
            if float(row["response_percent"]) < MEANINGFUL_PERCENT:
                continue
            entry = defence.setdefault(str(row["label"]), {"label": row["label"], "tested_change": row["tested_change"], "parts": []})
            entry["parts"].append(_evidence(row, label))
    if defence:
        stats = [{"label": e["label"], "tested_change": e["tested_change"], "evidence": " · ".join(e["parts"])} for e in list(defence.values())[:MAX_PACKAGE_STATS]]
        packages.append({"key": "defence", "title": "DEFENCE FOCUS", "stats": stats})
    hybrid = [
        {"label": row["label"], "tested_change": row["tested_change"],
         "evidence": " · ".join(f"{name} {_pct(value)}" for name, value in (row.get("responses") or {}).items())}
        for row in (priorities.get("multi_axis") or [])[:MAX_PACKAGE_STATS]
    ]
    if hybrid:
        packages.append({"key": "hybrid", "title": "HYBRID FOCUS", "stats": hybrid})
    return packages


# -------------------------------------------------------------------------- health


def _axis_health(key: str, title: str, ladder: list, actions: list, *, limited_reason: str) -> dict[str, Any]:
    if not ladder:
        return {"key": key, "title": title, "state": LIMITED, "reason": limited_reason}
    top = ladder[0]
    if any(a["kind"] == "IMPROVE" and a.get("axis") == key for a in actions):
        return {"key": key, "title": title, "state": OPPORTUNITY, "reason": f"{top['label']} shows the strongest measured response."}
    return {"key": key, "title": title, "state": NO_URGENT_ISSUE, "reason": f"Measured; strongest response is {top['label']}."}


def _build_health(priorities: Mapping[str, Any], ladders: Mapping[str, list], breakpoints: list, actions: list) -> list[dict[str, Any]]:
    """Qualitative state per dimension ExileLens can support. A state never comes from sensitivity size alone:
    OPPORTUNITY means "this is one of the current next actions", not "this number is large"."""
    damage_reason = ("Limited confidence in this build's damage number." if priorities.get("offense_limited_confidence")
                     else "No tested stat moved this build's damage.")
    rows = [
        _axis_health("damage", "Damage", ladders.get("damage") or [], actions, limited_reason=damage_reason),
        _axis_health("ehp", "EHP", ladders.get("ehp") or [], actions, limited_reason="No tested stat moved EHP."),
        _axis_health("max_hit", "Max Hit", ladders.get("max_hit") or [], actions, limited_reason="No tested stat moved Max Hit."),
    ]
    resistances = [b for b in breakpoints if b["kind"] == "RESISTANCE_CAP"]
    below = [b["title"] for b in resistances if b["status"] == "BELOW_CAP"]
    pinned = [b["title"] for b in resistances if b["status"] == "PINNED"]
    if below:
        rows.append({"key": "resistances", "title": "Resistances", "state": NEEDS_ATTENTION, "reason": f"{' and '.join(below)} below cap."})
    elif resistances:
        note = f" {' and '.join(pinned)} fixed by an equipped item." if pinned else ""
        rows.append({"key": "resistances", "title": "Resistances", "state": NO_URGENT_ISSUE,
                     "reason": ("Other measured resistances are at cap." if pinned else "Measured resistances are at cap.") + note})
    else:
        rows.append({"key": "resistances", "title": "Resistances", "state": LIMITED, "reason": "Resistance values were not available."})
    deficits = [b["title"] for b in breakpoints if b["kind"] == "ATTRIBUTE_REQUIREMENT"]
    if deficits:
        rows.append({"key": "requirements", "title": "Requirements", "state": NEEDS_ATTENTION, "reason": f"{' and '.join(deficits)} below requirement."})
    resource = next((b for b in breakpoints if b["kind"] == "RESOURCE"), None)
    if resource is not None:
        unaffordable = resource["status"] == "UNAFFORDABLE"
        rows.append({"key": "resources", "title": "Resources", "state": NEEDS_ATTENTION if unaffordable else NO_URGENT_ISSUE,
                     "reason": "Mana does not cover one use of the main skill." if unaffordable else "Mana covers one use of the main skill."})
    movement = ladders.get("movement") or []
    rows.append({"key": "movement", "title": "Movement", "state": NO_URGENT_ISSUE if movement else LIMITED,
                 "reason": "Movement response measured." if movement else "Movement response was not established."})
    return rows


# ------------------------------------------------------------------------ coverage


def _coverage(result: Mapping[str, Any], priorities: Mapping[str, Any], curves: list[Mapping[str, Any]]) -> dict[str, Any]:
    """How much of the relevant analysis could be carried out. Not a confidence in any single number."""
    signals = list((result.get("build_sensitivity") or {}).get("signals") or [])
    relevant = len(signals)
    established = sum(1 for s in signals if s.get("applied"))
    share = established / relevant if relevant else 0.0
    damage_limited = bool(priorities.get("offense_limited_confidence"))
    if relevant == 0 or share < COVERAGE_PARTIAL_FROM:
        level = COVERAGE_LIMITED
    elif share < COVERAGE_HIGH_FROM or damage_limited:
        level = COVERAGE_PARTIAL
    else:
        level = COVERAGE_HIGH
    notes: list[str] = []
    if relevant and established < relevant:
        notes.append(f"{relevant - established} test{'s' if relevant - established != 1 else ''} could not be applied to this build's items.")
    if damage_limited:
        notes.append("Damage could not be established reliably for this build's main skill.")
    if any(slot.get("analysis_limited") for slot in result.get("slots") or []):
        notes.append("Weapon optimization remains limited.")
    failed_curves = sum(1 for c in curves if c.get("status") != MEASURED)
    if failed_curves:
        notes.append(f"{failed_curves} follow-up measurement{'s' if failed_curves != 1 else ''} could not be established.")
    return {
        "level": level,
        "label": COVERAGE_LABELS[level],
        "established": established,
        "relevant": relevant,
        "summary": f"{established} / {relevant} relevant measurements established." if relevant else "No measurement could be established.",
        "notes": notes,
    }


# ---------------------------------------------------------------------- public API


def build_actionable(result: Mapping[str, Any]) -> dict[str, Any]:
    """The actionable layer for one analysis result. Pure; safe on partial results (returns {} without priorities)."""
    priorities = result.get("build_priorities") or {}
    if not priorities:
        return {}
    curves = list((result.get("response_curves") or {}).get("curves") or [])
    ladders = _ladders(result, priorities)
    breakpoints = _breakpoints(result, priorities)
    actions = _action_plan(priorities, ladders, breakpoints, curves)
    measured = int((priorities.get("coverage") or {}).get("signals_considered") or 0)
    return {
        "schema_version": SCHEMA_VERSION,
        "identity": dict(priorities.get("identity") or {}),
        "current_focus": _current_focus(actions, measured),
        "action_plan": actions,
        "best_response": _best_response(ladders, priorities),
        "ladders": ladders,
        "response_curves": curves,
        "breakpoints": breakpoints,
        "stat_packages": _packages(ladders, priorities),
        "build_health": _build_health(priorities, ladders, breakpoints, actions),
        "coverage": _coverage(result, priorities, curves),
        "multi_impact": [str(row.get("label")) for row in priorities.get("multi_axis") or []],
        "changes": {"comparable": False, "items": []},
    }


def curve_text(curve: Mapping[str, Any]) -> str:
    """`Next +10% Cast Speed: +3.0% · Response weakens` -- or the honest empty state."""
    if curve.get("status") != MEASURED:
        return CURVE_STATE_LABELS[CURVE_NOT_ESTABLISHED]
    return f"{_pct(curve['second_percent'])} · {CURVE_STATE_LABELS[str(curve['state'])]}"


# -------------------------------------------------------------------- what changed


def _norm_path(path: Any) -> str:
    text = str(path or "")
    return os.path.normcase(os.path.normpath(text)) if text else ""


def comparable(previous: Mapping[str, Any] | None, current: Mapping[str, Any] | None) -> bool:
    """Same build file, loadout and context: gear, tree or item-set edits to one build are worth comparing; another
    build, loadout or context starts a new comparison baseline."""
    a, b = (previous or {}).get("identity") or {}, (current or {}).get("identity") or {}
    if not a or not b or not a.get("build_path"):
        return False
    return (_norm_path(a.get("build_path")), str(a.get("loadout") or ""), str(a.get("context") or "")) == (
        _norm_path(b.get("build_path")), str(b.get("loadout") or ""), str(b.get("context") or ""))


def _same_state(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    a, b = previous.get("identity") or {}, current.get("identity") or {}
    return bool(a.get("baseline_fingerprint")) and a.get("baseline_fingerprint") == b.get("baseline_fingerprint")


def _material(old: float, new: float) -> bool:
    return abs(new - old) >= CHANGE_MIN_POINTS and abs(new - old) >= CHANGE_MIN_RELATIVE * max(abs(old), 1e-9)


def diff_actionable(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> dict[str, Any]:
    """Meaningful differences between two analyses of the same build. Compares semantic identities (fix ids, stat
    labels, ladder positions, states), never rendered strings, and ignores movement below the noise thresholds."""
    if not comparable(previous, current):
        return {"comparable": False, "items": []}
    if _same_state(previous, current):
        return {"comparable": True, "items": []}  # same PoB state analysed twice: nothing changed
    items: list[dict[str, Any]] = []

    def add(kind: str, key: str, text: str) -> None:
        if not any(item["key"] == key for item in items):
            items.append({"kind": kind, "key": key, "text": text})

    old_fixes = {a["id"]: a for a in previous.get("action_plan") or [] if a["kind"] == "FIX"}
    new_fixes = {a["id"]: a for a in current.get("action_plan") or [] if a["kind"] == "FIX"}
    old_issues = {f"{b['kind']}:{b['key']}" for b in previous.get("breakpoints") or [] if b["status"] in {"BELOW_CAP", "BELOW_REQUIREMENT", "UNAFFORDABLE"}}
    new_issues = {f"{b['kind']}:{b['key']}": b for b in current.get("breakpoints") or [] if b["status"] in {"BELOW_CAP", "BELOW_REQUIREMENT", "UNAFFORDABLE"}}
    for fix_id, action in old_fixes.items():
        if fix_id not in new_fixes:
            add("RESOLVED", fix_id, f"✓ {action['subject']} is no longer a priority.")
    for fix_id, action in new_fixes.items():
        if fix_id not in old_fixes:
            add("ADDED", fix_id, f"! {action['subject']} is now a priority: {action['issue'][:1].lower()}{action['issue'][1:]}")
    old_focus, new_focus = previous.get("current_focus") or {}, current.get("current_focus") or {}
    if old_focus.get("action_id") != new_focus.get("action_id") and new_focus.get("kind") == FOCUS_NO_CRITICAL and old_focus.get("kind") == FOCUS_ISSUE:
        add("FOCUS", "focus", "→ No critical issue remains.")
    del old_issues, new_issues  # breakpoint facts are covered by the fix ids above

    for key, _axis, label in _LADDERS:
        old_rows, new_rows = (previous.get("ladders") or {}).get(key) or [], (current.get("ladders") or {}).get(key) or []
        if not old_rows and not new_rows:
            continue
        if old_rows and not new_rows:
            add("TOP", f"top:{key}", f"↓ {label}: no measured response any more.")
            continue
        if new_rows and not old_rows:
            add("TOP", f"top:{key}", f"NEW: {label} now has a measured response — {new_rows[0]['label']}.")
            continue
        old_top, new_top = old_rows[0], new_rows[0]
        if old_top["label"] != new_top["label"]:
            add("TOP", f"top:{key}", f"→ {new_top['label']} is now your strongest {label} response (was {old_top['label']}).")
        elif _material(float(old_top["response_percent"]), float(new_top["response_percent"])):
            arrow = "↑" if float(new_top["response_percent"]) > float(old_top["response_percent"]) else "↓"
            add("RESPONSE", f"top:{key}", f"{arrow} {new_top['label']}: {label} response {_pct(old_top['response_percent'])} → {_pct(new_top['response_percent'])}.")
        old_positions = {row["label"]: row["position"] for row in old_rows}
        for row in new_rows[1:]:
            before = old_positions.get(row["label"])
            if before is not None and abs(before - row["position"]) >= CHANGE_MIN_RANK_MOVE:
                arrow = "↑" if row["position"] < before else "↓"
                add("RANK", f"rank:{key}:{row['label']}", f"{arrow} {row['label']} moved from #{before} to #{row['position']} for {label}.")
    for name in current.get("multi_impact") or []:
        if name not in (previous.get("multi_impact") or []):
            add("MULTI", f"multi:{name}", f"NEW: {name} is now a multi-impact response.")
    old_health = {row["key"]: row["state"] for row in previous.get("build_health") or []}
    for row in current.get("build_health") or []:
        before = old_health.get(row["key"])
        if before and before != row["state"] and {before, row["state"]} & {NEEDS_ATTENTION, LIMITED} and row["key"] in {"damage", "ehp", "max_hit", "movement"}:
            add("HEALTH", f"health:{row['key']}", f"→ {row['title']}: {HEALTH_LABELS[before]} → {HEALTH_LABELS[row['state']]}.")
    old_cov, new_cov = (previous.get("coverage") or {}).get("level"), (current.get("coverage") or {}).get("level")
    if old_cov and new_cov and old_cov != new_cov:
        add("COVERAGE", "coverage", f"→ Analysis coverage: {COVERAGE_LABELS[old_cov]} → {COVERAGE_LABELS[new_cov]}.")
    if items:  # one line of continuity, only when something else did change
        damage_old, damage_new = (previous.get("ladders") or {}).get("damage") or [], (current.get("ladders") or {}).get("damage") or []
        if damage_old and damage_new and damage_old[0]["label"] == damage_new[0]["label"]:
            add("UNCHANGED", "top:damage", f"↔ {damage_new[0]['label']} remains your strongest Damage response.")
    return {"comparable": True, "items": items[:MAX_CHANGES]}
