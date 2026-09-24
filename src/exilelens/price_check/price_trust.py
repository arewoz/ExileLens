"""MARKET-02E — price trust / confidence decision layer.

Zero network. Given market evidence we already have, how much should the
product trust this price? Product states are HIGH CONFIDENCE, ASSISTED
ESTIMATE, NEEDS REFINEMENT, and BASE MARKET ESTIMATE — not a numeric score.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

from exilelens.price_check.comparable_features import FAMILY_MATCH_THRESHOLD
from exilelens.price_check.hypothesis_discovery import HypothesisStability
from exilelens.price_check.market_drivers import EstimateState, HypothesisSource, SlotFamily
from exilelens.price_check.market_signatures import SignatureMaturity
from exilelens.price_check.models import PriceCheckResult, PriceConfidence

# ---------------------------------------------------------------------------
# Named constants — listing freshness is NOT cache TTL (B11 90s item cache).
# ---------------------------------------------------------------------------

LISTING_FRESHNESS_CURRENT_SECONDS = 6 * 3600
LISTING_FRESHNESS_RECENT_SECONDS = 24 * 3600
LISTING_FRESHNESS_AGING_SECONDS = 3 * 24 * 3600

# Cached *sample* age. A 30–60s neighbourhood hit must not reduce trust.
TRUST_CACHE_CURRENT_SECONDS = 120
TRUST_CACHE_RECENT_SECONDS = 15 * 60
TRUST_CACHE_AGING_SECONDS = 60 * 60

# B7 similarity scale. Do not lower these.
SIMILARITY_STRONG = FAMILY_MATCH_THRESHOLD  # 0.85
SIMILARITY_OK = 0.70

SAMPLE_UNUSABLE_MAX = 2
SAMPLE_THIN_MAX = 4
SAMPLE_LIMITED_MAX = 7
SAMPLE_HEALTHY_MAX = 15
HIGH_MIN_ACCEPTED = 8

FX_STRONG_MIN = 0.80
FX_SEVERE_MAX = 0.50

DISPERSION_TIGHT_IQR = 0.20
DISPERSION_NORMAL_IQR = 0.40
DISPERSION_WIDE_IQR = 0.75
DISPERSION_TIGHT_COV = 0.20
DISPERSION_NORMAL_COV = 0.35
DISPERSION_WIDE_COV = 0.60

MULTIMODAL_GAP_RATIO = 2.5
MULTIMODAL_GAP_ABS = 0.75
MULTIMODAL_MIN_SUPPORT = 2

UNSUPPORTED_RATIO_VETO = 0.50
REMOTE_DEEP = 80
REMOTE_THIN = 15
REMOTE_ILLIQUID = 2

_COMPACT_REASON_PRIORITY = (
    "COVERAGE_ANCHOR_OMITTED",
    "BASE_ONLY",
    "MARKET_MULTIMODAL",
    "STABILITY_SENSITIVE",
    "UNSUPPORTED_IDENTITY",
    "QUERY_IDENTITY_WEAKENED",
    "COVERAGE_GROUP_OMITTED",
    "SAMPLE_TOO_SMALL",
    "SIMILARITY_WEAK",
    "PRICE_WIDE",
    "PRICE_DATA_STALE",
    "FX_PARTIAL",
    "LIQUIDITY_THIN",
    "SAMPLE_THIN",
    "STABILITY_RECOVERY_ONLY",
    "SIGNATURE_DEGRADED",
    "COVERAGE_UNSEARCHABLE",
    "SIMILARITY_STRONG",
    "PRICE_TIGHT",
    "SAMPLE_HEALTHY",
    "LIQUIDITY_HEALTHY",
    "FX_STRONG",
    "STABILITY_STABLE",
    "SIGNATURE_MATURE",
)


class TrustReason(str, Enum):
    SAMPLE_TOO_SMALL = "SAMPLE_TOO_SMALL"
    SAMPLE_THIN = "SAMPLE_THIN"
    SAMPLE_HEALTHY = "SAMPLE_HEALTHY"
    SIMILARITY_STRONG = "SIMILARITY_STRONG"
    SIMILARITY_WEAK = "SIMILARITY_WEAK"
    PRICE_TIGHT = "PRICE_TIGHT"
    PRICE_WIDE = "PRICE_WIDE"
    MARKET_MULTIMODAL = "MARKET_MULTIMODAL"
    LIQUIDITY_THIN = "LIQUIDITY_THIN"
    LIQUIDITY_HEALTHY = "LIQUIDITY_HEALTHY"
    PRICE_DATA_STALE = "PRICE_DATA_STALE"
    FX_PARTIAL = "FX_PARTIAL"
    FX_STRONG = "FX_STRONG"
    STABILITY_STABLE = "STABILITY_STABLE"
    STABILITY_SENSITIVE = "STABILITY_SENSITIVE"
    STABILITY_RECOVERY_ONLY = "STABILITY_RECOVERY_ONLY"
    SIGNATURE_MATURE = "SIGNATURE_MATURE"
    SIGNATURE_DEGRADED = "SIGNATURE_DEGRADED"
    BASE_ONLY = "BASE_ONLY"
    UNSUPPORTED_IDENTITY = "UNSUPPORTED_IDENTITY"
    QUERY_IDENTITY_WEAKENED = "QUERY_IDENTITY_WEAKENED"
    #: The compiled query left out something that defines the item. The listings may be
    #: perfectly consistent and still be answering a different question.
    COVERAGE_ANCHOR_OMITTED = "COVERAGE_ANCHOR_OMITTED"
    #: A substitutable set the Trade grammar could not express.
    COVERAGE_GROUP_OMITTED = "COVERAGE_GROUP_OMITTED"
    #: A modifier no trade stat can express at all.
    COVERAGE_UNSEARCHABLE = "COVERAGE_UNSEARCHABLE"


class SampleQuality(str, Enum):
    UNUSABLE = "UNUSABLE"
    THIN = "THIN"
    LIMITED = "LIMITED"
    HEALTHY = "HEALTHY"
    STRONG = "STRONG"


class SimilarityBand(str, Enum):
    STRONG = "STRONG"
    OK = "OK"
    WEAK = "WEAK"
    UNKNOWN = "UNKNOWN"


class DispersionBand(str, Enum):
    TIGHT = "TIGHT"
    NORMAL = "NORMAL"
    WIDE = "WIDE"
    EXTREME = "EXTREME"
    UNKNOWN = "UNKNOWN"


class PriceStructure(str, Enum):
    UNIMODAL = "UNIMODAL"
    OUTLIER = "OUTLIER"
    MULTIMODAL = "MULTIMODAL"
    EMPTY = "EMPTY"


class LiquidityBand(str, Enum):
    DEEP = "DEEP"
    NORMAL = "NORMAL"
    THIN = "THIN"
    ILLIQUID = "ILLIQUID"


class FreshnessBand(str, Enum):
    CURRENT = "CURRENT"
    RECENT = "RECENT"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class SpecificityBand(str, Enum):
    BASE_ONLY = "BASE_ONLY"
    BROAD = "BROAD"
    USEFUL = "USEFUL"
    OVER_SPECIFIC = "OVER_SPECIFIC"


class DisplayPriceMode(str, Enum):
    FULL_BANDS = "FULL_BANDS"
    OBSERVED_RANGE = "OBSERVED_RANGE"
    NONE = "NONE"


@dataclass(frozen=True)
class PriceTrustEvidence:
    """Already-collected market evidence. Never fetched by the trust layer."""

    accepted_prices: tuple[float, ...] = ()
    accepted_similarities: tuple[float, ...] = ()
    listing_ages_seconds: tuple[float | None, ...] = ()
    remote_count: int = 0
    priced_count: int = 0
    fx_usable_count: int = 0
    cache_age_seconds: float | None = None
    hypothesis_stability: str = HypothesisStability.UNMEASURED.value
    signature_maturity: str = ""
    hypothesis_source: str = HypothesisSource.AUTO_PRIOR.value
    identity_source: str = ""
    selected_driver_count: int = 0
    available_driver_count: int = 0
    ignored_mod_count: int = 0
    unsupported_selected_count: int = 0
    match_mode: str = "ALL"
    count_min: int | None = None
    auto_adjusted: bool = False
    query_repaired: bool = False
    already_needs_refinement: bool = False
    slot_family: str = ""
    item_class_unsupported: bool = False
    discovery_estimate_state: str = ""
    #: From CompilationCoverageReport.trust_evidence(). The query's own account of what
    #: it could not ask. A price built on a query that omitted an anchor is not a HIGH
    #: confidence price, however tidy the listings look.
    coverage_severity: str = "NONE"
    omitted_anchor_labels: tuple[str, ...] = ()
    omitted_flexible_labels: tuple[str, ...] = ()
    unsearchable_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class PriceTrustAssessment:
    """Immutable trust decision. Internal diagnostics are allowed; the product
    state is not `score >= X → HIGH`. Hard vetoes win."""

    state: EstimateState
    reason_codes: tuple[str, ...]
    accepted_count: int
    median_similarity: float | None
    low_similarity_quantile: float | None
    price_median: float | None
    q25: float | None
    q75: float | None
    price_dispersion: float | None
    multimodal: bool
    liquidity: str
    freshness: str
    fx_coverage: float | None
    hypothesis_stability: str
    signature_maturity: str
    hypothesis_source: str
    market_specificity: str
    unsupported_driver_ratio: float
    hard_vetoes: tuple[str, ...]
    sample_quality: str = SampleQuality.UNUSABLE.value
    similarity_band: str = SimilarityBand.UNKNOWN.value
    dispersion_band: str = DispersionBand.UNKNOWN.value
    price_structure: str = PriceStructure.EMPTY.value
    display_price_mode: str = DisplayPriceMode.NONE.value
    compact_reasons: tuple[str, ...] = ()
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "reason_codes": list(self.reason_codes),
            "compact_reasons": list(self.compact_reasons),
            "accepted_count": self.accepted_count,
            "median_similarity": self.median_similarity,
            "low_similarity_quantile": self.low_similarity_quantile,
            "price_median": self.price_median,
            "q25": self.q25,
            "q75": self.q75,
            "price_dispersion": self.price_dispersion,
            "multimodal": self.multimodal,
            "liquidity": self.liquidity,
            "freshness": self.freshness,
            "fx_coverage": self.fx_coverage,
            "hypothesis_stability": self.hypothesis_stability,
            "signature_maturity": self.signature_maturity,
            "hypothesis_source": self.hypothesis_source,
            "market_specificity": self.market_specificity,
            "unsupported_driver_ratio": self.unsupported_driver_ratio,
            "hard_vetoes": list(self.hard_vetoes),
            "sample_quality": self.sample_quality,
            "similarity_band": self.similarity_band,
            "dispersion_band": self.dispersion_band,
            "price_structure": self.price_structure,
            "display_price_mode": self.display_price_mode,
            "note": self.note,
        }


def classify_sample_quality(accepted_count: int) -> SampleQuality:
    if accepted_count <= SAMPLE_UNUSABLE_MAX:
        return SampleQuality.UNUSABLE
    if accepted_count <= SAMPLE_THIN_MAX:
        return SampleQuality.THIN
    if accepted_count <= SAMPLE_LIMITED_MAX:
        return SampleQuality.LIMITED
    if accepted_count <= SAMPLE_HEALTHY_MAX:
        return SampleQuality.HEALTHY
    return SampleQuality.STRONG


def classify_similarity(median: float | None, low_quantile: float | None) -> SimilarityBand:
    if median is None:
        return SimilarityBand.UNKNOWN
    if median >= SIMILARITY_STRONG and (low_quantile is None or low_quantile >= SIMILARITY_OK):
        return SimilarityBand.STRONG
    if median >= SIMILARITY_OK:
        return SimilarityBand.OK
    return SimilarityBand.WEAK


def _coefficient_of_variation(amounts: list[float]) -> float:
    if len(amounts) < 2:
        return 0.0
    mean = statistics.fmean(amounts)
    if mean <= 0:
        return 1.0
    return statistics.pstdev(amounts) / mean


def _percentile(sorted_amounts: list[float], percentile: float) -> float:
    if not sorted_amounts:
        return 0.0
    if len(sorted_amounts) == 1:
        return sorted_amounts[0]
    rank = (len(sorted_amounts) - 1) * (percentile / 100.0)
    low = int(rank)
    high = min(low + 1, len(sorted_amounts) - 1)
    weight = rank - low
    return sorted_amounts[low] * (1.0 - weight) + sorted_amounts[high] * weight


def classify_dispersion(amounts: Iterable[float]) -> tuple[DispersionBand, float | None, float | None, float | None]:
    values = [float(row) for row in amounts if row is not None]
    if len(values) < 2:
        if not values:
            return DispersionBand.UNKNOWN, None, None, None
        return DispersionBand.TIGHT, values[0], values[0], 0.0
    ordered = sorted(values)
    median = statistics.median(ordered)
    q25 = _percentile(ordered, 25)
    q75 = _percentile(ordered, 75)
    iqr = q75 - q25
    iqr_ratio = (iqr / median) if median > 0 else 1.0
    cov = _coefficient_of_variation(ordered)
    if iqr_ratio <= DISPERSION_TIGHT_IQR and cov <= DISPERSION_TIGHT_COV:
        band = DispersionBand.TIGHT
    elif iqr_ratio <= DISPERSION_NORMAL_IQR and cov <= DISPERSION_NORMAL_COV:
        band = DispersionBand.NORMAL
    elif iqr_ratio <= DISPERSION_WIDE_IQR and cov <= DISPERSION_WIDE_COV:
        band = DispersionBand.WIDE
    else:
        band = DispersionBand.EXTREME
    return band, q25, q75, (iqr_ratio if median > 0 else cov)


def _gap_is_economically_large(low: float, high: float) -> bool:
    if low <= 0:
        return high >= MULTIMODAL_GAP_ABS
    ratio = high / low
    gap = high - low
    return ratio >= MULTIMODAL_GAP_RATIO and gap >= MULTIMODAL_GAP_ABS


def classify_price_structure(amounts: Iterable[float]) -> PriceStructure:
    """Bounded deterministic split. Several-vs-several = MULTIMODAL; a lone spike = OUTLIER.

    Must run *before* MAD/IQR so a 1ex cluster plus a 10ex cluster cannot be
    trimmed into a fake 1.2 ex HIGH CONFIDENCE market.
    """
    values = sorted(float(row) for row in amounts if row is not None)
    if not values:
        return PriceStructure.EMPTY
    if len(values) < 4:
        return PriceStructure.UNIMODAL
    best_index = -1
    best_ratio = 1.0
    for index in range(len(values) - 1):
        low = values[index]
        high = values[index + 1]
        if not _gap_is_economically_large(low, high):
            continue
        ratio = high / low if low > 0 else high
        if ratio > best_ratio:
            best_ratio = ratio
            best_index = index
    if best_index < 0:
        return PriceStructure.UNIMODAL
    left = best_index + 1
    right = len(values) - left
    if left >= MULTIMODAL_MIN_SUPPORT and right >= MULTIMODAL_MIN_SUPPORT:
        return PriceStructure.MULTIMODAL
    return PriceStructure.OUTLIER


def classify_liquidity(*, remote_count: int, accepted_count: int) -> LiquidityBand:
    if remote_count <= REMOTE_ILLIQUID or (accepted_count <= 1 and remote_count < 8):
        return LiquidityBand.ILLIQUID
    if remote_count < REMOTE_THIN or accepted_count <= SAMPLE_THIN_MAX:
        return LiquidityBand.THIN
    if remote_count >= REMOTE_DEEP and accepted_count >= HIGH_MIN_ACCEPTED:
        return LiquidityBand.DEEP
    return LiquidityBand.NORMAL


def classify_freshness(
    listing_ages: Iterable[float | None],
    cache_age_seconds: float | None,
) -> FreshnessBand:
    """Listing age and cached-sample age are separate. Cache TTL is not this scale."""
    ages = [float(row) for row in listing_ages if row is not None]
    listing_band = FreshnessBand.UNKNOWN
    if ages:
        typical = statistics.median(ages)
        if typical <= LISTING_FRESHNESS_CURRENT_SECONDS:
            listing_band = FreshnessBand.CURRENT
        elif typical <= LISTING_FRESHNESS_RECENT_SECONDS:
            listing_band = FreshnessBand.RECENT
        elif typical <= LISTING_FRESHNESS_AGING_SECONDS:
            listing_band = FreshnessBand.AGING
        else:
            listing_band = FreshnessBand.STALE
    cache_band = FreshnessBand.UNKNOWN
    if cache_age_seconds is not None:
        age = float(cache_age_seconds)
        if age <= TRUST_CACHE_CURRENT_SECONDS:
            cache_band = FreshnessBand.CURRENT
        elif age <= TRUST_CACHE_RECENT_SECONDS:
            cache_band = FreshnessBand.RECENT
        elif age <= TRUST_CACHE_AGING_SECONDS:
            cache_band = FreshnessBand.AGING
        else:
            cache_band = FreshnessBand.STALE
    order = {
        FreshnessBand.STALE: 3,
        FreshnessBand.AGING: 2,
        FreshnessBand.RECENT: 1,
        FreshnessBand.CURRENT: 0,
        FreshnessBand.UNKNOWN: -1,
    }
    # A 30–60s cache hit stays CURRENT. Long-old cached observations can still
    # pull the combined band down. Stale *listings* always win.
    if listing_band is FreshnessBand.STALE:
        return FreshnessBand.STALE
    if cache_band is FreshnessBand.STALE:
        return FreshnessBand.STALE
    if order[listing_band] >= order[cache_band]:
        return listing_band if listing_band is not FreshnessBand.UNKNOWN else cache_band
    return cache_band if cache_band is not FreshnessBand.UNKNOWN else listing_band


def classify_specificity(
    *,
    identity_source: str,
    selected_driver_count: int,
    match_mode: str,
    count_min: int | None,
    remote_count: int,
    auto_adjusted: bool,
) -> SpecificityBand:
    if identity_source == "BASE_ONLY" or selected_driver_count <= 0:
        return SpecificityBand.BASE_ONLY
    if selected_driver_count >= 4 and str(match_mode).upper() == "ALL":
        return SpecificityBand.OVER_SPECIFIC
    if str(match_mode).upper() == "COUNT" and (count_min or 0) <= 1 and remote_count >= 400:
        return SpecificityBand.BROAD
    if selected_driver_count == 1 and remote_count >= 400:
        return SpecificityBand.BROAD
    if auto_adjusted and selected_driver_count == 1:
        return SpecificityBand.BROAD
    return SpecificityBand.USEFUL


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return _percentile(ordered, q)


def _compact_reasons(codes: tuple[str, ...]) -> tuple[str, ...]:
    ranked = [code for code in _COMPACT_REASON_PRIORITY if code in codes]
    extra = [code for code in codes if code not in ranked]
    picked = (ranked + extra)[:2]
    return tuple(picked)


def _note_for(
    state: EstimateState,
    reasons: tuple[str, ...],
    *,
    auto_adjusted: bool,
    user_refined: bool,
    omitted_anchor_labels: tuple[str, ...] = (),
) -> str:
    if omitted_anchor_labels:
        # Named, not coded: the reader has to know which stat the price ignores.
        return f"Search could not include {omitted_anchor_labels[0]} — treat this as a rough guide."
    if state is EstimateState.BASE_MARKET_ESTIMATE:
        return "Around this base — not an item price."
    if state is EstimateState.NEEDS_REFINEMENT:
        if TrustReason.MARKET_MULTIMODAL.value in reasons:
            return "Market has two price clusters — pick drivers."
        if TrustReason.STABILITY_SENSITIVE.value in reasons:
            return "Market depends heavily on matched mods."
        if TrustReason.SAMPLE_TOO_SMALL.value in reasons:
            return "Market is thin — pick drivers and Refresh."
        return "Market is thin or split — pick drivers."
    if user_refined:
        return "Refined by you."
    if auto_adjusted:
        return "Auto-adjusted market match. Original match was too narrow."
    if state is EstimateState.HIGH_CONFIDENCE:
        return "Stable live comparables."
    return "Assisted estimate — Refine if the drivers look wrong."


def assess_price_trust(evidence: PriceTrustEvidence) -> PriceTrustAssessment:
    """Pure function. Must never search, fetch, exchange, or resolve a league."""
    prices = tuple(float(row) for row in evidence.accepted_prices if row is not None)
    accepted = len(prices)
    sample = classify_sample_quality(accepted)
    sims = [float(row) for row in evidence.accepted_similarities if row is not None]
    median_sim = statistics.median(sims) if sims else None
    low_sim = _quantile(sims, 25) if sims else None
    similarity = classify_similarity(median_sim, low_sim)
    dispersion_band, q25, q75, disp = classify_dispersion(prices)
    median = statistics.median(prices) if prices else None
    structure = classify_price_structure(prices)
    multimodal = structure is PriceStructure.MULTIMODAL
    liquidity = classify_liquidity(remote_count=int(evidence.remote_count or 0), accepted_count=accepted)
    freshness = classify_freshness(evidence.listing_ages_seconds, evidence.cache_age_seconds)
    priced = max(int(evidence.priced_count or 0), accepted)
    fx_usable = int(evidence.fx_usable_count or 0)
    if priced > 0 and fx_usable > 0:
        fx_coverage = min(1.0, fx_usable / priced)
    elif accepted > 0 and fx_usable == 0 and priced == 0:
        fx_coverage = 1.0
    elif priced > 0:
        fx_coverage = min(1.0, fx_usable / priced) if fx_usable else 0.0
    else:
        fx_coverage = None
    denom = max(int(evidence.available_driver_count or 0), int(evidence.selected_driver_count or 0), 1)
    unsupported_ratio = (
        (int(evidence.unsupported_selected_count or 0) + int(evidence.ignored_mod_count or 0)) / denom
    )
    specificity = classify_specificity(
        identity_source=str(evidence.identity_source or ""),
        selected_driver_count=int(evidence.selected_driver_count or 0),
        match_mode=str(evidence.match_mode or "ALL"),
        count_min=evidence.count_min,
        remote_count=int(evidence.remote_count or 0),
        auto_adjusted=bool(evidence.auto_adjusted),
    )
    stability = str(evidence.hypothesis_stability or HypothesisStability.UNMEASURED.value)
    maturity = str(evidence.signature_maturity or "")
    source = str(evidence.hypothesis_source or HypothesisSource.AUTO_PRIOR.value)
    reasons: list[str] = []
    vetoes: list[str] = []

    def veto(code: TrustReason) -> None:
        if code.value not in vetoes:
            vetoes.append(code.value)
        if code.value not in reasons:
            reasons.append(code.value)

    def add(code: TrustReason) -> None:
        if code.value not in reasons:
            reasons.append(code.value)

    base_only = (
        specificity is SpecificityBand.BASE_ONLY
        or str(evidence.identity_source or "") == "BASE_ONLY"
        or str(evidence.discovery_estimate_state or "") == EstimateState.BASE_MARKET_ESTIMATE.value
        or int(evidence.selected_driver_count or 0) <= 0
    )
    if base_only:
        veto(TrustReason.BASE_ONLY)
    if stability == HypothesisStability.SENSITIVE.value:
        veto(TrustReason.STABILITY_SENSITIVE)
    elif stability == HypothesisStability.STABLE.value:
        add(TrustReason.STABILITY_STABLE)
    elif stability == HypothesisStability.RECOVERY_ONLY.value:
        add(TrustReason.STABILITY_RECOVERY_ONLY)
    if evidence.already_needs_refinement or evidence.discovery_estimate_state == EstimateState.NEEDS_REFINEMENT.value:
        if TrustReason.STABILITY_SENSITIVE.value not in vetoes:
            # Discovery already refused an authoritative price.
            if sample is SampleQuality.UNUSABLE:
                veto(TrustReason.SAMPLE_TOO_SMALL)
            elif multimodal:
                veto(TrustReason.MARKET_MULTIMODAL)
            else:
                veto(TrustReason.SAMPLE_TOO_SMALL if accepted < HIGH_MIN_ACCEPTED else TrustReason.QUERY_IDENTITY_WEAKENED)
    if sample is SampleQuality.UNUSABLE:
        veto(TrustReason.SAMPLE_TOO_SMALL)
    elif sample is SampleQuality.THIN:
        add(TrustReason.SAMPLE_THIN)
    elif sample in {SampleQuality.HEALTHY, SampleQuality.STRONG}:
        add(TrustReason.SAMPLE_HEALTHY)
    if similarity is SimilarityBand.STRONG:
        add(TrustReason.SIMILARITY_STRONG)
    elif similarity is SimilarityBand.WEAK:
        add(TrustReason.SIMILARITY_WEAK)
        if sample in {SampleQuality.UNUSABLE, SampleQuality.THIN, SampleQuality.LIMITED}:
            veto(TrustReason.SIMILARITY_WEAK)
    if multimodal:
        veto(TrustReason.MARKET_MULTIMODAL)
    elif dispersion_band is DispersionBand.TIGHT:
        add(TrustReason.PRICE_TIGHT)
    elif dispersion_band in {DispersionBand.WIDE, DispersionBand.EXTREME}:
        add(TrustReason.PRICE_WIDE)
        if dispersion_band is DispersionBand.EXTREME:
            veto(TrustReason.PRICE_WIDE)
    if liquidity is LiquidityBand.ILLIQUID:
        veto(TrustReason.LIQUIDITY_THIN)
    elif liquidity is LiquidityBand.THIN:
        add(TrustReason.LIQUIDITY_THIN)
    elif liquidity in {LiquidityBand.NORMAL, LiquidityBand.DEEP}:
        add(TrustReason.LIQUIDITY_HEALTHY)
    if freshness is FreshnessBand.STALE:
        veto(TrustReason.PRICE_DATA_STALE)
    if fx_coverage is not None:
        if fx_coverage >= FX_STRONG_MIN:
            add(TrustReason.FX_STRONG)
        else:
            add(TrustReason.FX_PARTIAL)
            if fx_coverage <= FX_SEVERE_MAX:
                veto(TrustReason.FX_PARTIAL)
    if evidence.item_class_unsupported or evidence.slot_family in {
        SlotFamily.OTHER.value,
        SlotFamily.OTHER.name.lower(),
        "other",
        "unique",
    }:
        if evidence.item_class_unsupported:
            veto(TrustReason.UNSUPPORTED_IDENTITY)
    if unsupported_ratio >= UNSUPPORTED_RATIO_VETO and int(evidence.selected_driver_count or 0) > 0:
        veto(TrustReason.UNSUPPORTED_IDENTITY)
    elif int(evidence.unsupported_selected_count or 0) > 0 and int(evidence.selected_driver_count or 0) <= int(
        evidence.unsupported_selected_count or 0
    ):
        veto(TrustReason.UNSUPPORTED_IDENTITY)
    if evidence.query_repaired or (evidence.auto_adjusted and source != HypothesisSource.USER_REFINED.value):
        add(TrustReason.QUERY_IDENTITY_WEAKENED)
        if evidence.query_repaired:
            veto(TrustReason.QUERY_IDENTITY_WEAKENED)
    if maturity == SignatureMaturity.MATURE.value:
        add(TrustReason.SIGNATURE_MATURE)
    elif maturity == SignatureMaturity.DEGRADED.value:
        add(TrustReason.SIGNATURE_DEGRADED)

    current_excellent = (
        sample in {SampleQuality.HEALTHY, SampleQuality.STRONG}
        and similarity is SimilarityBand.STRONG
        and dispersion_band in {DispersionBand.TIGHT, DispersionBand.NORMAL}
        and not multimodal
        and liquidity is not LiquidityBand.ILLIQUID
        and freshness in {FreshnessBand.CURRENT, FreshnessBand.RECENT, FreshnessBand.UNKNOWN}
        and (fx_coverage is None or fx_coverage >= FX_STRONG_MIN)
        and specificity is SpecificityBand.USEFUL
        and accepted >= HIGH_MIN_ACCEPTED
    )
    plus_ok = (
        stability == HypothesisStability.STABLE.value
        or (maturity == SignatureMaturity.MATURE.value and current_excellent)
        or (source == HypothesisSource.USER_REFINED.value and current_excellent)
    )
    user_refined = source == HypothesisSource.USER_REFINED.value
    auto_adjusted = bool(evidence.auto_adjusted)

    # Compilation coverage. An omitted anchor is a hard veto: the listings may be
    # perfectly consistent with each other and still be answering a different question
    # from the one the item asks. Group omissions and unsearchable modifiers are recorded
    # so the panel can say so, but they do not by themselves force a state.
    if evidence.omitted_anchor_labels:
        reasons.append(TrustReason.COVERAGE_ANCHOR_OMITTED.value)
        if TrustReason.COVERAGE_ANCHOR_OMITTED.value not in vetoes:
            vetoes.append(TrustReason.COVERAGE_ANCHOR_OMITTED.value)
    if evidence.omitted_flexible_labels:
        reasons.append(TrustReason.COVERAGE_GROUP_OMITTED.value)
    if evidence.unsearchable_labels:
        reasons.append(TrustReason.COVERAGE_UNSEARCHABLE.value)

    if base_only:
        state = EstimateState.BASE_MARKET_ESTIMATE
    elif vetoes:
        # Hard vetoes make HIGH impossible. SENSITIVE / multimodal / unusable /
        # unsupported / stale / BASE usually need refinement, not a Fair price.
        needs_vetoes = {
            TrustReason.BASE_ONLY.value,
            TrustReason.STABILITY_SENSITIVE.value,
            TrustReason.MARKET_MULTIMODAL.value,
            TrustReason.SAMPLE_TOO_SMALL.value,
            TrustReason.UNSUPPORTED_IDENTITY.value,
            TrustReason.PRICE_DATA_STALE.value,
            TrustReason.SIMILARITY_WEAK.value,
            TrustReason.PRICE_WIDE.value,
        }
        if any(code in needs_vetoes for code in vetoes) or evidence.already_needs_refinement:
            state = EstimateState.NEEDS_REFINEMENT
        elif sample in {SampleQuality.HEALTHY, SampleQuality.STRONG, SampleQuality.LIMITED} and median is not None:
            state = EstimateState.ASSISTED_ESTIMATE
        else:
            state = EstimateState.NEEDS_REFINEMENT
    elif current_excellent and plus_ok:
        state = EstimateState.HIGH_CONFIDENCE
    elif median is not None and sample is not SampleQuality.UNUSABLE:
        state = EstimateState.ASSISTED_ESTIMATE
    else:
        state = EstimateState.NEEDS_REFINEMENT

    if state is EstimateState.HIGH_CONFIDENCE and vetoes:
        state = EstimateState.ASSISTED_ESTIMATE if sample is not SampleQuality.UNUSABLE else EstimateState.NEEDS_REFINEMENT

    if state is EstimateState.BASE_MARKET_ESTIMATE:
        display = DisplayPriceMode.FULL_BANDS if median is not None else DisplayPriceMode.NONE
    elif state is EstimateState.NEEDS_REFINEMENT:
        display = DisplayPriceMode.OBSERVED_RANGE if prices else DisplayPriceMode.NONE
    elif state is EstimateState.HIGH_CONFIDENCE:
        display = DisplayPriceMode.FULL_BANDS
    else:
        display = DisplayPriceMode.FULL_BANDS if median is not None else DisplayPriceMode.NONE

    reason_tuple = tuple(reasons)
    compact = _compact_reasons(reason_tuple)
    return PriceTrustAssessment(
        state=state,
        reason_codes=reason_tuple,
        accepted_count=accepted,
        median_similarity=median_sim,
        low_similarity_quantile=low_sim,
        price_median=median,
        q25=q25,
        q75=q75,
        price_dispersion=disp,
        multimodal=multimodal,
        liquidity=liquidity.value,
        freshness=freshness.value,
        fx_coverage=fx_coverage,
        hypothesis_stability=stability,
        signature_maturity=maturity,
        hypothesis_source=source,
        market_specificity=specificity.value,
        unsupported_driver_ratio=round(unsupported_ratio, 3),
        hard_vetoes=tuple(vetoes),
        sample_quality=sample.value,
        similarity_band=similarity.value,
        dispersion_band=dispersion_band.value,
        price_structure=structure.value,
        display_price_mode=display.value,
        compact_reasons=compact,
        note=_note_for(
            state,
            reason_tuple,
            auto_adjusted=auto_adjusted,
            user_refined=user_refined,
            omitted_anchor_labels=tuple(evidence.omitted_anchor_labels),
        ),
    )


def listing_age_seconds(captured_at: str | None, *, now: float | None = None) -> float | None:
    if not captured_at:
        return None
    text = str(captured_at).strip().replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    current = float(now if now is not None else datetime.now(timezone.utc).timestamp())
    return max(0.0, current - stamp.timestamp())


def evidence_from_result(result: PriceCheckResult, *, now: float | None = None) -> PriceTrustEvidence:
    """Project a PriceCheckResult into trust evidence. Local only — no HTTP."""
    from exilelens.price_check.models import CompiledPriceCheckRequest
    compiled_request = result.request if isinstance(result.request, CompiledPriceCheckRequest) else None
    hypothesis = None if compiled_request else result.hypothesis
    estimate = result.estimate
    comparables = tuple(estimate.comparables or ())
    prices: list[float] = []
    ages: list[float | None] = []
    for row in comparables:
        amount = row.normalized_amount if row.normalized_amount is not None else row.price_amount
        if amount is not None:
            prices.append(float(amount))
        ages.append(listing_age_seconds(getattr(row, "captured_at", None), now=now))
    if not prices:
        for band in estimate.currency_bands or ():
            prices.append(float(band.amount))
            if band.amount_high is not None:
                prices.append(float(band.amount_high))
    discovery = result.discovery if isinstance(result.discovery, dict) else {}
    chosen = discovery.get("h2") if result.auto_adjusted and isinstance(discovery.get("h2"), dict) else discovery.get("h1")
    if not isinstance(chosen, dict):
        chosen = {}
    remote = int(chosen.get("remote_count") or 0)
    priced = int(chosen.get("priced_count") or getattr(result.diagnostics, "priced_listings", 0) or 0)
    accepted = int(result.comparable_count or len(prices) or chosen.get("accepted_count") or 0)
    fx_usable = sum(1 for row in comparables if row.normalized_amount is not None or row.price_amount is not None)
    if result.diagnostics is not None:
        passes = result.diagnostics.relaxation_passes or ()
        if passes:
            last = passes[-1] if not isinstance(passes[-1], dict) else passes[-1]
            if isinstance(last, dict):
                remote = int(last.get("search_total") or remote)
                priced = int(last.get("priced_listings") or priced)
                fx_usable = int(last.get("fx_usable") or fx_usable)
    signature = discovery.get("signature") if isinstance(discovery.get("signature"), dict) else {}
    selected = list(hypothesis.selected_drivers) if hypothesis is not None else []
    available = list(hypothesis.available_drivers) if hypothesis is not None else []
    ignored = list(hypothesis.ignored_mod_texts) if hypothesis is not None else []
    unsupported = sum(1 for row in selected if not row.trade_stat_ids and not row.equipment_key)
    slot = hypothesis.slot_family.value if hypothesis is not None and hasattr(hypothesis.slot_family, "value") else str(
        getattr(hypothesis, "slot_family", "") or ""
    )
    unsupported_class = slot in {SlotFamily.OTHER.value, "other"} and not selected
    identity = str(getattr(result, "identity_source", "") or "")
    if hypothesis is not None and not selected:
        identity = identity or "BASE_ONLY"
    similarities: list[float] = []
    median_from_obs = chosen.get("median_similarity")
    if median_from_obs is not None:
        similarities = [float(median_from_obs)] * max(1, len(prices) or accepted or 1)
    query_repaired = bool(discovery.get("query_repaired"))
    already_needs = str(result.estimate_state or "") == EstimateState.NEEDS_REFINEMENT.value
    source = (
        hypothesis.hypothesis_source.value
        if hypothesis is not None and hasattr(hypothesis.hypothesis_source, "value")
        else str(getattr(hypothesis, "hypothesis_source", "") or HypothesisSource.AUTO_PRIOR.value)
    )
    evidence = PriceTrustEvidence(
        accepted_prices=tuple(prices),
        accepted_similarities=tuple(similarities),
        listing_ages_seconds=tuple(ages),
        remote_count=remote,
        priced_count=priced or len(prices),
        fx_usable_count=fx_usable or len(prices),
        cache_age_seconds=result.cache_age_seconds,
        hypothesis_stability=str(result.stability or HypothesisStability.UNMEASURED.value),
        signature_maturity=str(signature.get("maturity") or ""),
        hypothesis_source=source,
        identity_source=identity,
        selected_driver_count=len(selected),
        available_driver_count=len(available),
        ignored_mod_count=len(ignored),
        unsupported_selected_count=unsupported,
        match_mode=hypothesis.match_mode.value if hypothesis is not None else "ALL",
        count_min=hypothesis.count_min if hypothesis is not None else None,
        auto_adjusted=bool(result.auto_adjusted),
        query_repaired=query_repaired,
        already_needs_refinement=already_needs,
        slot_family=slot,
        item_class_unsupported=unsupported_class and not selected,
        discovery_estimate_state=str(result.estimate_state or ""),
    )
    if compiled_request is not None:
        from dataclasses import replace
        plan = compiled_request.plan
        selected_count = sum(row.enabled for row in plan.emitted_filters)
        evidence = replace(evidence, **compiled_request.compiled_query.coverage.trust_evidence(),
                           selected_driver_count=selected_count,
                           available_driver_count=len(plan.characteristics),
                           identity_source="PRIMARY" if selected_count else "BASE_ONLY",
                           unsupported_selected_count=0, item_class_unsupported=False,
                           hypothesis_source="USER_REFINED" if compiled_request.user_refined else "AUTO_PRIOR",
                           already_needs_refinement=False)
    return evidence


def apply_price_trust(result: PriceCheckResult, *, now: float | None = None) -> PriceCheckResult:
    """Attach a PriceTrustAssessment. Never performs network I/O."""
    from dataclasses import replace

    from exilelens.price_check.models import CompiledPriceCheckRequest
    if isinstance(result.request, CompiledPriceCheckRequest):
        original = result.unassessed_estimate or result.estimate
        result = replace(result, estimate=original, unassessed_estimate=original)
    assessment = assess_price_trust(evidence_from_result(result, now=now))
    estimate = result.estimate
    if assessment.state is EstimateState.NEEDS_REFINEMENT:
        if assessment.display_price_mode == DisplayPriceMode.NONE.value:
            estimate = replace(
                estimate,
                currency_bands=(),
                confidence=PriceConfidence.NONE,
                confidence_reason=" · ".join(assessment.compact_reasons) or assessment.note,
                summary=assessment.note,
            )
        else:
            estimate = replace(
                estimate,
                confidence=PriceConfidence.LOW,
                confidence_reason=" · ".join(assessment.compact_reasons) or assessment.note,
                summary=assessment.note,
            )
    elif assessment.state is EstimateState.HIGH_CONFIDENCE:
        estimate = replace(
            estimate,
            confidence=PriceConfidence.HIGH,
            confidence_reason=" · ".join(assessment.compact_reasons) or assessment.note,
            summary=assessment.note or estimate.summary,
        )
    elif assessment.state is EstimateState.BASE_MARKET_ESTIMATE:
        estimate = replace(
            estimate,
            confidence=PriceConfidence.LOW,
            confidence_reason=" · ".join(assessment.compact_reasons) or assessment.note,
        )
    else:
        estimate = replace(
            estimate,
            confidence=PriceConfidence.LOW if estimate.confidence is PriceConfidence.HIGH else estimate.confidence,
            confidence_reason=" · ".join(assessment.compact_reasons) or estimate.confidence_reason or assessment.note,
        )
        if assessment.hypothesis_source == HypothesisSource.USER_REFINED.value and assessment.note:
            estimate = replace(estimate, summary=assessment.note)
    payload = dict(result.discovery or {})
    payload["price_trust"] = assessment.to_dict()
    return replace(
        result,
        estimate=estimate,
        estimate_state=assessment.state.value,
        discovery=payload,
    )


def format_price_check_overlay_text(model: dict[str, Any]) -> str:
    """Compact text dump of the overlay payload. Used for visual validation without EXE."""
    lines = [
        str(model.get("headline") or "PRICE CHECK"),
        str(model.get("title") or ""),
    ]
    subtitle = str(model.get("subtitle") or "").strip()
    if subtitle:
        lines.append(subtitle)
    if model.get("refined_by_you") and "Refined by you." not in subtitle:
        lines.append("Refined by you.")
    compact = model.get("trust_compact_reasons") or []
    if compact:
        lines.append(" · ".join(str(row) for row in compact))
    if model.get("show_observed_range") and model.get("observed_range"):
        lines.append(f"Observed {model.get('observed_range')}")
    elif model.get("show_currency"):
        if model.get("bands_collapsed") and model.get("cluster_text"):
            lines.append(str(model.get("cluster_text")))
        else:
            for row in model.get("currency_bands") or []:
                lines.append(f"{row.get('label')}: {row.get('display')}")
    if model.get("drivers_collapsed"):
        n = sum(1 for row in (model.get("drivers") or []) if row.get("enabled"))
        match = str(model.get("match_mode_label") or "").strip()
        lines.append(f"{n} drivers" + (f" · MATCH {match}" if match else ""))
    else:
        for row in model.get("drivers") or []:
            if not row.get("enabled"):
                continue
            lines.append(str(row.get("overlay_row") or row.get("label") or ""))
    if model.get("refine_hint"):
        lines.append(str(model.get("refine_hint")))
    return "\n".join(line for line in lines if line).strip()


# Re-export product states used by presentation.
PRODUCT_STATES = (
    EstimateState.HIGH_CONFIDENCE,
    EstimateState.ASSISTED_ESTIMATE,
    EstimateState.NEEDS_REFINEMENT,
    EstimateState.BASE_MARKET_ESTIMATE,
)
