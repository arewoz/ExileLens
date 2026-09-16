from __future__ import annotations

from typing import Any

from poe2value.items.price import ManualPrice
from poe2value.items.item_check_settings import ItemCheckProSettings
from poe2value.items.ranking import rank_slot_comparisons
from poe2value.items.value_profiles import ValueProfile


def parse_profile(value: str | ValueProfile | None) -> ValueProfile:
    if isinstance(value, ValueProfile):
        return value
    if not value:
        return ValueProfile.BALANCED
    return ValueProfile(str(value).upper())


def rescore_evaluation(
    result: dict[str, Any],
    *,
    profile: str | ValueProfile,
    price: ManualPrice | None = None,
    build_name: str = "",
    loadout_name: str = "",
    item_set_name: str = "",
    context: str = "MAP",
    item_check_pro: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Re-interpret stored PoB metrics. Does not invoke Path of Building."""
    selected = parse_profile(profile)
    primary = result.get("primary_metric") or {}
    comparisons = list(result.get("slot_comparisons") or [])
    offense_coverage = result.get("offense_coverage")
    ranking = rank_slot_comparisons(
        comparisons,
        profile=selected,
        primary_field=primary.get("pob_field") or "CombinedDPS",
        primary_confidence=primary.get("confidence") or "high",
        price=price,
        offense_coverage=offense_coverage,
    )
    result = dict(result)
    result["slot_comparisons"] = ranking["slot_comparisons"]
    result["recommendation"] = ranking["recommendation"]
    result["pareto"] = ranking["pareto"]
    result["value_profile"] = selected.value
    rec = ranking["recommendation"] or {}
    result["value"] = rec.get("value")
    result["power_per_currency"] = rec.get("power_per_currency")
    if offense_coverage is not None:
        result["offense_coverage"] = offense_coverage
    if price is None:
        result.pop("manual_price", None)
    else:
        result["manual_price"] = price.to_dict()
    pro = ItemCheckProSettings.from_dict(item_check_pro)
    from poe2value.items.intelligence import enrich_fast_result

    return enrich_fast_result(
        result,
        recommendation_style=pro.recommendation_style,
        popup_density=pro.popup_density,
        multi_profile_enabled=pro.multi_profile,
        decision_enabled=pro.decision_intelligence,
        best_slot_enabled=pro.best_replacement_slot,
        build_name=build_name or str((result.get("build") or {}).get("build_name") or ""),
        loadout_name=loadout_name or str((result.get("build") or {}).get("active_loadout") or ""),
        item_set_name=item_set_name,
        context=context or str(result.get("request_meta", {}).get("context") or "MAP"),
    )


def attach_price(result: dict[str, Any], price: ManualPrice | None, **kwargs: Any) -> dict[str, Any]:
    profile = parse_profile(result.get("value_profile"))
    return rescore_evaluation(result, profile=profile, price=price, **kwargs)


def price_key(content_hash: str, baseline_identity: str) -> tuple[str, str]:
    return content_hash, baseline_identity
