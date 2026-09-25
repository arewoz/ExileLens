"""Bounded whole-item counterfactual decomposition. No power-set search."""

from __future__ import annotations

from typing import Any

from exilelens.items.build_intel.cache import decomposition_cache_key
from exilelens.items.build_intel.item_semantics import ItemSemanticModel, group_label, strip_group_lines
from exilelens.items.build_intel.models import GroupContribution, SynergyFinding, SynergyKind
from exilelens.items.ranking import enrich_slot_comparison
from exilelens.items.value_profiles import ValueProfile

MAX_GROUP_PROBES = 5
MAX_SYNERGY_PAIRS = 2
MAX_TOTAL_RECALCS = 8
SYNERGY_GAP = 0.8


def _score(result: dict[str, Any]) -> float:
    value = result.get("value") or {}
    try:
        return float(value.get("score_delta") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _evaluate_variant(
    engine: Any,
    *,
    slot: str,
    item_raw: str,
    context: str,
    baseline: dict[str, Any],
    restore_template: dict[str, Any],
    primary_field: str,
    primary_confidence: str,
    profile: str,
    offense_coverage: dict[str, Any] | None,
) -> tuple[dict[str, Any], int]:
    evaluation = engine.evaluate_candidate(slot, item_raw, context=context)
    comparison = enrich_slot_comparison(
        {
            "product_slot": "",
            "pob_slot": slot,
            "baseline": evaluation.get("baseline") or baseline,
            "candidate": evaluation.get("candidate") or {},
            "restore": evaluation.get("restore") or restore_template,
        },
        primary_field=primary_field,
        primary_confidence=primary_confidence,
        profile=ValueProfile(str(profile).upper()),
        offense_coverage=offense_coverage,
    )
    return comparison, 1


def run_bounded_decomposition(
    engine: Any,
    *,
    slot: str,
    item_raw: str,
    semantic: ItemSemanticModel,
    groups: list[str],
    whole_comparison: dict[str, Any],
    context: str = "MAP",
    profile: str = "BALANCED",
    primary_field: str = "CombinedDPS",
    primary_confidence: str = "high",
    offense_coverage: dict[str, Any] | None = None,
    cache: dict[str, dict[str, Any]] | None = None,
    cache_key: str = "",
) -> dict[str, Any]:
    """Evaluate whole item first (already done), then drop top semantic groups.

    Budget: at most MAX_GROUP_PROBES leave-one-group probes plus MAX_SYNERGY_PAIRS
    pair probes, hard-capped at MAX_TOTAL_RECALCS. Never 2^n combinations.
    """
    if cache is not None and cache_key and cache_key in cache:
        return dict(cache[cache_key])

    whole_score = _score(whole_comparison)
    baseline = whole_comparison.get("baseline") or {}
    restore = whole_comparison.get("restore") or {"pass": True}
    selected = [group for group in groups if semantic.groups.get(group)][:MAX_GROUP_PROBES]
    contributions: list[GroupContribution] = []
    recalcs = 0
    without_scores: dict[str, float] = {}

    for group in selected:
        if recalcs >= MAX_TOTAL_RECALCS:
            break
        texts = list(semantic.groups.get(group) or [])
        variant = strip_group_lines(item_raw, texts)
        if variant.strip() == (item_raw or "").strip():
            contributions.append(
                GroupContribution(
                    group=group,
                    label=group_label(group),
                    whole_score_delta=whole_score,
                    without_group_score_delta=whole_score,
                    marginal=0.0,
                    measured=False,
                    reason="group lines not removable",
                )
            )
            continue
        comparison, used = _evaluate_variant(
            engine,
            slot=slot,
            item_raw=variant,
            context=context,
            baseline=baseline,
            restore_template=restore,
            primary_field=primary_field,
            primary_confidence=primary_confidence,
            profile=profile,
            offense_coverage=offense_coverage,
        )
        recalcs += used
        without = _score(comparison)
        without_scores[group] = without
        contributions.append(
            GroupContribution(
                group=group,
                label=group_label(group),
                whole_score_delta=whole_score,
                without_group_score_delta=without,
                marginal=round(whole_score - without, 3),
                measured=True,
                pob_recalcs=used,
                reason="leave-one-group",
            )
        )

    synergy: list[SynergyFinding] = []
    pair_candidates = [item.group for item in contributions if item.measured][:4]
    pairs: list[tuple[str, str]] = []
    if "crit" in pair_candidates:
        # crit is already a group; pair with spell or attack if present
        for other in pair_candidates:
            if other != "crit":
                pairs.append(("crit", other))
                break
    if "spell_damage" in pair_candidates and "cast_speed" in pair_candidates:
        pairs.append(("spell_damage", "cast_speed"))
    if "life" in pair_candidates and "resistance" in pair_candidates:
        pairs.append(("life", "resistance"))
    if "local_es" in pair_candidates and "base_es" in pair_candidates:
        pairs.append(("local_es", "base_es"))
    if "flat_pct_damage" in pair_candidates and "attack_speed" in pair_candidates:
        pairs.append(("flat_pct_damage", "attack_speed"))

    seen_pairs: set[tuple[str, str]] = set()
    for left, right in pairs:
        key = tuple(sorted((left, right)))
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        if len(synergy) >= MAX_SYNERGY_PAIRS or recalcs >= MAX_TOTAL_RECALCS:
            break
        texts = list(semantic.groups.get(left) or []) + list(semantic.groups.get(right) or [])
        variant = strip_group_lines(item_raw, texts)
        comparison, used = _evaluate_variant(
            engine,
            slot=slot,
            item_raw=variant,
            context=context,
            baseline=baseline,
            restore_template=restore,
            primary_field=primary_field,
            primary_confidence=primary_confidence,
            profile=profile,
            offense_coverage=offense_coverage,
        )
        recalcs += used
        without_both = _score(comparison)
        impact_ab = whole_score - without_both
        impact_a = whole_score - without_scores.get(left, whole_score)
        impact_b = whole_score - without_scores.get(right, whole_score)
        additive = impact_a + impact_b
        gap = impact_ab - additive
        if abs(gap) < SYNERGY_GAP:
            kind = SynergyKind.DIMINISHING_OVERLAP.value if gap < 0 else SynergyKind.POSITIVE_SYNERGY.value
            # Near-additive is not a finding.
            continue
        kind = SynergyKind.POSITIVE_SYNERGY.value if gap > 0 else SynergyKind.DIMINISHING_OVERLAP.value
        synergy.append(
            SynergyFinding(
                groups=[left, right],
                kind=kind,
                measured=True,
                impact_a=round(impact_a, 3),
                impact_b=round(impact_b, 3),
                impact_ab=round(impact_ab, 3),
                additive_expect=round(additive, 3),
                detail=f"{group_label(left)} + {group_label(right)} {kind.lower().replace('_', ' ')}",
            )
        )

    payload = {
        "status": "COMPLETE",
        "contribution": [item.to_dict() for item in contributions],
        "synergy": [item.to_dict() for item in synergy],
        "pob_recalcs": recalcs,
        "groups": selected,
        "cache_key": cache_key or decomposition_cache_key(slot=slot, item_raw=item_raw, profile=profile),
    }
    if cache is not None and payload["cache_key"]:
        cache[str(payload["cache_key"])] = dict(payload)
    return payload
