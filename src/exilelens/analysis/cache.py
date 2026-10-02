from __future__ import annotations

from typing import Any

from exilelens.analysis.identity import baseline_fingerprint_key


class ProbeCache:
    def __init__(self) -> None:
        self._raw: dict[str, dict[str, Any]] = {}
        # M5.5: whether PoB applies modifiers appended to a given item, per baseline identity + slot + item text.
        self._carrier: dict[str, bool] = {}
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

    def carrier_key(self, identity: str, slot: str, raw: str) -> str:
        import hashlib

        return f"{identity}|{slot}|{hashlib.sha256(raw.encode('utf-8', 'replace')).hexdigest()[:16]}"

    def get_carrier(self, key: str) -> bool | None:
        return self._carrier.get(key)

    def put_carrier(self, key: str, applies: bool) -> None:
        self._carrier[key] = applies

    def invalidate(self) -> None:
        self._raw.clear()
        self._carrier.clear()

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "size": len(self._raw)}
