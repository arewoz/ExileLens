from __future__ import annotations

from typing import Any

from poe2value.config import fingerprint_hash


def tree_fingerprint_from_components(fingerprint: dict[str, Any] | None) -> str:
    components = fingerprint or {}
    focused = {
        "tree_nodes": components.get("tree_nodes"),
        "tree_set_index": components.get("tree_set_index"),
        "tree_set_title": components.get("tree_set_title"),
        "tree_version": components.get("tree_version"),
        "alloc_mode": components.get("alloc_mode"),
        "jewels": components.get("jewels"),
        "mastery": components.get("mastery"),
        "hash_overrides": components.get("hash_overrides"),
        "weapon_set_alloc": components.get("weapon_set_alloc"),
        "context": components.get("context"),
        "active_loadout": components.get("active_loadout"),
        "active_item_set_id": components.get("active_item_set_id"),
    }
    return fingerprint_hash(focused)


def path_identity(node_ids: list[int] | tuple[int, ...]) -> str:
    return ",".join(str(int(nid)) for nid in node_ids)
