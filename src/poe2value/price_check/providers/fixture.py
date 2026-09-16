from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from poe2value.market.sources import FixtureCandidateSource
from poe2value.price_check.comparable_engine import ComparableMarketEngine, CorpusListing, comparable_listing_from_row
from poe2value.price_check.models import (
    PriceCheckRequest,
    PriceCheckResult,
    PriceSourceKind,
    ProviderCapabilities,
)

_DEFAULT_CORPUS = Path(__file__).resolve().parents[4] / "fixtures" / "market" / "comparable_corpus"


def _load_corpus_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_dir():
        rows: list[dict[str, Any]] = []
        for file in sorted(path.glob("*.json")):
            rows.extend(FixtureCandidateSource._load_corpus(file))
        return rows
    return FixtureCandidateSource._load_corpus(path)


class FixtureComparableProvider:
    provider_id = "fixture_comparable"

    def __init__(self, fixtures: list[dict[str, Any]] | None = None, corpus_path: str | Path | None = None) -> None:
        self._inline_fixtures = list(fixtures or [])
        self._corpus_path = Path(corpus_path) if corpus_path else default_fixture_corpus_path()
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
            supports_league=True,
            source_kind=PriceSourceKind.OBSERVATION_CORPUS,
        )

    def _corpus_listings(self) -> list[CorpusListing]:
        rows: list[CorpusListing] = []
        for row in self._inline_fixtures:
            listing = comparable_listing_from_row(row, source=self.provider_id)
            if listing is not None:
                rows.append(listing)
        for row in _load_corpus_rows(self._corpus_path):
            listing = comparable_listing_from_row(row, source=self.provider_id)
            if listing is not None:
                rows.append(listing)
        return rows

    def lookup(self, request: PriceCheckRequest) -> PriceCheckResult | None:
        from poe2value.price_check.models import CompiledPriceCheckRequest
        if isinstance(request, CompiledPriceCheckRequest):
            # Historical corpora are matched with legacy semantics, not this body.
            return None
        return self._engine.lookup(request)


def default_fixture_corpus_path() -> Path:
    env_path = os.environ.get("POE2VALUE_COMPARABLE_CORPUS")
    if env_path:
        return Path(env_path)
    return _DEFAULT_CORPUS
