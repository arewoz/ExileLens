"""Phase 5B candidate source boundary — re-exports market providers."""

from __future__ import annotations

from typing import Any, Protocol

from exilelens.market.sources import FixtureCandidateSource, ImportedCandidateSource

__all__ = ["CandidateSource", "FixtureCandidateSource", "ImportedCandidateSource"]


class CandidateSource(Protocol):
    """Phase 5B boundary. Phase 5A must not perform network I/O."""

    name: str

    def search(self, intent: dict[str, Any], plan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...
