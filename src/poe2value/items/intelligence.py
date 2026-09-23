"""ITEM-PRO-01 fast-path enrichment — no extra PoB recalcs."""

from __future__ import annotations

from typing import Any

from poe2value.items.best_slot import best_slot_label, rank_comparisons_guardrail_first, select_best_comparison
from poe2value.items.build_intel.engine import attach_build_intelligence
from poe2value.items.decision import RecommendationStyle, build_decision_summary
from poe2value.items.multi_profile import score_all_profiles
from poe2value.items.presentation import PopupDensity, build_presentation
from poe2value.items.upgrade_path import attach_upgrade_path_presentation
from poe2value.items.ranking import rank_slot_comparisons
from poe2value.items.value_profiles import ValueProfile


def parse_profile(value: str | ValueProfile | None) -> ValueProfile:
    if isinstance(value, ValueProfile):
        return value
    if not value:
        return ValueProfile.BALANCED
    return ValueProfile(str(value).upper())


def enrich_fast_result(
    payload: dict[str, Any],
    *,
    recommendation_style: str = RecommendationStyle.BALANCED.value,
    popup_density: str = PopupDensity.COMPACT.value,
    multi_profile_enabled: bool = True,
    decision_enabled: bool = True,
    best_slot_enabled: bool = True,
    build_name: str = "",
    loadout_name: str = "",
    item_set_name: str = "",
    context: str = "MAP",
) -> dict[str, Any]:
    """Attach decision intelligence, best slot, and multi-profile without PoB."""
    result = dict(payload)
    primary = result.get("primary_metric") or {}
    comparisons = list(result.get("slot_comparisons") or [])
    profile = parse_profile(result.get("value_profile"))

    if best_slot_enabled and comparisons:
        ranked = rank_comparisons_guardrail_first(comparisons)
        best = select_best_comparison(ranked) or ranked[0]
        result["slot_comparisons"] = ranked
        result["recommendation"] = best
        result["value"] = best.get("value")
        result["damage_claim"] = best.get("damage_claim") or (best.get("evaluation_outcome") or {}).get("damage_claim") or {}
        result["power_per_currency"] = best.get("power_per_currency")
        result["best_slot"] = {
            "pob_slot": best.get("pob_slot"),
            "product_slot": best.get("product_slot"),
            "label": best_slot_label(best),
        }
    else:
        ranking = rank_slot_comparisons(
            comparisons,
            profile=profile,
            primary_field=primary.get("pob_field") or "CombinedDPS",
            primary_confidence=primary.get("confidence") or "high",
            offense_coverage=result.get("offense_coverage"),
        )
        result["slot_comparisons"] = ranking["slot_comparisons"]
        result["recommendation"] = ranking["recommendation"]
        result["value"] = (ranking["recommendation"] or {}).get("value")
        selected = ranking["recommendation"] or {}
        result["damage_claim"] = selected.get("damage_claim") or (selected.get("evaluation_outcome") or {}).get("damage_claim") or {}
        result["power_per_currency"] = (ranking["recommendation"] or {}).get("power_per_currency")
        result["pareto"] = ranking["pareto"]
        best = ranking["recommendation"]

    if multi_profile_enabled and comparisons:
        result["multi_profile"] = score_all_profiles(
            comparisons,
            primary_field=primary.get("pob_field") or "CombinedDPS",
            primary_confidence=primary.get("confidence") or "high",
            offense_coverage=result.get("offense_coverage"),
        )
    else:
        result["multi_profile"] = None

    recommendation = result.get("recommendation") or {}
    if decision_enabled and recommendation:
        slot_label = (result.get("best_slot") or {}).get("label") or best_slot_label(recommendation)
        result["decision"] = build_decision_summary(
            recommendation,
            style=recommendation_style,
            primary_metric=primary,
            best_slot_label=slot_label,
        ).to_dict()
    else:
        result["decision"] = None

    result = attach_build_intelligence(result)

    result["presentation"] = build_presentation(
        result,
        build_name=build_name or str((result.get("build") or {}).get("build_name") or ""),
        loadout_name=loadout_name or str((result.get("build") or {}).get("active_loadout") or ""),
        item_set_name=item_set_name,
        context=context,
        value_profile=profile.value,
        popup_density=popup_density,
        decision_enabled=decision_enabled,
        multi_profile_enabled=multi_profile_enabled,
        best_slot_enabled=best_slot_enabled,
    )
    pending = bool((result.get("upgrade_potential") or {}).get("status") == "PENDING")
    if result.get("upgrade_potential") is not None or pending:
        return attach_upgrade_path_presentation(
            result,
            pending=pending,
            style=recommendation_style,
        )
    return result
