from __future__ import annotations

from typing import Any

from exilelens.analysis.identity import baseline_fingerprint_key


class ProbeCache:
    def __init__(self) -> None:
        self._raw: dict[str, dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0

    def key(self, *, fingerprint: str, generation: int, probe_id: str, magnitude: float, context: str) -> str:
        return baseline_fingerprint_key(
            fingerprint=fingerprint,
            generation=generation,
            probe_id=probe_id,
            magnitude=magnitude,
            context=context,
        )

    def get(self, key: str) -> dict[str, Any] | None:
        value = self._raw.get(key)
        if value is None:
            self.misses += 1
            return None
        self.hits += 1
        return value

    def put(self, key: str, value: dict[str, Any]) -> None:
        self._raw[key] = value

    def invalidate(self) -> None:
        self._raw.clear()

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "size": len(self._raw)}
