from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from poe2value.price_check.cache import InFlightCoalescer, PriceCheckCache
from poe2value.price_check.comparable_query import RelaxationTier
from poe2value.price_check.diagnostic_mode import (
    PriceCheckDiagnosticMode,
    resolve_price_check_diagnostic_mode,
)
from poe2value.price_check.provider import MarketCandidateProvider
from poe2value.price_check.market_policy import is_live_market_enabled
from poe2value.price_check.providers.cached_live_trade2 import CachedLiveMarketProvider
from poe2value.price_check.providers.fixture import FixtureComparableProvider, default_fixture_corpus_path
from poe2value.price_check.providers.live_trade2 import LiveTradeComparableProvider
from poe2value.price_check.providers.market_session_provider import MarketSessionProvider
from poe2value.price_check.providers.observation import ObservationCorpusProvider
from poe2value.price_check.trade2_client import Trade2Client


def build_default_price_check_providers(
    *,
    observations_fn: Callable[[], list[dict[str, Any]]] | None = None,
    corpus_path: str | Path | None = None,
    league: str | None = None,
    cache: PriceCheckCache | None = None,
    include_fixture: bool = False,
    client: Trade2Client | None = None,
    live_market_mode: str | None = None,
    diagnostic_mode: str | None = None,
) -> list[MarketCandidateProvider]:
    """Production chain: live → cached live → observation corpus. Fixture dev/test only."""
    mode = resolve_price_check_diagnostic_mode(diagnostic_mode)
    if mode == PriceCheckDiagnosticMode.CAPTURE_ONLY:
        return []
    if mode == PriceCheckDiagnosticMode.MARKET_ONLY:
        return build_market_only_price_check_providers(
            league=league,
            cache=cache,
            client=client,
        )

    shared_cache = cache or PriceCheckCache()
    providers: list[MarketCandidateProvider] = []
    if is_live_market_enabled(live_market_mode):
        providers.extend(
            [
                # MARKET-01B11: reuse real listings this session already fetched before
                # spending a scarce search request.
                MarketSessionProvider(client=client),
                LiveTradeComparableProvider(client=client, cache=shared_cache, league=league),
                CachedLiveMarketProvider(cache=shared_cache),
            ]
        )
    if observations_fn is not None:
        providers.append(ObservationCorpusProvider(observations_fn=observations_fn))
    if include_fixture or os.environ.get("POE2VALUE_COMPARABLE_FIXTURE", "").strip() in {"1", "true", "yes"}:
        resolved_corpus = corpus_path or default_fixture_corpus_path()
        if Path(resolved_corpus).exists():
            providers.append(FixtureComparableProvider(corpus_path=resolved_corpus))
    return providers


def build_market_only_price_check_providers(
    *,
    league: str | None = None,
    cache: PriceCheckCache | None = None,
    client: Trade2Client | None = None,
) -> list[MarketCandidateProvider]:
    """Strict live-only chain for MARKET-01B6 validation — no cache/observation/fixture."""
    return [
        LiveTradeComparableProvider(
            client=client,
            cache=cache,
            league=league,
            max_search_requests=1,
            max_fetch_requests=1,
            relaxation_order=(RelaxationTier.STRICT,),
            in_flight=InFlightCoalescer(),
        )
    ]


def build_dev_price_check_providers(
    *,
    observations_fn: Callable[[], list[dict[str, Any]]] | None = None,
    corpus_path: str | Path | None = None,
    league: str | None = None,
) -> list[MarketCandidateProvider]:
    """Explicit dev/test chain with fixture corpus enabled."""
    return build_default_price_check_providers(
        observations_fn=observations_fn,
        corpus_path=corpus_path,
        league=league,
        include_fixture=True,
    )
