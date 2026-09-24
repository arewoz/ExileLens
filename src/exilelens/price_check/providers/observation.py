from __future__ import annotations

from typing import Any, Callable

from exilelens.price_check.comparable_engine import ComparableMarketEngine, CorpusListing, comparable_listing_from_row
from exilelens.price_check.models import (
    LeagueStatus,
    PriceCheckRequest,
    PriceCheckResult,
    PriceConfidence,
    PriceSourceKind,
    ProviderCapabilities,
)


class ObservationCorpusProvider:
    """Matches user-captured market-assist observations with comparable band estimation."""

    provider_id = "observation_corpus"

    def __init__(self, observations_fn: Callable[[], list[dict[str, Any]]] | None = None) -> None:
        self._observations_fn = observations_fn or (lambda: [])
        self._engine = ComparableMarketEngine(
            self._corpus_listings,
            provider_id=self.provider_id,
            source_kind=PriceSourceKind.OBSERVATION_CORPUS,
            min_comparables=1,
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_comparables=True,
            supports_historical_prices=True,
            supports_price_ordering=False,
            supports_global_price_ordering=False,
            supports_league=True,
            source_kind=PriceSourceKind.OBSERVATION_CORPUS,
        )

    def _corpus_listings(self) -> list[CorpusListing]:
        rows: list[CorpusListing] = []
        for row in self._observations_fn():
            listing = comparable_listing_from_row(row, source=self.provider_id)
            if listing is not None:
                rows.append(listing)
        return rows

    def lookup(self, request: PriceCheckRequest) -> PriceCheckResult | None:
        from exilelens.price_check.models import CompiledPriceCheckRequest
        if isinstance(request, CompiledPriceCheckRequest):
            # Historical corpora are matched with legacy semantics, not this body.
            return None
        exact = self._exact_hash_match(request)
        if exact is not None:
            return exact
        return self._engine.lookup(request)

    def _exact_hash_match(self, request: PriceCheckRequest) -> PriceCheckResult | None:
        from exilelens.items.raw_input import RawItemInput
        from exilelens.price_check.models import ComparableListing, CurrencyBand, PriceEstimate

        observations = self._observations_fn()
        matches: list[dict[str, Any]] = []
        for row in observations:
            item_raw = str(row.get("item_raw") or "")
            if not item_raw:
                continue
            raw = RawItemInput.from_text(item_raw)
            if raw.content_hash != request.content_hash:
                continue
            obs_league = str(row.get("league") or "").strip() or None
            if request.league.status == LeagueStatus.KNOWN and obs_league:
                if obs_league.lower() != str(request.league.league or "").lower():
                    continue
            matches.append(row)
        if not matches:
            return None
        best = matches[0]
        amount = best.get("price_amount")
        currency = best.get("price_currency")
        if amount is None or not currency:
            return None
        comparable = ComparableListing(
            listing_id=str(best.get("observation_id") or best.get("listing_id") or "obs"),
            item_raw=str(best.get("item_raw") or request.item_raw),
            price_amount=float(amount),
            price_currency=str(currency),
            source=self.provider_id,
            league=best.get("league"),
        )
        confidence = PriceConfidence.MEDIUM if request.league.status == LeagueStatus.KNOWN else PriceConfidence.LOW
        estimate = PriceEstimate(
            source_kind=PriceSourceKind.OBSERVATION_CORPUS,
            confidence=confidence,
            currency_bands=(
                CurrencyBand(label="quick_sale", amount=float(amount), currency=str(currency)),
                CurrencyBand(label="fair", amount=float(amount), currency=str(currency)),
                CurrencyBand(label="optimistic", amount=float(amount), currency=str(currency)),
            ),
            comparables=(comparable,),
            summary="Session observation match",
            disclaimer="Based on captured session observations — not live market.",
        )
        return PriceCheckResult(
            request=request,
            estimate=estimate,
            provider_id=self.provider_id,
            comparable_count=1,
            search_basis="Exact session observation",
            search_relaxation_tier=0,
        )
