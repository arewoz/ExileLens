from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MarketEvalCache:
    """Cache PoB evaluations by baseline fingerprint + slot + item hash."""

    _store: dict[str, dict[str, Any]] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def key(self, *, fingerprint: str, slot: str, content_hash: str) -> str:
        return f"{fingerprint}|{slot}|{content_hash}"

    def get(self, *, fingerprint: str, slot: str, content_hash: str) -> dict[str, Any] | None:
        value = self._store.get(self.key(fingerprint=fingerprint, slot=slot, content_hash=content_hash))
        if value is not None:
            self.hits += 1
        return value

    def put(self, *, fingerprint: str, slot: str, content_hash: str, payload: dict[str, Any]) -> None:
        self._store[self.key(fingerprint=fingerprint, slot=slot, content_hash=content_hash)] = payload
        self.misses += 1

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "entries": len(self._store)}

    def invalidate(self) -> None:
        self._store.clear()
        self.hits = 0
        self.misses = 0
