from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable

from exilelens.items.raw_input import RawItemInput
from exilelens.price_check.market_drivers import estimate_state_for
from exilelens.price_check.price_trust import apply_price_trust
from exilelens.price_check.comparable_pricing import build_band_estimate
from exilelens.price_check.comparable_query import (
    ComparableSearchQuery,
    RelaxationTier,
    build_search_query,
    listing_matches_query,
    with_relaxation,
)
from exilelens.price_check.models import (
    ComparableListing,
    LeagueStatus,
    PriceCheckRequest,
    PriceCheckResult,
    PriceConfidence,
    PriceEstimate,
    PriceSourceKind,
)


@dataclass(frozen=True)
class CorpusListing:
    listing_id: str
    item_raw: str
    price_amount: float
    price_currency: str
    source: str
    league: str | None = None
    seller_id: str | None = None
    captured_at: str | None = None

    def to_comparable(self) -> ComparableListing:
        return ComparableListing(
            listing_id=self.listing_id,
            item_raw=self.item_raw,
            price_amount=self.price_amount,
            price_currency=self.price_currency,
            source=self.source,
            league=self.league,
            seller_id=self.seller_id,
            captured_at=self.captured_at,
        )


def comparable_listing_from_row(row: dict[str, Any], *, source: str) -> CorpusListing | None:
    item_raw = str(row.get("item_raw") or "").strip()
    if not item_raw:
        return None
    price = row.get("price") or {}
    amount = price.get("amount")
    currency = price.get("price_currency") or price.get("currency")
    if amount is None or not currency:
        amount = row.get("price_amount")
        currency = row.get("price_currency")
    if amount is None or not currency:
        return None
    listing_id = str(row.get("listing_id") or row.get("id") or RawItemInput.from_text(item_raw).content_hash[:16])
    return CorpusListing(
        listing_id=listing_id,
        item_raw=item_raw,
        price_amount=float(amount),
        price_currency=str(currency),
        source=source,
        league=row.get("league"),
        seller_id=row.get("seller_id"),
        captured_at=row.get("captured_at"),
    )


class ComparableMarketEngine:
    """Search comparable corpus with relaxation tiers and estimate price bands."""

    def __init__(
        self,
        listings: Iterable[CorpusListing] | Callable[[], list[CorpusListing]],
        *,
        provider_id: str,
        source_kind: PriceSourceKind,
        min_comparables: int = 3,
    ) -> None:
        self._listings_fn = listings if callable(listings) else (lambda: list(listings))
        self._provider_id = provider_id
        self._source_kind = source_kind
        self._min_comparables = min_comparables

    def lookup(self, request: PriceCheckRequest) -> PriceCheckResult | None:
        base_query = build_search_query(
            request.item_raw,
            league=request.league.league,
        )
        if request.hypothesis is not None:
            base_query = replace(base_query, hypothesis=request.hypothesis)
        if not base_query.base_type:
            return None

        corpus = self._listings_fn()
        for tier in (
            RelaxationTier.STRICT,
            RelaxationTier.RELAXED_MODS,
            RelaxationTier.PSEUDO_EQUIV,
            RelaxationTier.DROP_LOWEST_HIGH,
            RelaxationTier.BASE_AND_RARITY,
            RelaxationTier.BASE_ONLY,
            RelaxationTier.ULTRA_LOOSE,
        ):
            query = with_relaxation(base_query, tier)
            matches = self._search_corpus(corpus, query, request)
            if len(matches) < self._min_comparables:
                continue
            comparable_matches = tuple(row.to_comparable() for row in matches)
            band, confidence, kept = build_band_estimate(
                comparable_matches,
                query=query,
                league_known=request.league.status == LeagueStatus.KNOWN,
            )
            if band is None:
                continue
            comparables = comparable_matches[:5]
            summary = (
                f"{len(kept)} comparable listing{'s' if len(kept) != 1 else ''}"
                if len(kept) != len(matches)
                else f"{len(matches)} comparable listing{'s' if len(matches) != 1 else ''}"
            )
            estimate = PriceEstimate(
                source_kind=self._source_kind,
                confidence=confidence,
                currency_bands=band.to_currency_bands(),
                comparables=comparables,
                summary=summary,
                disclaimer=self._disclaimer_for(source_kind=self._source_kind),
            )
            hypo = query.hypothesis
            return apply_price_trust(
                PriceCheckResult(
                    request=request,
                    estimate=estimate,
                    provider_id=self._provider_id,
                    comparable_count=len(matches),
                    search_basis=query.search_basis,
                    matched_features=query.matched_summary(),
                    identity_source=query.economic_identity.source.value,
                    search_relaxation_tier=int(tier),
                    hypothesis=hypo,
                    estimate_state=estimate_state_for(hypo).value if hypo is not None else "",
                )
            )
        return None

    def _search_corpus(
        self,
        corpus: list[CorpusListing],
        query: ComparableSearchQuery,
        request: PriceCheckRequest,
    ) -> list[CorpusListing]:
        matches: list[CorpusListing] = []
        for row in corpus:
            if request.league.status == LeagueStatus.KNOWN and row.league:
                if str(row.league).lower() != str(request.league.league or "").lower():
                    continue
            if listing_matches_query(row.item_raw, query):
                matches.append(row)
        return matches

    @staticmethod
    def _disclaimer_for(*, source_kind: PriceSourceKind) -> str:
        if source_kind == PriceSourceKind.LIVE_MARKET:
            return "Live trade comparables — verify listing before trading."
        if source_kind == PriceSourceKind.OBSERVATION_CORPUS:
            return "Based on captured session observations — not live market."
        return "Comparable market estimate from offline corpus."
