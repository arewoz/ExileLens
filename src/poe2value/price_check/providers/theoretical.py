from __future__ import annotations

from poe2value.price_check.models import (
    PriceCheckRequest,
    PriceCheckResult,
    PriceEstimate,
    PriceSourceKind,
    ProviderCapabilities,
    TheoreticalTier,
)
from poe2value.price_check.theoretical import classify_theoretical_desirability

_TIER_SUMMARY = {
    TheoreticalTier.HIGH_VALUE_RARE: "High-value rare",
    TheoreticalTier.MODERATE_VALUE: "Moderate-value item",
    TheoreticalTier.LOW_VALUE: "Low-value item",
    TheoreticalTier.UNKNOWN: "Unknown desirability",
}


class TheoreticalValueProvider:
    provider_id = "theoretical_value"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_comparables=False,
            source_kind=PriceSourceKind.MODEL_THEORETICAL,
        )

    def lookup(self, request: PriceCheckRequest) -> PriceCheckResult:
        tier, mods, confidence = classify_theoretical_desirability(request.item_raw)
        estimate = PriceEstimate(
            source_kind=PriceSourceKind.MODEL_THEORETICAL,
            confidence=confidence,
            theoretical_tier=tier,
            summary=_TIER_SUMMARY.get(tier, "Unknown"),
            disclaimer="Theoretical desirability only — not a market price.",
        )
        return PriceCheckResult(
            request=request,
            estimate=estimate,
            provider_id=self.provider_id,
            important_mods=mods,
        )
