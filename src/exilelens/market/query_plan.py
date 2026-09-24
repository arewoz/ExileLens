from __future__ import annotations

from typing import Any

from exilelens.items.slots import ProductSlot, product_slot_to_pob
from exilelens.market.models import (
    DEPTH_EVAL_LIMITS,
    DEPTH_PREFILTER_LIMITS,
    ListingPrice,
    MarketQueryPlan,
    MarketSearchRequest,
    SearchDepth,
)
from exilelens.market.trade_url import trade_site_search_hint


def build_query_plan(
    intent: dict[str, Any],
    request: MarketSearchRequest,
) -> MarketQueryPlan:
    depth = request.depth if isinstance(request.depth, SearchDepth) else SearchDepth(str(request.depth).upper())
    slot = request.slot or str(intent.get("slot") or "")
    pob_slot = str(intent.get("pob_slot") or product_slot_to_pob(ProductSlot(slot)))
    budget = None
    if request.budget_amount is not None and request.budget_currency:
        budget = ListingPrice(amount=float(request.budget_amount), currency=str(request.budget_currency))

    required = list(intent.get("required") or [])
    high_value = list(intent.get("high_value") or [])
    useful = list(intent.get("useful") or [])
    avoid = list(intent.get("avoid") or [])

    filters: list[dict[str, Any]] = []
    for row in required:
        filters.append({"tier": "REQUIRED", "stat": row.get("stat"), "probe_id": row.get("probe_id"), "minimum": row.get("minimum")})
    for row in high_value[:6]:
        filters.append({"tier": "HIGH_VALUE", "stat": row.get("stat"), "probe_id": row.get("probe_id")})
    for row in avoid[:4]:
        filters.append({"tier": "AVOID", "stat": row.get("stat"), "probe_id": row.get("probe_id")})

    return MarketQueryPlan(
        slot=slot,
        pob_slot=pob_slot,
        profile=str(request.profile or intent.get("profile") or "BALANCED"),
        budget=budget,
        depth=depth.value,
        max_evaluations=DEPTH_EVAL_LIMITS[depth],
        prefilter_limit=DEPTH_PREFILTER_LIMITS[depth],
        intent_summary={
            "required_count": len(required),
            "high_value_count": len(high_value),
            "useful_count": len(useful),
            "avoid_count": len(avoid),
            "opportunity_score": intent.get("opportunity_score"),
            "opportunity_band": intent.get("opportunity_band"),
        },
        filters=filters,
        trade_site_hint=trade_site_search_hint(intent),
    )
