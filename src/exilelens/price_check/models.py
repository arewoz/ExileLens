from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, TYPE_CHECKING

from exilelens.price_check.market_drivers import EstimateState, PriceCheckHypothesis
from exilelens.price_check.network_withhold import NetworkWithhold, PipelineContinuation


if TYPE_CHECKING:
    from exilelens.price_check.market_plan import CompiledTradeQuery, MarketSearchPlan


class PriceSourceKind(str, Enum):
    LIVE_MARKET = "LIVE_MARKET"
    CACHED_LIVE_MARKET = "CACHED_LIVE_MARKET"
    HISTORICAL_MARKET = "HISTORICAL_MARKET"
    OBSERVATION_CORPUS = "OBSERVATION_CORPUS"
    MODEL_THEORETICAL = "MODEL_THEORETICAL"
    UNKNOWN = "UNKNOWN"


class AuthenticationMode(str, Enum):
    ANONYMOUS = "ANONYMOUS"
    SESSION = "SESSION"
    AUTH_REQUIRED = "AUTH_REQUIRED"


class PriceConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class LeagueStatus(str, Enum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class LiveSearchState(str, Enum):
    LIVE_SEARCH_OK_ZERO_RESULTS = "LIVE_SEARCH_OK_ZERO_RESULTS"
    LIVE_SEARCH_OK_RESULTS = "LIVE_SEARCH_OK_RESULTS"
    LIVE_SEARCH_AUTH_REQUIRED = "LIVE_SEARCH_AUTH_REQUIRED"
    LIVE_SEARCH_FORBIDDEN = "LIVE_SEARCH_FORBIDDEN"
    LIVE_SEARCH_RATE_LIMITED = "LIVE_SEARCH_RATE_LIMITED"
    LIVE_SEARCH_BAD_REQUEST = "LIVE_SEARCH_BAD_REQUEST"
    LIVE_SEARCH_NETWORK_ERROR = "LIVE_SEARCH_NETWORK_ERROR"
    LIVE_SEARCH_PARSE_ERROR = "LIVE_SEARCH_PARSE_ERROR"
    LIVE_FETCH_ERROR = "LIVE_FETCH_ERROR"
    LIVE_FETCH_NO_PRICES = "LIVE_FETCH_NO_PRICES"
    LIVE_COMPARABLES_TOO_WEAK = "LIVE_COMPARABLES_TOO_WEAK"
    LIVE_PROVIDER_DISABLED = "LIVE_PROVIDER_DISABLED"
    LEAGUE_REQUIRED = "LEAGUE_REQUIRED"


class TheoreticalTier(str, Enum):
    HIGH_VALUE_RARE = "HIGH_VALUE_RARE"
    MODERATE_VALUE = "MODERATE_VALUE"
    LOW_VALUE = "LOW_VALUE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class LeagueContext:
    league: str | None
    status: LeagueStatus

    @classmethod
    def from_settings(cls, league: str | None) -> LeagueContext:
        cleaned = str(league or "").strip()
        if cleaned:
            return cls(league=cleaned, status=LeagueStatus.KNOWN)
        return cls(league=None, status=LeagueStatus.UNKNOWN)

    def to_dict(self) -> dict[str, Any]:
        return {"league": self.league, "status": self.status.value}


@dataclass(frozen=True)
class PriceCheckDiagnostics:
    league: str | None = None
    league_source: str | None = None
    provider_id: str | None = None
    authentication_mode: str | None = None
    auth_required: bool = False
    query_summary: str = ""
    relaxation_tier: int | None = None
    comparable_count: int = 0
    http_status: int | None = None
    price_check_id: int | None = None
    live_state: LiveSearchState | None = None
    search_id: str | None = None
    fetch_count: int = 0
    priced_listings: int = 0
    currencies: tuple[str, ...] = ()
    similarity_counts: dict[str, int] | None = None
    relaxation_passes: tuple[dict[str, Any], ...] = ()
    search_url: str | None = None
    rate_limit_retry_after: float | None = None
    search_requests: int = 0
    fetch_requests: int = 0
    total_http_requests: int = 0
    cache_age_seconds: float | None = None
    provider_enabled: bool = True
    provider_selected: tuple[str, ...] = ()
    provider_attempted: tuple[str, ...] = ()
    provider_result: str | None = None
    discovery: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "league": self.league,
            "league_source": self.league_source,
            "provider_id": self.provider_id,
            "authentication_mode": self.authentication_mode,
            "auth_required": self.auth_required,
            "query_summary": self.query_summary,
            "relaxation_tier": self.relaxation_tier,
            "comparable_count": self.comparable_count,
            "http_status": self.http_status,
            "price_check_id": self.price_check_id,
            "live_state": self.live_state.value if self.live_state else None,
            "search_id": self.search_id,
            "fetch_count": self.fetch_count,
            "priced_listings": self.priced_listings,
            "currencies": list(self.currencies),
            "similarity_counts": self.similarity_counts or {},
            "relaxation_passes": list(self.relaxation_passes),
            "search_url": self.search_url,
            "rate_limit_retry_after": self.rate_limit_retry_after,
            "search_requests": self.search_requests,
            "fetch_requests": self.fetch_requests,
            "total_http_requests": self.total_http_requests,
            "cache_age_seconds": self.cache_age_seconds,
            "provider_enabled": self.provider_enabled,
            "provider_selected": list(self.provider_selected),
            "provider_attempted": list(self.provider_attempted),
            "provider_result": self.provider_result,
            "discovery": dict(self.discovery) if self.discovery else None,
        }


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_comparables: bool = False
    supports_live_prices: bool = False
    supports_historical_prices: bool = False
    supports_listing_age: bool = False
    supports_seller_identity: bool = False
    supports_price_ordering: bool = False
    supports_global_price_ordering: bool = False
    supports_league: bool = False
    source_kind: PriceSourceKind = PriceSourceKind.UNKNOWN
    authentication_mode: AuthenticationMode = AuthenticationMode.ANONYMOUS

    def to_dict(self) -> dict[str, Any]:
        return {
            "supports_comparables": self.supports_comparables,
            "supports_live_prices": self.supports_live_prices,
            "supports_historical_prices": self.supports_historical_prices,
            "supports_listing_age": self.supports_listing_age,
            "supports_seller_identity": self.supports_seller_identity,
            "supports_price_ordering": self.supports_price_ordering,
            "supports_global_price_ordering": self.supports_global_price_ordering,
            "supports_league": self.supports_league,
            "source_kind": self.source_kind.value,
            "authentication_mode": self.authentication_mode.value,
        }


@dataclass(frozen=True)
class ComparableListing:
    listing_id: str
    item_raw: str
    price_amount: float | None = None
    price_currency: str | None = None
    source: str = ""
    league: str | None = None
    seller_id: str | None = None
    captured_at: str | None = None
    # MARKET-01B12: the value the estimator actually used, after currency conversion.
    # Carried here so the UI can show "1 regal (~0.9 ex)" without recomputing FX.
    normalized_amount: float | None = None
    normalized_currency: str | None = None

    @property
    def was_converted(self) -> bool:
        if self.normalized_currency is None or self.price_currency is None:
            return False
        return self.normalized_currency.lower() != self.price_currency.lower()

    def with_normalized(self, amount: float | None, currency: str | None) -> ComparableListing:
        return replace(self, normalized_amount=amount, normalized_currency=currency)

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing_id": self.listing_id,
            "item_raw": self.item_raw,
            "price_amount": self.price_amount,
            "price_currency": self.price_currency,
            "source": self.source,
            "league": self.league,
            "seller_id": self.seller_id,
            "captured_at": self.captured_at,
            "normalized_amount": self.normalized_amount,
            "normalized_currency": self.normalized_currency,
        }


@dataclass(frozen=True)
class CurrencyBand:
    label: str
    amount: float
    currency: str
    amount_high: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "amount": self.amount,
            "currency": self.currency,
            "amount_high": self.amount_high,
        }


@dataclass(frozen=True)
class PriceEstimate:
    source_kind: PriceSourceKind
    confidence: PriceConfidence
    theoretical_tier: TheoreticalTier | None = None
    currency_bands: tuple[CurrencyBand, ...] = ()
    comparables: tuple[ComparableListing, ...] = ()
    summary: str = ""
    disclaimer: str = ""
    # MARKET-01B12: the currency every band and normalized comparable is expressed in,
    # and one short sentence explaining the confidence rating.
    display_currency: str | None = None
    confidence_reason: str = ""

    @property
    def has_currency_estimate(self) -> bool:
        if self.source_kind in {PriceSourceKind.MODEL_THEORETICAL, PriceSourceKind.UNKNOWN}:
            return False
        return bool(self.currency_bands)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind.value,
            "confidence": self.confidence.value,
            "theoretical_tier": self.theoretical_tier.value if self.theoretical_tier else None,
            "currency_bands": [row.to_dict() for row in self.currency_bands],
            "comparables": [row.to_dict() for row in self.comparables],
            "summary": self.summary,
            "disclaimer": self.disclaimer,
            "display_currency": self.display_currency,
            "confidence_reason": self.confidence_reason,
            "has_currency_estimate": self.has_currency_estimate,
        }


@dataclass(frozen=True)
class PriceCheckRequest:
    item_raw: str
    content_hash: str
    league: LeagueContext
    request_id: int = 0
    league_source: str | None = None
    hypothesis: PriceCheckHypothesis | None = None
    pipeline_continuation: PipelineContinuation | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "item_raw": self.item_raw,
            "content_hash": self.content_hash,
            "league": self.league.to_dict(),
            "request_id": self.request_id,
            "league_source": self.league_source,
        }
        if self.hypothesis is not None:
            payload["hypothesis"] = self.hypothesis.to_dict()
        if self.pipeline_continuation is not None:
            payload["pipeline_continuation"] = self.pipeline_continuation.to_dict()
        return payload


@dataclass(frozen=True, kw_only=True)
class CompiledPriceCheckRequest(PriceCheckRequest):
    """Explicit MARKET-03 transport. Legacy requests remain PriceCheckRequest."""

    compiled_query: CompiledTradeQuery
    plan: MarketSearchPlan
    generation: int
    user_refined: bool = False

    def __post_init__(self) -> None:
        from exilelens.price_check.market_plan import CompiledTradeQuery, MarketSearchPlan
        if not isinstance(self.compiled_query, CompiledTradeQuery) or not isinstance(self.plan, MarketSearchPlan):
            raise TypeError("compiled request requires CompiledTradeQuery and MarketSearchPlan")
        if self.hypothesis is not None:
            raise ValueError("compiled requests cannot carry a legacy hypothesis")

    def to_dict(self) -> dict[str, Any]:
        return {**super().to_dict(), "request_kind": "compiled_market03",
                "compiled_query": self.compiled_query.to_dict(), "plan": self.plan.to_dict(),
                "generation": self.generation, "user_refined": self.user_refined}


@dataclass(frozen=True)
class PriceCheckResult:
    request: PriceCheckRequest
    estimate: PriceEstimate
    provider_id: str
    important_mods: tuple[str, ...] = ()
    message: str | None = None
    no_item_text: bool = False
    cache_hit: bool = False
    comparable_count: int = 0
    search_basis: str = ""
    # MARKET-01B12: the economic families the query actually matched on, for the overlay.
    matched_features: str = ""
    # MARKET-01B13: PRIMARY / FALLBACK_MEDIUM / FALLBACK_LOW / BASE_ONLY. A BASE_ONLY
    # result is a base-type price and must not be presented as a valuation of the item.
    identity_source: str = ""
    search_relaxation_tier: int | None = None
    diagnostics: PriceCheckDiagnostics | None = None
    live_search_state: LiveSearchState | None = None
    cache_age_seconds: float | None = None
    market_status: str | None = None
    hypothesis: PriceCheckHypothesis | None = None
    estimate_state: str = ""
    original_hypothesis: PriceCheckHypothesis | None = None
    pending_hypothesis: PriceCheckHypothesis | None = None
    stability: str = ""
    auto_adjusted: bool = False
    discovery: dict[str, Any] | None = None
    network_withhold: NetworkWithhold | None = None
    unassessed_estimate: PriceEstimate | None = None

    @property
    def is_live_failure(self) -> bool:
        if self.live_search_state is None:
            return False
        return self.live_search_state != LiveSearchState.LIVE_SEARCH_OK_RESULTS

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "estimate": self.estimate.to_dict(),
            "provider_id": self.provider_id,
            "important_mods": list(self.important_mods),
            "message": self.message,
            "no_item_text": self.no_item_text,
            "cache_hit": self.cache_hit,
            "comparable_count": self.comparable_count,
            "search_basis": self.search_basis,
            "search_relaxation_tier": self.search_relaxation_tier,
            "diagnostics": self.diagnostics.to_dict() if self.diagnostics else None,
            "live_search_state": self.live_search_state.value if self.live_search_state else None,
            "cache_age_seconds": self.cache_age_seconds,
            "market_status": self.market_status,
            "estimate_state": self.estimate_state,
            "hypothesis": self.hypothesis.to_dict() if self.hypothesis is not None else None,
            "original_hypothesis": (
                self.original_hypothesis.to_dict() if self.original_hypothesis is not None else None
            ),
            "stability": self.stability,
            "auto_adjusted": self.auto_adjusted,
            "discovery": dict(self.discovery) if self.discovery else None,
            "network_withhold": self.network_withhold.to_dict() if self.network_withhold else None,
        }
