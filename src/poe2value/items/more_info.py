"""More Info payload — expanded state of the same tooltip.

Reads EvaluationOutcome (and the compact ranker's impact rows). Never recomputes
score or verdict. Empty sections are omitted.
"""

from __future__ import annotations

from typing import Any

MORE_INFO_TITLE = "MORE INFO"

#: Player-facing order: verdict + replacement target, then the impact that
#: actually matters, then offense/defense/resist consequences, then why, then
#: any truthful uncertainty caveats. Advanced/PoB-provenance sections (build
#: flexibility detail, score drivers, damage reference, native component
#: detail) come last and render inside a collapsed-by-default "Advanced"
#: disclosure (P1.1c) -- `ui.overlay_detail_drawer._render_sections` reads
#: `ADVANCED_SECTION_IDS` to split the two groups; this tuple only controls
#: order within each group. `unmodeled` deliberately stays in the normal
#: group: it carries truthful uncertainty/coverage caveats (the same
#: philosophy as the compact surface's UNCERTAIN quality note), not PoB
#: internals, so it must not be buried behind a click.
MORE_INFO_SECTION_ORDER = (
    "verdict_header",
    "key_impact",
    "offense",
    "defense",
    "resists",
    "why_verdict",
    "unmodeled",
    "flexibility",
    "score_drivers",
    "damage_reference",
    "native_components",
)

#: Section ids that are advanced/PoB-provenance detail rather than a decision
#: the player needs. `ui.overlay_detail_drawer` renders these inside a
#: collapsed-by-default "Advanced" disclosure instead of inline with the
#: normal sections (P1.1c) -- not a change to what data exists, only how
#: prominent/accessible it is by default. `flexibility` (resistance buffer
#: detail) joined this set in P1.1c: the normal `resists` section now shows
#: only the decision-relevant cap state per element, and the raw
#: over-cap/buffer numbers that used to repeat inline live only here.
ADVANCED_SECTION_IDS = frozenset({"flexibility", "score_drivers", "damage_reference", "native_components"})

_OFFENSE_KEYS = ("primary_offense", "cast_attack_speed")
_DEFENSE_KEYS = ("ehp", "worst_max_hit", "life", "energy_shield", "movement_speed")
_DRIVER_PLAYER = {
    "primary_offense": "Damage",
    "ehp": "EHP",
    "max_hit": "Max Hit",
    "res_cap": "Resistance cap",
    "res_flex": "Resistance buffer",
    "movement": "Movement",
    "chaos_res": "Chaos Resistance",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _num(value: Any, *, digits: int = 0) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if digits == 0:
        return f"{number:.0f}"
    return f"{number:.{digits}f}"


def _delta_line(delta: dict[str, Any]) -> str:
    from poe2value.items.compact_tooltip import impact_marker

    label = _text(delta.get("label") or delta.get("key"))
    current = delta.get("current")
    candidate = delta.get("candidate")
    pct = delta.get("percent_delta")
    marker = impact_marker(
        {
            "direction": delta.get("direction"),
            "percent_delta": pct,
            "absolute_delta": delta.get("absolute_delta"),
            "emphasis": "medium",
        }
    )
    change = _pct(pct) if pct is not None else _num(delta.get("absolute_delta"), digits=1)
    if current is None and candidate is None:
        return f"{marker} {label}  {change}".strip()
    return f"{marker} {label}  {_num(current, digits=1)} → {_num(candidate, digits=1)}  {change}"


def _verdict_header(model: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any] | None:
    lines: list[str] = []
    label = _text(outcome.get("verdict_label") or model.get("verdict_headline"))
    if label:
        lines.append(label)
    score = outcome.get("final_score")
    if score is not None:
        lines.append(f"Score {_num(score)} / 100")
    quality = _text(outcome.get("quality_label"))
    if quality:
        reasons = [
            _text(item.get("detail"))
            for item in (outcome.get("evaluation_quality_reasons") or [])
        ]
        reasons = [reason for reason in reasons if reason]
        lines.append(f"{quality}: {reasons[0]}" if reasons else quality)
    slot = _text(outcome.get("replacement_slot"))
    from poe2value.items.slots import is_jewel_socket_pob_slot

    is_jewel = is_jewel_socket_pob_slot(slot)
    paired_offhand_cleared = model.get("paired_offhand_cleared")
    paired_offhand_slot = model.get("paired_offhand_slot") or ""
    paired_offhand_name = str(model.get("paired_offhand_name") or "").strip()
    if paired_offhand_cleared and paired_offhand_slot:
        # Production evaluation carries the verified removed item directly.
        # Retain the replacement-choice fallback for older/synthetic models.
        if not paired_offhand_name:
            for choice in (model.get("replacement_choices") or []):
                if choice.get("slot") == paired_offhand_slot:
                    paired_offhand_name = str(choice.get("replacing_item") or choice.get("item_name") or "").strip()
                    break

    # More Info is bound to one outcome (including a non-best ring). Never read the
    # compact Best line, which always comes from replacement_choices. A jewel
    # socket's raw tree-node id ("Jewel 11184") is never player copy here either
    # -- it stays out of the slot suffix/bare-slot case the same way it does in
    # the compact surface's replacing_line().
    if outcome.get("replacing_empty_slot"):
        if is_jewel:
            replacing = "Equip to empty jewel socket"
        else:
            replacing = f"Equip to empty {slot}" if slot else "Equip to empty slot"
    elif outcome.get("replacing_item"):
        suffix = "" if is_jewel else (f" · {slot}" if slot else "")
        replacing = f"Replacing: {outcome['replacing_item']}" + suffix
        if paired_offhand_cleared and paired_offhand_name:
            replacing += f" (also removes {paired_offhand_name})"
    elif slot and not is_jewel:
        replacing = slot
    else:
        replacing = ""
    if not replacing and paired_offhand_cleared and paired_offhand_name:
        replacing = f"Also removes {paired_offhand_name}"
    if replacing:
        lines.append(replacing)
    if not lines:
        return None
    return {"id": "verdict_header", "title": "VERDICT", "lines": lines, "score_secondary": True}


def _damage_reference_section(model: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any] | None:
    from poe2value.items.primary_metric import build_damage_reference, format_damage_reference_lines

    primary = model.get("primary_metric") or {}
    damage_reference = primary.get("damage_reference") or build_damage_reference(primary)
    lines = format_damage_reference_lines(damage_reference)
    if not lines:
        return None
    return {"id": "damage_reference", "title": "DAMAGE REFERENCE", "lines": lines}


def _native_components_section(model: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any] | None:
    discovery = model.get("native_damage_discovery") or {}
    if discovery.get("damage_scope") != "PARTIAL" or not discovery.get("components"):
        return None
    lines = ["PARTIAL COMPARISON — separate PoB components"]
    for row in discovery["components"]:
        name = _text(row.get("label") or row.get("name")) or "Selected skill"
        field = _text(row.get("field"))
        if row.get("status") != "MEASURED":
            lines.append(f"{name} ({field}): unavailable after item change")
            continue
        lines.append(
            f"{name} ({field}): {_num(row.get('before'))} → {_num(row.get('after'))}"
            f" ({_pct(row.get('percent_delta'))})"
        )
    lines.append("Overall build damage: unavailable from this PoB configuration")
    lines.append("Defensive values remain separately measured")
    return {"id": "native_components", "title": "POB DAMAGE COMPONENTS", "lines": lines}


def _key_impact(model: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any] | None:
    from poe2value.items.compact_tooltip import impact_marker, rows_from_outcome_deltas, select_impact_rows

    rows = list(model.get("impact_rows") or [])
    if not rows:
        rows = select_impact_rows(rows_from_outcome_deltas(outcome))
    lines: list[str] = []
    impact_rows: list[dict[str, Any]] = []
    for row in rows:
        marker = _text(row.get("marker")) or impact_marker(row)
        label = _text(row.get("label") or row.get("key"))
        delta = _text(row.get("delta_text"))
        cap = _text(row.get("cap_label"))
        line = f"{marker} {label}  {delta}".strip()
        if cap:
            line = f"{line}  {cap}"
        lines.append(line)
        impact_rows.append(
            {
                "marker": marker,
                "label": label,
                "delta_text": delta,
                "cap_label": cap,
                "direction": str(row.get("direction") or "neutral"),
                "emphasis": str(row.get("emphasis") or "medium"),
            }
        )
    if not lines:
        return None
    return {"id": "key_impact", "title": "KEY IMPACT", "lines": lines, "impact_rows": impact_rows}


def _score_drivers(outcome: dict[str, Any]) -> dict[str, Any] | None:
    lines: list[str] = []
    for item in outcome.get("score_contributors") or []:
        amount = item.get("contribution")
        if amount is None:
            continue
        try:
            value = float(amount)
        except (TypeError, ValueError):
            continue
        if abs(value) < 0.0001:
            continue
        key = str(item.get("key") or "")
        label = _DRIVER_PLAYER.get(key, _text(item.get("label") or key) or key)
        kind = "gain" if value > 0 else "loss"
        lines.append(f"{'+' if value > 0 else '−'} {label} {kind}")
    if not lines:
        return None
    return {"id": "score_drivers", "title": "SCORE DRIVERS", "lines": lines}


def _table_row(delta: dict[str, Any]) -> dict[str, Any]:
    from poe2value.items.compact_tooltip import impact_marker

    pct = delta.get("percent_delta")
    change = _pct(pct) if pct is not None else _num(delta.get("absolute_delta"), digits=1)
    return {
        "label": _text(delta.get("label") or delta.get("key")),
        "current": _num(delta.get("current"), digits=1),
        "new": _num(delta.get("candidate"), digits=1),
        "change": change,
        "marker": _text(delta.get("marker")) or impact_marker(delta),
        "direction": str(delta.get("direction") or "neutral"),
        "emphasis": str(delta.get("emphasis") or "medium"),
    }


def _table_section(outcome: dict[str, Any], *, keys: tuple[str, ...], section_id: str, title: str) -> dict[str, Any] | None:
    wanted = set(keys)
    lines: list[str] = []
    table_rows: list[dict[str, Any]] = []
    for delta in outcome.get("all_deltas") or []:
        if str(delta.get("key") or "") not in wanted:
            continue
        line = _delta_line(delta)
        if line:
            lines.append(line)
            table_rows.append(_table_row(delta))
    if not lines:
        return None
    return {"id": section_id, "title": title, "lines": lines, "table_rows": table_rows}


#: States where being AT the effective cap is the whole decision-relevant
#: fact -- the exact overflow number is buffer/flexibility detail, which
#: lives in the Advanced `flexibility` section instead of repeating here.
_AT_CAP_BOTH_SIDES_STATES = frozenset({"CAPPED_STAYS_CAPPED", "OVER_CAP_REDUCED_BUT_STILL_CAPPED"})
#: `EvaluationOutcome`'s own resistance severity classification (unchanged,
#: read not re-derived) that marks a line as a warning the player must see.
_RESIST_WARNING_SEVERITIES = frozenset({"critical", "high"})


def _resist_summary(item: dict[str, Any]) -> tuple[str, bool]:
    """One decision-relevant line per resistance -- state over raw numbers.

    "capped -> capped" once both sides are at the effective cap (PoE2's
    elemental resistances commonly sit here); the actual over-cap amount is
    a flexibility/buffer question, not a "is this resistance fine" one.
    Anything not at cap on both sides (most often Chaos Resistance, which
    rarely reaches a hard cap) shows its real effective values, since there
    is no cap fact to collapse into a word. `severity` is read from the
    outcome's own classification, never re-derived, so this never disagrees
    with what the engine actually decided.
    """
    state = str(item.get("state") or "")
    current = item.get("current")
    candidate = item.get("candidate")
    warning = str(item.get("severity") or "") in _RESIST_WARNING_SEVERITIES
    if state in _AT_CAP_BOTH_SIDES_STATES:
        return "capped → capped", warning
    if state == "CAP_REACHED":
        return f"{_num(current)} → capped", warning
    if state == "CAP_LOST":
        return f"capped → {_num(candidate)}", warning
    if current is None and candidate is None:
        return "", warning
    return f"{_num(current)} → {_num(candidate)}", warning


def _resists_section(outcome: dict[str, Any]) -> dict[str, Any] | None:
    lines: list[str] = []
    resist_rows: list[dict[str, Any]] = []
    for item in outcome.get("resistances") or []:
        element = _text(item.get("element")).title()
        if not element:
            continue
        summary, warning = _resist_summary(item)
        if not summary:
            continue
        marker = "⚠" if warning else ""
        lines.append(f"{marker} {element}: {summary}".strip())
        resist_rows.append({"element": element, "marker": marker, "summary": summary, "warning": warning})
    for delta in outcome.get("all_deltas") or []:
        key = str(delta.get("key") or "")
        if key not in {"strength", "dexterity", "intelligence"} and "require" not in key:
            continue
        lines.append(_delta_line(delta))
    if not lines:
        return None
    return {
        "id": "resists",
        "title": "RESISTS & REQUIREMENTS",
        "lines": lines,
        "resist_rows": resist_rows,
    }


def _flexibility_section(outcome: dict[str, Any]) -> dict[str, Any] | None:
    lines: list[str] = []
    for item in outcome.get("resistances") or []:
        delta = item.get("flexibility_delta")
        buffer_delta = item.get("buffer_delta")
        amount = delta if delta is not None else buffer_delta
        if amount is None:
            continue
        try:
            value = float(amount)
        except (TypeError, ValueError):
            continue
        if abs(value) < 0.05:
            continue
        element = _text(item.get("element")).title() or "Resistance"
        lines.append(f"{element} buffer {value:+.1f}")
    contributors = [
        item for item in (outcome.get("score_contributors") or []) if str(item.get("key") or "") == "res_flex"
    ]
    for item in contributors:
        amount = item.get("contribution")
        if amount is None:
            continue
        try:
            value = float(amount)
        except (TypeError, ValueError):
            continue
        if abs(value) < 0.0001:
            continue
        lines.append(f"Resistance buffer {'gain' if value > 0 else 'loss'}")
    if not lines:
        return None
    # Unique while preserving order.
    seen: set[str] = set()
    unique = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        unique.append(line)
    return {"id": "flexibility", "title": "BUILD FLEXIBILITY", "lines": unique}


def _why_verdict(model: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any] | None:
    lines: list[str] = []
    reason = _text(outcome.get("verdict_reason") or model.get("verdict_reason"))
    if reason:
        lines.append(reason)
    for item in outcome.get("guardrails_applied") or []:
        text = _text(item.get("reason"))
        if text and text not in lines:
            lines.append(text)
    for item in outcome.get("critical_tradeoffs") or []:
        text = _text(item.get("text"))
        if text and text not in lines:
            marker = _text(item.get("marker")) or "▼"
            lines.append(f"{marker} {text}")
    if not lines:
        return None
    return {"id": "why_verdict", "title": "WHY THIS VERDICT", "lines": lines}


def _unmodeled(outcome: dict[str, Any]) -> dict[str, Any] | None:
    lines: list[str] = []
    for item in list(outcome.get("unsupported_or_unmodeled") or []) + list(
        outcome.get("evaluation_quality_reasons") or []
    ):
        text = _text(item.get("detail") or item.get("text"))
        if text and text not in lines:
            lines.append(text)
    if not lines:
        return None
    return {"id": "unmodeled", "title": "CONDITIONAL / UNMODELED", "lines": lines}


_BUILDERS = {
    "verdict_header": _verdict_header,
    "damage_reference": _damage_reference_section,
    "native_components": _native_components_section,
    "key_impact": _key_impact,
    "score_drivers": lambda model, outcome: _score_drivers(outcome),
    "offense": lambda model, outcome: _table_section(
        outcome, keys=_OFFENSE_KEYS, section_id="offense", title="OFFENSE"
    ),
    "defense": lambda model, outcome: _table_section(
        outcome, keys=_DEFENSE_KEYS, section_id="defense", title="DEFENSE"
    ),
    "resists": lambda model, outcome: _resists_section(outcome),
    "flexibility": lambda model, outcome: _flexibility_section(outcome),
    "why_verdict": _why_verdict,
    "unmodeled": lambda model, outcome: _unmodeled(outcome),
}


def build_more_info(model: dict[str, Any], *, outcome: dict[str, Any] | None = None) -> dict[str, Any]:
    """Structured More Info payload for one EvaluationOutcome."""
    bound = dict(outcome or model.get("evaluation_outcome") or {})
    sections: list[dict[str, Any]] = []
    for section_id in MORE_INFO_SECTION_ORDER:
        builder = _BUILDERS[section_id]
        section = builder(model, bound)
        if section and section.get("lines"):
            sections.append(section)
    return {
        "title": MORE_INFO_TITLE,
        "sections": sections,
        "section_ids": [section["id"] for section in sections],
        "outcome": bound,
        "replacement_choices": list(model.get("replacement_choices") or []),
        "slot_verdict_lines": _slot_lines(model),
    }


def _slot_lines(model: dict[str, Any]) -> list[dict[str, Any]]:
    from poe2value.items.compact_tooltip import slot_verdict_lines

    return slot_verdict_lines(model)


def more_info_for_choice(model: dict[str, Any], choice: dict[str, Any]) -> dict[str, Any]:
    """Bind More Info to a different legal slot's EvaluationOutcome."""
    outcome = dict(choice.get("evaluation_outcome") or choice.get("outcome") or {})
    if choice.get("slot"):
        outcome["replacement_slot"] = str(choice.get("slot") or outcome.get("replacement_slot") or "")
    if choice.get("empty") or choice.get("replacing_empty_slot"):
        outcome["replacing_empty_slot"] = True
        outcome["replacing_item"] = str(choice.get("replacing_item") or "")
    elif choice.get("replacing_item"):
        outcome["replacing_item"] = str(choice.get("replacing_item") or "")
        outcome["replacing_empty_slot"] = False
    scratch = dict(model)
    scratch["evaluation_outcome"] = outcome
    scratch["native_damage_discovery"] = choice.get("native_damage_discovery") or {}
    scratch["replacement_choices"] = list(model.get("replacement_choices") or [])
    scratch["impact_rows"] = []
    return build_more_info(scratch, outcome=outcome)
