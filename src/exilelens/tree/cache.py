from __future__ import annotations

from typing import Any


class TreeEvalCache:
    def __init__(self) -> None:
        self._raw: dict[str, dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0
        self.pob_recalcs = 0

    def key(
        self,
        *,
        prefix: str,
        path_identity: str,
        context: str,
    ) -> str:
        return f"{prefix}|{path_identity}|{context}"

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

    def stats(self) -> dict[str, int | float]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "size": len(self._raw),
            "pob_recalcs": self.pob_recalcs,
            "hit_rate": (self.hits / total) if total else 0.0,
        }
