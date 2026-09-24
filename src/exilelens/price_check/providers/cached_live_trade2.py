from __future__ import annotations

from exilelens.price_check.cache import PriceCheckCache
from exilelens.price_check.market_drivers import build_auto_hypothesis
from exilelens.price_check.price_trust import apply_price_trust
from exilelens.price_check.models import (
    CompiledPriceCheckRequest,
    AuthenticationMode,
    PriceCheckRequest,
    PriceCheckResult,
    PriceEstimate,
    PriceSourceKind,
    ProviderCapabilities,
)
from exilelens.price_check.providers.live_trade2 import LiveTradeComparableProvider


class CachedLiveMarketProvider:
    """Serve stale-but-valid live market cache when fresh live lookup is unavailable."""

    provider_id = "cached_live_trade2"

    def __init__(self, cache: PriceCheckCache | None = None) -> None:
        self._cache = cache or PriceCheckCache()
        self._live_provider_id = LiveTradeComparableProvider.provider_id
        self._live_generation = LiveTradeComparableProvider.provider_generation

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
        league = request.league.league
        compiled = isinstance(request, CompiledPriceCheckRequest)
        hypothesis = None if compiled else request.hypothesis or build_auto_hypothesis(request.item_raw, league=league)
        cache_key = self._cache.make_key(
            item_fingerprint=request.content_hash,
            league=league,
            provider_id=self._live_provider_id,
            provider_generation="v3-compiled" if compiled else self._live_generation,
            hypothesis_fingerprint=request.compiled_query.query_fingerprint if compiled else hypothesis.query_fingerprint,
        )
        cached = self._cache.get_stale(cache_key)
        if cached is None:
            return None
        estimate = cached.estimate
        stale_estimate = PriceEstimate(
            source_kind=PriceSourceKind.CACHED_LIVE_MARKET,
            confidence=estimate.confidence,
            currency_bands=estimate.currency_bands,
            comparables=estimate.comparables,
            summary=estimate.summary or "Cached live market estimate",
            disclaimer="Cached live market data — prices may be stale.",
        )
        diagnostics = cached.diagnostics
        return apply_price_trust(
            PriceCheckResult(
                request=request,
                estimate=stale_estimate,
                provider_id=self.provider_id,
                comparable_count=cached.comparable_count,
                search_basis=cached.search_basis,
                matched_features=cached.matched_features,
                identity_source=cached.identity_source,
                search_relaxation_tier=cached.search_relaxation_tier,
                cache_hit=True,
                diagnostics=diagnostics,
                hypothesis=cached.hypothesis or hypothesis,
                estimate_state=cached.estimate_state,
                cache_age_seconds=getattr(cached, "cache_age_seconds", None),
                stability=getattr(cached, "stability", "") or "",
                auto_adjusted=bool(getattr(cached, "auto_adjusted", False)),
                discovery=getattr(cached, "discovery", None),
                unassessed_estimate=cached.unassessed_estimate,
            )
        )
