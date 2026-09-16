"""Offline (and optional live) market funnel diagnosis."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from poe2value.items.metadata import parse_lightweight_metadata
from poe2value.items.raw_input import RawItemInput
from poe2value.items.recognition import is_probable_poe2_item
from poe2value.ops.models import StageStatus
from poe2value.ops.paths import fixture_corpus_path, repo_root
from poe2value.price_check.comparable_pricing import build_band_estimate
from poe2value.price_check.comparable_query import (
    build_search_query,
    listing_matches_query,
    listing_similarity_score,
)
from poe2value.price_check.currency_fx import CurrencyFxTable
from poe2value.price_check.models import ComparableListing
from poe2value.price_check.trade2_query import build_trade2_search_body

STAGES = (
    "capture_item",
    "normalized_item",
    "compiled_query",
    "search",
    "listing_fetch",
    "listing_parse",
    "similarity",
    "accepted_comparables",
    "currency_normalization",
    "estimate",
    "presentation",
)


@dataclass
class MarketHealthReport:
    mode: str
    stages: dict[str, str]
    metrics: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def overall(self) -> str:
        values = list(self.stages.values())
        if StageStatus.FAIL.value in values:
            return StageStatus.FAIL.value
        if StageStatus.DEGRADED.value in values:
            return StageStatus.DEGRADED.value
        if all(value == StageStatus.NOT_CHECKED.value for value in values):
            return StageStatus.NOT_CHECKED.value
        return StageStatus.PASS.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "overall": self.overall,
            "stages": self.stages,
            "metrics": self.metrics,
            "notes": self.notes,
        }


def _stage_map() -> dict[str, str]:
    return {name: StageStatus.NOT_CHECKED.value for name in STAGES}


def load_default_fixtures(root: Path | None = None) -> tuple[str, list[dict[str, Any]]]:
    base = root or repo_root()
    corpus = json.loads(fixture_corpus_path(base).read_text(encoding="utf-8"))
    item_path = base / corpus["market"]["query_item"]
    listings_path = base / corpus["market"]["healthy_comparables"]
    item_raw = item_path.read_text(encoding="utf-8")
    payload = json.loads(listings_path.read_text(encoding="utf-8"))
    listings = list(payload.get("listings") or [])
    return item_raw, listings


def _listing_from_fixture(row: dict[str, Any]) -> ComparableListing | None:
    item_raw = str(row.get("item_raw") or "")
    price = row.get("price") if isinstance(row.get("price"), dict) else {}
    amount = price.get("amount")
    currency = str(price.get("currency") or "")
    if not item_raw or amount is None:
        return None
    return ComparableListing(
        listing_id=str(row.get("listing_id") or ""),
        item_raw=item_raw,
        price_amount=float(amount),
        price_currency=currency,
        source="fixture",
    )


def diagnose_offline(
    item_raw: str | None = None,
    listings_payload: list[dict[str, Any]] | None = None,
    *,
    league: str = "Standard",
    root: Path | None = None,
    fx_rates: dict[tuple[str, str], float] | None = None,
) -> MarketHealthReport:
    stages = _stage_map()
    metrics: dict[str, Any] = {"search_result_count": 0, "fetched_listings": 0, "parsed_listings": 0, "accepted_comparables": 0}
    notes: list[str] = ["mode=fixture/offline; live trade was not contacted"]
    if item_raw is None or listings_payload is None:
        item_raw, listings_payload = load_default_fixtures(root)

    recognized = is_probable_poe2_item(item_raw)
    stages["capture_item"] = StageStatus.PASS.value if recognized.recognized else StageStatus.FAIL.value
    if not recognized.recognized:
        notes.append(f"item not recognized: {recognized.reason}")
        return MarketHealthReport(mode="offline", stages=stages, metrics=metrics, notes=notes)

    meta = parse_lightweight_metadata(RawItemInput.from_text(item_raw))
    stages["normalized_item"] = StageStatus.PASS.value if meta.base_type else StageStatus.FAIL.value
    metrics["base_type"] = meta.base_type
    metrics["rarity"] = meta.rarity

    query = build_search_query(item_raw, league=league)
    body = build_trade2_search_body(query)
    stages["compiled_query"] = StageStatus.PASS.value if body.get("query") else StageStatus.FAIL.value
    metrics["query_type"] = (body.get("query") or {}).get("type")

    metrics["search_result_count"] = len(listings_payload)
    stages["search"] = StageStatus.PASS.value if listings_payload else StageStatus.FAIL.value
    stages["listing_fetch"] = stages["search"]
    metrics["fetched_listings"] = len(listings_payload)

    parsed: list[ComparableListing] = []
    for row in listings_payload:
        listing = _listing_from_fixture(row)
        if listing is not None:
            parsed.append(listing)
    metrics["parsed_listings"] = len(parsed)
    stages["listing_parse"] = StageStatus.PASS.value if parsed else StageStatus.FAIL.value

    scores: list[float] = []
    accepted: list[ComparableListing] = []
    for listing in parsed:
        score = listing_similarity_score(listing.item_raw, query)
        scores.append(score)
        if listing_matches_query(listing.item_raw, query):
            accepted.append(listing)
    metrics["similarity_scores"] = [round(score, 3) for score in scores[:12]]
    metrics["similarity_threshold"] = "listing_matches_query"
    if not scores:
        stages["similarity"] = StageStatus.FAIL.value
    elif accepted:
        stages["similarity"] = StageStatus.PASS.value
    else:
        stages["similarity"] = StageStatus.DEGRADED.value
        notes.append("listings parsed but none met similarity threshold")

    metrics["accepted_comparables"] = len(accepted)
    stages["accepted_comparables"] = (
        StageStatus.PASS.value if len(accepted) >= 3 else StageStatus.DEGRADED.value if accepted else StageStatus.FAIL.value
    )

    fx = CurrencyFxTable(league=league, client=None)
    if fx_rates:
        fx._rates.update(fx_rates)
    currencies = sorted({listing.price_currency for listing in accepted})
    metrics["currencies"] = currencies
    known = [currency for currency in currencies if fx.is_known_currency(currency)]
    stages["currency_normalization"] = StageStatus.PASS.value if known else StageStatus.DEGRADED.value
    metrics["fx_availability"] = bool(fx_rates) or len(set(fx.normalize_currency(c) for c in currencies)) <= 1
    if not fx_rates and len({fx.normalize_currency(c) for c in currencies}) > 1:
        stages["currency_normalization"] = StageStatus.DEGRADED.value
        notes.append("mixed currencies without fixture FX rates; conversion not proven")

    if accepted:
        band, confidence, _kept = build_band_estimate(
            accepted,
            query=query,
            league_known=True,
            fx_table=fx if fx_rates else None,
        )
        metrics["estimate_confidence"] = getattr(confidence, "value", str(confidence))
        if band is None:
            stages["estimate"] = StageStatus.DEGRADED.value
            notes.append("accepted comparables present but band estimate unavailable")
        else:
            metrics["estimate"] = {
                "quick_sale": band.quick_sale,
                "fair_low": band.fair_low,
                "fair_high": band.fair_high,
                "currency": band.currency,
                "sample_count": band.sample_count,
            }
            stages["estimate"] = StageStatus.PASS.value
    else:
        stages["estimate"] = StageStatus.FAIL.value

    stages["presentation"] = stages["estimate"]
    metrics["rate_limit"] = "not_applicable_offline"
    return MarketHealthReport(mode="offline", stages=stages, metrics=metrics, notes=notes)
