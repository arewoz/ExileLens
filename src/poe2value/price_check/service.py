from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from poe2value.items.raw_input import RawItemInput
from poe2value.items.recognition import recognize_input
from poe2value.price_check.cache import PriceCheckCache
from poe2value.price_check.diagnostic_mode import is_theoretical_disabled, resolve_price_check_diagnostic_mode
from poe2value.price_check.live_acquisition import live_trade2_strict_mode
from poe2value.price_check.market_policy import is_live_market_enabled
from poe2value.price_check.models import (
    CompiledPriceCheckRequest,
    LeagueContext,
    LiveSearchState,
    PriceCheckDiagnostics,
    PriceCheckRequest,
    PriceCheckResult,
    PriceConfidence,
    PriceEstimate,
    PriceSourceKind,
)
from poe2value.price_check.market_signatures import build_assisted_hypothesis
from poe2value.price_check.presentation import build_price_check_presentation
from poe2value.price_check.provider import MarketCandidateProvider
from poe2value.price_check.theoretical import classify_theoretical_desirability
from poe2value.price_check.providers.theoretical import TheoreticalValueProvider


def _provider_result_label(provider_id: str, result: PriceCheckResult | None) -> str:
    if result is None:
        return f"{provider_id}:skipped"
    if result.is_live_failure:
        state = result.live_search_state.value if result.live_search_state else "live_failure"
        return f"{provider_id}:{state}"
    if result.estimate.has_currency_estimate:
        return f"{provider_id}:hit"
    return f"{provider_id}:miss"


def _attach_pipeline_diagnostics(
    result: PriceCheckResult,
    *,
    request: PriceCheckRequest,
    provider_enabled: bool,
    provider_selected: tuple[str, ...],
    provider_attempted: tuple[str, ...],
    provider_result: str,
) -> PriceCheckResult:
    existing = result.diagnostics
    diagnostics = PriceCheckDiagnostics(
        league=existing.league if existing else request.league.league,
        league_source=existing.league_source if existing else request.league_source,
        provider_id=existing.provider_id if existing else result.provider_id,
        authentication_mode=existing.authentication_mode if existing else None,
        auth_required=existing.auth_required if existing else False,
        query_summary=existing.query_summary if existing else "",
        relaxation_tier=existing.relaxation_tier if existing else None,
        comparable_count=existing.comparable_count if existing else result.comparable_count,
        http_status=existing.http_status if existing else None,
        price_check_id=request.request_id,
        live_state=existing.live_state if existing else result.live_search_state,
        search_id=existing.search_id if existing else None,
        fetch_count=existing.fetch_count if existing else 0,
        priced_listings=existing.priced_listings if existing else 0,
        currencies=existing.currencies if existing else (),
        similarity_counts=existing.similarity_counts if existing else None,
        relaxation_passes=existing.relaxation_passes if existing else (),
        search_url=existing.search_url if existing else None,
        rate_limit_retry_after=existing.rate_limit_retry_after if existing else None,
        search_requests=existing.search_requests if existing else 0,
        fetch_requests=existing.fetch_requests if existing else 0,
        total_http_requests=existing.total_http_requests if existing else 0,
        cache_age_seconds=existing.cache_age_seconds if existing else result.cache_age_seconds,
        provider_enabled=provider_enabled,
        provider_selected=provider_selected,
        provider_attempted=provider_attempted,
        provider_result=provider_result,
    )
    # MARKET-01B13: `replace` rather than a hand-written field list. The list here had
    # gone stale and was silently dropping `matched_features`, so B12's "Matched:" line
    # never survived the trip through the service — only the diagnostics change.
    result = replace(result, request=request, diagnostics=diagnostics)
    if isinstance(request, CompiledPriceCheckRequest):
        from poe2value.price_check.price_trust import apply_price_trust
        result = apply_price_trust(result)
    return result


def _live_provider_disabled_result(request: PriceCheckRequest) -> PriceCheckResult:
    message = "Live market search is disabled for this build."
    estimate = PriceEstimate(
        source_kind=PriceSourceKind.LIVE_MARKET,
        confidence=PriceConfidence.NONE,
        summary=message,
        disclaimer=message,
    )
    return PriceCheckResult(
        request=request,
        estimate=estimate,
        provider_id="live_trade2",
        message=message,
        live_search_state=LiveSearchState.LIVE_PROVIDER_DISABLED,
        diagnostics=PriceCheckDiagnostics(
            league=request.league.league,
            league_source=request.league_source,
            provider_id="live_trade2",
            price_check_id=request.request_id,
            live_state=LiveSearchState.LIVE_PROVIDER_DISABLED,
            provider_enabled=False,
            provider_selected=(),
            provider_attempted=(),
            provider_result="live_trade2:disabled",
        ),
    )


class PriceCheckService:
    """Orchestrates provider chain for Shift+C price check. No PoB evaluation."""

    def __init__(
        self,
        providers: Iterable[MarketCandidateProvider] | None = None,
        cache: PriceCheckCache | None = None,
        *,
        strict_live: bool | None = None,
        live_market_mode: str | None = None,
        settings_strict_live: bool | None = None,
        diagnostic_mode: str | None = None,
    ) -> None:
        self._providers = list(providers or [])
        self._cache = cache or PriceCheckCache()
        self._fallback = TheoreticalValueProvider()
        self._live_market_mode = live_market_mode
        self._diagnostic_mode = resolve_price_check_diagnostic_mode(diagnostic_mode)
        self._provider_enabled = is_live_market_enabled(live_market_mode)
        self._strict_live = (
            strict_live
            if strict_live is not None
            else live_trade2_strict_mode(settings_strict_live)
        )
        self._theoretical_disabled = is_theoretical_disabled(diagnostic_mode)
        self._provider_selected = tuple(provider.provider_id for provider in self._providers)

    @property
    def cache(self) -> PriceCheckCache:
        return self._cache

    def cached_compiled(self, request: CompiledPriceCheckRequest) -> PriceCheckResult | None:
        """Exact body cache lookup before controller pacing; never enters a provider."""
        from poe2value.price_check.price_trust import apply_price_trust
        for provider in self._providers:
            key = self._cache.make_key(item_fingerprint=request.content_hash,
                league=request.league.league, provider_id=provider.provider_id,
                provider_generation="v3-compiled", hypothesis_fingerprint=request.compiled_query.query_fingerprint)
            cached = self._cache.get(key)
            if cached is not None:
                return apply_price_trust(replace(cached, request=request))
        return None

    def check(self, request: PriceCheckRequest) -> PriceCheckResult:
        if not str(request.item_raw or "").strip():
            estimate = PriceEstimate(
                source_kind=PriceSourceKind.UNKNOWN,
                confidence=PriceConfidence.NONE,
                summary="No item text",
                disclaimer="No item text available.",
            )
            return PriceCheckResult(
                request=request,
                estimate=estimate,
                provider_id="none",
                no_item_text=True,
                message="No current item text available.",
            )

        raw = RawItemInput.from_text(request.item_raw)
        recognition = recognize_input(raw)
        if not recognition.recognized:
            estimate = PriceEstimate(
                source_kind=PriceSourceKind.UNKNOWN,
                confidence=PriceConfidence.NONE,
                summary="Not a recognized item",
                disclaimer="Clipboard does not contain recognizable PoE2 item text.",
            )
            return PriceCheckResult(
                request=request,
                estimate=estimate,
                provider_id="none",
                message="Clipboard does not contain recognizable PoE2 item text.",
            )

        provider_enabled = self._provider_enabled
        provider_selected = self._provider_selected
        provider_attempted: list[str] = []
        provider_results: list[str] = []

        if not provider_enabled and not self._providers:
            return _live_provider_disabled_result(request)

        auth_required = False
        live_failure: PriceCheckResult | None = None
        compiled = isinstance(request, CompiledPriceCheckRequest)
        hypothesis = None if compiled else request.hypothesis or build_assisted_hypothesis(
            request.item_raw, league=request.league.league
        )
        if not compiled and request.hypothesis is None:
            request = replace(request, hypothesis=hypothesis)
        for provider in self._providers:
            provider_attempted.append(provider.provider_id)
            cache_key = self._cache.make_key(
                item_fingerprint=request.content_hash,
                league=request.league.league,
                provider_id=provider.provider_id,
                provider_generation="v3-compiled" if compiled else "v2-assisted",
                hypothesis_fingerprint=request.compiled_query.query_fingerprint if compiled else hypothesis.query_fingerprint,
            )
            cached = self._cache.get(cache_key)
            if cached is not None:
                provider_results.append(_provider_result_label(provider.provider_id, cached))
                return _attach_pipeline_diagnostics(
                    cached,
                    request=request,
                    provider_enabled=provider_enabled,
                    provider_selected=provider_selected,
                    provider_attempted=tuple(provider_attempted),
                    provider_result=";".join(provider_results),
                )
            result = provider.lookup(request)
            provider_results.append(_provider_result_label(provider.provider_id, result))
            if result is None:
                continue
            if getattr(provider, "_auth_required", False):
                auth_required = True
            if result.diagnostics and result.diagnostics.auth_required:
                auth_required = True
            if result.estimate.has_currency_estimate or (
                compiled and result.live_search_state == LiveSearchState.LIVE_SEARCH_OK_RESULTS
            ):
                # Coverage may withhold the price. Preserve that real result instead
                # of replacing its evidence with a theoretical fallback.
                self._cache.put(cache_key, result)
                return _attach_pipeline_diagnostics(
                    result,
                    request=request,
                    provider_enabled=provider_enabled,
                    provider_selected=provider_selected,
                    provider_attempted=tuple(provider_attempted),
                    provider_result=";".join(provider_results),
                )
            if result.is_live_failure:
                live_failure = result
                continue

        if live_failure is not None and (
            self._strict_live
            or live_failure.live_search_state == LiveSearchState.LIVE_SEARCH_RATE_LIMITED
        ):
            return _attach_pipeline_diagnostics(
                live_failure,
                request=request,
                provider_enabled=provider_enabled,
                provider_selected=provider_selected,
                provider_attempted=tuple(provider_attempted),
                provider_result=";".join(provider_results),
            )

        if not provider_enabled and live_failure is None:
            return _attach_pipeline_diagnostics(
                _live_provider_disabled_result(request),
                request=request,
                provider_enabled=False,
                provider_selected=provider_selected,
                provider_attempted=tuple(provider_attempted),
                provider_result=";".join(provider_results) or "live_trade2:disabled",
            )

        if self._theoretical_disabled:
            message = "Theoretical fallback disabled for diagnostic validation."
            estimate = PriceEstimate(
                source_kind=PriceSourceKind.UNKNOWN,
                confidence=PriceConfidence.NONE,
                summary=message,
                disclaimer=message,
            )
            provider_attempted.append("theoretical")
            provider_results.append("theoretical:disabled")
            return _attach_pipeline_diagnostics(
                PriceCheckResult(
                    request=request,
                    estimate=estimate,
                    provider_id="none",
                    message=message,
                    live_search_state=live_failure.live_search_state if live_failure else None,
                ),
                request=request,
                provider_enabled=provider_enabled,
                provider_selected=provider_selected,
                provider_attempted=tuple(provider_attempted),
                provider_result=";".join(provider_results),
            )

        fallback_key = self._cache.make_key(
            item_fingerprint=request.content_hash,
            league=request.league.league,
            provider_id=self._fallback.provider_id,
            provider_generation="v3-compiled" if compiled else "v2-assisted",
            hypothesis_fingerprint=request.compiled_query.query_fingerprint if compiled else hypothesis.query_fingerprint,
        )
        cached_fallback = self._cache.get(fallback_key)
        if cached_fallback is not None:
            provider_attempted.append(self._fallback.provider_id)
            provider_results.append(_provider_result_label(self._fallback.provider_id, cached_fallback))
            return _attach_pipeline_diagnostics(
                cached_fallback,
                request=request,
                provider_enabled=provider_enabled,
                provider_selected=provider_selected,
                provider_attempted=tuple(provider_attempted),
                provider_result=";".join(provider_results),
            )
        provider_attempted.append(self._fallback.provider_id)
        result = self._fallback.lookup(request)
        assert result is not None
        provider_results.append(_provider_result_label(self._fallback.provider_id, result))
        if auth_required and not result.estimate.has_currency_estimate:
            result = PriceCheckResult(
                request=result.request,
                estimate=result.estimate,
                provider_id=result.provider_id,
                important_mods=result.important_mods,
                message="Connect Trade to search live market.",
                live_search_state=LiveSearchState.LIVE_SEARCH_AUTH_REQUIRED,
                diagnostics=PriceCheckDiagnostics(
                    league=request.league.league,
                    league_source=request.league_source,
                    provider_id="live_trade2",
                    authentication_mode="AUTH_REQUIRED",
                    auth_required=True,
                    price_check_id=request.request_id,
                    live_state=LiveSearchState.LIVE_SEARCH_AUTH_REQUIRED,
                    provider_enabled=provider_enabled,
                    provider_selected=provider_selected,
                    provider_attempted=tuple(provider_attempted),
                    provider_result=";".join(provider_results),
                ),
            )
        else:
            result = _attach_pipeline_diagnostics(
                result,
                request=request,
                provider_enabled=provider_enabled,
                provider_selected=provider_selected,
                provider_attempted=tuple(provider_attempted),
                provider_result=";".join(provider_results),
            )
        self._cache.put(fallback_key, result)
        return result

    def presentation_for(self, result: PriceCheckResult, *, debug: bool = False) -> dict:
        return build_price_check_presentation(result, debug=debug)

    def theoretical_preview(self, item_raw: str) -> tuple:
        return classify_theoretical_desirability(item_raw)
