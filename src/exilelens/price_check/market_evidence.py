"""MarketEvidence v1: the one small, serialisable contract Item Check reads about a market lookup (R5-B).

Pure. Nothing here searches, fetches, resolves a league, or imports the trade2 stack. `evidence_from_price_result` is the single conversion
from the internal `PriceCheckResult` / trust model to this contract, so no UI has to interpret price_check internals.

Rules the contract enforces:
- `NO_TRUSTWORTHY_ESTIMATE` (and any state without a full-band display) means `price is None`. A number is never kept just because it
  was computed.
- `headline` / `estimate_state` / `reasons` are set only when a lookup actually produced evidence (status AVAILABLE).
- No confidence percentage, score, history, or buy recommendation exists in this contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from exilelens.price_check.price_trust import (
    DisplayPriceMode,
    EstimateState,
    FreshnessBand,
    MarketHeadline,
    PriceTrustAssessment,
    TRUST_CACHE_AGING_SECONDS,
    TRUST_CACHE_CURRENT_SECONDS,
    TRUST_CACHE_RECENT_SECONDS,
    TrustReason,
    assess_price_trust,
    evidence_from_result,
    market_headline,
)

CONTRACT_VERSION = 1


class EvidenceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"
    PENDING = "PENDING"
    RATE_LIMITED = "RATE_LIMITED"


class Freshness(str, Enum):
    CURRENT = "CURRENT"
    RECENT = "RECENT"
    AGING = "AGING"
    STALE = "STALE"


class BandBasis(str, Enum):
    #: The sample is the cheapest comparable listings (the search is sorted by price ascending), not every listing.
    CHEAPEST_COMPARABLES = "CHEAPEST_COMPARABLES"
    #: The server reported no more listings than were fetched.
    FULL_SAMPLE = "FULL_SAMPLE"


class ListedVsMarket(str, Enum):
    BELOW = "BELOW"
    WITHIN = "WITHIN"
    ABOVE = "ABOVE"
    NOT_COMPARABLE = "NOT_COMPARABLE"


#: Stable reason codes for non-lookup states (lookup states use the leading TrustReason value or one of these).
REASON_TEXT: dict[str, str] = {
    "DISABLED_BY_USER": "Market prices are off.",
    "NETWORK_DISABLED": "Network access is disabled in this build.",
    "PROVIDER_NOT_AUTHORIZED": "The market provider is not available.",
    "PENDING": "Looking up market prices.",
    "RATE_LIMITED": "The market is busy; try again shortly.",
    "UNAVAILABLE": "Market prices are unavailable right now.",
    "PROVIDER_ERROR": "Market prices are unavailable right now.",
    "NO_LISTINGS": "No comparable listings were found.",
    "WEAK_COMPARABLES": "Too few comparable listings for an estimate.",
    "UNIQUE_NOT_PRICED": "Unique items are not priced from their base type.",
    "LEAGUE_REQUIRED": "No league is selected for market prices.",
    "TIMEOUT": "The market lookup took too long.",
}
_TRUST_TEXT: dict[str, str] = {
    "SAMPLE_TOO_SMALL": "Too few comparable listings for an estimate.",
    "SAMPLE_THIN": "Only a few comparable listings.",
    "SIMILARITY_WEAK": "The listings are not close enough to this item.",
    "MARKET_MULTIMODAL": "Prices fall into separate groups.",
    "PRICE_WIDE": "Prices vary widely.",
    "LIQUIDITY_THIN": "Few of these are listed.",
    "PRICE_DATA_STALE": "The listings are old.",
    "FX_PARTIAL": "Some listings use currencies that could not be converted.",
    "COVERAGE_ANCHOR_OMITTED": "The search could not include everything that defines this item.",
    "COVERAGE_GROUP_OMITTED": "Part of the search had to be left out.",
    "SELLER_CONCENTRATED": "Most listings come from one or two sellers.",
    "UNIQUE_NOT_PRICED": "Unique items are not priced from their base type.",
    "BASE_ONLY": "Only the item base could be searched.",
    "UNSUPPORTED_IDENTITY": "This kind of item cannot be searched accurately.",
}


@dataclass(frozen=True)
class MarketPrice:
    """Asking price of comparable listings: the cost to buy a comparable item, not what the item is worth."""

    display_currency: str
    low: float
    high: float
    point: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"display_currency": self.display_currency, "low": self.low, "high": self.high, "point": self.point}


@dataclass(frozen=True)
class ListedPrice:
    amount: float
    currency: str
    source: str = "NOTE"

    def to_dict(self) -> dict[str, Any]:
        return {"amount": self.amount, "currency": self.currency, "source": self.source}


@dataclass(frozen=True)
class MarketEvidence:
    status: EvidenceStatus
    reason_code: str = ""
    reason: str = ""
    provider_id: str = ""
    league: str = ""
    fetched_at: float | None = None
    freshness: Freshness | None = None
    headline: MarketHeadline | None = None
    estimate_state: EstimateState | None = None
    reasons: tuple[str, ...] = ()
    price: MarketPrice | None = None
    band_basis: BandBasis | None = None
    comparable_count: int = 0
    distinct_sellers: int = 0
    coverage: tuple[str, ...] = ()
    listed_price: ListedPrice | None = None
    listed_vs_market: ListedVsMarket | None = None
    contract_version: int = CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "status": self.status.value,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "provider_id": self.provider_id,
            "league": self.league,
            "fetched_at": self.fetched_at,
            "freshness": self.freshness.value if self.freshness else None,
            "headline": self.headline.value if self.headline else None,
            "estimate_state": self.estimate_state.value if self.estimate_state else None,
            "reasons": list(self.reasons),
            "price": self.price.to_dict() if self.price else None,
            "band_basis": self.band_basis.value if self.band_basis else None,
            "comparable_count": self.comparable_count,
            "distinct_sellers": self.distinct_sellers,
            "coverage": list(self.coverage),
            "listed_price": self.listed_price.to_dict() if self.listed_price else None,
            "listed_vs_market": self.listed_vs_market.value if self.listed_vs_market else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MarketEvidence:
        def enum(kind, value):
            return kind(value) if value else None

        price = data.get("price")
        listed = data.get("listed_price")
        return cls(
            status=EvidenceStatus(data["status"]),
            reason_code=str(data.get("reason_code") or ""),
            reason=str(data.get("reason") or ""),
            provider_id=str(data.get("provider_id") or ""),
            league=str(data.get("league") or ""),
            fetched_at=data.get("fetched_at"),
            freshness=enum(Freshness, data.get("freshness")),
            headline=enum(MarketHeadline, data.get("headline")),
            estimate_state=enum(EstimateState, data.get("estimate_state")),
            reasons=tuple(data.get("reasons") or ()),
            price=MarketPrice(price["display_currency"], price["low"], price["high"], price.get("point")) if price else None,
            band_basis=enum(BandBasis, data.get("band_basis")),
            comparable_count=int(data.get("comparable_count") or 0),
            distinct_sellers=int(data.get("distinct_sellers") or 0),
            coverage=tuple(data.get("coverage") or ()),
            listed_price=ListedPrice(listed["amount"], listed["currency"], listed.get("source", "NOTE")) if listed else None,
            listed_vs_market=enum(ListedVsMarket, data.get("listed_vs_market")),
            contract_version=int(data.get("contract_version") or CONTRACT_VERSION),
        )

    def with_listed(self, listed: ListedPrice | None) -> MarketEvidence:
        """Attach the copied item's `~b/o` note and derive the comparison from it. Pure."""
        from dataclasses import replace

        return replace(self, listed_price=listed, listed_vs_market=listed_vs_market(self, listed))


# ---------------------------------------------------------------------------------------------------------- status builders


def status_evidence(
    status: EvidenceStatus,
    reason_code: str,
    *,
    provider_id: str = "",
    league: str = "",
    listed: ListedPrice | None = None,
) -> MarketEvidence:
    """Evidence for a state in which no market evidence exists (disabled, unavailable, rate limited, pending). Never carries a price."""
    return MarketEvidence(
        status=status,
        reason_code=reason_code,
        reason=REASON_TEXT.get(reason_code, REASON_TEXT["UNAVAILABLE"]),
        provider_id=provider_id,
        league=league,
        listed_price=listed,
    )


# ------------------------------------------------------------------------------------------------------------- listed price


def _same_currency(a: str, b: str) -> bool:
    from exilelens.price_check.currency_fx import CurrencyFxTable

    table = CurrencyFxTable(league="")
    return table.normalize_currency(a) == table.normalize_currency(b)


def listed_vs_market(evidence: MarketEvidence, listed: ListedPrice | None) -> ListedVsMarket | None:
    """Deterministic: the actual band, no tolerance. Only for a trustworthy Strong/Weak set that is not stale, in the same currency."""
    if listed is None:
        return None
    price = evidence.price
    if (
        evidence.status is not EvidenceStatus.AVAILABLE
        or price is None
        or evidence.headline not in {MarketHeadline.STRONG_COMPARABLE_SET, MarketHeadline.WEAK_COMPARABLE_SET}
        or evidence.freshness is Freshness.STALE
        or not _same_currency(listed.currency, price.display_currency)
    ):
        return ListedVsMarket.NOT_COMPARABLE
    if listed.amount < price.low:
        return ListedVsMarket.BELOW
    if listed.amount > price.high:
        return ListedVsMarket.ABOVE
    return ListedVsMarket.WITHIN


def listed_price_from_note(item_raw: str) -> ListedPrice | None:
    """The existing `~b/o` parser, reused as is."""
    from exilelens.market_assist.price_parser import parse_price_note

    parsed = parse_price_note(item_raw or "")
    if not parsed.supported or parsed.price is None:
        return None
    return ListedPrice(float(parsed.price.amount), str(parsed.price.currency))


# -------------------------------------------------------------------------------------------------------------- freshness


def _freshness(band: str) -> Freshness | None:
    try:
        value = FreshnessBand(band)
    except ValueError:
        return None
    return None if value is FreshnessBand.UNKNOWN else Freshness(value.value)


_ORDER = (Freshness.CURRENT, Freshness.RECENT, Freshness.AGING, Freshness.STALE)


def age_freshness(freshness: Freshness | None, cache_age_seconds: float) -> Freshness | None:
    """Evidence served from the evidence cache is never fresher than its own age says."""
    age = max(0.0, float(cache_age_seconds))
    if age <= TRUST_CACHE_CURRENT_SECONDS:
        by_age = Freshness.CURRENT
    elif age <= TRUST_CACHE_RECENT_SECONDS:
        by_age = Freshness.RECENT
    elif age <= TRUST_CACHE_AGING_SECONDS:
        by_age = Freshness.AGING
    else:
        by_age = Freshness.STALE
    if freshness is None:
        return by_age
    return max(freshness, by_age, key=_ORDER.index)


# ------------------------------------------------------------------------------------------------------ the one conversion


def evidence_from_price_result(
    result: Any,
    *,
    fetched_at: float | None = None,
    now: float | None = None,
    listed: ListedPrice | None = None,
) -> MarketEvidence:
    """PriceCheckResult (already trust-assessed or not) -> MarketEvidence. Deterministic; never raises (a failure becomes UNAVAILABLE)."""
    try:
        return _convert(result, fetched_at=fetched_at, now=now, listed=listed)
    except Exception:  # noqa: BLE001 - the contract's own failure mode is a typed state
        return status_evidence(EvidenceStatus.UNAVAILABLE, "PROVIDER_ERROR", listed=listed)


def _league_of(result: Any) -> str:
    request = getattr(result, "request", None)
    league = getattr(getattr(request, "league", None), "league", None)
    return str(league or "")


def _convert(result: Any, *, fetched_at: float | None, now: float | None, listed: ListedPrice | None) -> MarketEvidence:
    from exilelens.price_check.models import LiveSearchState

    provider = str(getattr(result, "provider_id", "") or "")
    league = _league_of(result)
    state = getattr(result, "live_search_state", None)

    def typed(status: EvidenceStatus, code: str) -> MarketEvidence:
        return status_evidence(status, code, provider_id=provider, league=league, listed=listed)

    if state is LiveSearchState.LIVE_SEARCH_RATE_LIMITED:
        return typed(EvidenceStatus.RATE_LIMITED, "RATE_LIMITED")
    if state is LiveSearchState.LIVE_PROVIDER_DISABLED:
        return typed(EvidenceStatus.UNAVAILABLE, "PROVIDER_NOT_AUTHORIZED")
    if state is LiveSearchState.LEAGUE_REQUIRED:
        return typed(EvidenceStatus.UNAVAILABLE, "LEAGUE_REQUIRED")
    if state is LiveSearchState.LIVE_ITEM_CLASS_UNSUPPORTED:
        return typed(EvidenceStatus.UNAVAILABLE, "UNIQUE_NOT_PRICED")
    if state is LiveSearchState.LIVE_PROVIDER_ERROR:
        return typed(EvidenceStatus.UNAVAILABLE, "PROVIDER_ERROR")
    if state in {
        LiveSearchState.LIVE_SEARCH_AUTH_REQUIRED,
        LiveSearchState.LIVE_SEARCH_FORBIDDEN,
        LiveSearchState.LIVE_SEARCH_BAD_REQUEST,
        LiveSearchState.LIVE_SEARCH_NETWORK_ERROR,
        LiveSearchState.LIVE_SEARCH_PARSE_ERROR,
        LiveSearchState.LIVE_FETCH_ERROR,
        LiveSearchState.LIVE_FETCH_NO_PRICES,
    }:
        return typed(EvidenceStatus.UNAVAILABLE, "UNAVAILABLE")

    # A completed lookup: evidence exists, even if it is "no trustworthy estimate".
    if state is LiveSearchState.LIVE_SEARCH_OK_ZERO_RESULTS:
        return _evidence_without_price(provider, league, "NO_LISTINGS", fetched_at, listed)
    if state is LiveSearchState.LIVE_COMPARABLES_TOO_WEAK:
        return _evidence_without_price(provider, league, "WEAK_COMPARABLES", fetched_at, listed)
    if state is not LiveSearchState.LIVE_SEARCH_OK_RESULTS:
        return typed(EvidenceStatus.UNAVAILABLE, "UNAVAILABLE")

    assessment = _assessment(result, now)
    headline = market_headline(assessment)
    estimate = result.estimate
    bands = {row.label: row for row in (estimate.currency_bands or ())}
    # The range is the interquartile range of comparable asks (quick_sale = p25, optimistic = p75): wide enough to be a market range,
    # unlike the narrow p40-p60 "fair" band, which is an internal label and is not exposed.
    low_band = bands.get("quick_sale")
    high_band = bands.get("optimistic")
    fair = low_band or bands.get("fair")
    price: MarketPrice | None = None
    if (
        headline is not MarketHeadline.NO_TRUSTWORTHY_ESTIMATE
        and headline is not MarketHeadline.VOLATILE_ESTIMATE
        and assessment.display_price_mode == DisplayPriceMode.FULL_BANDS.value
        and fair is not None
    ):
        top = high_band.amount if high_band is not None else (fair.amount_high if fair.amount_high is not None else fair.amount)
        price = MarketPrice(
            display_currency=str(fair.currency),
            low=float(min(fair.amount, top)),
            high=float(max(fair.amount, top)),
            point=float(assessment.price_median) if assessment.price_median is not None else None,
        )
    reasons = tuple(assessment.compact_reasons) + tuple(r for r in assessment.reason_codes if r not in assessment.compact_reasons)
    pass_row = _last_pass(result)
    sellers = int(pass_row.get("distinct_sellers") or 0) or int(result.comparable_count or 0)
    total = int(pass_row.get("search_total") or 0)
    returned = int(pass_row.get("fetch_returned") or 0)
    basis = BandBasis.FULL_SAMPLE if total and returned >= total else BandBasis.CHEAPEST_COMPARABLES
    coverage = _coverage_lines(result)
    leading = reasons[0] if reasons else ""
    evidence = MarketEvidence(
        status=EvidenceStatus.AVAILABLE,
        reason_code=leading,
        reason=_TRUST_TEXT.get(leading, ""),
        provider_id=provider,
        league=league,
        fetched_at=fetched_at,
        freshness=_freshness(assessment.freshness),
        headline=headline,
        estimate_state=assessment.state,
        reasons=reasons,
        price=price,
        band_basis=basis if price else None,
        comparable_count=int(result.comparable_count or 0),
        distinct_sellers=sellers,
        coverage=coverage,
    )
    return evidence.with_listed(listed) if listed is not None else evidence


def _evidence_without_price(provider: str, league: str, code: str, fetched_at: float | None, listed: ListedPrice | None) -> MarketEvidence:
    evidence = MarketEvidence(
        status=EvidenceStatus.AVAILABLE,
        reason_code=code,
        reason=REASON_TEXT[code],
        provider_id=provider,
        league=league,
        fetched_at=fetched_at,
        headline=MarketHeadline.NO_TRUSTWORTHY_ESTIMATE,
        estimate_state=EstimateState.NEEDS_REFINEMENT,
    )
    return evidence.with_listed(listed) if listed is not None else evidence


def _assessment(result: Any, now: float | None) -> PriceTrustAssessment:
    return assess_price_trust(evidence_from_result(result, now=now))


def _last_pass(result: Any) -> dict[str, Any]:
    passes = getattr(getattr(result, "diagnostics", None), "relaxation_passes", None) or ()
    last = passes[-1] if passes else {}
    return last if isinstance(last, dict) else {}


def _coverage_lines(result: Any) -> tuple[str, ...]:
    from exilelens.price_check.models import CompiledPriceCheckRequest

    request = getattr(result, "request", None)
    if not isinstance(request, CompiledPriceCheckRequest):
        return ()
    return tuple(request.compiled_query.coverage.explain())


__all__ = [
    "BandBasis",
    "CONTRACT_VERSION",
    "EvidenceStatus",
    "Freshness",
    "ListedPrice",
    "ListedVsMarket",
    "MarketEvidence",
    "MarketPrice",
    "age_freshness",
    "evidence_from_price_result",
    "listed_price_from_note",
    "listed_vs_market",
    "status_evidence",
    "TrustReason",
]
