"""BuildRelevanceEngine — interpret exact evaluation evidence into BuildMods."""

from __future__ import annotations

from typing import Any

from poe2value.items.build_intel.item_semantics import ItemSemanticModel, group_label
from poe2value.items.build_intel.models import (
    AxisDelta,
    AxisId,
    BuildConfidence,
    BuildMod,
    BuildRole,
    ContributionKind,
    SynergyFinding,
    SynergyKind,
    ThresholdEvent,
)
from poe2value.items.resist_caps import CapState

_FAMILY_KIND = {
    "movement_speed": ContributionKind.MOBILITY.value,
    "cast_speed": ContributionKind.DAMAGE.value,
    "attack_speed": ContributionKind.DAMAGE.value,
    "crit_chance": ContributionKind.DAMAGE.value,
    "crit_multi": ContributionKind.DAMAGE.value,
    "spell_damage": ContributionKind.DAMAGE.value,
    "elemental_damage": ContributionKind.DAMAGE.value,
    "lightning_damage": ContributionKind.DAMAGE.value,
    "fire_damage": ContributionKind.DAMAGE.value,
    "cold_damage": ContributionKind.DAMAGE.value,
    "physical_damage": ContributionKind.DAMAGE.value,
    "accuracy": ContributionKind.DAMAGE.value,
    "life": ContributionKind.DEFENCE.value,
    "energy_shield": ContributionKind.DEFENCE.value,
    "es_recharge": ContributionKind.RECOVERY.value,
    "life_regen": ContributionKind.RECOVERY.value,
    "mana": ContributionKind.RESOURCE.value,
    "mana_regen": ContributionKind.RESOURCE.value,
    "spirit": ContributionKind.RESOURCE.value,
    "fire_res": ContributionKind.RESISTANCE.value,
    "cold_res": ContributionKind.RESISTANCE.value,
    "lightning_res": ContributionKind.RESISTANCE.value,
    "chaos_res": ContributionKind.RESISTANCE.value,
    "all_res": ContributionKind.RESISTANCE.value,
    "strength": ContributionKind.ATTRIBUTE.value,
    "dexterity": ContributionKind.ATTRIBUTE.value,
    "intelligence": ContributionKind.ATTRIBUTE.value,
    "all_attributes": ContributionKind.ATTRIBUTE.value,
    "armour": ContributionKind.DEFENCE.value,
    "evasion": ContributionKind.DEFENCE.value,
    "block": ContributionKind.DEFENCE.value,
    "skill_gem_levels": ContributionKind.ENABLER.value,
    "leech": ContributionKind.RECOVERY.value,
}

_RES_FAMILY = {"fire_res": "fire", "cold_res": "cold", "lightning_res": "lightning", "chaos_res": "chaos", "all_res": "all"}

_SYNERGY_PACKAGES = (
    (("crit_chance", "crit_multi"), "crit"),
    (("spell_damage", "cast_speed"), "spell_tempo"),
    (("physical_damage", "attack_speed"), "attack_scaling"),
    (("life", "fire_res"), "life_res"),
    (("life", "cold_res"), "life_res"),
    (("life", "lightning_res"), "life_res"),
    (("energy_shield",), "local_es"),
    (("mana_regen", "mana"), "resource"),
)


def _pct(axis: AxisDelta | None) -> float:
    if not axis or axis.percent_delta is None:
        return 0.0
    if axis.delta_kind in {"UNMEASURED", "UNSUPPORTED", "MISSING", "ESTIMATED"}:
        return 0.0
    return float(axis.percent_delta)


def _role_from_evidence(
    *,
    family: str,
    kind: str,
    axes: dict[str, AxisDelta],
    thresholds: list[ThresholdEvent],
    resist: dict[str, Any],
    offense_zero: bool,
) -> tuple[str, list[str], str, float]:
    reasons: list[str] = []
    threshold_relation = ""
    strength = 0.0

    for event in thresholds:
        if event.is_build_fix and _event_matches_family(event, family):
            return BuildRole.CORE.value, [event.code], event.code, 1.0
        if event.is_hard_break and _event_matches_family(event, family):
            return BuildRole.HARMFUL.value, [event.code], event.code, -1.0

    element = _RES_FAMILY.get(family)
    if element:
        info = ((resist.get("elements") or {}).get(element if element != "all" else "fire") or {})
        state = str(info.get("state") or "")
        if family == "all_res":
            states = {str((item or {}).get("state") or "") for item in (resist.get("elements") or {}).values()}
            if CapState.CAP_REACHED.value in states:
                return BuildRole.CORE.value, ["RES_CAP_REACHED"], "RES_CAP_REACHED", 1.0
            if CapState.CAP_LOST.value in states:
                return BuildRole.HARMFUL.value, ["RES_CAP_LOST"], "RES_CAP_LOST", -1.0
            if states <= {
                CapState.CAPPED_STAYS_CAPPED.value,
                CapState.OVER_CAP_REDUCED_BUT_STILL_CAPPED.value,
                "",
            }:
                return BuildRole.REDUNDANT.value, ["OVERCAP"], "OVERCAP", 0.05
        if state == CapState.CAP_REACHED.value:
            return BuildRole.CORE.value, ["RES_CAP_REACHED"], "RES_CAP_REACHED", 1.0
        if state == CapState.CAP_LOST.value:
            return BuildRole.HARMFUL.value, ["RES_CAP_LOST"], "RES_CAP_LOST", -1.0
        if state in {CapState.CAPPED_STAYS_CAPPED.value, CapState.OVER_CAP_REDUCED_BUT_STILL_CAPPED.value}:
            return BuildRole.REDUNDANT.value, ["OVERCAP"], "OVERCAP", 0.05
        if state == CapState.BELOW_CAP_IMPROVED.value:
            return BuildRole.IMPORTANT.value, ["BELOW_CAP_IMPROVED"], "BELOW_CAP_IMPROVED", 0.7
        if state == CapState.BELOW_CAP_WORSENED.value:
            return BuildRole.HARMFUL.value, ["BELOW_CAP_WORSENED"], "BELOW_CAP_WORSENED", -0.6

    if kind == ContributionKind.DAMAGE.value:
        axis = axes.get(AxisId.OFFENSE.value)
        if offense_zero or (axis and axis.delta_kind in {"MEASURED_ZERO", "UNMEASURED", "UNSUPPORTED", "MISSING", "ESTIMATED"}):
            if axis and axis.delta_kind == "MEASURED_ZERO":
                return BuildRole.REDUNDANT.value, ["LOW_MARGINAL_VALUE"], "MEASURED_ZERO", 0.0
            if axis and axis.delta_kind in {"UNMEASURED", "UNSUPPORTED", "ESTIMATED"}:
                return BuildRole.NEUTRAL.value, [str(axis.delta_kind)], axis.delta_kind, 0.0
        pct = _pct(axis)
        strength = pct / 12.0
        if pct >= 8:
            return BuildRole.CORE.value, ["OFFENSE_GAIN"], "DAMAGE", min(1.0, strength)
        if pct >= 3:
            return BuildRole.IMPORTANT.value, ["OFFENSE_GAIN"], "DAMAGE", min(1.0, strength)
        if pct >= 1:
            return BuildRole.USEFUL.value, ["OFFENSE_GAIN"], "DAMAGE", min(1.0, strength)
        if pct <= -3:
            return BuildRole.HARMFUL.value, ["OFFENSE_LOSS"], "DAMAGE", max(-1.0, strength)

    if kind == ContributionKind.DEFENCE.value:
        pct = _pct(axes.get(AxisId.DEFENCE.value))
        strength = pct / 10.0
        if pct >= 8:
            return BuildRole.CORE.value, ["DEFENCE_GAIN"], "DEFENCE", min(1.0, strength)
        if pct >= 3:
            return BuildRole.IMPORTANT.value, ["DEFENCE_GAIN"], "DEFENCE", min(1.0, strength)
        if pct >= 1:
            return BuildRole.USEFUL.value, ["DEFENCE_GAIN"], "DEFENCE", min(1.0, strength)
        if pct <= -3:
            return BuildRole.HARMFUL.value, ["DEFENCE_LOSS"], "DEFENCE", max(-1.0, strength)

    if kind == ContributionKind.MOBILITY.value:
        pct = _pct(axes.get(AxisId.MOBILITY.value))
        strength = pct / 8.0
        if pct <= -20:
            return BuildRole.HARMFUL.value, ["MAJOR_MOBILITY_LOSS"], "MOBILITY", max(-1.0, strength)
        if pct <= -4:
            return BuildRole.HARMFUL.value, ["MOBILITY_LOSS"], "MOBILITY", max(-1.0, strength)
        if pct >= 4:
            return BuildRole.IMPORTANT.value, ["MOBILITY_GAIN"], "MOBILITY", min(1.0, strength)
        if abs(pct) < 0.4:
            return BuildRole.NEUTRAL.value, ["MOBILITY_STABLE"], "MOBILITY", 0.0
        return BuildRole.USEFUL.value if pct > 0 else BuildRole.HARMFUL.value, ["MOBILITY"], "MOBILITY", strength

    if kind == ContributionKind.RESOURCE.value:
        axis = axes.get(AxisId.RESOURCE.value)
        if axis and axis.delta_kind == "UNMEASURED":
            return BuildRole.NEUTRAL.value, ["UNMEASURED"], "UNMEASURED", 0.0
        abs_delta = float(axis.absolute_delta or 0) if axis else 0.0
        if abs_delta > 0.05:
            return BuildRole.IMPORTANT.value, ["RESOURCE_GAIN"], "RESOURCE", 0.6
        if abs_delta < -0.05:
            return BuildRole.HARMFUL.value, ["RESOURCE_LOSS"], "RESOURCE", -0.6

    if kind == ContributionKind.RECOVERY.value:
        axis = axes.get(AxisId.RECOVERY.value)
        if axis and axis.delta_kind == "UNMEASURED":
            return BuildRole.NEUTRAL.value, ["UNMEASURED"], "UNMEASURED", 0.0
        pct = _pct(axis)
        if pct >= 3:
            return BuildRole.IMPORTANT.value, ["RECOVERY_GAIN"], "RECOVERY", 0.6
        if pct <= -3:
            return BuildRole.HARMFUL.value, ["RECOVERY_LOSS"], "RECOVERY", -0.6

    if kind == ContributionKind.ENABLER.value and family == "skill_gem_levels":
        axis = axes.get(AxisId.OFFENSE.value)
        if axis and axis.delta_kind in {"UNMEASURED", "UNSUPPORTED", "ESTIMATED"}:
            return BuildRole.NEUTRAL.value, [str(axis.delta_kind)], str(axis.delta_kind), 0.0
        pct = _pct(axis)
        strength = pct / 10.0
        if pct >= 8:
            return BuildRole.CORE.value, ["SKILL_LEVEL_GAIN"], "SKILL_LEVEL", min(1.0, strength)
        if pct >= 3:
            return BuildRole.IMPORTANT.value, ["SKILL_LEVEL_GAIN"], "SKILL_LEVEL", min(1.0, strength)
        if pct >= 1:
            return BuildRole.USEFUL.value, ["SKILL_LEVEL_GAIN"], "SKILL_LEVEL", min(1.0, strength)
        if pct <= -3:
            return BuildRole.HARMFUL.value, ["SKILL_LEVEL_LOSS"], "SKILL_LEVEL", max(-1.0, strength)

    del reasons
    if threshold_relation:
        return BuildRole.USEFUL.value, reasons, threshold_relation, strength
    return BuildRole.NEUTRAL.value, ["NO_MEASURED_IMPACT"], "", 0.0


def _event_matches_family(event: ThresholdEvent, family: str) -> bool:
    metric = event.metric
    if family in {"fire_res", "cold_res", "lightning_res", "chaos_res"} and metric == family:
        return True
    if family == "all_res" and metric.endswith("_res"):
        return True
    if family in {"strength", "dexterity", "intelligence"} and metric == family:
        return True
    if kind_guess := _FAMILY_KIND.get(family):
        if kind_guess == ContributionKind.RESOURCE.value and event.metric == "mana_sustain":
            return True
        if kind_guess == ContributionKind.DAMAGE.value and event.metric == "primary_offense":
            return True
        if kind_guess == ContributionKind.DEFENCE.value and event.metric == "ehp":
            return True
    return False


def assign_build_mods(
    semantic: ItemSemanticModel,
    *,
    axes: dict[str, AxisDelta],
    thresholds: list[ThresholdEvent],
    resist: dict[str, Any],
) -> list[BuildMod]:
    offense = axes.get(AxisId.OFFENSE.value)
    offense_zero = bool(offense and offense.delta_kind == "MEASURED_ZERO")
    mods: list[BuildMod] = []
    for fact in [*semantic.properties, *semantic.mods]:
        kind = _FAMILY_KIND.get(fact.family, ContributionKind.UTILITY.value)
        if fact.base_related:
            kind = ContributionKind.BASE.value if kind == ContributionKind.UTILITY.value else kind
        role, reasons, relation, strength = _role_from_evidence(
            family=fact.family,
            kind=kind if kind != ContributionKind.BASE.value else _FAMILY_KIND.get(fact.family, ContributionKind.DEFENCE.value),
            axes=axes,
            thresholds=thresholds,
            resist=resist,
            offense_zero=offense_zero,
        )
        # Static taxonomy must never mint CORE without evaluation/threshold support.
        if role == BuildRole.CORE.value and not reasons:
            role = BuildRole.NEUTRAL.value
        confidence = BuildConfidence.HIGH.value if reasons and reasons != ["NO_MEASURED_IMPACT"] else BuildConfidence.ASSISTED.value
        mods.append(
            BuildMod(
                family=fact.family,
                source=fact.source,
                raw_text=fact.raw_text,
                raw_value=fact.raw_value,
                base_related=fact.base_related,
                build_role=role,
                contribution_kind=kind,
                contribution_strength=round(float(strength), 4),
                reason_codes=reasons,
                threshold_relation=threshold_relation if (threshold_relation := relation) else "",
                synergy_tags=list(fact.synergy_tags),
                redundancy_group="overcap" if "OVERCAP" in reasons else "",
                confidence=confidence,
                group=fact.group,
            )
        )
    return mods


def candidate_synergy(semantic: ItemSemanticModel) -> list[SynergyFinding]:
    families = {item.family for item in [*semantic.properties, *semantic.mods]}
    findings: list[SynergyFinding] = []
    seen: set[str] = set()
    for members, name in _SYNERGY_PACKAGES:
        if len(members) == 1:
            continue
        if all(member in families for member in members) and name not in seen:
            seen.add(name)
            findings.append(
                SynergyFinding(
                    groups=list(members),
                    kind=SynergyKind.UNMEASURED.value,
                    measured=False,
                    detail=f"{' + '.join(members)} present; synergy unmeasured on first paint",
                )
            )
    return findings


def rank_groups_for_decomposition(mods: list[BuildMod], *, limit: int = 5) -> list[str]:
    ranked: list[tuple[float, str]] = []
    seen: set[str] = set()
    for mod in mods:
        group = mod.group or mod.family
        if not group or group in seen or group == "other":
            continue
        seen.add(group)
        weight = abs(float(mod.contribution_strength or 0.0))
        if mod.build_role == BuildRole.CORE.value:
            weight += 2.0
        elif mod.build_role == BuildRole.IMPORTANT.value:
            weight += 1.0
        elif mod.build_role == BuildRole.HARMFUL.value:
            weight += 1.2
        elif mod.build_role == BuildRole.REDUNDANT.value:
            weight += 0.2
        ranked.append((weight, group))
    ranked.sort(reverse=True)
    return [group for _weight, group in ranked[:limit]]


def important_mod_rows(mods: list[BuildMod], *, limit: int = 4) -> list[dict[str, Any]]:
    order = {
        BuildRole.CORE.value: 0,
        BuildRole.IMPORTANT.value: 1,
        BuildRole.HARMFUL.value: 2,
        BuildRole.USEFUL.value: 3,
        BuildRole.REDUNDANT.value: 4,
        BuildRole.NEUTRAL.value: 5,
    }
    stars = {
        BuildRole.CORE.value: "★★★",
        BuildRole.IMPORTANT.value: "★★",
        BuildRole.USEFUL.value: "★",
        BuildRole.REDUNDANT.value: "—",
        BuildRole.NEUTRAL.value: "—",
        BuildRole.HARMFUL.value: "↓",
    }
    selected = [mod for mod in mods if mod.build_role != BuildRole.NEUTRAL.value or abs(mod.contribution_strength) > 0]
    selected.sort(key=lambda item: (order.get(item.build_role, 9), -abs(item.contribution_strength)))
    rows = []
    seen_group: set[str] = set()
    for mod in selected:
        key = mod.group or mod.family
        if key in seen_group:
            continue
        seen_group.add(key)
        rows.append(
            {
                "stars": stars.get(mod.build_role, "—"),
                "role": mod.build_role,
                "label": group_label(mod.group or mod.family),
                "text": mod.raw_text,
                "family": mod.family,
                "reason_codes": list(mod.reason_codes),
            }
        )
        if len(rows) >= limit:
            break
    return rows
