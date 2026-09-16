"""Single-item PoB evaluation for market capture (reuses Phase 5B path)."""

from __future__ import annotations

from typing import Any

from poe2value.items.price import ManualPrice, compute_power_per_currency
from poe2value.items.ranking import enrich_slot_comparison
from poe2value.items.raw_input import ItemInputSource, RawItemInput
from poe2value.items.value_layer import parse_profile
from poe2value.market.eval_cache import MarketEvalCache
from poe2value.market.engine import _evaluate_listing, _price_for_listing
from poe2value.market.models import CandidateListing, CandidateIdentity, ListingPrice
from poe2value.items.primary_metric import resolve_primary_metric


def evaluate_capture_observation(
    engine: Any,
    *,
    item_raw: str,
    product_slot: str,
    pob_slot: str,
    build_path: str,
    context: str,
    profile: str,
    price: ListingPrice | None,
    fingerprint: str,
    cache: MarketEvalCache | None = None,
    budget_currency: str | None = None,
) -> dict[str, Any]:
    """Evaluate one captured listing against the session target slot."""
    cache = cache or MarketEvalCache()
    listing = CandidateListing(
        identity=CandidateIdentity(
            listing_id="capture",
            content_hash=RawItemInput.from_text(item_raw, source=ItemInputSource.CLIPBOARD).content_hash,
            source="MARKET_CAPTURE",
        ),
        slot=product_slot,
        pob_slot=pob_slot,
        item_raw=item_raw,
        price=price,
    )
    loaded = engine.ensure_build_ready(build_path, context=context)
    build_info = loaded.get("build") or {}
    primary = resolve_primary_metric(build_info, loaded.get("metrics"))
    value_profile = parse_profile(profile)
    evaluation = _evaluate_listing(
        engine,
        listing,
        build_path=build_path,
        context=context,
        profile=value_profile,
        primary_field=primary.pob_field,
        primary_confidence=primary.confidence,
        pob_slot=pob_slot,
        fingerprint=fingerprint,
        cache=cache,
        budget_currency=budget_currency,
        rates=None,
    )
    manual = _price_for_listing(listing, budget_currency, None)
    if manual and evaluation.comparison:
        enriched = enrich_slot_comparison(
            evaluation.comparison,
            profile=value_profile,
            primary_field=primary.pob_field,
            primary_confidence=primary.confidence,
            price=manual,
        )
        evaluation.comparison = enriched
        evaluation.verdict = str(enriched.get("verdict") or evaluation.verdict)
        evaluation.build_value_delta = float((enriched.get("value") or {}).get("score_delta") or evaluation.build_value_delta)
        profile_gain = float((enriched.get("value") or {}).get("score_delta") or 0.0)
        evaluation.power_per_currency = compute_power_per_currency(profile_gain, manual)

    return {
        "comparison": evaluation.comparison,
        "build_value_delta": evaluation.build_value_delta,
        "offense_delta": evaluation.offense_delta,
        "defense_delta": evaluation.defense_delta,
        "verdict": evaluation.verdict,
        "power_per_currency": evaluation.power_per_currency,
        "restore_pass": evaluation.restore_pass,
        "cache_hit": evaluation.cache_hit,
        "status": evaluation.status,
        "error": evaluation.error,
    }
