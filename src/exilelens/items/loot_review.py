"""Loot Review Mode — session ranking and categories."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from exilelens.items.evaluation_outcome import VERDICT_ORDER, authoritative_public_verdict


class LootCategory(str, Enum):
    STRONG_UPGRADES = "STRONG UPGRADES"
    UPGRADES = "UPGRADES"
    BUILD_REPAIRS = "BUILD REPAIRS"
    TRADEOFFS = "TRADEOFFS"
    DOWNGRADES = "DOWNGRADES"
    UNCERTAIN = "UNCERTAIN"


_UPGRADE_VERDICTS = {
    "STRONG_UPGRADE",
    "CLEAR_UPGRADE",
    "OFFENSE_UPGRADE",
    "DEFENSE_UPGRADE",
}


@dataclass
class LootReviewEntry:
    entry_id: str
    content_hash: str
    item_name: str
    verdict: str
    category: str
    best_slot: str
    rating: float | None
    baseline_identity: str
    recorded_at: float
    result: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "content_hash": self.content_hash,
            "item_name": self.item_name,
            "verdict": self.verdict,
            "category": self.category,
            "best_slot": self.best_slot,
            "rating": self.rating,
            "baseline_identity": self.baseline_identity,
            "recorded_at": self.recorded_at,
        }


@dataclass
class LootReviewSession:
    active: bool = False
    started_at: float | None = None
    baseline_identity: str = ""
    entries: list[LootReviewEntry] = field(default_factory=list)

    def start(self, *, baseline_identity: str) -> None:
        if self.active and self.baseline_identity and baseline_identity != self.baseline_identity:
            self.entries.clear()
        self.active = True
        self.started_at = time.time()
        self.baseline_identity = baseline_identity

    def stop(self) -> None:
        self.active = False

    def record(self, result: dict[str, Any], *, baseline_identity: str) -> LootReviewEntry | None:
        if not self.active:
            return None
        if baseline_identity != self.baseline_identity:
            self.entries.clear()
            self.baseline_identity = baseline_identity
            self.started_at = time.time()
        recommendation = result.get("recommendation") or {}
        decision = result.get("decision") or {}
        verdict = authoritative_public_verdict(recommendation)
        category = categorize_loot(verdict, build_repair=bool(decision.get("build_repair")))
        content_hash = str((result.get("raw_input") or {}).get("content_hash") or "")
        entry = LootReviewEntry(
            entry_id=f"{content_hash[:12]}-{int(time.time() * 1000)}",
            content_hash=content_hash,
            item_name=str((result.get("pob_parse") or {}).get("display_name") or "Item"),
            verdict=verdict,
            category=category.value,
            best_slot=str((result.get("best_slot") or {}).get("label") or ""),
            rating=((recommendation.get("value") or {}).get("rating")),
            baseline_identity=baseline_identity,
            recorded_at=time.time(),
            result=result,
        )
        self.entries = [item for item in self.entries if item.content_hash != content_hash]
        self.entries.append(entry)
        return entry

    def ranked(self) -> list[LootReviewEntry]:
        return sorted(
            self.entries,
            key=lambda item: (VERDICT_ORDER.get(item.verdict, 99), -(item.rating or 0), item.item_name),
        )

    def by_category(self) -> dict[str, list[LootReviewEntry]]:
        grouped: dict[str, list[LootReviewEntry]] = {cat.value: [] for cat in LootCategory}
        for entry in self.ranked():
            grouped.setdefault(entry.category, []).append(entry)
        return grouped

    def best_per_slot(self) -> dict[str, LootReviewEntry]:
        best: dict[str, LootReviewEntry] = {}
        for entry in self.ranked():
            slot = str((entry.result.get("best_slot") or {}).get("pob_slot") or entry.best_slot or "unknown")
            if slot not in best:
                best[slot] = entry
        return best


def categorize_loot(verdict: str, *, build_repair: bool = False) -> LootCategory:
    if verdict in {"UNCERTAIN", "UNSUPPORTED", "NOT_EVALUATED"}:
        return LootCategory.UNCERTAIN
    if build_repair:
        return LootCategory.BUILD_REPAIRS
    if verdict in {"STRONG_UPGRADE", "MEANINGFUL_UPGRADE"}:
        return LootCategory.STRONG_UPGRADES
    if verdict in _UPGRADE_VERDICTS or verdict == "MINOR_UPGRADE":
        return LootCategory.UPGRADES
    if verdict == "TRADEOFF":
        return LootCategory.TRADEOFFS
    if verdict in {"DOWNGRADE", "STRONG_DOWNGRADE", "MINOR_DOWNGRADE", "MEANINGFUL_DOWNGRADE", "NOT_VIABLE"}:
        return LootCategory.DOWNGRADES
    return LootCategory.TRADEOFFS
