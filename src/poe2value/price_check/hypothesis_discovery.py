"""MARKET-02C — bounded H1/H2 market-hypothesis recovery. Not a new taxonomy.

H1 is the MARKET-02B AUTO_PRIOR hypothesis, or a MARKET-02D mature signature H1.
At most one H2 is generated, and only when H1 has evidence of a problem.
Ordinary healthy Shift+C stays one search.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from poe2value.price_check.market_drivers import (
    ARMOUR_PRIMARY,
    BOOTS_PRIMARY,
    JEWEL_USEFUL,
    JEWELLERY_PRIMARY,
    JUNK_FAMILIES,
    MatchMode,
    MarketPriceDriver,
    PriceCheckHypothesis,
    SlotFamily,
    WEAPON_GLOBAL,
    EstimateState,
    HypothesisSource,
    hypothesis_with_selection,
)


class DiscoverySource(str, Enum):
    NONE = "NONE"
    CACHE_EVIDENCE = "CACHE_EVIDENCE"
    THIN_RESULT_RECOVERY = "THIN_RESULT_RECOVERY"
    COMBINATION_STABILITY = "COMBINATION_STABILITY"


class DiscoveryTrigger(str, Enum):
    ZERO_RESULTS = "ZERO_RESULTS"
    VERY_THIN_RESULTS = "VERY_THIN_RESULTS"
    WEAK_COMPARABLES = "WEAK_COMPARABLES"
    BASE_ONLY = "BASE_ONLY"
    CACHED_EVIDENCE = "CACHED_EVIDENCE"


class TransformationKind(str, Enum):
    NONE = "NONE"
    CASE_A_COUNT_2_OF_3 = "CASE_A_COUNT_2_OF_3"
    CASE_B_STRONGEST_TWO_ALL = "CASE_B_STRONGEST_TWO_ALL"
    CASE_C_STRONGEST_SINGLE = "CASE_C_STRONGEST_SINGLE"
    CASE_D_COUNT_DECREASE = "CASE_D_COUNT_DECREASE"
    CASE_E_STRONGEST_UNUSED = "CASE_E_STRONGEST_UNUSED"


class HypothesisStability(str, Enum):
    UNMEASURED = "UNMEASURED"
    STABLE = "STABLE"
    SENSITIVE = "SENSITIVE"
    RECOVERY_ONLY = "RECOVERY_ONLY"


class FinalHypothesis(str, Enum):
    H1 = "H1"
    H2_RECOVERY = "H2_RECOVERY"
    NEEDS_REFINEMENT = "NEEDS_REFINEMENT"
    BASE_ONLY = "BASE_ONLY"


class EvidenceSource(str, Enum):
    OBSERVATION_STORE = "OBSERVATION_STORE"
    H2_PROBE = "H2_PROBE"
    PRIOR_ONLY = "PRIOR_ONLY"


_MIN_USABLE = 3
_STABLE_RATIO = 1.5
_SENSITIVE_RATIO = 2.0
_BROAD_UNIVERSE = 400
_TINY_SAMPLE = 4


@dataclass(frozen=True)
class DriverEvidence:
    """Ephemeral per-result evidence. Not a persisted MarketSignature."""

    driver_id: str
    support_count: int
    observed_count: int
    price_with_median: float | None
    price_without_median: float | None
    uplift_ratio: float | None
    source: EvidenceSource
    reliability: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "driver_id": self.driver_id,
            "support_count": self.support_count,
            "observed_count": self.observed_count,
            "price_with_median": self.price_with_median,
            "price_without_median": self.price_without_median,
            "uplift_ratio": self.uplift_ratio,
            "source": self.source.value,
            "reliability": self.reliability,
        }


@dataclass(frozen=True)
class HypothesisObservation:
    hypothesis: PriceCheckHypothesis
    fingerprint: str
    selected_families: tuple[str, ...]
    match_mode: str
    count_min: int | None
    remote_count: int
    fetched_count: int
    priced_count: int
    accepted_count: int
    median_similarity: float | None
    price_median: float | None
    price_low: float | None
    price_high: float | None
    dispersion: float | None
    query_age_seconds: float | None
    query_source: str
    search_requests: int
    http_status: int | None = None

    @property
    def usable(self) -> bool:
        return observation_is_usable(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "selected_drivers": [row.family for row in self.hypothesis.selected_drivers],
            "match_mode": self.match_mode,
            "count_min": self.count_min,
            "remote_count": self.remote_count,
            "fetched_count": self.fetched_count,
            "priced_count": self.priced_count,
            "accepted_count": self.accepted_count,
            "median_similarity": self.median_similarity,
            "price_median": self.price_median,
            "price_low": self.price_low,
            "price_high": self.price_high,
            "dispersion": self.dispersion,
            "query_age_seconds": self.query_age_seconds,
            "query_source": self.query_source,
            "search_requests": self.search_requests,
            "http_status": self.http_status,
            "usable": self.usable,
            "quality": quality_score(self),
        }


@dataclass(frozen=True)
class HypothesisPlan:
    primary_hypothesis: PriceCheckHypothesis
    alternate_hypothesis: PriceCheckHypothesis | None
    trigger: DiscoveryTrigger | None
    reason: str
    max_searches: int
    discovery_source: DiscoverySource
    transformation: TransformationKind = TransformationKind.NONE

    def to_dict(self) -> dict[str, Any]:
        h2 = self.alternate_hypothesis
        return {
            "trigger": self.trigger.value if self.trigger else None,
            "reason": self.reason,
            "max_searches": self.max_searches,
            "discovery_source": self.discovery_source.value,
            "transformation": self.transformation.value,
            "h1_fingerprint": self.primary_hypothesis.query_fingerprint,
            "h1_drivers": [row.family for row in self.primary_hypothesis.selected_drivers],
            "h1_match": self.primary_hypothesis.match_mode.value,
            "h1_count_min": self.primary_hypothesis.count_min,
            "h2_generated": h2 is not None,
            "h2_fingerprint": h2.query_fingerprint if h2 is not None else None,
            "h2_drivers": [row.family for row in h2.selected_drivers] if h2 is not None else [],
            "h2_match": h2.match_mode.value if h2 is not None else None,
            "h2_count_min": h2.count_min if h2 is not None else None,
        }


@dataclass(frozen=True)
class DiscoverySelection:
    final_hypothesis: PriceCheckHypothesis
    original_hypothesis: PriceCheckHypothesis
    estimate_state: EstimateState
    stability: HypothesisStability
    winner: FinalHypothesis
    auto_adjusted: bool
    note: str
    pending_hypothesis: PriceCheckHypothesis | None = None
    queued: bool = False
    queued_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_hypothesis": self.winner.value,
            "estimate_state": self.estimate_state.value,
            "stability": self.stability.value,
            "auto_adjusted": self.auto_adjusted,
            "note": self.note,
            "queued": self.queued,
            "queued_seconds": self.queued_seconds,
            "final_fingerprint": self.final_hypothesis.query_fingerprint,
            "final_drivers": [row.family for row in self.final_hypothesis.selected_drivers],
        }


def discovery_allowed(hypothesis: PriceCheckHypothesis | None) -> bool:
    """USER_REFINED and already-recovered H2 never spawn another automatic probe."""
    if hypothesis is None:
        return False
    source = hypothesis.hypothesis_source
    value = source.value if isinstance(source, HypothesisSource) else str(source)
    return value in {HypothesisSource.AUTO_PRIOR.value, HypothesisSource.SIGNATURE.value}


def observation_is_usable(obs: HypothesisObservation) -> bool:
    if obs.accepted_count < _MIN_USABLE:
        return False
    if obs.price_median is None:
        return False
    return True


def classify_h1_problem(obs: HypothesisObservation) -> DiscoveryTrigger | None:
    hypothesis = obs.hypothesis
    if not hypothesis.selected_drivers:
        unused = market_relevant_unused(hypothesis)
        if unused:
            return DiscoveryTrigger.BASE_ONLY
        return None
    if observation_is_usable(obs):
        return None
    if obs.remote_count <= 0 and obs.accepted_count <= 0 and obs.fetched_count <= 0:
        return DiscoveryTrigger.ZERO_RESULTS
    if obs.priced_count <= 0 and obs.fetched_count <= 0:
        return DiscoveryTrigger.ZERO_RESULTS
    if obs.accepted_count <= 0 or obs.price_median is None:
        return DiscoveryTrigger.WEAK_COMPARABLES
    if obs.accepted_count < _MIN_USABLE:
        return DiscoveryTrigger.VERY_THIN_RESULTS
    return DiscoveryTrigger.WEAK_COMPARABLES


def market_relevant_unused(hypothesis: PriceCheckHypothesis) -> tuple[MarketPriceDriver, ...]:
    selected_ids = {row.driver_id for row in hypothesis.selected_drivers}
    rows: list[MarketPriceDriver] = []
    for row in hypothesis.available_drivers:
        if row.driver_id in selected_ids:
            continue
        if row.family in JUNK_FAMILIES:
            continue
        if row.actual_value <= 0:
            continue
        if not row.trade_stat_ids and not row.equipment_key:
            continue
        rows.append(row)
    return tuple(rows)


def _class_prior(slot: SlotFamily) -> tuple[str, ...]:
    if slot is SlotFamily.JEWELLERY:
        return JEWELLERY_PRIMARY
    if slot is SlotFamily.WEAPON:
        return ("equip_dps", "equip_pdps", "equip_edps") + WEAPON_GLOBAL
    if slot is SlotFamily.BOOTS:
        return BOOTS_PRIMARY + ("equip_ar", "equip_ev", "equip_es")
    if slot is SlotFamily.ARMOUR:
        return ("equip_ar", "equip_ev", "equip_es") + ARMOUR_PRIMARY
    if slot is SlotFamily.JEWEL:
        return tuple(sorted(JEWEL_USEFUL))
    return JEWELLERY_PRIMARY


def driver_strength_key(driver: MarketPriceDriver, slot: SlotFamily) -> tuple:
    """Market-shaped rank. Lower tuple sorts as stronger. Not PoB DPS / build score."""
    prior = _class_prior(slot)
    try:
        rank = prior.index(driver.family)
    except ValueError:
        rank = 80 + max(0, int(driver.priority))
    equipment = 0 if driver.equipment_key else 1
    return (equipment, rank, -float(driver.actual_value or 0.0))


def rank_drivers(
    drivers: Iterable[MarketPriceDriver],
    slot: SlotFamily,
) -> tuple[MarketPriceDriver, ...]:
    return tuple(sorted(drivers, key=lambda row: driver_strength_key(row, slot)))


def strongest_driver(drivers: Iterable[MarketPriceDriver], slot: SlotFamily) -> MarketPriceDriver | None:
    ranked = rank_drivers(drivers, slot)
    return ranked[0] if ranked else None


def weakest_driver(drivers: Iterable[MarketPriceDriver], slot: SlotFamily) -> MarketPriceDriver | None:
    ranked = rank_drivers(drivers, slot)
    return ranked[-1] if ranked else None


def generate_alternate(
    hypothesis: PriceCheckHypothesis,
) -> tuple[PriceCheckHypothesis, TransformationKind, str] | None:
    """Exactly one canonical H2. Never try both CASE B options."""
    selected = list(hypothesis.selected_drivers)
    n = len(selected)
    slot = hypothesis.slot_family
    mode = hypothesis.match_mode

    if slot is SlotFamily.JEWEL and mode is MatchMode.COUNT and int(hypothesis.count_min or 0) > 1:
        h2 = hypothesis_with_selection(
            hypothesis,
            selected,
            match_mode=MatchMode.COUNT,
            count_min=int(hypothesis.count_min) - 1,
            hypothesis_source=HypothesisSource.AUTO_RECOVERY,
        )
        if h2.query_fingerprint == hypothesis.query_fingerprint:
            return None
        return h2, TransformationKind.CASE_D_COUNT_DECREASE, "jewel COUNT N-of-M decreased by one"

    if n == 0:
        unused = market_relevant_unused(hypothesis)
        strongest = strongest_driver(unused, slot)
        if strongest is None:
            return None
        h2 = hypothesis_with_selection(
            hypothesis,
            (strongest,),
            match_mode=MatchMode.ALL,
            hypothesis_source=HypothesisSource.AUTO_RECOVERY,
        )
        return h2, TransformationKind.CASE_E_STRONGEST_UNUSED, "BASE_ONLY unused driver promoted"

    if n == 3 and mode is MatchMode.ALL:
        h2 = hypothesis_with_selection(
            hypothesis,
            selected,
            match_mode=MatchMode.COUNT,
            count_min=2,
            hypothesis_source=HypothesisSource.AUTO_RECOVERY,
        )
        return h2, TransformationKind.CASE_A_COUNT_2_OF_3, "3 ALL → MATCH 2 of 3"

    if n == 3 and mode is MatchMode.COUNT and slot is SlotFamily.JEWELLERY:
        weakest = weakest_driver(selected, slot)
        kept = [row for row in rank_drivers(selected, slot) if weakest is None or row.driver_id != weakest.driver_id][:2]
        if len(kept) < 2:
            return None
        h2 = hypothesis_with_selection(
            hypothesis,
            kept,
            match_mode=MatchMode.ALL,
            hypothesis_source=HypothesisSource.AUTO_RECOVERY,
        )
        return h2, TransformationKind.CASE_B_STRONGEST_TWO_ALL, "jewellery COUNT 2/3 → strongest 2 ALL"

    if n == 2 and mode is MatchMode.ALL:
        strongest = strongest_driver(selected, slot)
        if strongest is None:
            return None
        h2 = hypothesis_with_selection(
            hypothesis,
            (strongest,),
            match_mode=MatchMode.ALL,
            hypothesis_source=HypothesisSource.AUTO_RECOVERY,
        )
        return h2, TransformationKind.CASE_C_STRONGEST_SINGLE, "2 ALL → strongest single driver"

    return None


def plan_discovery(
    hypothesis: PriceCheckHypothesis,
    *,
    trigger: DiscoveryTrigger | None,
    cache_can_evaluate_h2: bool = False,
) -> HypothesisPlan:
    if not discovery_allowed(hypothesis) or trigger is None:
        return HypothesisPlan(
            primary_hypothesis=hypothesis,
            alternate_hypothesis=None,
            trigger=None,
            reason="discovery disabled or H1 healthy",
            max_searches=0,
            discovery_source=DiscoverySource.NONE,
        )
    generated = generate_alternate(hypothesis)
    if generated is None:
        return HypothesisPlan(
            primary_hypothesis=hypothesis,
            alternate_hypothesis=None,
            trigger=trigger,
            reason="no legal single H2 transformation",
            max_searches=0,
            discovery_source=DiscoverySource.NONE,
        )
    h2, kind, reason = generated
    if cache_can_evaluate_h2:
        source = (
            DiscoverySource.CACHE_EVIDENCE
            if trigger is DiscoveryTrigger.CACHED_EVIDENCE
            else DiscoverySource.THIN_RESULT_RECOVERY
        )
        return HypothesisPlan(
            primary_hypothesis=hypothesis,
            alternate_hypothesis=h2,
            trigger=trigger,
            reason=f"{reason}; evaluated from cache",
            max_searches=0,
            discovery_source=source,
            transformation=kind,
        )
    source = DiscoverySource.THIN_RESULT_RECOVERY
    if trigger is DiscoveryTrigger.CACHED_EVIDENCE:
        source = DiscoverySource.CACHE_EVIDENCE
    return HypothesisPlan(
        primary_hypothesis=hypothesis,
        alternate_hypothesis=h2,
        trigger=trigger,
        reason=reason,
        max_searches=1,
        discovery_source=source,
        transformation=kind,
    )


def quality_score(obs: HypothesisObservation) -> float:
    """Bounded deterministic score. Not 'whichever has more listings' and not a trained model."""
    if not observation_is_usable(obs):
        return -1000.0
    accepted = obs.accepted_count
    similarity = float(obs.median_similarity or 0.0)
    dispersion = float(obs.dispersion or 0.0)
    selected_n = len(obs.hypothesis.selected_drivers)
    specific = float(selected_n)
    if obs.hypothesis.match_mode is MatchMode.ALL:
        specific += 0.5
    if not obs.hypothesis.selected_drivers:
        specific -= 4.0
    score = 0.0
    score += min(accepted, 8) * 3.0
    score += similarity * 18.0
    score -= min(max(dispersion, 0.0), 2.0) * 10.0
    score += specific * 2.0
    if obs.remote_count >= _BROAD_UNIVERSE:
        score -= 12.0
    if accepted < 3:
        score -= 40.0
    return score


def better_observation(
    left: HypothesisObservation,
    right: HypothesisObservation,
) -> HypothesisObservation:
    left_score = quality_score(left)
    right_score = quality_score(right)
    if right_score > left_score + 1e-6:
        return right
    return left


def _band_overlap(left: HypothesisObservation, right: HypothesisObservation) -> bool:
    if left.price_low is None or left.price_high is None:
        return False
    if right.price_low is None or right.price_high is None:
        return False
    return not (left.price_high < right.price_low or right.price_high < left.price_low)


def median_ratio(left: HypothesisObservation, right: HypothesisObservation) -> float | None:
    a = left.price_median
    b = right.price_median
    if a is None or b is None:
        return None
    lo = min(abs(a), abs(b))
    hi = max(abs(a), abs(b))
    if lo <= 0:
        return None
    return hi / lo


def measure_stability(
    h1: HypothesisObservation,
    h2: HypothesisObservation | None,
) -> HypothesisStability:
    if h2 is None:
        if observation_is_usable(h1):
            return HypothesisStability.UNMEASURED
        return HypothesisStability.UNMEASURED
    h1_ok = observation_is_usable(h1)
    h2_ok = observation_is_usable(h2)
    if not h1_ok and h2_ok:
        return HypothesisStability.RECOVERY_ONLY
    if not h1_ok and not h2_ok:
        return HypothesisStability.UNMEASURED
    if h1_ok and not h2_ok:
        return HypothesisStability.UNMEASURED
    ratio = median_ratio(h1, h2)
    if ratio is None:
        return HypothesisStability.UNMEASURED
    overlap = _band_overlap(h1, h2)
    if ratio > _SENSITIVE_RATIO or (ratio > _STABLE_RATIO and not overlap):
        return HypothesisStability.SENSITIVE
    if ratio <= _STABLE_RATIO and overlap:
        return HypothesisStability.STABLE
    if ratio <= _STABLE_RATIO:
        return HypothesisStability.STABLE
    return HypothesisStability.SENSITIVE


def select_final(
    h1: HypothesisObservation,
    h2: HypothesisObservation | None,
    *,
    h2_from_search: bool,
) -> DiscoverySelection:
    original = h1.hypothesis
    if not original.selected_drivers and (h2 is None or not observation_is_usable(h2)):
        unused = market_relevant_unused(original)
        if not unused:
            return DiscoverySelection(
                final_hypothesis=original,
                original_hypothesis=original,
                estimate_state=EstimateState.BASE_MARKET_ESTIMATE,
                stability=HypothesisStability.UNMEASURED,
                winner=FinalHypothesis.BASE_ONLY,
                auto_adjusted=False,
                note="",
            )
    h1_ok = observation_is_usable(h1)
    h2_ok = h2 is not None and observation_is_usable(h2)
    stability = measure_stability(h1, h2)

    if h1_ok and h2_ok and stability is HypothesisStability.SENSITIVE:
        return DiscoverySelection(
            final_hypothesis=original,
            original_hypothesis=original,
            estimate_state=EstimateState.NEEDS_REFINEMENT,
            stability=stability,
            winner=FinalHypothesis.NEEDS_REFINEMENT,
            auto_adjusted=False,
            note="Price is highly sensitive to which mods are matched.",
        )
    if h1_ok and not h2_from_search:
        return DiscoverySelection(
            final_hypothesis=original,
            original_hypothesis=original,
            estimate_state=EstimateState.ASSISTED_ESTIMATE,
            stability=stability if h2_ok else HypothesisStability.UNMEASURED,
            winner=FinalHypothesis.H1,
            auto_adjusted=False,
            note="",
        )
    if not h1_ok and h2_ok and h2 is not None:
        recovered = h2.hypothesis
        if recovered.hypothesis_source in {HypothesisSource.AUTO_PRIOR, HypothesisSource.SIGNATURE}:
            recovered = hypothesis_with_selection(
                recovered,
                recovered.selected_drivers,
                match_mode=recovered.match_mode,
                count_min=recovered.count_min,
                hypothesis_source=HypothesisSource.AUTO_RECOVERY,
            )
        return DiscoverySelection(
            final_hypothesis=recovered,
            original_hypothesis=original,
            estimate_state=EstimateState.ASSISTED_ESTIMATE,
            stability=HypothesisStability.RECOVERY_ONLY,
            winner=FinalHypothesis.H2_RECOVERY,
            auto_adjusted=True,
            note="Auto-adjusted market match. Original match was too narrow.",
        )
    if h1_ok:
        return DiscoverySelection(
            final_hypothesis=original,
            original_hypothesis=original,
            estimate_state=EstimateState.ASSISTED_ESTIMATE,
            stability=HypothesisStability.UNMEASURED,
            winner=FinalHypothesis.H1,
            auto_adjusted=False,
            note="",
        )
    return DiscoverySelection(
        final_hypothesis=original,
        original_hypothesis=original,
        estimate_state=EstimateState.NEEDS_REFINEMENT,
        stability=stability,
        winner=FinalHypothesis.NEEDS_REFINEMENT,
        auto_adjusted=False,
        note="Market is thin — pick drivers and Refresh.",
    )


def driver_evidence_from_counts(
    *,
    driver_id: str,
    support_count: int,
    observed_count: int,
    price_with_median: float | None,
    price_without_median: float | None,
    source: EvidenceSource,
) -> DriverEvidence:
    uplift = None
    if price_with_median and price_without_median and price_without_median > 0:
        uplift = price_with_median / price_without_median
    reliability = "INSUFFICIENT"
    if min(support_count, observed_count) >= 8 and uplift is not None:
        reliability = "MODERATE"
    elif min(support_count, observed_count) >= _TINY_SAMPLE and uplift is not None:
        reliability = "LOW"
    if min(support_count, max(observed_count, 0)) < _TINY_SAMPLE:
        reliability = "INSUFFICIENT"
        uplift = None
    return DriverEvidence(
        driver_id=driver_id,
        support_count=support_count,
        observed_count=observed_count,
        price_with_median=price_with_median,
        price_without_median=price_without_median,
        uplift_ratio=uplift,
        source=source,
        reliability=reliability,
    )


def price_stats(amounts: Iterable[float]) -> tuple[float | None, float | None, float | None, float | None]:
    values = [float(value) for value in amounts]
    if not values:
        return None, None, None, None
    median = statistics.median(values)
    low = min(values)
    high = max(values)
    if len(values) < 2:
        return median, low, high, 0.0
    mean = statistics.fmean(values)
    dispersion = (statistics.pstdev(values) / mean) if mean > 0 else 1.0
    return median, low, high, dispersion


def observation_from_counts(
    hypothesis: PriceCheckHypothesis,
    *,
    remote_count: int = 0,
    fetched_count: int = 0,
    priced_count: int = 0,
    accepted_count: int = 0,
    amounts: Iterable[float] = (),
    similarities: Iterable[float] = (),
    query_source: str = "SEARCH",
    search_requests: int = 0,
    query_age_seconds: float | None = None,
    http_status: int | None = None,
) -> HypothesisObservation:
    median, low, high, dispersion = price_stats(amounts)
    sim_values = [float(value) for value in similarities]
    median_sim = statistics.median(sim_values) if sim_values else None
    return HypothesisObservation(
        hypothesis=hypothesis,
        fingerprint=hypothesis.query_fingerprint,
        selected_families=tuple(row.family for row in hypothesis.selected_drivers),
        match_mode=hypothesis.match_mode.value,
        count_min=hypothesis.count_min,
        remote_count=int(remote_count),
        fetched_count=int(fetched_count),
        priced_count=int(priced_count),
        accepted_count=int(accepted_count),
        median_similarity=median_sim,
        price_median=median,
        price_low=low,
        price_high=high,
        dispersion=dispersion,
        query_age_seconds=query_age_seconds,
        query_source=query_source,
        search_requests=int(search_requests),
        http_status=http_status,
    )
