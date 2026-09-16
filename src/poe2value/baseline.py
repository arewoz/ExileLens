"""Canonical loadout / item-set / tree-set identity for every product surface."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


def canonical_item_set_id(value: Any) -> str:
    """Normalize PoB item-set keys so numeric 3 and string '3' are the same identity."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if not text:
        return ""
    if text.lstrip("-").isdigit():
        return str(int(text))
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer() and "e" not in text.lower() and "E" not in text:
        return str(int(number))
    return text


def item_set_wire_value(item_set_id: Any) -> int | str:
    """JSON value sent to Lua: numeric IDs stay numbers so PoB table keys match."""
    canonical = canonical_item_set_id(item_set_id)
    if canonical == "":
        return ""
    if canonical.lstrip("-").isdigit():
        return int(canonical)
    return canonical


def display_item_set_name(title: Any, item_set_id: Any) -> str:
    """Friendly label. Missing title does not mean the set is invalid."""
    text = str(title or "").strip()
    lowered = text.lower()
    if text and lowered not in {"unknown", "unknown item set"}:
        return text
    canonical = canonical_item_set_id(item_set_id)
    return f"Item Set {canonical}" if canonical else "Item Set"


def _catalog_entries(catalog: Any) -> list[Mapping[str, Any]]:
    if isinstance(catalog, Mapping) and "item_sets" in catalog:
        catalog = catalog.get("item_sets")
    if not catalog:
        return []
    return [entry for entry in catalog if isinstance(entry, Mapping)]


def normalize_item_set_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    canonical = canonical_item_set_id(entry.get("id"))
    raw_title = entry.get("title") if "title" in entry else entry.get("name")
    payload = dict(entry)
    payload["id"] = canonical
    payload["title_raw"] = "" if raw_title is None else str(raw_title)
    payload["title"] = display_item_set_name(raw_title, canonical)
    payload["name"] = payload["title"]
    return payload


def normalize_item_sets_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    entries = [normalize_item_set_entry(entry) for entry in _catalog_entries(data)]
    data["item_sets"] = entries
    active = canonical_item_set_id(data.get("active_id"))
    data["active_id"] = active
    if active:
        known = {entry["id"]: entry for entry in entries}
        match = known.get(active)
        data["active_name"] = match["title"] if match else display_item_set_name("", active)
        data["active_valid"] = (not entries) or (active in known)
    else:
        data["active_name"] = ""
        data["active_valid"] = True
    return data


@dataclass(frozen=True)
class ResolvedItemSet:
    id: str
    name: str
    valid: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_item_set(catalog: Any, item_set_id: Any) -> ResolvedItemSet:
    """Identity is valid when the id exists (or catalog is unknown). Name is display-only."""
    canonical = canonical_item_set_id(item_set_id)
    entries = [normalize_item_set_entry(entry) for entry in _catalog_entries(catalog)]
    if not canonical:
        return ResolvedItemSet(id="", name="", valid=True)
    known = {entry["id"]: entry for entry in entries}
    match = known.get(canonical)
    if match is not None:
        return ResolvedItemSet(id=canonical, name=str(match["title"]), valid=True)
    if not entries:
        return ResolvedItemSet(id=canonical, name=display_item_set_name("", canonical), valid=True)
    return ResolvedItemSet(id=canonical, name=display_item_set_name("", canonical), valid=False)


@dataclass(frozen=True)
class ResolvedBaseline:
    build_path: str = ""
    build_name: str = ""
    loadout_id: str = ""
    loadout_name: str = ""
    item_set_id: str = ""
    item_set_name: str = ""
    tree_set_id: str = ""
    tree_set_name: str = ""
    context: str = "MAP"
    fingerprint: str = ""
    item_set_valid: bool = True

    def identity_key(self) -> str:
        return "|".join(
            [
                self.fingerprint,
                self.build_path,
                self.loadout_id or self.loadout_name,
                self.item_set_id,
                self.tree_set_id or self.tree_set_name,
                self.context,
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def apply_engine_identity(engine: Any, *, loadout: str = "", item_set: str = "") -> None:
    """Switch PoB to the resolved loadout / item set. Shared by item eval, 5A, and Tree Coach."""
    if loadout and hasattr(engine, "set_active_loadout"):
        engine.set_active_loadout(loadout)
    if item_set and hasattr(engine, "set_active_item_set"):
        engine.set_active_item_set(item_set)
