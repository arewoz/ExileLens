from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from exilelens.price_check.market_policy import resolve_strict_live
from exilelens.price_check.models import LiveSearchState

logger = logging.getLogger(__name__)


_LIVE_STATE_UI: dict[LiveSearchState, tuple[str, str]] = {
    LiveSearchState.LEAGUE_REQUIRED: (
        "LEAGUE REQUIRED",
        "Set or confirm your league before live market search.",
    ),
    LiveSearchState.LIVE_SEARCH_AUTH_REQUIRED: (
        "CONNECT TRADE",
        "Live market search requires trade authentication.",
    ),
    LiveSearchState.LIVE_SEARCH_FORBIDDEN: (
        "MARKET ACCESS BLOCKED",
        "Trade search was forbidden for this session.",
    ),
    LiveSearchState.LIVE_SEARCH_RATE_LIMITED: (
        "MARKET TEMPORARILY LIMITED",
        "Trade search is rate limited. Try again shortly.",
    ),
    LiveSearchState.LIVE_SEARCH_BAD_REQUEST: (
        "MARKET QUERY REJECTED",
        "Trade search rejected the generated query.",
    ),
    LiveSearchState.LIVE_SEARCH_NETWORK_ERROR: (
        "MARKET UNREACHABLE",
        "Could not reach the trade service.",
    ),
    LiveSearchState.LIVE_SEARCH_PARSE_ERROR: (
        "MARKET RESPONSE ERROR",
        "Trade search returned an unreadable response.",
    ),
    LiveSearchState.LIVE_FETCH_ERROR: (
        "LIVE FETCH FAILED",
        "Matching listings were found but could not be fetched.",
    ),
    LiveSearchState.LIVE_FETCH_NO_PRICES: (
        "LIVE PRICES UNREADABLE",
        "Listings were fetched but no priced asks were parsed.",
    ),
    LiveSearchState.LIVE_SEARCH_OK_ZERO_RESULTS: (
        "NO LISTINGS FOUND",
        "No matching listings on trade right now.",
    ),
    LiveSearchState.LIVE_COMPARABLES_TOO_WEAK: (
        "WEAK COMPARABLES",
        "Listings found but too few similar priced items for a band.",
    ),
    LiveSearchState.LIVE_PROVIDER_DISABLED: (
        "LIVE PROVIDER DISABLED",
        "Live market search is disabled for this build.",
    ),
    LiveSearchState.LIVE_PROVIDER_ERROR: (
        "MARKET UNAVAILABLE",
        "The market lookup failed internally; no estimate is shown.",
    ),
    LiveSearchState.LIVE_ITEM_CLASS_UNSUPPORTED: (
        "NO ESTIMATE",
        "Unique items are not priced from their base type, so there is no trustworthy estimate.",
    ),
}


def live_trade2_strict_mode(settings_strict: bool | None = None) -> bool:
    return resolve_strict_live(settings_strict)


def is_live_terminal_failure(state: LiveSearchState | None) -> bool:
    if state is None:
        return False
    return state != LiveSearchState.LIVE_SEARCH_OK_RESULTS


def live_state_ui(state: LiveSearchState) -> tuple[str, str]:
    return _LIVE_STATE_UI.get(state, ("LIVE MARKET UNAVAILABLE", "Live market search did not return comparables."))


def map_trade2_error_code(code: str, http_status: int | None) -> LiveSearchState:
    if code == "auth_required":
        return LiveSearchState.LIVE_SEARCH_AUTH_REQUIRED
    if code == "forbidden":
        return LiveSearchState.LIVE_SEARCH_FORBIDDEN
    if code in {"rate_limited", "rate_limit_pacing"}:
        # MARKET-01B11: `rate_limit_pacing` is *our* scheduler declining to send a
        # request the server policy would penalise. No 429 was issued.
        return LiveSearchState.LIVE_SEARCH_RATE_LIMITED
    if code in {"search_error", "bad_request", "http_error"} and http_status == 400:
        return LiveSearchState.LIVE_SEARCH_BAD_REQUEST
    if code in {"network_error", "timeout"}:
        return LiveSearchState.LIVE_SEARCH_NETWORK_ERROR
    if code == "not_permitted":
        # Central market access refused the request before anything was sent (disabled / no_network / provider not authorized).
        return LiveSearchState.LIVE_PROVIDER_DISABLED
    if code in {"invalid_response", "parse_error"}:
        return LiveSearchState.LIVE_SEARCH_PARSE_ERROR
    if code in {"fetch_error"}:
        return LiveSearchState.LIVE_FETCH_ERROR
    if http_status == 403:
        return LiveSearchState.LIVE_SEARCH_FORBIDDEN
    if http_status == 401:
        return LiveSearchState.LIVE_SEARCH_AUTH_REQUIRED
    if http_status == 429:
        return LiveSearchState.LIVE_SEARCH_RATE_LIMITED
    return LiveSearchState.LIVE_SEARCH_NETWORK_ERROR


@dataclass
class RelaxationPassDiagnostics:
    pass_index: int
    relaxation_tier: int
    search_total: int = 0
    search_result_count: int = 0
    fetch_requested: int = 0
    fetch_returned: int = 0
    priced_listings: int = 0
    similarity_matched: int = 0
    fx_usable: int = 0
    http_status: int | None = None
    search_id: str = ""
    error: str | None = None
    funnel: dict[str, Any] = field(default_factory=dict)
    #: Seller structure of the similar listings BEFORE per-seller dedupe: how many listings, how many distinct sellers and the
    #: share held by the busiest seller. The trust layer reads it to flag a sample that is really one or two accounts.
    seller_listing_count: int = 0
    distinct_sellers: int = 0
    top_seller_share: float = 0.0
    fetch_batches: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "seller_listing_count": self.seller_listing_count,
            "distinct_sellers": self.distinct_sellers,
            "top_seller_share": self.top_seller_share,
            "fetch_batches": self.fetch_batches,
            "pass_index": self.pass_index,
            "relaxation_tier": self.relaxation_tier,
            "search_total": self.search_total,
            "search_result_count": self.search_result_count,
            "fetch_requested": self.fetch_requested,
            "fetch_returned": self.fetch_returned,
            "priced_listings": self.priced_listings,
            "similarity_matched": self.similarity_matched,
            "fx_usable": self.fx_usable,
            "http_status": self.http_status,
            "search_id": self.search_id,
            "error": self.error,
            "funnel": dict(self.funnel),
        }


@dataclass
class LiveAcquisitionDiagnostics:
    price_check_id: int = 0
    item_category: str | None = None
    item_base: str | None = None
    item_rarity: str | None = None
    league: str | None = None
    league_source: str | None = None
    canonical_league: str | None = None
    provider_id: str = "live_trade2"
    auth_mode: str = "ANONYMOUS"
    generated_query: dict[str, Any] = field(default_factory=dict)
    search_url: str = ""
    http_status: int | None = None
    rate_limit_retry_after: float | None = None
    rate_limit_headers: dict[str, str] = field(default_factory=dict)
    search_requests: int = 0
    fetch_requests: int = 0
    total_http_requests: int = 0
    cache_age_seconds: float | None = None
    result_count: int = 0
    search_id: str = ""
    fetch_count: int = 0
    priced_listings: int = 0
    currencies: list[str] = field(default_factory=list)
    similarity_counts: dict[str, int] = field(default_factory=dict)
    final_source: str = ""
    live_state: LiveSearchState | None = None
    relaxation_passes: list[RelaxationPassDiagnostics] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "price_check_id": self.price_check_id,
            "item_category": self.item_category,
            "item_base": self.item_base,
            "item_rarity": self.item_rarity,
            "league": self.league,
            "league_source": self.league_source,
            "canonical_league": self.canonical_league,
            "provider_id": self.provider_id,
            "auth_mode": self.auth_mode,
            "generated_query": self.generated_query,
            "search_url": self.search_url,
            "http_status": self.http_status,
            "rate_limit_retry_after": self.rate_limit_retry_after,
            "rate_limit_headers": self.rate_limit_headers,
            "search_requests": self.search_requests,
            "fetch_requests": self.fetch_requests,
            "total_http_requests": self.total_http_requests,
            "cache_age_seconds": self.cache_age_seconds,
            "result_count": self.result_count,
            "search_id": self.search_id,
            "fetch_count": self.fetch_count,
            "priced_listings": self.priced_listings,
            "currencies": list(self.currencies),
            "similarity_counts": dict(self.similarity_counts),
            "final_source": self.final_source,
            "live_state": self.live_state.value if self.live_state else None,
            "relaxation_passes": [row.to_dict() for row in self.relaxation_passes],
        }


def log_live_acquisition(diagnostics: LiveAcquisitionDiagnostics) -> None:
    payload = diagnostics.to_dict()
    logger.info("price_check_live %s", json.dumps(payload, default=str, sort_keys=True))
