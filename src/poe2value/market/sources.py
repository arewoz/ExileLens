from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from poe2value.items.raw_input import RawItemInput
from poe2value.items.slots import ProductSlot, product_slot_to_pob
from poe2value.market.models import (
    CandidateIdentity,
    CandidateListing,
    CandidateSourceCapabilities,
    ListingPrice,
)


class CandidateSource(Protocol):
    name: str
    capabilities: CandidateSourceCapabilities

    def search(self, intent: dict[str, Any], plan: dict[str, Any]) -> list[CandidateListing]:
        ...


def _listing_from_row(row: dict[str, Any], *, source: str, slot: str, pob_slot: str) -> CandidateListing | None:
    item_raw = str(row.get("item_raw") or "").strip()
    if not item_raw:
        return None
    raw = RawItemInput.from_text(item_raw)
    listing_id = str(row.get("listing_id") or row.get("id") or raw.content_hash[:16])
    price = ListingPrice.from_dict(row.get("price"))
    return CandidateListing(
        identity=CandidateIdentity(
            listing_id=listing_id,
            content_hash=raw.content_hash,
            source=source,
        ),
        slot=slot,
        pob_slot=pob_slot,
        item_raw=item_raw,
        price=price,
        label=row.get("label"),
        trade_url=row.get("trade_url"),
        metadata=dict(row.get("metadata") or {}),
    )


class FixtureCandidateSource:
    """Offline fixture adapter for tests and demos. No network."""

    name = "FixtureCandidateSource"

    def __init__(self, fixtures: list[dict[str, Any]] | None = None, corpus_path: str | Path | None = None) -> None:
        self.fixtures = list(fixtures or [])
        if corpus_path:
            self.fixtures.extend(self._load_corpus(corpus_path))

    @property
    def capabilities(self) -> CandidateSourceCapabilities:
        return CandidateSourceCapabilities(
            live_market=False,
            import_supported=False,
            fixture=True,
            network=False,
            trade_site_url_only=True,
            label="fixture",
        )

    @staticmethod
    def _load_corpus(path: str | Path) -> list[dict[str, Any]]:
        resolved = Path(path)
        if not resolved.exists():
            return []
        text = resolved.read_text(encoding="utf-8")
        if resolved.suffix.lower() == ".ndjson":
            rows = []
            for line in text.splitlines():
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
            return rows
        payload = json.loads(text)
        if isinstance(payload, list):
            return payload
        return list(payload.get("listings") or payload.get("candidates") or [])

    def search(self, intent: dict[str, Any], plan: dict[str, Any]) -> list[CandidateListing]:
        slot = str(intent.get("slot") or plan.get("slot") or "")
        pob_slot = str(intent.get("pob_slot") or plan.get("pob_slot") or "")
        if not pob_slot and slot:
            try:
                pob_slot = product_slot_to_pob(ProductSlot(slot))
            except KeyError:
                pob_slot = slot.replace("_", " ")
        matches = [row for row in self.fixtures if not row.get("slot") or row.get("slot") == slot]
        listings: list[CandidateListing] = []
        for row in matches:
            listing = _listing_from_row(row, source=self.name, slot=slot, pob_slot=pob_slot)
            if listing:
                listings.append(listing)
        return listings


class ImportedCandidateSource:
    """Manual JSON/NDJSON import — no network."""

    name = "ImportedCandidateSource"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._rows = FixtureCandidateSource._load_corpus(self.path)

    @property
    def capabilities(self) -> CandidateSourceCapabilities:
        return CandidateSourceCapabilities(
            live_market=False,
            import_supported=True,
            fixture=False,
            network=False,
            trade_site_url_only=True,
            label="import",
        )

    def search(self, intent: dict[str, Any], plan: dict[str, Any]) -> list[CandidateListing]:
        slot = str(intent.get("slot") or plan.get("slot") or "")
        pob_slot = str(intent.get("pob_slot") or plan.get("pob_slot") or "")
        if not pob_slot and slot:
            try:
                pob_slot = product_slot_to_pob(ProductSlot(slot))
            except KeyError:
                pob_slot = slot.replace("_", " ")
        listings: list[CandidateListing] = []
        for row in self._rows:
            if row.get("slot") and row.get("slot") != slot:
                continue
            listing = _listing_from_row(row, source=self.name, slot=slot, pob_slot=pob_slot)
            if listing:
                listings.append(listing)
        return listings
