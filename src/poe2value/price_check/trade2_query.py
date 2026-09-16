from __future__ import annotations

from dataclasses import replace
from typing import Any

from poe2value.price_check.comparable_features import ComparableFeature
from poe2value.price_check.comparable_query import ComparableSearchQuery, RelaxationTier
from poe2value.price_check.feature_fallback import select_economic_identity
from poe2value.price_check.market_drivers import (
    MatchMode,
    PriceCheckHypothesis,
    build_auto_hypothesis,
    canonical_search_min,
    hypothesis_to_search_body,
)
from poe2value.price_check.stat_registry import FloorKind, get_family
from poe2value.price_check.trade2_query_validation import ensure_valid_trade2_search_body

_PSEUDO_STAT_IDS = {
    "total_elemental_resistance": "pseudo.pseudo_total_elemental_resistance",
    "total_fire_resistance": "pseudo.pseudo_total_fire_resistance",
    "total_cold_resistance": "pseudo.pseudo_total_cold_resistance",
    "total_chaos_resistance": "pseudo.pseudo_total_chaos_resistance",
    "total_life": "pseudo.pseudo_total_life",
    "total_mana": "pseudo.pseudo_total_mana",
    "total_energy_shield": "pseudo.pseudo_total_energy_shield",
}


def relaxed_query_min_value(value: float, tier: RelaxationTier, *, family: str | None = None) -> float:
    """Canonical floors on the assisted path. The 75/55/40 ladder is retired as policy.

    `tier` is kept for diagnostics and older callers. STRICT uses the canonical
    haircut; any later diagnostic tier only widens slightly, never to 40%.
    """
    record = get_family(family or "")
    floor, _policy = canonical_search_min(
        family or "",
        value,
        floor_kind=record.floor_kind if record else FloorKind.INTEGER_SMALL,
        affix_range=record.affix_range if record else None,
    )
    if tier == RelaxationTier.STRICT:
        return floor
    if tier == RelaxationTier.RELAXED_MODS:
        return max(1.0, round(floor * 0.92, 1))
    return max(1.0, round(floor * 0.85, 1))


def query_features_for_tier(
    features: tuple[ComparableFeature, ...],
    tier: RelaxationTier,
) -> tuple[ComparableFeature, ...]:
    identity_features = select_economic_identity(features).features
    ranked = sorted(
        identity_features,
        key=lambda row: (row.importance.value != "CRITICAL", -row.value),
    )
    if not ranked:
        return ()
    if tier == RelaxationTier.STRICT:
        return tuple(ranked[: min(3, len(ranked))])
    if tier == RelaxationTier.RELAXED_MODS:
        return tuple(ranked)
    if tier == RelaxationTier.PSEUDO_EQUIV:
        pseudo_rows: list[ComparableFeature] = []
        for row in ranked:
            pseudo_id = _PSEUDO_STAT_IDS.get(row.pseudo_family or "")
            if not pseudo_id:
                continue
            pseudo_rows.append(
                ComparableFeature(
                    family=row.pseudo_family or row.family,
                    pseudo_family=row.pseudo_family,
                    value=row.value,
                    normalized_roll=row.normalized_roll,
                    tier=row.tier,
                    importance=row.importance,
                    market_role=row.market_role,
                    trade_stat_id=pseudo_id,
                    source_text=row.source_text,
                )
            )
        return tuple(pseudo_rows) if pseudo_rows else tuple(ranked[:1])
    if tier == RelaxationTier.DROP_LOWEST_HIGH:
        return tuple(ranked[:-1]) if len(ranked) > 1 else tuple(ranked)
    return ()


def _hypothesis_for(query: ComparableSearchQuery) -> PriceCheckHypothesis:
    if query.hypothesis is not None:
        return query.hypothesis
    return build_auto_hypothesis(query.item_raw or "", league=query.league)


def build_trade2_search_body(query: ComparableSearchQuery) -> dict[str, Any]:
    """Assisted query: MarketPriceDriver hypothesis → Trade JSON. Validated locally."""
    if str(query.rarity or "").upper() == "UNIQUE" and query.item_name and query.base_type:
        body = {
            "query": {
                "status": {"option": "available"},
                "type": query.base_type,
                "name": query.item_name,
            },
            "sort": {"price": "asc"},
        }
        return ensure_valid_trade2_search_body(body)

    hypothesis = _hypothesis_for(query)
    if query.league and not hypothesis.league:
        hypothesis = replace(hypothesis, league=query.league)

    tier = query.relaxation_tier
    if tier >= RelaxationTier.BASE_ONLY:
        # Diagnostic / explicit base-only: type only. Never send the assisted
        # driver set or rarity under a BASE_ONLY relaxation.
        hypothesis = replace(
            hypothesis,
            selected_drivers=(),
            rarity=None,
            match_mode=MatchMode.ALL,
            count_min=None,
        )
    elif tier >= RelaxationTier.BASE_AND_RARITY:
        hypothesis = replace(
            hypothesis,
            selected_drivers=(),
            match_mode=MatchMode.ALL,
            count_min=None,
        )
    body = hypothesis_to_search_body(hypothesis)
    if query.item_name and str(query.rarity or "").upper() == "UNIQUE":
        body["query"]["name"] = query.item_name
    return ensure_valid_trade2_search_body(body)
