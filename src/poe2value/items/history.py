from __future__ import annotations

from typing import Any

HISTORY_LIMIT = 20


def baseline_identity(
    *,
    fingerprint: str = "",
    build_path: str = "",
    source_identity: str = "",
    loadout: str = "",
    item_set: str = "",
    context: str = "",
    generation: int = 0,
) -> str:
    return f"{fingerprint}|{source_identity or build_path}|{loadout}|{item_set}|{context}|{generation}"


class ResultHistory:
    def __init__(self, limit: int = HISTORY_LIMIT) -> None:
        self.limit = limit
        self._entries: list[dict[str, Any]] = []

    def record(self, result: dict[str, Any], *, identity: str, current: bool = True) -> None:
        recommendation = result.get("recommendation") or {}
        outcome = recommendation.get("evaluation_outcome") or {}
        entry = {
            "status": "CURRENT" if current else "HISTORICAL",
            "baseline_identity": identity,
            "evaluation_context": dict(result.get("evaluation_context") or {}),
            "evaluation_identity": dict(result.get("evaluation_identity") or {}),
            "content_hash": ((result.get("raw_input") or {}).get("content_hash")),
            "item_name": (result.get("pob_parse") or {}).get("display_name"),
            # CORE-01's public outcome is authoritative; fall back only for
            # pre-outcome payloads retained in existing history.
            "verdict": outcome.get("verdict") or recommendation.get("verdict"),
            "result": result,
        }
        self._entries.append(entry)
        self._entries = self._entries[-self.limit :]

    def mark_historical(self, except_identity: str | None = None) -> None:
        for entry in self._entries:
            if except_identity is None or entry.get("baseline_identity") != except_identity:
                entry["status"] = "HISTORICAL"

    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def last(self) -> dict[str, Any] | None:
        return self._entries[-1] if self._entries else None
