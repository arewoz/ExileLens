from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Iterable

from poe2value.price_check.comparable_query import ComparableSearchQuery, RelaxationTier
from poe2value.price_check.currency_fx import CurrencyFxTable
from poe2value.price_check.models import ComparableListing, CurrencyBand, PriceConfidence


@dataclass(frozen=True)
class NormalizedPrice:
    listing_id: str
    amount: float
    currency: str
    seller_id: str | None = None

    @property
    def key(self) -> str:
        return self.listing_id


class PriceNormalizer:
    """Normalize comparable listing prices to a single display currency."""

    def __init__(
        self,
        display_currency: str | None = None,
        fx_table: CurrencyFxTable | None = None,
    ) -> None:
        self._display_currency = display_currency
        self._fx_table = fx_table

    def normalize(self, listings: Iterable[ComparableListing]) -> list[NormalizedPrice]:
        rows = [
            NormalizedPrice(
                listing_id=row.listing_id,
                amount=float(row.price_amount or 0.0),
                currency=str(row.price_currency or ""),
                seller_id=getattr(row, "seller_id", None),
            )
            for row in listings
            if row.price_amount is not None and row.price_currency
        ]
        if not rows:
            return []
        if self._fx_table is not None:
            rows = [row for row in rows if self._fx_table.is_known_currency(row.currency)]
        if not rows:
            return []
        currency = self._display_currency or self._dominant_currency(rows)
        normalized: list[NormalizedPrice] = []
        for row in rows:
            if row.currency.lower() == currency.lower():
                normalized.append(
                    NormalizedPrice(
                        listing_id=row.listing_id,
                        amount=row.amount,
                        currency=currency,
                        seller_id=row.seller_id,
                    )
                )
                continue
            if self._fx_table is None:
                continue
            converted = self._fx_table.convert(row.amount, row.currency, currency)
            if converted is None:
                continue
            normalized.append(
                NormalizedPrice(
                    listing_id=row.listing_id,
                    amount=converted,
                    currency=currency,
                    seller_id=row.seller_id,
                )
            )
        return normalized or [row for row in rows if row.currency.lower() == currency.lower()]

    @staticmethod
    def _dominant_currency(rows: list[NormalizedPrice]) -> str:
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.currency] = counts.get(row.currency, 0) + 1
        return max(counts, key=counts.get)


class OutlierFilter:
    """Remove price outliers via IQR and dedupe sellers."""

    def __init__(self, *, iqr_multiplier: float = 1.5, use_mad: bool = True) -> None:
        self._iqr_multiplier = iqr_multiplier
        self._use_mad = use_mad

    def filter(self, prices: list[NormalizedPrice]) -> list[NormalizedPrice]:
        if len(prices) < 4:
            return self._dedupe_sellers(prices)
        from poe2value.price_check.price_trust import PriceStructure, classify_price_structure

        structure = classify_price_structure(row.amount for row in prices)
        if structure is PriceStructure.MULTIMODAL:
            # MARKET-02E: do not MAD-trim one cluster away and call it a market.
            return self._dedupe_sellers(prices)
        amounts = sorted(row.amount for row in prices)
        q1 = statistics.quantiles(amounts, n=4)[0]
        q3 = statistics.quantiles(amounts, n=4)[2]
        iqr = q3 - q1
        lower = q1 - self._iqr_multiplier * iqr
        upper = q3 + self._iqr_multiplier * iqr
        filtered = [row for row in prices if lower <= row.amount <= upper]
        if self._use_mad and len(filtered) >= 4:
            filtered = self._mad_filter(filtered)
        return self._dedupe_sellers(filtered or prices)

    def _mad_filter(self, prices: list[NormalizedPrice]) -> list[NormalizedPrice]:
        amounts = [row.amount for row in prices]
        median = statistics.median(amounts)
        deviations = [abs(value - median) for value in amounts]
        mad = statistics.median(deviations) or 1.0
        threshold = 3.5 * mad
        return [row for row in prices if abs(row.amount - median) <= threshold]

    @staticmethod
    def _dedupe_sellers(prices: list[NormalizedPrice]) -> list[NormalizedPrice]:
        best_by_seller: dict[str, NormalizedPrice] = {}
        anonymous: list[NormalizedPrice] = []
        for row in prices:
            if not row.seller_id:
                anonymous.append(row)
                continue
            existing = best_by_seller.get(row.seller_id)
            if existing is None or row.amount < existing.amount:
                best_by_seller[row.seller_id] = row
        return list(best_by_seller.values()) + anonymous


@dataclass(frozen=True)
class PriceBandEstimate:
    quick_sale: float
    fair_low: float
    fair_high: float
    optimistic: float
    currency: str
    sample_count: int

    def to_currency_bands(self) -> tuple[CurrencyBand, ...]:
        return (
            CurrencyBand(label="quick_sale", amount=self.quick_sale, currency=self.currency),
            CurrencyBand(
                label="fair",
                amount=self.fair_low,
                currency=self.currency,
                amount_high=self.fair_high,
            ),
            CurrencyBand(label="optimistic", amount=self.optimistic, currency=self.currency),
        )


class PriceBandEstimator:
    """Estimate quick/fair/optimistic bands from comparable prices."""

    def estimate(self, prices: list[NormalizedPrice]) -> PriceBandEstimate | None:
        if not prices:
            return None
        amounts = sorted(row.amount for row in prices)
        currency = prices[0].currency
        if len(amounts) == 1:
            value = amounts[0]
            return PriceBandEstimate(
                quick_sale=value,
                fair_low=value,
                fair_high=value,
                optimistic=value,
                currency=currency,
                sample_count=1,
            )
        p25 = _percentile(amounts, 25)
        p40 = _percentile(amounts, 40)
        p60 = _percentile(amounts, 60)
        p75 = _percentile(amounts, 75)
        return PriceBandEstimate(
            quick_sale=round(p25, 1),
            fair_low=round(min(p40, p60), 1),
            fair_high=round(max(p40, p60), 1),
            optimistic=round(p75, 1),
            currency=currency,
            sample_count=len(amounts),
        )


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


class ConfidenceScorer:
    """Score confidence from comparable count, dispersion, and relaxation tier."""

    def score(
        self,
        *,
        sample_count: int,
        amounts: list[float],
        relaxation_tier: RelaxationTier,
        league_known: bool,
    ) -> PriceConfidence:
        if sample_count <= 0:
            return PriceConfidence.NONE
        if sample_count <= 2:
            return PriceConfidence.NONE
        dispersion = _coefficient_of_variation(amounts)
        confidence = PriceConfidence.LOW
        if sample_count >= 30 and dispersion <= 0.35 and relaxation_tier == RelaxationTier.STRICT:
            confidence = PriceConfidence.HIGH
        elif sample_count >= 20 and dispersion <= 0.45 and relaxation_tier <= RelaxationTier.RELAXED_MODS:
            confidence = PriceConfidence.MEDIUM
        elif sample_count >= 8:
            confidence = PriceConfidence.LOW
        elif sample_count >= 3:
            confidence = PriceConfidence.LOW
        else:
            confidence = PriceConfidence.NONE
        if not league_known and confidence == PriceConfidence.HIGH:
            confidence = PriceConfidence.MEDIUM
        if relaxation_tier >= RelaxationTier.BASE_AND_RARITY and confidence == PriceConfidence.HIGH:
            confidence = PriceConfidence.MEDIUM
        return confidence


def _coefficient_of_variation(amounts: list[float]) -> float:
    if len(amounts) < 2:
        return 0.0
    mean = statistics.fmean(amounts)
    if mean <= 0:
        return 1.0
    return statistics.pstdev(amounts) / mean


def confidence_reason(
    *,
    sample_count: int,
    amounts: list[float],
    relaxation_tier: RelaxationTier,
) -> str:
    """One short sentence saying *why* the confidence is what it is.

    MARKET-01B12: "LOW" on its own does not tell the owner whether the market is
    genuinely uncertain or whether we simply did not see many listings.
    """
    if sample_count <= 0:
        return "no comparable listings"
    dispersion = _coefficient_of_variation(amounts)
    parts = [f"{sample_count} comp{'s' if sample_count != 1 else ''}"]
    if dispersion >= 0.75:
        parts.append("very wide price spread")
    elif dispersion >= 0.45:
        parts.append("wide price spread")
    elif sample_count >= 12:
        parts.append("close prices")
    elif dispersion <= 0.15:
        parts.append("tight prices")
    if relaxation_tier > RelaxationTier.STRICT:
        parts.append("relaxed match")
    return " · ".join(parts)


def build_band_estimate(
    listings: Iterable[ComparableListing],
    *,
    query: ComparableSearchQuery,
    league_known: bool,
    fx_table: CurrencyFxTable | None = None,
) -> tuple[PriceBandEstimate | None, PriceConfidence, list[ComparableListing]]:
    listings = list(listings)
    normalizer = PriceNormalizer(fx_table=fx_table)
    normalized = normalizer.normalize(listings)
    filtered = OutlierFilter().filter(normalized)
    amounts = [row.amount for row in filtered]
    if len(filtered) <= 2:
        return None, PriceConfidence.NONE, []
    band = PriceBandEstimator().estimate(filtered)
    confidence = ConfidenceScorer().score(
        sample_count=len(filtered),
        amounts=amounts,
        relaxation_tier=query.relaxation_tier,
        league_known=league_known,
    )
    if band is not None and len(filtered) <= 7:
        confidence = PriceConfidence.LOW
    # MARKET-01B12: carry the value the estimator actually used back onto each accepted
    # listing, so the UI can show raw and normalized side by side without doing its own
    # currency conversion.
    normalized_by_id = {row.listing_id: row for row in filtered}
    kept_listings = [
        row.with_normalized(
            normalized_by_id[row.listing_id].amount,
            normalized_by_id[row.listing_id].currency,
        )
        for row in listings
        if row.listing_id in normalized_by_id
    ]
    return band, confidence, kept_listings


def count_fx_usable_listings(
    listings: Iterable[ComparableListing],
    *,
    fx_table: CurrencyFxTable | None = None,
) -> int:
    normalizer = PriceNormalizer(fx_table=fx_table)
    return len(normalizer.normalize(listings))
