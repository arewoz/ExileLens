from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from poe2value.market.sources import ImportedCandidateSource
from poe2value.price_check.comparable_engine import ComparableMarketEngine, CorpusListing, comparable_listing_from_row
from poe2value.price_check.models import (
    PriceCheckRequest,
    PriceCheckResult,
    PriceSourceKind,
    ProviderCapabilities,
)


class ImportComparableProvider:
    provider_id = "import_comparable"

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._source = ImportedCandidateSource(self._path)
        self._engine = ComparableMarketEngine(
            self._corpus_listings,
            provider_id=self.provider_id,
            source_kind=PriceSourceKind.OBSERVATION_CORPUS,
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_comparables=True,
            supports_price_ordering=True,
            supports_global_price_ordering=True,
            supports_league=False,
            source_kind=PriceSourceKind.OBSERVATION_CORPUS,
        )

    def _corpus_listings(self) -> list[CorpusListing]:
        if not self._path.exists():
            return []
        rows: list[CorpusListing] = []
        for row in self._source._rows:
            listing = comparable_listing_from_row(row, source=self.provider_id)
            if listing is not None:
                rows.append(listing)
        return rows

    def lookup(self, request: PriceCheckRequest) -> PriceCheckResult | None:
        from poe2value.price_check.models import CompiledPriceCheckRequest
        if isinstance(request, CompiledPriceCheckRequest):
            # Historical corpora are matched with legacy semantics, not this body.
            return None
        if not self._path.exists():
            return None
        return self._engine.lookup(request)
