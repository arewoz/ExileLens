from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from poe2value.errors import BaselineItemUnresolved
from poe2value.items.metadata import parse_lightweight_metadata
from poe2value.items.raw_input import ItemInputSource, RawItemInput
from poe2value.items.slots import ProductSlot, product_slot_to_pob


@dataclass(frozen=True)
class ResolvedBaselineItem:
    slot: str
    product_slot: str
    item_id: str | None
    name: str
    base_type: str
    rarity: str
    raw: str
    empty: bool
    item_set_id: str
    item_set_name: str
    loadout_id: str
    loadout_name: str
    fingerprint: str
    source: str = "pob_baseline"

    def display_name(self) -> str:
        if self.empty:
            return f"Empty {self.slot} Slot"
        return self.name or self.base_type or "Unknown item"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["display_name"] = self.display_name()
        return payload


@dataclass(frozen=True)
class ResolvedCandidateItem:
    name: str
    base_type: str
    rarity: str
    category: str
    pob_parsed: dict[str, Any]
    target_slot: str
    product_slot: str
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _identity_from_raw(raw: str) -> tuple[str, str, str]:
    if not (raw or "").strip():
        return "", "", ""
    meta = parse_lightweight_metadata(RawItemInput.from_text(raw, source=ItemInputSource.UNKNOWN))
    return str(meta.name or ""), str(meta.base_type or ""), str(meta.rarity or "").upper()


def _equipment_raw_for_slot(equipment: Any, pob_slot: str) -> tuple[bool, str, dict[str, Any] | None]:
    """Return (slot_known, raw_text, slot_summary)."""
    if equipment is None:
        return False, "", None
    if isinstance(equipment, dict):
        if pob_slot in equipment:
            value = equipment.get(pob_slot)
            if isinstance(value, dict):
                return True, str(value.get("raw") or ""), value
            return True, str(value or ""), None
        return False, "", None
    if isinstance(equipment, list):
        for entry in equipment:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("slot") or "") == pob_slot:
                raw = str(entry.get("raw") or entry.get("item_raw") or "")
                return True, raw, entry
        return False, "", None
    return False, "", None


def resolve_baseline_item(
    *,
    pob_slot: str,
    product_slot: str,
    baseline: dict[str, Any] | None,
    item_set_id: str = "",
    item_set_name: str = "",
    loadout_id: str = "",
    loadout_name: str = "",
    fingerprint: str = "",
) -> ResolvedBaselineItem:
    payload = baseline or {}
    slot_summary = payload.get("slot_item") if isinstance(payload.get("slot_item"), dict) else None
    known, raw, summary = _equipment_raw_for_slot(payload.get("equipment"), pob_slot)
    if slot_summary:
        summary = slot_summary
        if not raw:
            raw = str(slot_summary.get("raw") or "")
        known = True
        if slot_summary.get("equipped") is False:
            raw = raw if raw else ""
    equipment = payload.get("equipment")
    if (
        not known
        and isinstance(equipment, dict)
        and equipment
        and pob_slot not in equipment
        and not slot_summary
    ):
        raise BaselineItemUnresolved(
            f"PoB baseline item could not be resolved for slot {pob_slot}",
            {"slot": pob_slot, "product_slot": product_slot},
        )
    if not known:
        return ResolvedBaselineItem(
            slot=pob_slot,
            product_slot=product_slot,
            item_id=None,
            name="",
            base_type="",
            rarity="",
            raw="",
            empty=False,
            item_set_id=item_set_id,
            item_set_name=item_set_name,
            loadout_id=loadout_id,
            loadout_name=loadout_name,
            fingerprint=fingerprint or str(payload.get("fingerprint_hash") or ""),
        )
    empty = not (raw or "").strip()
    name, base_type, rarity = _identity_from_raw(raw)
    if summary:
        if summary.get("equipped") is False:
            empty = True
            raw = ""
            name, base_type, rarity = "", "", ""
        else:
            name = str(summary.get("name") or name)
            base_type = str(summary.get("base_name") or summary.get("base_type") or base_type)
            rarity = str(summary.get("rarity") or rarity).upper()
    item_id = None
    if summary and summary.get("item_id") is not None and not empty:
        item_id = str(summary.get("item_id"))
    return ResolvedBaselineItem(
        slot=pob_slot,
        product_slot=product_slot,
        item_id=item_id,
        name=name,
        base_type=base_type,
        rarity=rarity,
        raw=raw,
        empty=empty,
        item_set_id=item_set_id,
        item_set_name=item_set_name,
        loadout_id=loadout_id,
        loadout_name=loadout_name,
        fingerprint=fingerprint or str(payload.get("fingerprint_hash") or ""),
    )


def resolve_candidate_item(
    *,
    metadata: Any,
    pob_parse: dict[str, Any] | None,
    product_slot: str,
    pob_slot: str,
    raw_text: str = "",
) -> ResolvedCandidateItem:
    identity = (pob_parse or {}).get("identity") or {}
    meta = metadata if isinstance(metadata, dict) else getattr(metadata, "__dict__", {}) or {}
    name = str(meta.get("name") or (pob_parse or {}).get("display_name") or identity.get("name") or "")
    base = str(meta.get("base_type") or identity.get("base_name") or "")
    rarity = str(meta.get("rarity") or identity.get("rarity") or "").upper()
    category = str(meta.get("category") or (pob_parse or {}).get("category") or "")
    return ResolvedCandidateItem(
        name=name,
        base_type=base,
        rarity=rarity,
        category=category,
        pob_parsed=dict((pob_parse or {}).get("item") or identity or {}),
        target_slot=pob_slot,
        product_slot=product_slot,
        raw=raw_text,
    )


def empty_slot_label(pob_slot: str) -> str:
    return f"Empty {pob_slot} Slot"


def product_to_pob_or_self(product_slot: str) -> str:
    try:
        return product_slot_to_pob(ProductSlot(product_slot))
    except (ValueError, KeyError):
        return product_slot
