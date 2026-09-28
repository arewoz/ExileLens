"""MAIN-SKILL-01 — actionable diagnostics when the selected main skill has no offense.

Path of Building calculates one selected "main skill". When that skill deals no
damage (a reservation aura, a buff, a utility skill) every offense comparison is
correctly PARTIAL/UNCERTAIN: PoB has nothing to measure. That is the right
answer, but a bare refusal does not tell the player what to do.

This module reads only what PoB already calculated (the per-group skill report
native discovery uses) and reports:

* the selected skill by its real PoB identity and calculation context;
* why offense comparisons cannot receive a confident verdict;
* the other skills of the *same imported build* for which PoB calculated a real,
  identity-stable offensive output, in PoB's own group order (never ranked by
  damage, so nothing is implied to be the "best" skill);
* the recovery path: select the intended skill in PoB, save, reload the build.

It never selects, switches or recommends a skill, never calls a zero-damage buff
"wrong", and never turns an alternative's numbers into a verdict. Alternatives are
listed only when PoB calculated them; a skill PoB reports as zero (for example an
attack whose required weapon is not in the active weapon set) is not listed.
"""

from __future__ import annotations

from typing import Any

from exilelens.items.native_metric_discovery import MAX_REPORT_GROUPS, _number, _selection
from exilelens.items.primary_metric import (
    DamageOwner,
    DamageQuantity,
    OffenseKind,
    PrimaryMetricSelection,
)

MAIN_SKILL_DIAGNOSTIC_VERSION = 1
REASON_CODE = "MAIN_SKILL_NO_OFFENSE"
MAX_ALTERNATIVES_SHOWN = 6

_OFFENSE_FIELDS = (
    "CombinedDPS", "FullDPS", "TotalDPS", "TotalDot", "FullDotDPS",
    "PoisonDPS", "IgniteDPS", "BleedDPS",
    "Minion.CombinedDPS", "Minion.TotalDPS",
)
_EPS = 0.5

# Alternatives status values.
ALT_AVAILABLE = "AVAILABLE"
ALT_NONE = "NONE_CALCULATED"
ALT_NOT_ASSESSED = "NOT_ASSESSED"

RECOVERY_STEPS = (
    "In Path of Building, select the skill you want evaluated as your main skill.",
    "Save the build in Path of Building.",
    "Reload the build in ExileLens (tray menu: Reload Build). ExileLens also reloads "
    "automatically when the saved build file changes.",
)


# Used when a listed alternative lives in the same PoB socket group as the selection.
SAME_GROUP_RECOVERY_STEPS = (
    "In Path of Building, select the skill you want evaluated as your main skill. A skill "
    "marked 'same group' is chosen from the skill list of the group that is already selected.",
    *RECOVERY_STEPS[1:],
)


def selected_skill_has_no_offense(primary: PrimaryMetricSelection, baseline_metrics: dict[str, Any] | None) -> bool:
    """True when PoB reports no usable offensive output for the selected skill.

    Deliberately narrow: the resolver must itself have found nothing to measure
    (``UNRESOLVED``), and every offensive PoB field must be absent or ~0. A skill
    with real but ambiguous output (mixed DoT and ailment, for example) is a
    different, already-handled case and is not a "no offense" skill.
    """
    if primary.selected != OffenseKind.UNRESOLVED:
        return False
    if primary.semantic_quantity == DamageQuantity.MIXED_OUTPUT:
        return False
    metrics = baseline_metrics or {}
    for field in _OFFENSE_FIELDS:
        value = _number(metrics.get(field))
        if value is not None and value > _EPS:
            return False
    return True


def _selected_summary(primary: PrimaryMetricSelection, context: str) -> dict[str, Any]:
    skill = primary.skill
    return {
        "name": skill.name,
        "skill_id": skill.skill_id,
        "group_index": skill.group,
        "group_label": skill.group_label,
        "stat_set": skill.stat_set,
        "part_name": skill.part_name,
        "calculation_mode": skill.calculation_mode,
        "damage_owner": skill.damage_owner.value,
        "item_granted": skill.item_granted,
        "context": context,
    }


def _alternative_label(row: dict[str, Any], name_counts: dict[str, int]) -> str:
    name = str(row.get("skill_name") or row.get("display_label") or "").strip() or "Skill"
    if name_counts.get(name, 0) > 1:
        return f"{name} (PoB group {row.get('index')})"
    return name


def calculated_alternatives(rows: list[dict[str, Any]], main_index: Any) -> list[dict[str, Any]]:
    """Other groups whose offense PoB calculated with a valid, confident identity.

    Reuses native discovery's own eligibility test (enabled, slot enabled, known
    skill, resolved stat set/part, HIGH-confidence primary metric, significant
    value) so a skill is listed here only if it could also serve as a measured
    component. Order is PoB's group order.
    """
    eligible: list[tuple[dict[str, Any], dict[str, Any], float]] = []
    for row in rows:
        if row.get("index") == main_index:
            continue
        chosen = _selection(row)
        if chosen is None:
            continue
        metric, value = chosen
        eligible.append((row, metric, value))
    counts: dict[str, int] = {}
    for row, _metric, _value in eligible:
        name = str(row.get("skill_name") or row.get("display_label") or "").strip() or "Skill"
        counts[name] = counts.get(name, 0) + 1
    alternatives = []
    for row, metric, value in eligible:
        alternatives.append({
            "name": str(row.get("skill_name") or "").strip() or "Skill",
            "label": _alternative_label(row, counts),
            "skill_id": str(row.get("skill_id") or ""),
            "group_index": row.get("index"),
            "effect_selector": None,
            "same_group": False,
            "stat_set": str(row.get("stat_set") or ""),
            "owner": str(metric.get("metric_source") or DamageOwner.PLAYER.value),
            "field": str(metric.get("pob_field") or ""),
            "value": value,
            "gems": [str(gem) for gem in (row.get("gems") or [])],
        })
    return _in_pob_order(alternatives)


def _in_pob_order(alternatives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PoB group order, then the skill's position inside its group. Never by damage."""
    return sorted(alternatives, key=lambda item: (
        item["group_index"] is None, item["group_index"] or 0, item.get("effect_selector") or 0,
    ))


def _effect_offense(output: dict[str, Any]) -> tuple[str, float] | None:
    """The first significant offensive PoB field of one calculated effect."""
    minion = output.get("Minion") or {}
    for field, source in (
        ("Minion.CombinedDPS", minion.get("CombinedDPS")), ("CombinedDPS", output.get("CombinedDPS")),
        ("TotalDPS", output.get("TotalDPS")), ("TotalDot", output.get("TotalDot")),
    ):
        value = _number(source)
        if value is not None and value > _EPS:
            return field, value
    return None


def sibling_alternatives(effect_catalog: dict[str, Any] | None, main_index: Any) -> list[dict[str, Any]]:
    """Other skills inside the *selected* PoB socket group that PoB calculated.

    One socket group can hold several skills (an ascendancy summon and its Command,
    an attack and its alternate mode). The per-group skill report shows only the
    currently selected one, so the effect catalog PoB already returned for the
    selected group is the source. Only enabled, non-selected, measured effects with a
    significant offensive output qualify.
    """
    siblings = []
    for effect in (effect_catalog or {}).get("effects") or []:
        if effect.get("selected") or effect.get("status") != "MEASURED" or effect.get("enabled") is False:
            continue
        reference = effect.get("reference") or {}
        if reference.get("group_selector") != main_index:
            continue
        offense = _effect_offense(effect.get("output") or {})
        if offense is None:
            continue
        field, value = offense
        name = str(effect.get("name") or "").strip() or "Skill"
        siblings.append({
            "name": name,
            "label": name,
            "skill_id": str(reference.get("effect_id") or ""),
            "group_index": main_index,
            "effect_selector": reference.get("effect_selector"),
            "same_group": True,
            "stat_set": "",
            "owner": str(reference.get("owner") or DamageOwner.PLAYER.value),
            "field": field,
            "value": value,
            "gems": [],
        })
    return siblings


def _summary(selected: dict[str, Any]) -> str:
    name = selected.get("name") or "unnamed skill"
    # Lower-case opening: it is embedded as "Partial comparison: <summary>." and the
    # tooltip capitalises its own copy.
    return (
        f"the selected main skill, {name}, has no calculated offense in Path of Building, so "
        "damage cannot get a confident verdict; to evaluate another skill, select it in Path "
        "of Building, save, and reload the build"
    )


def build_main_skill_diagnostic(
    primary: PrimaryMetricSelection,
    baseline_metrics: dict[str, Any] | None,
    report: dict[str, Any] | None,
    *,
    context: str = "MAP",
    skill_group_count: int = 0,
    effect_catalog: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The structured diagnostic, or ``None`` when the selected skill has offense."""
    if not selected_skill_has_no_offense(primary, baseline_metrics):
        return None
    selected = _selected_summary(primary, context)
    siblings = sibling_alternatives(effect_catalog, primary.skill.group)
    if report is None and not siblings:
        status, alternatives = ALT_NOT_ASSESSED, []
        note = (
            "PoB's per-skill report was not read for this build, so other skills are not listed"
            if skill_group_count <= MAX_REPORT_GROUPS
            else f"This build has {skill_group_count} skill groups (limit {MAX_REPORT_GROUPS} for listing); other skills are not listed"
        )
    else:
        others = calculated_alternatives(list((report or {}).get("groups") or []), primary.skill.group)
        alternatives = _in_pob_order([*siblings, *others])
        status = ALT_AVAILABLE if alternatives else ALT_NONE
        note = "" if alternatives else "PoB calculated no offense for any other skill in this build"
        if report is None:
            note = "PoB's per-skill report was not read for this build, so only skills in the selected group are listed"
    return {
        "version": MAIN_SKILL_DIAGNOSTIC_VERSION,
        "code": REASON_CODE,
        "selected": selected,
        "summary": _summary(selected),
        "explanation": (
            "Path of Building calculates offense for the selected main skill only. "
            "A skill that deals no damage, such as an aura or buff, has nothing to compare, "
            "so offense is reported as not measured rather than guessed."
        ),
        "alternatives_status": status,
        "alternatives": alternatives[:MAX_ALTERNATIVES_SHOWN],
        "alternatives_total": len(alternatives),
        "alternatives_note": note,
        "recovery_steps": list(
            SAME_GROUP_RECOVERY_STEPS if any(alt["same_group"] for alt in alternatives) else RECOVERY_STEPS
        ),
        "auto_switched": False,
    }
