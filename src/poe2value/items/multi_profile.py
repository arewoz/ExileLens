"""Multi-profile scoring bundle — zero extra PoB recalcs."""

from __future__ import annotations

from typing import Any

from poe2value.items.ranking import enrich_slot_comparison, rank_slot_comparisons
from poe2value.items.value_profiles import ValueProfile


def _public_verdict(comparison: dict[str, Any]) -> Any:
    outcome = comparison.get("evaluation_outcome") or {}
    return outcome.get("verdict") or comparison.get("verdict")


def score_all_profiles(
    comparisons: list[dict[str, Any]],
    *,
    primary_field: str = "CombinedDPS",
    primary_confidence: str = "high",
    offense_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score every profile from stored raw metrics. Does not call PoB."""
    if not comparisons:
        return {"profiles": {}, "best_by_profile": {}, "profile_order": []}

    base = enrich_slot_comparison(
        dict(comparisons[0]),
        primary_field=comparisons[0].get("primary_metric_field") or primary_field,
        primary_confidence=primary_confidence,
        profile=ValueProfile.BALANCED,
    )

    profiles: dict[str, Any] = {}
    best_by_profile: dict[str, dict[str, Any] | None] = {}
    for profile in ValueProfile:
        enriched = enrich_slot_comparison(
            {
                "product_slot": base.get("product_slot"),
                "pob_slot": base.get("pob_slot"),
                "baseline": base.get("baseline"),
                "candidate": base.get("candidate"),
                "restore": base.get("restore") or {"pass": True},
                "metric_profile": base.get("metric_profile"),
                "resist_caps": base.get("resist_caps"),
                "warnings": base.get("warnings"),
            },
            primary_field=primary_field,
            primary_confidence=primary_confidence,
            profile=profile,
            offense_coverage=offense_coverage,
        )
        value = enriched.get("value") or {}
        profiles[profile.value] = {
            "profile": profile.value,
            "rating": value.get("rating"),
            "score_delta": value.get("score_delta"),
            "verdict": _public_verdict(enriched),
            "ranking_verdict": enriched.get("verdict"),
            "best_slot": enriched.get("pob_slot"),
            "band": value.get("band"),
        }
        best_by_profile[profile.value] = enriched

    ranked = []
    for comparison in comparisons[1:]:
        ranked.append(
            enrich_slot_comparison(
                dict(comparison),
                primary_field=comparison.get("primary_metric_field") or primary_field,
                primary_confidence=primary_confidence,
                profile=ValueProfile.BALANCED,
                offense_coverage=offense_coverage,
            )
        )

    if len(comparisons) > 1:
        for profile in ValueProfile:
            ranking = rank_slot_comparisons(
                [base] + ranked,
                profile=profile,
                primary_field=primary_field,
                primary_confidence=primary_confidence,
                offense_coverage=offense_coverage,
            )
            recommendation = ranking.get("recommendation") or {}
            value = recommendation.get("value") or {}
            profiles[profile.value]["best_slot"] = recommendation.get("pob_slot")
            profiles[profile.value]["rating"] = value.get("rating")
            profiles[profile.value]["verdict"] = _public_verdict(recommendation)
            profiles[profile.value]["ranking_verdict"] = recommendation.get("verdict")
            best_by_profile[profile.value] = recommendation

    return {
        "profiles": profiles,
        "best_by_profile": best_by_profile,
        "profile_order": [profile.value for profile in ValueProfile],
    }
