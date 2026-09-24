from __future__ import annotations

import logging
import math
import re
from dataclasses import replace
from typing import Any, Callable

from exilelens.items.metadata import parse_lightweight_metadata
from exilelens.items.raw_input import RawItemInput
from exilelens.price_check.cache import InFlightCoalescer, PriceCheckCache
from exilelens.price_check.comparable_funnel_diag import build_pass_funnel_snapshot
from exilelens.price_check.comparable_pricing import (
    build_band_estimate,
    confidence_reason,
    count_fx_usable_listings,
)
from exilelens.price_check.comparable_query import (
    RelaxationTier,
    build_search_query,
    listing_matches_query,
    listing_similarity_score,
    with_relaxation,
)
from exilelens.price_check.currency_fx import CurrencyFxTable
from exilelens.price_check.live_acquisition import (
    LiveAcquisitionDiagnostics,
    RelaxationPassDiagnostics,
    log_live_acquisition,
    map_trade2_error_code,
)
from exilelens.price_check.models import (
    CompiledPriceCheckRequest,
    AuthenticationMode,
    ComparableListing,
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
from exilelens.price_check.hypothesis_discovery import (
    DiscoverySelection,
    DiscoverySource,
    DiscoveryTrigger,
    FinalHypothesis,
    HypothesisPlan,
    HypothesisStability,
    classify_h1_problem,
    discovery_allowed,
    generate_alternate,
    observation_from_counts,
    plan_discovery,
    select_final,
)
from exilelens.price_check.market_drivers import (
    HypothesisSource,
    build_auto_hypothesis,
    estimate_state_for,
)
from exilelens.price_check.market_signatures import (
    annotate_discovery_payload,
    build_assisted_hypothesis,
    record_signature_evidence,
)
from exilelens.price_check.price_trust import apply_price_trust
from exilelens.price_check.network_withhold import (
    FetchContinuation,
    STAGE_FETCH,
    build_fetch_withhold,
)
from exilelens.price_check.rate_policy import FETCH
from exilelens.price_check.trade2_client import Trade2Client, Trade2Error
from exilelens.price_check.trade2_query import build_trade2_search_body

logger = logging.getLogger(__name__)

_MIN_BAND_COMPARABLES = 3
# MARKET-01B11: search is the scarce endpoint (5/10s, 30/300s) while fetch is far more
# permissive (12/4s, 50/300s). Fetching a larger sample from ONE search makes the
# neighbourhood reusable for nearby items instead of pricing a single item and
# discarding it. Batches are 10, so 4 fetch requests cover this target.
_TARGET_SAMPLE = 36
_MAX_FETCH_IDS = 40
# MARKET-02C: ordinary healthy AUTO is still one search. Difficult cold items may
# spend one extra H2 search. Never three.
_MAX_SEARCH_REQUESTS = 2
# MARKET-02C: H1 may fetch a 40-id sample (4 batches). That must not starve the
# one legal H2 search — fetch is the cheap bucket. Two searches × 4 batches.
_MAX_FETCH_REQUESTS = 8
_RELAXATION_ORDER = (RelaxationTier.STRICT,)

_INFLIGHT = InFlightCoalescer()

_MOD_LINE_RE = re.compile(r"^(\+?\d+%?|\d+%)\s+(.+)$|^.+(increased|reduced|to)\s+.+$", re.I)


def _mod_text(row: dict[str, Any]) -> str:
    if isinstance(row, str):
        from exilelens.price_check.comparable_features import strip_mod_markup

        return strip_mod_markup(row.strip())
    if isinstance(row, dict):
        from exilelens.price_check.comparable_features import strip_mod_markup

        return strip_mod_markup(str(row.get("description") or row.get("text") or "").strip())
    return ""


_UNNAMED_ITEM_SENTINEL = "__UNNAMED__"


def _item_raw_from_trade2(item: dict[str, Any]) -> str:
    lines: list[str] = []
    rarity = str(item.get("rarity") or item.get("frameType") or "RARE")
    if rarity.isdigit():
        rarity_map = {"0": "NORMAL", "1": "MAGIC", "2": "RARE", "3": "UNIQUE"}
        rarity = rarity_map.get(rarity, "RARE")
    lines.append(f"Rarity: {rarity.upper()}")
    base = str(item.get("typeLine") or item.get("baseType") or "").strip()
    name = str(item.get("name") or "").strip()
    if name:
        lines.append(name)
    elif base:
        lines.append(_UNNAMED_ITEM_SENTINEL)
    if base:
        lines.append(base)
    for key in ("implicitMods", "explicitMods", "fracturedMods", "enchantMods"):
        for mod in item.get(key) or []:
            text = _mod_text(mod)
            if text:
                lines.append(text)
    return "\n".join(lines)


def _parse_listing(row: dict[str, Any], *, league: str, source: str) -> ComparableListing | None:
    listing = row.get("listing") or {}
    item = row.get("item") or {}
    price = listing.get("price") or {}
    amount = price.get("amount")
    currency = price.get("currency")
    if amount is None or not currency:
        return None
    listing_id = str(row.get("id") or listing.get("id") or "")
    if not listing_id:
        return None
    account = listing.get("account") or {}
    seller_id = str(account.get("name") or "") or None
    return ComparableListing(
        listing_id=listing_id,
        item_raw=_item_raw_from_trade2(item),
        price_amount=float(amount),
        price_currency=str(currency),
        source=source,
        league=league,
        seller_id=seller_id,
        captured_at=str(listing.get("indexed") or "") or None,
    )


def _live_similarity_match(item_raw: str, query) -> bool:
    if query.compiled_query is not None:
        # These listings came from the exact compiled search ID. Legacy local feature
        # gates would turn COUNT into AND and reinstate an unconditional exact base.
        return True
    if query.relaxation_tier >= RelaxationTier.BASE_AND_RARITY:
        return listing_matches_query(item_raw, query)
    from exilelens.price_check.comparable_features import FAMILY_MATCH_THRESHOLD

    # MARKET-01B13: gate on the features the query searched on. The threshold formula
    # below is untouched — only the set it is computed over changed, so a fallback item
    # gets real precision instead of matching everything.
    important = query.identity_features()
    if not important:
        return listing_matches_query(item_raw, query)
    score = listing_similarity_score(item_raw, query)
    required = max(1, len(important) - 1) if query.relaxation_tier == RelaxationTier.STRICT else max(
        1, int(len(important) * 0.5)
    )
    threshold = (FAMILY_MATCH_THRESHOLD * required) / len(important)
    return score >= threshold


def _filter_similar_listings(
    listings: list[ComparableListing],
    query,
) -> list[ComparableListing]:
    return [row for row in listings if _live_similarity_match(row.item_raw, query)]


def _parse_fetched_listings(
    fetched: list[dict[str, Any]],
    *,
    league: str,
    source: str,
) -> list[ComparableListing]:
    return [
        parsed
        for row in fetched
        for parsed in [_parse_listing(row, league=league, source=source)]
        if parsed is not None
    ]


def _market_status_rate_limited(retry_after: float | None) -> str:
    seconds = max(1, int(math.ceil(retry_after or 1)))
    return f"LIVE MARKET TEMPORARILY LIMITED — Retry in {seconds}s"


def _failure_estimate(state: LiveSearchState, message: str) -> PriceEstimate:
    return PriceEstimate(
        source_kind=PriceSourceKind.LIVE_MARKET,
        confidence=PriceConfidence.NONE,
        summary=message,
        disclaimer=message,
    )


class LiveTradeComparableProvider:
    """Primary live trade2 comparable provider — anonymous-first."""

    provider_id = "live_trade2"
    provider_generation = "v2-assisted"

    def __init__(
        self,
        *,
        client: Trade2Client | None = None,
        cache: PriceCheckCache | None = None,
        league: str | None = None,
        search_fn: Callable[[str, dict[str, Any]], Any] | None = None,
        fetch_fn: Callable[[list[str], str], list[dict[str, Any]]] | None = None,
        in_flight: InFlightCoalescer | None = None,
        max_search_requests: int | None = None,
        max_fetch_requests: int | None = None,
        relaxation_order: tuple[RelaxationTier, ...] | None = None,
        session=None,
        signature_store=None,
    ) -> None:
        self._client = client or Trade2Client()
        self._cache = cache
        self._default_league = league
        self._search_fn = search_fn
        self._fetch_fn = fetch_fn
        self._in_flight = in_flight or _INFLIGHT
        self._auth_required = False
        self._last_http_status: int | None = None
        self._last_live_state: LiveSearchState | None = None
        from exilelens.price_check.market_session import shared_market_session
        from exilelens.price_check.signature_store import shared_signature_store

        self._session = session if session is not None else shared_market_session()
        self._signature_store = signature_store if signature_store is not None else shared_signature_store()
        self._max_search_requests = max_search_requests if max_search_requests is not None else _MAX_SEARCH_REQUESTS
        self._max_fetch_requests = max_fetch_requests if max_fetch_requests is not None else _MAX_FETCH_REQUESTS
        self._relaxation_order = relaxation_order if relaxation_order is not None else _RELAXATION_ORDER
        self._lookup_searches = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        mode = AuthenticationMode.SESSION if self._client.session_id else AuthenticationMode.ANONYMOUS
        if self._auth_required:
            mode = AuthenticationMode.AUTH_REQUIRED
        return ProviderCapabilities(
            supports_comparables=True,
            supports_live_prices=True,
            supports_price_ordering=True,
            supports_global_price_ordering=True,
            supports_league=True,
            source_kind=PriceSourceKind.LIVE_MARKET,
            authentication_mode=mode,
        )

    def lookup(self, request: PriceCheckRequest) -> PriceCheckResult | None:
        if isinstance(request, CompiledPriceCheckRequest):
            from exilelens.price_check.trade2_query_validation import validate_trade2_search_body, InvalidTradeQuery
            validation = validate_trade2_search_body(request.compiled_query.body)
            if not validation.ok or validation.body != request.compiled_query.body:
                raise InvalidTradeQuery(validation.fatal or "compiled body requires repair; recompile offline")
        result = self._lookup(request)
        if result is not None and isinstance(request, CompiledPriceCheckRequest):
            result = apply_price_trust(replace(result, request=request, hypothesis=None))
        return result

    def _lookup(self, request: PriceCheckRequest) -> PriceCheckResult | None:
        meta = parse_lightweight_metadata(RawItemInput.from_text(request.item_raw))
        diagnostics = LiveAcquisitionDiagnostics(
            price_check_id=request.request_id,
            item_category=meta.category,
            item_base=meta.base_type,
            item_rarity=meta.rarity,
            league_source=request.league_source,
            auth_mode=self._client.authentication_mode,
        )

        if request.league.status == LeagueStatus.UNKNOWN or not str(request.league.league or "").strip():
            diagnostics.live_state = LiveSearchState.LEAGUE_REQUIRED
            diagnostics.final_source = "league_required"
            log_live_acquisition(diagnostics)
            return self._failure_result(
                request,
                LiveSearchState.LEAGUE_REQUIRED,
                diagnostics,
                message="League required for live market search.",
            )

        league = self._client.canonicalize_league(request.league.league or self._default_league or "")
        if not league:
            diagnostics.live_state = LiveSearchState.LEAGUE_REQUIRED
            diagnostics.final_source = "league_required"
            log_live_acquisition(diagnostics)
            return self._failure_result(
                request,
                LiveSearchState.LEAGUE_REQUIRED,
                diagnostics,
                message="League required for live market search.",
            )
        diagnostics.league = request.league.league
        diagnostics.canonical_league = league

        cache_key = None
        if self._cache is not None:
            hypothesis = None if isinstance(request, CompiledPriceCheckRequest) else request.hypothesis or build_assisted_hypothesis(
                request.item_raw,
                league=league,
                store=self._signature_store,
            )
            if not isinstance(request, CompiledPriceCheckRequest) and request.hypothesis is None:
                request = replace(request, hypothesis=hypothesis)
            cache_key = self._cache.make_key(
                item_fingerprint=request.content_hash,
                league=league,
                provider_id=self.provider_id,
                provider_generation="v3-compiled" if isinstance(request, CompiledPriceCheckRequest) else self.provider_generation,
                hypothesis_fingerprint=request.compiled_query.query_fingerprint if isinstance(request, CompiledPriceCheckRequest) else hypothesis.query_fingerprint,
            )

        rate_state = self._client.rate_limit_state
        if rate_state is not None and rate_state.is_limited():
            retry_after = rate_state.peek_cooldown(event="provider_precheck")
            diagnostics.rate_limit_retry_after = retry_after
            diagnostics.rate_limit_headers = dict(rate_state.last_headers)
            cached_result = self._cached_rate_limit_result(
                request,
                cache_key,
                retry_after,
                diagnostics,
                league,
            )
            if cached_result is not None:
                log_live_acquisition(diagnostics)
                return cached_result
            diagnostics.live_state = LiveSearchState.LIVE_SEARCH_RATE_LIMITED
            diagnostics.final_source = LiveSearchState.LIVE_SEARCH_RATE_LIMITED.value.lower()
            log_live_acquisition(diagnostics)
            return self._rate_limited_result(request, diagnostics, retry_after, league)

        if cache_key is not None and self._cache is not None:
            cached = self._cache.get_live(cache_key)
            if cached is not None and cached.estimate.has_currency_estimate:
                return cached

        if cache_key is None:
            return self._lookup_pipeline(request, diagnostics, league, cache_key=None)

        return self._in_flight.run(
            cache_key,
            lambda: self._lookup_pipeline(request, diagnostics, league, cache_key=cache_key),
        )

    def _lookup_pipeline(
        self,
        request: PriceCheckRequest,
        diagnostics: LiveAcquisitionDiagnostics,
        league: str,
        *,
        cache_key: str | None,
        skip_discovery: bool = False,
        preserve_counters: bool = False,
    ) -> PriceCheckResult:
        continuation = request.pipeline_continuation
        if continuation is not None and continuation.stage == STAGE_FETCH and continuation.fetch is not None:
            return self._lookup_pipeline_resume_fetch(
                request,
                diagnostics,
                league,
                cache_key=cache_key,
                fetch_cont=continuation.fetch,
                skip_discovery=skip_discovery,
                preserve_counters=True,
            )
        if cache_key and self._cache is not None:
            cached = self._cache.get_live(cache_key)
            if cached is not None and cached.estimate.has_currency_estimate:
                return cached

        rate_state = self._client.rate_limit_state
        if rate_state is not None and rate_state.is_limited():
            retry_after = rate_state.peek_cooldown(event="pipeline_precheck")
            cached_result = self._cached_rate_limit_result(
                request,
                cache_key,
                retry_after,
                diagnostics,
                league,
            )
            if cached_result is not None:
                return cached_result
            return self._rate_limited_result(request, diagnostics, retry_after, league)

        if not isinstance(request, CompiledPriceCheckRequest) and request.hypothesis is None:
            request = replace(
                request,
                hypothesis=build_assisted_hypothesis(
                    request.item_raw,
                    league=league,
                    store=self._signature_store,
                ),
            )

        if not preserve_counters:
            self._client.reset_request_counters()
            self._lookup_searches = 0
        base_query = build_search_query(request.item_raw, league=league)
        if request.hypothesis is not None:
            base_query = replace(base_query, hypothesis=request.hypothesis)
        if isinstance(request, CompiledPriceCheckRequest):
            base_query = replace(base_query, hypothesis=None, features=(), mods=(), compiled_query=request.compiled_query)
        if not base_query.base_type:
            diagnostics.live_state = LiveSearchState.LIVE_SEARCH_BAD_REQUEST
            diagnostics.final_source = "missing_base_type"
            log_live_acquisition(diagnostics)
            return self._failure_result(
                request,
                LiveSearchState.LIVE_SEARCH_BAD_REQUEST,
                diagnostics,
                message="Could not determine item base type for trade search.",
            )

        fx_table = CurrencyFxTable(league=league, client=self._client)
        terminal_state: LiveSearchState | None = None
        terminal_message = ""
        best_weak_count = 0
        best_similar_count = 0

        for pass_index, tier in enumerate((RelaxationTier.STRICT,) if isinstance(request, CompiledPriceCheckRequest) else self._relaxation_order):
            if pass_index > 0 and best_similar_count >= _MIN_BAND_COMPARABLES:
                break
            if self._lookup_searches >= self._max_search_requests:
                break
            if self._client.fetch_requests >= self._max_fetch_requests:
                break
            pass_diag = RelaxationPassDiagnostics(pass_index=pass_index, relaxation_tier=int(tier))
            query = with_relaxation(base_query, tier)
            body = request.compiled_query.body if isinstance(request, CompiledPriceCheckRequest) else build_trade2_search_body(query)
            diagnostics.generated_query = body
            diagnostics.search_url = self._client.search_url(league)
            try:
                search = self._search(league, body)
                pass_diag.http_status = search.http_status
                pass_diag.search_total = search.total
                pass_diag.search_result_count = len(search.result_ids)
                pass_diag.search_id = search.query_id
                diagnostics.http_status = search.http_status
                diagnostics.result_count = search.total
                diagnostics.search_id = search.query_id
                diagnostics.rate_limit_headers = {
                    key: value
                    for key, value in (search.response_headers or {}).items()
                    if key.lower().startswith("x-rate-limit") or key.lower() == "retry-after"
                }

                if search.total <= 0 or not search.result_ids:
                    terminal_state = LiveSearchState.LIVE_SEARCH_OK_ZERO_RESULTS
                    terminal_message = "No matching listings on trade right now."
                    pass_diag.error = "zero_results"
                    self._attach_pass_funnel(
                        pass_diag,
                        query=query,
                        http_status=search.http_status,
                        search_total=search.total,
                        result_ids=[],
                        fetch_requests=0,
                        fetched_count=0,
                        listings=[],
                        fx_table=fx_table,
                        failure_reason="zero_results",
                    )
                    diagnostics.relaxation_passes.append(pass_diag)
                    continue

                result_ids = search.result_ids[:_MAX_FETCH_IDS]
                pass_diag.fetch_requested = len(result_ids)
                fetch_state = {"query": query, "similar": 0, "listings": []}
                fetch_cont = FetchContinuation(
                    query_id=search.query_id,
                    result_ids=tuple(result_ids),
                    fetch_offset=0,
                    pass_index=pass_index,
                    relaxation_tier=int(tier),
                    search_http_status=search.http_status,
                    search_total=search.total,
                )
                withhold = self._proactive_fetch_withhold(request, diagnostics, fetch_cont)
                if withhold is not None:
                    diagnostics.relaxation_passes.append(pass_diag)
                    return withhold

                def _stop_when(rows: list[dict[str, Any]]) -> bool:
                    listings = _parse_fetched_listings(rows, league=league, source=self.provider_id)
                    similar = _filter_similar_listings(listings, fetch_state["query"])
                    fetch_state["similar"] = len(similar)
                    fetch_state["listings"] = similar
                    if len(similar) >= _TARGET_SAMPLE:
                        return True
                    return count_fx_usable_listings(similar, fx_table=fx_table) >= _MIN_BAND_COMPARABLES

                fetch_requests_before = self._client.fetch_requests
                try:
                    fetched, fetch_cont = self._fetch_progressive_resumable(
                        fetch_cont,
                        stop_when=_stop_when,
                    )
                except Trade2Error as exc:
                    withhold = self._fetch_error_withhold(
                        request,
                        diagnostics,
                        league,
                        fetch_cont=fetch_cont,
                        exc=exc,
                        pass_diag=pass_diag,
                    )
                    if withhold is not None:
                        diagnostics.relaxation_passes.append(pass_diag)
                        return withhold
                    raise
                fetch_requests_delta = self._client.fetch_requests - fetch_requests_before
                pass_diag.fetch_returned = len(fetched)
                diagnostics.fetch_count = len(fetched)

                listings = _parse_fetched_listings(fetched, league=league, source=self.provider_id)
                pass_diag.priced_listings = len(listings)
                diagnostics.priced_listings = len(listings)

                # MARKET-01B11: keep the whole fetched neighbourhood, not just the
                # listings that priced this one item. A nearby item can then be priced
                # from it without spending another search.
                self._remember_neighbourhood(listings, league=league, query=query)
                diagnostics.currencies = sorted({str(row.price_currency or "") for row in listings if row.price_currency})

                if not listings:
                    terminal_state = LiveSearchState.LIVE_FETCH_NO_PRICES
                    terminal_message = "Listings were fetched but no priced asks were parsed."
                    pass_diag.error = "fetch_no_prices"
                    self._attach_pass_funnel(
                        pass_diag,
                        query=query,
                        http_status=search.http_status,
                        search_total=search.total,
                        result_ids=result_ids,
                        fetch_requests=fetch_requests_delta,
                        fetched_count=len(fetched),
                        listings=[],
                        fx_table=fx_table,
                        failure_reason="fetch_no_prices",
                    )
                    diagnostics.relaxation_passes.append(pass_diag)
                    continue

                similar = fetch_state["listings"] or _filter_similar_listings(listings, query)
                pass_diag.similarity_matched = len(similar)
                diagnostics.similarity_counts[f"pass_{pass_index}"] = len(similar)
                best_similar_count = max(best_similar_count, len(similar))
                fx_usable = count_fx_usable_listings(similar, fx_table=fx_table)
                pass_diag.fx_usable = fx_usable

                if len(similar) <= 2:
                    best_weak_count = max(best_weak_count, len(similar))
                    terminal_state = LiveSearchState.LIVE_COMPARABLES_TOO_WEAK
                    terminal_message = "Too few similar priced listings for a confident band."
                    pass_diag.error = "similarity_too_weak"
                    self._attach_pass_funnel(
                        pass_diag,
                        query=query,
                        http_status=search.http_status,
                        search_total=search.total,
                        result_ids=result_ids,
                        fetch_requests=fetch_requests_delta,
                        fetched_count=len(fetched),
                        listings=listings,
                        similar=similar,
                        fx_table=fx_table,
                        failure_reason="similarity_too_weak",
                    )
                    diagnostics.relaxation_passes.append(pass_diag)
                    continue

                band, confidence, kept = build_band_estimate(
                    similar,
                    query=query,
                    league_known=request.league.status == LeagueStatus.KNOWN,
                    fx_table=fx_table,
                )
                reason = confidence_reason(
                    sample_count=len(kept),
                    amounts=[row.normalized_amount or 0.0 for row in kept],
                    relaxation_tier=query.relaxation_tier,
                )
                if band is None or len(kept) < _MIN_BAND_COMPARABLES:
                    best_weak_count = max(best_weak_count, len(similar))
                    terminal_state = LiveSearchState.LIVE_COMPARABLES_TOO_WEAK
                    terminal_message = "Too few similar priced listings for a confident band."
                    pass_diag.error = "band_too_weak"
                    self._attach_pass_funnel(
                        pass_diag,
                        query=query,
                        http_status=search.http_status,
                        search_total=search.total,
                        result_ids=result_ids,
                        fetch_requests=fetch_requests_delta,
                        fetched_count=len(fetched),
                        listings=listings,
                        similar=similar,
                        kept=kept,
                        fx_table=fx_table,
                        failure_reason="band_too_weak",
                    )
                    diagnostics.relaxation_passes.append(pass_diag)
                    continue

                # MARKET-01B13: the accepted set, not everything that merely looked
                # similar. `similar` still holds the listings the outlier filter threw
                # out and carries no normalized value, so B12's raw-plus-normalized
                # display and its accepted-only rule were both inert on the live path.
                comparables = tuple(kept)
                summary = f"{len(kept)} live comparable listing{'s' if len(kept) != 1 else ''}"
                if len(kept) <= 7:
                    summary = f"Tentative estimate from {len(kept)} similar listings"
                estimate = PriceEstimate(
                    source_kind=PriceSourceKind.LIVE_MARKET,
                    confidence=confidence,
                    currency_bands=band.to_currency_bands(),
                    comparables=comparables,
                    summary=summary,
                    disclaimer="Live trade comparables — verify listing before trading.",
                    display_currency=band.currency,
                    confidence_reason=reason,
                )
                diagnostics.live_state = LiveSearchState.LIVE_SEARCH_OK_RESULTS
                diagnostics.final_source = "live_trade2"
                self._attach_pass_funnel(
                    pass_diag,
                    query=query,
                    http_status=search.http_status,
                    search_total=search.total,
                    result_ids=result_ids,
                    fetch_requests=fetch_requests_delta,
                    fetched_count=len(fetched),
                    listings=listings,
                    similar=similar,
                    kept=kept,
                    fx_table=fx_table,
                    has_currency_estimate=True,
                    failure_reason="",
                )
                diagnostics.relaxation_passes.append(pass_diag)
                self._attach_request_counts(diagnostics)
                log_live_acquisition(diagnostics)
                result = PriceCheckResult(
                    request=request,
                    estimate=estimate,
                    provider_id=self.provider_id,
                    comparable_count=len(kept),
                    search_basis=query.search_basis,
                    matched_features=query.matched_summary(),
                    identity_source=query.economic_identity.source.value,
                    search_relaxation_tier=int(tier),
                    live_search_state=LiveSearchState.LIVE_SEARCH_OK_RESULTS,
                    diagnostics=self._result_diagnostics(request, diagnostics, league),
                    hypothesis=query.hypothesis,
                    estimate_state=(
                        estimate_state_for(query.hypothesis).value
                        if query.hypothesis is not None
                        else ""
                    ),
                )
                result = self._apply_discovery(
                    request,
                    diagnostics,
                    league,
                    cache_key=cache_key,
                    h1_result=result,
                    fx_table=fx_table,
                    skip_discovery=skip_discovery,
                )
                if cache_key and self._cache is not None and result.estimate.has_currency_estimate:
                    self._cache.put(cache_key, result)
                self._last_live_state = result.live_search_state
                return result
            except Trade2Error as exc:
                self._last_http_status = exc.http_status
                state = map_trade2_error_code(exc.code, exc.http_status)
                pass_diag.error = exc.code
                pass_diag.http_status = exc.http_status
                diagnostics.relaxation_passes.append(pass_diag)
                diagnostics.http_status = exc.http_status
                diagnostics.rate_limit_retry_after = exc.retry_after
                diagnostics.rate_limit_headers = dict(exc.response_headers or {})
                if state == LiveSearchState.LIVE_SEARCH_AUTH_REQUIRED:
                    self._auth_required = True
                terminal_state = state
                terminal_message = str(exc)
                if pass_diag.search_id and exc.code in {"rate_limit_pacing", "rate_limited"}:
                    fetch_cont = FetchContinuation(
                        query_id=pass_diag.search_id,
                        result_ids=tuple(),
                        fetch_offset=0,
                        pass_index=pass_index,
                        relaxation_tier=int(tier),
                        search_http_status=pass_diag.http_status or 200,
                        search_total=pass_diag.search_total,
                    )
                    withhold = self._fetch_error_withhold(
                        request,
                        diagnostics,
                        league,
                        fetch_cont=fetch_cont,
                        exc=exc,
                        pass_diag=pass_diag,
                    )
                    if withhold is not None:
                        return withhold
                if state in {
                    LiveSearchState.LIVE_SEARCH_AUTH_REQUIRED,
                    LiveSearchState.LIVE_SEARCH_FORBIDDEN,
                    LiveSearchState.LIVE_SEARCH_RATE_LIMITED,
                }:
                    self._attach_request_counts(diagnostics)
                    if state == LiveSearchState.LIVE_SEARCH_RATE_LIMITED:
                        if self._client.rate_limit_state is not None:
                            self._client.rate_limit_state.update_from_headers(
                                dict(exc.response_headers or {}),
                                retry_after=exc.retry_after,
                                http_status=429,
                            )
                        cached_result = self._cached_rate_limit_result(
                            request,
                            cache_key,
                            exc.retry_after,
                            diagnostics,
                            league,
                        )
                        if cached_result is not None:
                            log_live_acquisition(diagnostics)
                            return cached_result
                    diagnostics.live_state = state
                    diagnostics.final_source = state.value.lower()
                    log_live_acquisition(diagnostics)
                    if state == LiveSearchState.LIVE_SEARCH_RATE_LIMITED:
                        return self._rate_limited_result(
                            request,
                            diagnostics,
                            exc.retry_after,
                            league,
                        )
                    return self._failure_result(request, state, diagnostics, message=terminal_message)
                continue
            if self._client.fetch_requests >= self._max_fetch_requests:
                break

        if terminal_state is None:
            terminal_state = LiveSearchState.LIVE_SEARCH_OK_ZERO_RESULTS
            terminal_message = "No matching listings on trade right now."
        if terminal_state == LiveSearchState.LIVE_COMPARABLES_TOO_WEAK and best_weak_count > 0:
            terminal_message = (
                f"Found {best_weak_count} similar priced listing"
                f"{'s' if best_weak_count != 1 else ''} — not enough for a confident band."
            )
        diagnostics.live_state = terminal_state
        diagnostics.final_source = terminal_state.value.lower()
        self._attach_request_counts(diagnostics)
        log_live_acquisition(diagnostics)
        self._last_live_state = terminal_state
        return self._apply_discovery(
            request,
            diagnostics,
            league,
            cache_key=cache_key,
            h1_result=None,
            fx_table=fx_table,
            terminal_state=terminal_state,
            terminal_message=terminal_message,
            skip_discovery=skip_discovery,
        )

    def _apply_discovery(
        self,
        request: PriceCheckRequest,
        diagnostics: LiveAcquisitionDiagnostics,
        league: str,
        *,
        cache_key: str | None,
        h1_result: PriceCheckResult | None,
        fx_table,
        terminal_state: LiveSearchState | None = None,
        terminal_message: str = "",
        skip_discovery: bool = False,
    ) -> PriceCheckResult:
        if isinstance(request, CompiledPriceCheckRequest):
            # H2 speaks only MARKET-02. Do not weaken a compiled plan to reuse it.
            result = h1_result or self._failure_result(
                request, terminal_state or LiveSearchState.LIVE_SEARCH_OK_ZERO_RESULTS,
                diagnostics, message=terminal_message,
            )
            return apply_price_trust(replace(result, hypothesis=None, discovery={
                "h2_disabled_reason": "MARKET-02 recovery cannot preserve MARKET-03 anchors/groups",
            }))
        hypothesis = request.hypothesis
        if hypothesis is None:
            if h1_result is not None and h1_result.hypothesis is not None:
                hypothesis = h1_result.hypothesis
            else:
                hypothesis = build_assisted_hypothesis(
                    request.item_raw,
                    league=league,
                    store=self._signature_store,
                )
        h1_obs = self._observation_from_live(
            hypothesis,
            result=h1_result,
            diagnostics=diagnostics,
            query_source="SEARCH",
            search_requests=self._lookup_searches,
        )
        if skip_discovery or not discovery_allowed(hypothesis):
            selection = select_final(h1_obs, None, h2_from_search=False)
            plan = plan_discovery(hypothesis, trigger=None)
            if h1_result is not None:
                return self._with_discovery(
                    h1_result,
                    request,
                    diagnostics,
                    league,
                    h1_obs=h1_obs,
                    h2_obs=None,
                    plan=plan,
                    selection=selection,
                )
            failure = self._failure_result(
                request,
                terminal_state or LiveSearchState.LIVE_SEARCH_OK_ZERO_RESULTS,
                diagnostics,
                message=terminal_message,
            )
            return self._with_discovery(
                failure,
                request,
                diagnostics,
                league,
                h1_obs=h1_obs,
                h2_obs=None,
                plan=plan,
                selection=selection,
            )

        terminal = terminal_state or (
            h1_result.live_search_state if h1_result is not None else None
        )
        if terminal in {
            LiveSearchState.LIVE_SEARCH_AUTH_REQUIRED,
            LiveSearchState.LIVE_SEARCH_FORBIDDEN,
            LiveSearchState.LIVE_SEARCH_RATE_LIMITED,
            LiveSearchState.LIVE_SEARCH_BAD_REQUEST,
            LiveSearchState.LIVE_SEARCH_NETWORK_ERROR,
        }:
            failure = h1_result or self._failure_result(
                request, terminal, diagnostics, message=terminal_message
            )
            return replace(failure, hypothesis=hypothesis)

        trigger = classify_h1_problem(h1_obs)
        h1_has_estimate = h1_result is not None and h1_result.estimate.has_currency_estimate
        if trigger is None and not h1_has_estimate:
            trigger = (
                DiscoveryTrigger.ZERO_RESULTS
                if h1_obs.remote_count <= 0 and h1_obs.fetched_count <= 0
                else DiscoveryTrigger.WEAK_COMPARABLES
            )
        generated = generate_alternate(hypothesis)
        h2 = generated[0] if generated is not None else None
        cache_h2 = self._evaluate_hypothesis_locally(request, h2, league, fx_table) if h2 is not None else None
        if trigger is None:
            # Healthy H1: never spend a second search. Cache H2 is only a stability peek.
            selection = select_final(h1_obs, cache_h2, h2_from_search=False)
            plan = plan_discovery(
                hypothesis,
                trigger=DiscoveryTrigger.CACHED_EVIDENCE if cache_h2 is not None else None,
                cache_can_evaluate_h2=cache_h2 is not None,
            )
            if selection.stability is HypothesisStability.SENSITIVE and cache_h2 is not None:
                plan = replace(plan, discovery_source=DiscoverySource.COMBINATION_STABILITY)
            if h1_result is None:
                failure = self._failure_result(
                    request,
                    terminal_state or LiveSearchState.LIVE_SEARCH_OK_ZERO_RESULTS,
                    diagnostics,
                    message=terminal_message,
                )
                return self._with_discovery(
                    failure,
                    request,
                    diagnostics,
                    league,
                    h1_obs=h1_obs,
                    h2_obs=cache_h2,
                    plan=plan,
                    selection=selection,
                )
            return self._with_discovery(
                h1_result,
                request,
                diagnostics,
                league,
                h1_obs=h1_obs,
                h2_obs=cache_h2,
                plan=plan,
                selection=selection,
            )

        plan = plan_discovery(hypothesis, trigger=trigger, cache_can_evaluate_h2=cache_h2 is not None)
        h2_obs = cache_h2
        h2_from_search = False
        h2_result = None
        if h2 is not None and cache_h2 is None and plan.max_searches > 0:
            if self._lookup_searches >= self._max_search_requests:
                plan = plan_discovery(hypothesis, trigger=trigger, cache_can_evaluate_h2=False)
            else:
                wait = self._h2_wait_seconds()
                if wait > 0:
                    return self._queued_h2_result(
                        request,
                        diagnostics,
                        league,
                        h2=h2,
                        wait=wait,
                        h1_obs=h1_obs,
                        plan=plan,
                    )
                h2_result = self._search_alternate(
                    request,
                    diagnostics,
                    league,
                    cache_key=cache_key,
                    h2=h2,
                    fx_table=fx_table,
                )
                h2_from_search = True
                if h2_result is not None and h2_result.estimate.has_currency_estimate:
                    h2_obs = self._observation_from_live(
                        h2,
                        result=h2_result,
                        diagnostics=diagnostics,
                        query_source="SEARCH",
                        search_requests=self._lookup_searches,
                    )
                elif h2_result is not None and h2_result.live_search_state == LiveSearchState.LIVE_SEARCH_RATE_LIMITED:
                    return self._queued_h2_result(
                        request,
                        diagnostics,
                        league,
                        h2=h2,
                        wait=float(
                            (h2_result.diagnostics.rate_limit_retry_after if h2_result.diagnostics else 0.0) or 1.0
                        ),
                        h1_obs=h1_obs,
                        plan=plan,
                    )
                else:
                    h2_obs = self._observation_from_live(
                        h2,
                        result=None,
                        diagnostics=diagnostics,
                        query_source="SEARCH",
                        search_requests=self._lookup_searches,
                    )

        selection = select_final(h1_obs, h2_obs, h2_from_search=h2_from_search)
        if selection.winner.value == "H2_RECOVERY" and h2_result is not None and h2_result.estimate.has_currency_estimate:
            base = h2_result
        elif selection.winner.value == "H2_RECOVERY" and cache_h2 is not None:
            cached = self._cached_result_for_hypothesis(request, h2, league)
            if cached is not None and cached.estimate.has_currency_estimate:
                base = cached
            else:
                base = self._synthetic_cached_result(request, h2, cache_h2, league)
        elif h1_result is not None:
            base = h1_result
        else:
            base = self._failure_result(
                request,
                terminal_state or LiveSearchState.LIVE_SEARCH_OK_ZERO_RESULTS,
                diagnostics,
                message=terminal_message or selection.note,
            )
        finished = self._with_discovery(
            base,
            request,
            diagnostics,
            league,
            h1_obs=h1_obs,
            h2_obs=h2_obs,
            plan=plan,
            selection=selection,
        )
        logger.info(
            "price_check_discovery h1=%s trigger=%s h2=%s final=%s stability=%s searches=%s cache=%s",
            h1_obs.fingerprint,
            trigger.value if trigger else None,
            h2.query_fingerprint if h2 is not None else None,
            selection.winner.value,
            selection.stability.value,
            self._lookup_searches,
            cache_h2 is not None,
        )
        return finished

    def _h2_wait_seconds(self) -> float:
        try:
            from exilelens.price_check.rate_policy import SEARCH

            return float(self._client.seconds_until_safe(SEARCH) or 0.0)
        except Exception:  # noqa: BLE001
            return 0.0

    def _search_alternate(
        self,
        request: PriceCheckRequest,
        diagnostics: LiveAcquisitionDiagnostics,
        league: str,
        *,
        cache_key: str | None,
        h2,
        fx_table,
    ) -> PriceCheckResult | None:
        h2_key = None
        if self._cache is not None:
            h2_key = self._cache.make_key(
                item_fingerprint=request.content_hash,
                league=league,
                provider_id=self.provider_id,
                provider_generation=self.provider_generation,
                hypothesis_fingerprint=h2.query_fingerprint,
            )
        h2_request = replace(request, hypothesis=h2)
        return self._lookup_pipeline(
            h2_request,
            diagnostics,
            league,
            cache_key=h2_key or cache_key,
            skip_discovery=True,
            preserve_counters=True,
        )

    def _evaluate_hypothesis_locally(
        self,
        request: PriceCheckRequest,
        hypothesis,
        league: str,
        fx_table,
    ):
        if hypothesis is None:
            return None
        cached = self._cached_result_for_hypothesis(request, hypothesis, league)
        if cached is not None and cached.estimate.has_currency_estimate:
            return self._observation_from_live(
                hypothesis,
                result=cached,
                diagnostics=None,
                query_source="CACHE",
                search_requests=0,
            )
        if self._session is None:
            return None
        from exilelens.price_check.comparable_query import listing_similarity_score
        from exilelens.price_check.market_session import neighbourhood_identity, query_fingerprint

        query = build_search_query(request.item_raw, league=league, hypothesis=hypothesis)
        query = replace(query, hypothesis=hypothesis)
        hit = self._session.lookup(
            league=league,
            neighbourhood=neighbourhood_identity(hypothesis),
            source_query=query_fingerprint(query, league=league),
        )
        if hit is None or hit.count <= 0:
            return None
        similar = [row for row in hit.listings if _live_similarity_match(row.item_raw, query)]
        if len(similar) < _MIN_BAND_COMPARABLES:
            return None
        band, _confidence, kept = build_band_estimate(
            similar,
            query=query,
            league_known=True,
            fx_table=fx_table,
        )
        if band is None or len(kept) < _MIN_BAND_COMPARABLES:
            return None
        amounts = [float(row.normalized_amount or row.price_amount or 0.0) for row in kept]
        sims = [listing_similarity_score(row.item_raw, query) for row in kept]
        return observation_from_counts(
            hypothesis,
            remote_count=hit.total_candidates,
            fetched_count=len(hit.listings),
            priced_count=len(hit.listings),
            accepted_count=len(kept),
            amounts=amounts,
            similarities=sims,
            query_source="SESSION",
            search_requests=0,
            query_age_seconds=hit.age_seconds,
            http_status=200,
        )

    def _cached_result_for_hypothesis(self, request: PriceCheckRequest, hypothesis, league: str):
        if self._cache is None or hypothesis is None:
            return None
        key = self._cache.make_key(
            item_fingerprint=request.content_hash,
            league=league,
            provider_id=self.provider_id,
            provider_generation=self.provider_generation,
            hypothesis_fingerprint=hypothesis.query_fingerprint,
        )
        return self._cache.get_live(key)

    def _synthetic_cached_result(self, request: PriceCheckRequest, hypothesis, obs, league: str) -> PriceCheckResult:
        from exilelens.price_check.models import CurrencyBand

        median = float(obs.price_median or 0.0)
        high = float(obs.price_high or median)
        low = float(obs.price_low or median)
        estimate = PriceEstimate(
            source_kind=PriceSourceKind.CACHED_LIVE_MARKET,
            confidence=PriceConfidence.LOW,
            currency_bands=(
                CurrencyBand(label="quick_sale", amount=low, currency="exalted"),
                CurrencyBand(label="fair", amount=median, currency="exalted", amount_high=high),
                CurrencyBand(label="optimistic", amount=high, currency="exalted"),
            ),
            summary="Cached neighbourhood estimate",
            disclaimer="Cached live market data — prices may be stale.",
            display_currency="exalted",
        )
        return apply_price_trust(
            PriceCheckResult(
                request=request,
                estimate=estimate,
                provider_id=self.provider_id,
                comparable_count=obs.accepted_count,
                search_basis=hypothesis.search_basis,
                live_search_state=LiveSearchState.LIVE_SEARCH_OK_RESULTS,
                hypothesis=hypothesis,
                estimate_state=estimate_state_for(hypothesis).value,
            )
        )

    def _observation_from_live(
        self,
        hypothesis,
        *,
        result: PriceCheckResult | None,
        diagnostics: LiveAcquisitionDiagnostics | None,
        query_source: str,
        search_requests: int,
    ):
        amounts: list[float] = []
        accepted = 0
        if result is not None and result.estimate.has_currency_estimate:
            accepted = result.comparable_count or len(result.estimate.comparables)
            for row in result.estimate.comparables:
                amount = row.normalized_amount if row.normalized_amount is not None else row.price_amount
                if amount is not None:
                    amounts.append(float(amount))
            if not amounts:
                for band in result.estimate.currency_bands:
                    amounts.append(float(band.amount))
                    if band.amount_high is not None:
                        amounts.append(float(band.amount_high))
        last = None
        remote = 0
        fetched = 0
        priced = 0
        http_status = None
        if diagnostics is not None:
            remote = int(getattr(diagnostics, "result_count", 0) or 0)
            fetched = int(getattr(diagnostics, "fetch_count", 0) or 0)
            priced = int(getattr(diagnostics, "priced_listings", 0) or 0)
            http_status = getattr(diagnostics, "http_status", None)
            passes = getattr(diagnostics, "relaxation_passes", ()) or ()
            if passes:
                last = passes[-1]
        if last is not None:
            if isinstance(last, dict):
                remote = int(last.get("search_total") or remote)
                fetched = int(last.get("fetch_returned") or fetched)
                priced = int(last.get("priced_listings") or priced)
                http_status = last.get("http_status", http_status)
            else:
                remote = int(getattr(last, "search_total", 0) or remote)
                fetched = int(getattr(last, "fetch_returned", 0) or fetched)
                priced = int(getattr(last, "priced_listings", 0) or priced)
                if getattr(last, "http_status", None) is not None:
                    http_status = last.http_status
        age = result.cache_age_seconds if result is not None else None
        return observation_from_counts(
            hypothesis,
            remote_count=remote,
            fetched_count=fetched,
            priced_count=priced,
            accepted_count=accepted,
            amounts=amounts,
            query_source=query_source,
            search_requests=search_requests,
            query_age_seconds=age,
            http_status=http_status,
        )

    def _queued_h2_result(
        self,
        request: PriceCheckRequest,
        diagnostics: LiveAcquisitionDiagnostics,
        league: str,
        *,
        h2,
        wait: float,
        h1_obs,
        plan: HypothesisPlan,
    ) -> PriceCheckResult:
        diagnostics.live_state = LiveSearchState.LIVE_SEARCH_RATE_LIMITED
        diagnostics.rate_limit_retry_after = wait
        diagnostics.final_source = "queued_h2"
        self._attach_request_counts(diagnostics)
        result = self._rate_limited_result(request, diagnostics, wait, league)
        market_status = f"Refining market match — queued ~{max(1, int(wait))}s"
        selection = DiscoverySelection(
            final_hypothesis=h2,
            original_hypothesis=h1_obs.hypothesis,
            estimate_state=estimate_state_for(h1_obs.hypothesis),
            stability=HypothesisStability.UNMEASURED,
            winner=FinalHypothesis.H1,
            auto_adjusted=False,
            note=market_status,
            pending_hypothesis=h2,
            queued=True,
            queued_seconds=wait,
        )
        return replace(
            result,
            hypothesis=h1_obs.hypothesis,
            pending_hypothesis=h2,
            original_hypothesis=h1_obs.hypothesis,
            market_status=market_status,
            message=market_status,
            discovery=self._discovery_payload(plan, h1_obs, None, selection),
        )

    def _with_discovery(
        self,
        result: PriceCheckResult,
        request: PriceCheckRequest,
        diagnostics: LiveAcquisitionDiagnostics,
        league: str,
        *,
        h1_obs,
        h2_obs,
        plan: HypothesisPlan,
        selection: DiscoverySelection,
    ) -> PriceCheckResult:
        payload = self._discovery_payload(plan, h1_obs, h2_obs, selection)
        h1_ok = bool(h1_obs.usable)
        signature_h1 = selection.original_hypothesis.hypothesis_source is HypothesisSource.SIGNATURE
        discovery_avoided = bool(
            signature_h1
            and h1_ok
            and not selection.auto_adjusted
            and plan.max_searches == 0
        )
        if discovery_avoided and self._signature_store is not None:
            self._signature_store.metrics.discovery_avoided += 1
            self._signature_store.metrics.searches_saved_estimate += 1
        payload = annotate_discovery_payload(
            payload,
            hypothesis=selection.final_hypothesis if signature_h1 and not selection.auto_adjusted else selection.original_hypothesis,
            store=self._signature_store,
            discovery_avoided=discovery_avoided,
        )
        diag = result.diagnostics
        if diag is not None:
            diag = replace(diag, discovery=payload)
        estimate = result.estimate
        live_state = result.live_search_state
        if selection.auto_adjusted and result.estimate.has_currency_estimate:
            estimate = replace(
                estimate,
                summary=selection.note or estimate.summary,
                disclaimer=selection.note or estimate.disclaimer,
            )
            live_state = LiveSearchState.LIVE_SEARCH_OK_RESULTS
        elif selection.winner.value == "NEEDS_REFINEMENT" and not selection.auto_adjusted:
            live_state = live_state or LiveSearchState.LIVE_COMPARABLES_TOO_WEAK
        finished = replace(
            result,
            estimate=estimate,
            hypothesis=selection.final_hypothesis,
            original_hypothesis=selection.original_hypothesis,
            estimate_state=selection.estimate_state.value,
            stability=selection.stability.value,
            auto_adjusted=selection.auto_adjusted,
            pending_hypothesis=selection.pending_hypothesis,
            discovery=payload,
            diagnostics=diag,
            live_search_state=live_state,
            search_basis=selection.final_hypothesis.search_basis,
        )
        finished = apply_price_trust(finished)
        if selection.pending_hypothesis is None:
            try:
                record_signature_evidence(
                    self._signature_store,
                    request=request,
                    result=finished,
                )
            except Exception:  # noqa: BLE001 - learning must never break a price check
                logger.exception("market signature evidence write failed")
        return finished

    def _discovery_payload(self, plan: HypothesisPlan, h1_obs, h2_obs, selection: DiscoverySelection) -> dict:
        return {
            "plan": plan.to_dict(),
            "h1": h1_obs.to_dict(),
            "h2": h2_obs.to_dict() if h2_obs is not None else None,
            "final": selection.to_dict(),
            "stability": selection.stability.value,
            "total_search_requests": self._lookup_searches,
            "cache_hits": 1 if h2_obs is not None and h2_obs.query_source in {"CACHE", "SESSION"} else 0,
        }

    def _remember_neighbourhood(self, listings, *, league: str, query) -> None:
        if query.compiled_query is not None:
            return
        """Store real fetched listings so nearby items can reuse this search."""
        if self._session is None or not listings:
            return
        from exilelens.price_check.market_session import (
            neighbourhood_fingerprint,
            query_fingerprint,
        )

        try:
            self._session.record(
                listings,
                league=league,
                neighbourhood=neighbourhood_fingerprint(query, league=league),
                source_query=query_fingerprint(query, league=league),
            )
        except Exception:  # noqa: BLE001 - caching must never break a price check
            logger.exception("market session cache write failed")

    def _attach_pass_funnel(
        self,
        pass_diag: RelaxationPassDiagnostics,
        *,
        query,
        http_status: int | None,
        search_total: int,
        result_ids: list[str],
        fetch_requests: int,
        fetched_count: int,
        listings: list[ComparableListing],
        fx_table: CurrencyFxTable,
        similar: list[ComparableListing] | None = None,
        kept: list[ComparableListing] | None = None,
        has_currency_estimate: bool = False,
        failure_reason: str = "",
    ) -> None:
        pass_diag.funnel = build_pass_funnel_snapshot(
            query=query,
            http_status=http_status,
            search_result_count=search_total,
            query_result_ids_count=len(result_ids),
            fetch_requests=fetch_requests,
            fetched_listing_count=fetched_count,
            listings=listings,
            similar=similar,
            kept=kept,
            fx_table=fx_table,
            has_currency_estimate=has_currency_estimate,
            failure_reason=failure_reason,
        )

    def _attach_request_counts(self, diagnostics: LiveAcquisitionDiagnostics) -> None:
        diagnostics.search_requests = self._client.search_requests
        diagnostics.fetch_requests = self._client.fetch_requests
        diagnostics.total_http_requests = self._client.total_http_requests
        logger.info(
            "price_check_requests price_check_id=%s search=%s fetch=%s total=%s",
            diagnostics.price_check_id,
            diagnostics.search_requests,
            diagnostics.fetch_requests,
            diagnostics.total_http_requests,
        )

    def _cached_rate_limit_result(
        self,
        request: PriceCheckRequest,
        cache_key: str | None,
        retry_after: float | None,
        diagnostics: LiveAcquisitionDiagnostics,
        league: str,
    ) -> PriceCheckResult | None:
        if cache_key is None or self._cache is None:
            return None
        cached = self._cache.get_live(cache_key) or self._cache.get_stale(cache_key)
        if cached is None or not cached.estimate.has_currency_estimate:
            return None
        age = cached.cache_age_seconds or self._cache.cache_age_seconds(cache_key)
        market_status = _market_status_rate_limited(retry_after)
        estimate = PriceEstimate(
            source_kind=PriceSourceKind.CACHED_LIVE_MARKET,
            confidence=cached.estimate.confidence,
            currency_bands=cached.estimate.currency_bands,
            comparables=cached.estimate.comparables,
            summary=cached.estimate.summary or "Cached live market estimate",
            disclaimer=f"Cached live market data ({int(age or 0)}s old) — market temporarily limited.",
        )
        diagnostics.live_state = LiveSearchState.LIVE_SEARCH_RATE_LIMITED
        diagnostics.final_source = "cached_live_during_rate_limit"
        diagnostics.cache_age_seconds = age
        return PriceCheckResult(
            request=request,
            estimate=estimate,
            provider_id=self.provider_id,
            comparable_count=cached.comparable_count,
            search_basis=cached.search_basis,
            search_relaxation_tier=cached.search_relaxation_tier,
            cache_hit=True,
            cache_age_seconds=age,
            market_status=market_status,
            live_search_state=LiveSearchState.LIVE_SEARCH_RATE_LIMITED,
            diagnostics=self._result_diagnostics(
                request,
                diagnostics,
                league,
                market_status=market_status,
                cache_age_seconds=age,
            ),
        )

    def _rate_limited_result(
        self,
        request: PriceCheckRequest,
        diagnostics: LiveAcquisitionDiagnostics,
        retry_after: float | None,
        league: str,
    ) -> PriceCheckResult:
        market_status = _market_status_rate_limited(retry_after)
        message = market_status
        return PriceCheckResult(
            request=request,
            estimate=_failure_estimate(LiveSearchState.LIVE_SEARCH_RATE_LIMITED, message),
            provider_id=self.provider_id,
            message=message,
            live_search_state=LiveSearchState.LIVE_SEARCH_RATE_LIMITED,
            market_status=market_status,
            diagnostics=self._result_diagnostics(
                request,
                diagnostics,
                league,
                market_status=market_status,
            ),
        )

    def _failure_result(
        self,
        request: PriceCheckRequest,
        state: LiveSearchState,
        diagnostics: LiveAcquisitionDiagnostics,
        *,
        message: str,
    ) -> PriceCheckResult:
        auth_required = state == LiveSearchState.LIVE_SEARCH_AUTH_REQUIRED
        return PriceCheckResult(
            request=request,
            estimate=_failure_estimate(state, message),
            provider_id=self.provider_id,
            message=message,
            live_search_state=state,
            hypothesis=request.hypothesis,
            estimate_state=(
                estimate_state_for(request.hypothesis).value if request.hypothesis is not None else ""
            ),
            diagnostics=self._result_diagnostics(
                request,
                diagnostics,
                diagnostics.canonical_league or request.league.league,
                auth_required=auth_required,
            ),
        )

    def _result_diagnostics(
        self,
        request: PriceCheckRequest,
        diagnostics: LiveAcquisitionDiagnostics,
        league: str | None,
        *,
        auth_required: bool = False,
        market_status: str | None = None,
        cache_age_seconds: float | None = None,
    ) -> PriceCheckDiagnostics:
        return PriceCheckDiagnostics(
            league=league,
            league_source=diagnostics.league_source,
            provider_id=self.provider_id,
            authentication_mode=self.capabilities.authentication_mode.value,
            auth_required=auth_required,
            query_summary=str(diagnostics.generated_query.get("query", {}).get("type", "")),
            relaxation_tier=diagnostics.relaxation_passes[-1].relaxation_tier if diagnostics.relaxation_passes else None,
            comparable_count=diagnostics.similarity_counts.get(
                f"pass_{len(diagnostics.relaxation_passes) - 1}", 0
            )
            if diagnostics.relaxation_passes
            else 0,
            http_status=diagnostics.http_status,
            price_check_id=request.request_id,
            live_state=diagnostics.live_state,
            search_id=diagnostics.search_id,
            fetch_count=diagnostics.fetch_count,
            priced_listings=diagnostics.priced_listings,
            currencies=tuple(diagnostics.currencies),
            similarity_counts=dict(diagnostics.similarity_counts),
            relaxation_passes=tuple(row.to_dict() for row in diagnostics.relaxation_passes),
            search_url=diagnostics.search_url,
            rate_limit_retry_after=diagnostics.rate_limit_retry_after,
            search_requests=diagnostics.search_requests,
            fetch_requests=diagnostics.fetch_requests,
            total_http_requests=diagnostics.total_http_requests,
            cache_age_seconds=cache_age_seconds,
        )

    def _search(self, league: str, body: dict[str, Any]):
        self._lookup_searches = int(getattr(self, "_lookup_searches", 0)) + 1
        if self._search_fn is not None:
            return self._search_fn(league, body)
        return self._client.search(league, body)

    def _proactive_fetch_withhold(
        self,
        request: PriceCheckRequest,
        diagnostics: LiveAcquisitionDiagnostics,
        fetch_cont: FetchContinuation,
    ) -> PriceCheckResult | None:
        wait = self._client.seconds_until_safe(FETCH)
        if wait <= 0:
            return None
        withhold = build_fetch_withhold(
            wait_seconds=wait,
            request_id=request.request_id,
            fetch=fetch_cont,
            proactive=True,
            reason="fetch_pacing",
        )
        return self._network_withhold_result(request, diagnostics, withhold)

    def _fetch_error_withhold(
        self,
        request: PriceCheckRequest,
        diagnostics: LiveAcquisitionDiagnostics,
        league: str,
        *,
        fetch_cont: FetchContinuation,
        exc: Trade2Error,
        pass_diag: RelaxationPassDiagnostics,
    ) -> PriceCheckResult | None:
        if exc.code not in {"rate_limit_pacing", "rate_limited"}:
            return None
        wait = max(
            float(self._client.seconds_until_safe(FETCH)),
            float(exc.retry_after or 0.0),
        )
        proactive = exc.code == "rate_limit_pacing" or exc.http_status is None
        if proactive and wait > 0:
            withhold = build_fetch_withhold(
                wait_seconds=wait,
                request_id=request.request_id,
                fetch=fetch_cont,
                proactive=True,
                reason="fetch_pacing",
            )
            return self._network_withhold_result(request, diagnostics, withhold)
        if exc.http_status == 429:
            diagnostics.http_status = 429
            diagnostics.rate_limit_retry_after = wait
            self._attach_request_counts(diagnostics)
            log_live_acquisition(diagnostics)
            return self._rate_limited_result(request, diagnostics, wait, league)
        if wait > 0:
            withhold = build_fetch_withhold(
                wait_seconds=wait,
                request_id=request.request_id,
                fetch=fetch_cont,
                proactive=False,
                reason="fetch_penalty",
            )
            return self._network_withhold_result(request, diagnostics, withhold)
        return None

    def _network_withhold_result(
        self,
        request: PriceCheckRequest,
        diagnostics: LiveAcquisitionDiagnostics,
        withhold,
    ) -> PriceCheckResult:
        diagnostics.live_state = LiveSearchState.LIVE_SEARCH_RATE_LIMITED
        diagnostics.rate_limit_retry_after = withhold.wait_seconds
        diagnostics.final_source = "network_withhold"
        self._attach_request_counts(diagnostics)
        log_live_acquisition(diagnostics)
        if withhold.is_fetch_stage:
            message = f"Comparables queued — ~{max(1, int(math.ceil(withhold.wait_seconds)))}s"
        else:
            message = f"Live search queued — ~{max(1, int(math.ceil(withhold.wait_seconds)))}s"
        return PriceCheckResult(
            request=request,
            estimate=PriceEstimate(
                source_kind=PriceSourceKind.UNKNOWN,
                confidence=PriceConfidence.NONE,
                summary=message,
                disclaimer=message,
            ),
            provider_id=self.provider_id,
            message=message,
            live_search_state=LiveSearchState.LIVE_SEARCH_RATE_LIMITED,
            market_status=message,
            network_withhold=withhold,
            diagnostics=self._result_diagnostics(
                request,
                diagnostics,
                diagnostics.canonical_league or request.league.league,
                market_status=message,
            ),
            hypothesis=request.hypothesis,
        )

    def _fetch_progressive_resumable(
        self,
        fetch_cont: FetchContinuation,
        *,
        stop_when: Callable[[list[dict[str, Any]]], bool],
    ) -> tuple[list[dict[str, Any]], FetchContinuation]:
        rows: list[dict[str, Any]] = []
        batch_size = max(1, self._client.fetch_batch_size)
        offset = int(fetch_cont.fetch_offset or 0)
        result_ids = list(fetch_cont.result_ids)
        fetch_batches = 0
        while offset < len(result_ids):
            if fetch_batches >= self._max_fetch_requests:
                break
            batch = result_ids[offset : offset + batch_size]
            if self._fetch_fn is not None:
                rows.extend(self._fetch_fn(batch, fetch_cont.query_id))
                self._client.fetch_requests += 1
            else:
                rows.extend(self._client._fetch_batch(batch, fetch_cont.query_id))
            offset += len(batch)
            fetch_batches += 1
            fetch_cont = replace(fetch_cont, fetch_offset=offset)
            if stop_when(rows):
                break
        return rows, fetch_cont

    def _lookup_pipeline_resume_fetch(
        self,
        request: PriceCheckRequest,
        diagnostics: LiveAcquisitionDiagnostics,
        league: str,
        *,
        cache_key: str | None,
        fetch_cont: FetchContinuation,
        skip_discovery: bool,
        preserve_counters: bool,
    ) -> PriceCheckResult:
        if not preserve_counters:
            self._client.reset_request_counters()
            self._lookup_searches = 1
        diagnostics.search_id = fetch_cont.query_id
        diagnostics.http_status = fetch_cont.search_http_status
        diagnostics.result_count = fetch_cont.search_total
        tier = RelaxationTier(fetch_cont.relaxation_tier)
        pass_index = fetch_cont.pass_index
        pass_diag = RelaxationPassDiagnostics(
            pass_index=pass_index,
            relaxation_tier=int(tier),
            http_status=fetch_cont.search_http_status,
            search_total=fetch_cont.search_total,
            search_result_count=len(fetch_cont.result_ids),
            search_id=fetch_cont.query_id,
            fetch_requested=len(fetch_cont.result_ids),
        )
        base_query = build_search_query(request.item_raw, league=league)
        if request.hypothesis is not None:
            base_query = replace(base_query, hypothesis=request.hypothesis)
        if isinstance(request, CompiledPriceCheckRequest):
            base_query = replace(base_query, hypothesis=None, features=(), mods=(), compiled_query=request.compiled_query)
            diagnostics.generated_query = request.compiled_query.body
        query = with_relaxation(base_query, tier)
        fx_table = CurrencyFxTable(league=league, client=self._client)
        fetch_state = {"query": query, "similar": 0, "listings": []}

        withhold = self._proactive_fetch_withhold(request, diagnostics, fetch_cont)
        if withhold is not None:
            diagnostics.relaxation_passes.append(pass_diag)
            return withhold

        def _stop_when(rows: list[dict[str, Any]]) -> bool:
            listings = _parse_fetched_listings(rows, league=league, source=self.provider_id)
            similar = _filter_similar_listings(listings, fetch_state["query"])
            fetch_state["similar"] = len(similar)
            fetch_state["listings"] = similar
            if len(similar) >= _TARGET_SAMPLE:
                return True
            return count_fx_usable_listings(similar, fx_table=fx_table) >= _MIN_BAND_COMPARABLES

        fetch_requests_before = self._client.fetch_requests
        try:
            fetched, fetch_cont = self._fetch_progressive_resumable(fetch_cont, stop_when=_stop_when)
        except Trade2Error as exc:
            withhold = self._fetch_error_withhold(
                request,
                diagnostics,
                league,
                fetch_cont=fetch_cont,
                exc=exc,
                pass_diag=pass_diag,
            )
            if withhold is not None:
                diagnostics.relaxation_passes.append(pass_diag)
                return withhold
            raise
        fetch_requests_delta = self._client.fetch_requests - fetch_requests_before
        pass_diag.fetch_returned = len(fetched)
        diagnostics.fetch_count = len(fetched)
        listings = _parse_fetched_listings(fetched, league=league, source=self.provider_id)
        pass_diag.priced_listings = len(listings)
        diagnostics.priced_listings = len(listings)
        self._remember_neighbourhood(listings, league=league, query=query)
        diagnostics.currencies = sorted({str(row.price_currency or "") for row in listings if row.price_currency})
        if not listings:
            diagnostics.relaxation_passes.append(pass_diag)
            diagnostics.live_state = LiveSearchState.LIVE_FETCH_NO_PRICES
            diagnostics.final_source = "fetch_no_prices"
            self._attach_request_counts(diagnostics)
            log_live_acquisition(diagnostics)
            return self._failure_result(
                request,
                LiveSearchState.LIVE_FETCH_NO_PRICES,
                diagnostics,
                message="Listings were fetched but no priced asks were parsed.",
            )
        similar = fetch_state["listings"] or _filter_similar_listings(listings, query)
        pass_diag.similarity_matched = len(similar)
        diagnostics.similarity_counts[f"pass_{pass_index}"] = len(similar)
        fx_usable = count_fx_usable_listings(similar, fx_table=fx_table)
        pass_diag.fx_usable = fx_usable
        if len(similar) <= 2:
            diagnostics.relaxation_passes.append(pass_diag)
            return self._apply_discovery(
                request,
                diagnostics,
                league,
                cache_key=cache_key,
                h1_result=None,
                fx_table=fx_table,
                terminal_state=LiveSearchState.LIVE_COMPARABLES_TOO_WEAK,
                terminal_message="Too few similar priced listings for a confident band.",
                skip_discovery=skip_discovery,
            )
        band, confidence, kept = build_band_estimate(
            similar,
            query=query,
            league_known=request.league.status == LeagueStatus.KNOWN,
            fx_table=fx_table,
        )
        reason = confidence_reason(
            sample_count=len(kept),
            amounts=[row.normalized_amount or 0.0 for row in kept],
            relaxation_tier=query.relaxation_tier,
        )
        if band is None or len(kept) < _MIN_BAND_COMPARABLES:
            diagnostics.relaxation_passes.append(pass_diag)
            return self._apply_discovery(
                request,
                diagnostics,
                league,
                cache_key=cache_key,
                h1_result=None,
                fx_table=fx_table,
                terminal_state=LiveSearchState.LIVE_COMPARABLES_TOO_WEAK,
                terminal_message="Too few similar priced listings for a confident band.",
                skip_discovery=skip_discovery,
            )
        comparables = tuple(kept)
        summary = f"{len(kept)} live comparable listing{'s' if len(kept) != 1 else ''}"
        if len(kept) <= 7:
            summary = f"Tentative estimate from {len(kept)} similar listings"
        estimate = PriceEstimate(
            source_kind=PriceSourceKind.LIVE_MARKET,
            confidence=confidence,
            currency_bands=band.to_currency_bands(),
            comparables=comparables,
            summary=summary,
            disclaimer="Live trade comparables — verify listing before trading.",
            display_currency=band.currency,
            confidence_reason=reason,
        )
        diagnostics.live_state = LiveSearchState.LIVE_SEARCH_OK_RESULTS
        diagnostics.final_source = "live_trade2"
        self._attach_pass_funnel(
            pass_diag,
            query=query,
            http_status=fetch_cont.search_http_status,
            search_total=fetch_cont.search_total,
            result_ids=list(fetch_cont.result_ids),
            fetch_requests=fetch_requests_delta,
            fetched_count=len(fetched),
            listings=listings,
            similar=similar,
            kept=kept,
            fx_table=fx_table,
            has_currency_estimate=True,
            failure_reason="",
        )
        diagnostics.relaxation_passes.append(pass_diag)
        self._attach_request_counts(diagnostics)
        log_live_acquisition(diagnostics)
        result = PriceCheckResult(
            request=request,
            estimate=estimate,
            provider_id=self.provider_id,
            comparable_count=len(kept),
            search_basis=query.search_basis,
            matched_features=query.matched_summary(),
            identity_source=query.economic_identity.source.value,
            search_relaxation_tier=int(tier),
            live_search_state=LiveSearchState.LIVE_SEARCH_OK_RESULTS,
            diagnostics=self._result_diagnostics(request, diagnostics, league),
            hypothesis=query.hypothesis,
            estimate_state=(
                estimate_state_for(query.hypothesis).value if query.hypothesis is not None else ""
            ),
        )
        result = self._apply_discovery(
            request,
            diagnostics,
            league,
            cache_key=cache_key,
            h1_result=result,
            fx_table=fx_table,
            skip_discovery=skip_discovery,
        )
        if cache_key and self._cache is not None and result.estimate.has_currency_estimate:
            self._cache.put(cache_key, result)
        self._last_live_state = result.live_search_state
        return result

    def _fetch_progressive(
        self,
        result_ids: list[str],
        query_id: str,
        *,
        stop_when: Callable[[list[dict[str, Any]]], bool],
    ) -> list[dict[str, Any]]:
        if self._fetch_fn is not None:
            rows: list[dict[str, Any]] = []
            batch_size = max(1, self._client.fetch_batch_size)
            fetch_batches = 0
            for offset in range(0, len(result_ids), batch_size):
                if fetch_batches >= self._max_fetch_requests:
                    break
                batch = result_ids[offset : offset + batch_size]
                rows.extend(self._fetch_fn(batch, query_id))
                fetch_batches += 1
                self._client.fetch_requests += 1
                if stop_when(rows):
                    break
            return rows
        return self._client.fetch_progressive(
            result_ids,
            query_id,
            stop_when=stop_when,
            max_fetch_requests=self._max_fetch_requests,
        )


LiveTrade2Provider = LiveTradeComparableProvider

__all__ = ["LiveTradeComparableProvider", "LiveTrade2Provider"]
