"""Price an item from real listings this session already fetched, with no new request.

MARKET-01B11. Sits ahead of the live provider: if the market neighbourhood the item
belongs to was already fetched recently, rerank those real listings against this item
and price it locally. Zero search requests, zero fetch requests.

The similarity and band logic is exactly the live provider's — MARKET-01B7 precision is
not weakened to avoid a network call. If the cached sample is too small or too weak the
provider declines and the live path runs.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from poe2value.price_check.comparable_pricing import build_band_estimate, confidence_reason
from poe2value.price_check.comparable_query import build_search_query
from poe2value.price_check.currency_fx import CurrencyFxTable
from poe2value.price_check.market_session import (
    MarketSessionCache,
    neighbourhood_fingerprint,
    query_fingerprint,
    shared_market_session,
)
from poe2value.price_check.models import (
    CompiledPriceCheckRequest,
    AuthenticationMode,
    LeagueStatus,
    LiveSearchState,
    PriceCheckDiagnostics,
    PriceCheckRequest,
    PriceCheckResult,
    PriceConfidence,
    PriceEstimate,
    PriceSourceKind,
    ProviderCapabilities,
)
from poe2value.price_check.providers.live_trade2 import (
    _MIN_BAND_COMPARABLES,
    _live_similarity_match,
)
from poe2value.price_check.market_drivers import estimate_state_for
from poe2value.price_check.price_trust import apply_price_trust
from poe2value.price_check.trade2_client import Trade2Client

logger = logging.getLogger(__name__)

# A cached estimate must rest on at least as much real evidence as a live one.
MIN_CACHED_COMPARABLES = _MIN_BAND_COMPARABLES
# Beyond this the sample is too old to present as a market price without refreshing.
MAX_CACHED_AGE_SECONDS = 10 * 60.0


class MarketSessionProvider:
    """Rerank already-observed live listings for a new item. No network."""

    provider_id = "market_session"
    provider_generation = "v1"

    def __init__(
        self,
        session: MarketSessionCache | None = None,
        *,
        client: Trade2Client | None = None,
        max_age_seconds: float = MAX_CACHED_AGE_SECONDS,
        min_comparables: int = MIN_CACHED_COMPARABLES,
    ) -> None:
        self._session = session if session is not None else shared_market_session()
        self._client = client
        self._max_age = max_age_seconds
        self._min_comparables = min_comparables

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_comparables=True,
            supports_live_prices=False,
            supports_historical_prices=True,
            supports_price_ordering=True,
            supports_global_price_ordering=True,
            supports_league=True,
            source_kind=PriceSourceKind.CACHED_LIVE_MARKET,
            authentication_mode=AuthenticationMode.ANONYMOUS,
        )

    def lookup(self, request: PriceCheckRequest) -> PriceCheckResult | None:
        if isinstance(request, CompiledPriceCheckRequest):
            # Legacy neighbourhoods do not prove AND/COUNT membership. The exact
            # compiled-result and Trade response caches remain available.
            return None
        league = request.league.league
        if not league or request.league.status != LeagueStatus.KNOWN:
            return None

        query = build_search_query(request.item_raw, league=league)
        if request.hypothesis is not None:
            query = replace(query, hypothesis=request.hypothesis)
        neighbourhood = neighbourhood_fingerprint(query, league=league)
        hit = self._session.lookup(
            league=league,
            neighbourhood=neighbourhood,
            source_query=query_fingerprint(query, league=league),
            max_age_seconds=self._max_age,
        )
        if hit is None or hit.count < self._min_comparables:
            return None

        # Same similarity gate as the live path — no weakening to dodge a request.
        similar = [row for row in hit.listings if _live_similarity_match(row.item_raw, query)]
        if len(similar) < self._min_comparables:
            logger.info(
                "market_session declined neighbourhood=%s cached=%d similar=%d min=%d",
                neighbourhood[:12],
                hit.count,
                len(similar),
                self._min_comparables,
            )
            return None

        fx_table = CurrencyFxTable(league=league, client=self._client)
        band, confidence, kept = build_band_estimate(
            similar,
            query=query,
            league_known=True,
            fx_table=fx_table,
        )
        if band is None or len(kept) < self._min_comparables:
            return None

        estimate = PriceEstimate(
            source_kind=PriceSourceKind.CACHED_LIVE_MARKET,
            confidence=confidence if confidence != PriceConfidence.NONE else PriceConfidence.LOW,
            currency_bands=band.to_currency_bands(),
            comparables=tuple(kept),
            summary=f"Estimate from {len(kept)} recent live listings",
            disclaimer="Recent live market data — verify listing before trading.",
            display_currency=band.currency,
            confidence_reason=confidence_reason(
                sample_count=len(kept),
                amounts=[row.normalized_amount or 0.0 for row in kept],
                relaxation_tier=query.relaxation_tier,
            ),
        )
        diagnostics = PriceCheckDiagnostics(
            league=league,
            league_source=request.league_source,
            provider_id=self.provider_id,
            authentication_mode=AuthenticationMode.ANONYMOUS.value,
            comparable_count=len(kept),
            price_check_id=request.request_id,
            live_state=LiveSearchState.LIVE_SEARCH_OK_RESULTS,
            search_requests=0,
            fetch_requests=0,
            total_http_requests=0,
            cache_age_seconds=hit.age_seconds,
            provider_selected=(self.provider_id,),
            provider_attempted=(self.provider_id,),
            provider_result=f"{self.provider_id}:cached_live",
        )
        logger.info(
            "market_session priced from cache neighbourhood=%s level=%s cached=%d kept=%d age=%.1fs",
            neighbourhood[:12],
            hit.matched_level,
            hit.count,
            len(kept),
            hit.age_seconds,
        )
        return apply_price_trust(
            PriceCheckResult(
                request=request,
                estimate=estimate,
                provider_id=self.provider_id,
                comparable_count=len(kept),
                search_basis=query.search_basis,
                matched_features=query.matched_summary(),
                identity_source=query.economic_identity.source.value,
                cache_age_seconds=hit.age_seconds,
                market_status="CACHED LIVE MARKET",
                diagnostics=diagnostics,
                hypothesis=query.hypothesis,
                estimate_state=(
                    estimate_state_for(query.hypothesis).value if query.hypothesis is not None else ""
                ),
            )
        )
