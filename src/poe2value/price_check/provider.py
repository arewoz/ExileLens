from __future__ import annotations

from typing import Protocol

from poe2value.price_check.models import PriceCheckRequest, PriceCheckResult, ProviderCapabilities


class MarketCandidateProvider(Protocol):
    provider_id: str

    @property
    def capabilities(self) -> ProviderCapabilities:
        ...

    def lookup(self, request: PriceCheckRequest) -> PriceCheckResult | None:
        ...
