"""Pin & compare up to 4 candidates plus CURRENT."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from poe2value.items.evaluation_outcome import VERDICT_ORDER, authoritative_public_verdict

MAX_PINNED = 4
PIN_LABELS = ("A", "B", "C", "D")
STALE_BUILD_CHANGED = "BUILD CHANGED"


@dataclass
class CompareEntry:
    entry_id: str
    content_hash: str
    item_name: str
    baseline_identity: str
    result: dict[str, Any]
    pinned: bool = True
    stale: bool = False
    stale_reason: str = ""
    pin_label: str = ""
    is_current: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "content_hash": self.content_hash,
            "item_name": self.item_name,
            "baseline_identity": self.baseline_identity,
            "pinned": self.pinned,
            "stale": self.stale,
            "stale_reason": self.stale_reason,
            "pin_label": self.pin_label,
            "is_current": self.is_current,
            "compare_active": self.pinned and not self.is_current and not self.stale,
            "verdict": authoritative_public_verdict(self.result.get("recommendation") or {}),
            "best_slot": (self.result.get("best_slot") or {}).get("label"),
            "rating": ((self.result.get("recommendation") or {}).get("value") or {}).get("rating"),
        }


@dataclass
class PinCompareState:
    baseline_identity: str = ""
    entries: list[CompareEntry] = field(default_factory=list)

    def pinned_count(self) -> int:
        return len([item for item in self.entries if item.pinned and not item.is_current])

    def can_pin_more(self) -> bool:
        return self.pinned_count() < MAX_PINNED

    def _next_pin_label(self) -> str | None:
        used = {item.pin_label for item in self.entries if item.pinned and not item.is_current and item.pin_label}
        for label in PIN_LABELS:
            if label not in used:
                return label
        return None

    def pin(self, entry_id: str, result: dict[str, Any], *, baseline_identity: str) -> CompareEntry | None:
        if baseline_identity and self.baseline_identity and baseline_identity != self.baseline_identity:
            self.clear()
        self.baseline_identity = baseline_identity
        content_hash = str((result.get("raw_input") or {}).get("content_hash") or entry_id)
        for existing in self.entries:
            if existing.content_hash == content_hash and not existing.is_current:
                existing.result = result
                existing.stale = False
                existing.stale_reason = ""
                existing.item_name = str((result.get("pob_parse") or {}).get("display_name") or existing.item_name)
                if not existing.pin_label:
                    existing.pin_label = self._next_pin_label() or existing.pin_label
                return existing
        if not self.can_pin_more():
            return None
        label = self._next_pin_label()
        if label is None:
            return None
        entry = CompareEntry(
            entry_id=entry_id,
            content_hash=content_hash,
            item_name=str((result.get("pob_parse") or {}).get("display_name") or "Item"),
            baseline_identity=baseline_identity,
            result=result,
            pin_label=label,
        )
        self.entries.append(entry)
        return entry

    def unpin(self, entry_id: str) -> None:
        self.entries = [item for item in self.entries if item.entry_id != entry_id]

    def set_current(self, result: dict[str, Any], *, baseline_identity: str) -> None:
        if baseline_identity and self.baseline_identity and baseline_identity != self.baseline_identity:
            self.clear()
        self.baseline_identity = baseline_identity
        self.entries = [item for item in self.entries if not item.is_current]
        self.entries.append(
            CompareEntry(
                entry_id="CURRENT",
                content_hash="CURRENT",
                item_name=str((result.get("recommendation") or {}).get("baseline_item", {}).get("display_name") or "Current"),
                baseline_identity=baseline_identity,
                result=result,
                pinned=False,
                is_current=True,
            )
        )

    def mark_stale(self, baseline_identity: str | None = None, *, reason: str = STALE_BUILD_CHANGED) -> None:
        for entry in self.entries:
            if baseline_identity is None or entry.baseline_identity != baseline_identity:
                entry.stale = True
                entry.stale_reason = reason

    def clear(self) -> None:
        self.baseline_identity = ""
        self.entries.clear()

    def compare_table(self, *, profile: str = "BALANCED") -> list[dict[str, Any]]:
        rows = []
        for entry in self.entries:
            rec = entry.result.get("recommendation") or {}
            value = rec.get("value") or {}
            label = entry.pin_label
            display_name = entry.item_name
            if label and not entry.is_current:
                display_name = f"{label} — {entry.item_name}"
            rows.append(
                {
                    **entry.to_dict(),
                    "display_name": display_name,
                    "profile": profile,
                    "slot": rec.get("pob_slot"),
                    "score_delta": value.get("score_delta"),
                }
            )
        rows.sort(
            key=lambda row: (
                0 if row.get("is_current") else 1,
                str(row.get("pin_label") or ""),
                -(row.get("rating") or 0),
                row.get("item_name") or "",
            )
        )
        return rows

    def winner(self) -> CompareEntry | None:
        candidates = [item for item in self.entries if not item.is_current and not item.stale]
        if not candidates:
            return None
        def key(item: CompareEntry) -> tuple[int, float]:
            recommendation = item.result.get("recommendation") or {}
            verdict = authoritative_public_verdict(recommendation)
            rating = float((recommendation.get("value") or {}).get("rating") or 0)
            return VERDICT_ORDER.get(verdict, 99), -rating

        return min(candidates, key=key)


def _entry_compare_key(entry: CompareEntry, profile: str) -> tuple[str, str, str, str]:
    rec = entry.result.get("recommendation") or {}
    fingerprint = str(((rec.get("baseline") or {}).get("fingerprint_hash")) or "")
    slot = str(
        rec.get("pob_slot")
        or rec.get("product_slot")
        or (entry.result.get("best_slot") or {}).get("label")
        or ""
    ).upper()
    entry_profile = str(entry.result.get("value_profile") or profile).upper()
    context = str((entry.result.get("request_meta") or {}).get("context") or "").upper()
    return fingerprint, slot, entry_profile, context


def entries_comparable(entries: list[CompareEntry], *, profile: str) -> bool:
    pinned = [item for item in entries if item.pinned and not item.is_current and not item.stale]
    if len(pinned) < 2:
        return False
    keys = [_entry_compare_key(item, profile) for item in pinned]
    if any(not key[0] or not key[1] for key in keys):
        return False
    first = keys[0]
    return all(key == first for key in keys[1:])


def best_current_pin(state: PinCompareState, *, profile: str = "BALANCED") -> CompareEntry | None:
    if not entries_comparable(state.entries, profile=profile):
        return None
    return state.winner()


def build_compare_summary(state: PinCompareState, *, profile: str = "BALANCED") -> dict[str, Any]:
    pinned = [item for item in state.entries if item.pinned and not item.is_current and not item.stale]
    rows: list[dict[str, Any]] = []
    for entry in sorted(pinned, key=lambda item: str(item.pin_label or "")):
        rec = entry.result.get("recommendation") or {}
        value = rec.get("value") or {}
        rows.append(
            {
                "pin_label": entry.pin_label,
                "item_name": entry.item_name,
                "rating": value.get("rating"),
                "verdict": authoritative_public_verdict(rec),
                "display_name": f"{entry.pin_label} — {entry.item_name}" if entry.pin_label else entry.item_name,
            }
        )
    comparable = entries_comparable(state.entries, profile=profile)
    winner_entry = best_current_pin(state, profile=profile) if comparable else None
    best_current = None
    if winner_entry is not None:
        winner_verdict = authoritative_public_verdict(winner_entry.result.get("recommendation") or {})
        if winner_verdict not in {"UNCERTAIN", "UNSUPPORTED", "NOT_EVALUATED"}:
            best_current = {
                "pin_label": winner_entry.pin_label,
                "item_name": winner_entry.item_name,
                "label": f"BEST CURRENT OPTION: {winner_entry.pin_label}",
            }
    return {
        "title": "PINNED ITEMS",
        "rows": rows,
        "comparable": comparable,
        "best_current_option": best_current,
    }
