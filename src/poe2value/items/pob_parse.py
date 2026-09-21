from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from poe2value.items.metadata import LightweightItemMetadata
from poe2value.items.raw_input import RawItemInput


@dataclass
class PobParseResult:
    parse_ok: bool
    identity: dict[str, Any]
    category: str | None
    display_name: str
    valid_slot_families: list[str]
    primary_slot: str | None
    compatible_slots: list[str]
    weapon_layout: str | None
    weapon_layout_reason: str | None
    item: dict[str, Any]
    mismatches: list[dict[str, str]]
    # M1.3: only meaningful when `item["type"] == "Jewel"`; how many allocated
    # jewel sockets this build has, regardless of compatibility with this
    # particular candidate. Lets callers distinguish "no allocated sockets at
    # all" from "sockets exist but none accept this jewel family".
    allocated_jewel_socket_count: int | None = None
    # M1.3: how many of those allocated sockets were excluded because their
    # CURRENT jewel affects passive-tree connectivity for other allocated
    # nodes (e.g. "From Nothing" -- see bridge.lua's
    # `jewel_socket_is_connectivity_risky`), and so cannot be safely
    # round-tripped through the ordinary jewel-swap transaction. Always 0 for
    # a non-Jewel item.
    excluded_connectivity_risky_socket_count: int | None = None

    @classmethod
    def from_engine(cls, engine_result: dict[str, Any], metadata: LightweightItemMetadata) -> PobParseResult:
        mismatches: list[dict[str, str]] = []
        identity = engine_result.get("identity") or {}
        if metadata.rarity and identity.get("rarity") and metadata.rarity != identity.get("rarity"):
            mismatches.append(
                {
                    "field": "rarity",
                    "lightweight": metadata.rarity,
                    "pob": str(identity.get("rarity")),
                }
            )
        if metadata.base_type and identity.get("base_name") and metadata.base_type != identity.get("base_name"):
            mismatches.append(
                {
                    "field": "base_type",
                    "lightweight": metadata.base_type,
                    "pob": str(identity.get("base_name")),
                }
            )
        return cls(
            parse_ok=bool(engine_result.get("parse_ok")),
            identity=identity,
            category=engine_result.get("category"),
            display_name=engine_result.get("display_name") or identity.get("name") or "",
            valid_slot_families=list(engine_result.get("valid_slot_families") or []),
            primary_slot=engine_result.get("primary_slot"),
            compatible_slots=list(engine_result.get("compatible_slots") or []),
            weapon_layout=engine_result.get("weapon_layout"),
            weapon_layout_reason=engine_result.get("weapon_layout_reason"),
            item=dict(engine_result.get("item") or {}),
            mismatches=mismatches,
            allocated_jewel_socket_count=engine_result.get("allocated_jewel_socket_count"),
            excluded_connectivity_risky_socket_count=engine_result.get("excluded_connectivity_risky_socket_count"),
        )


def parse_item_with_pob(engine, raw: RawItemInput, metadata: LightweightItemMetadata) -> PobParseResult:
    result = engine.parse_item(raw.raw_text)
    return PobParseResult.from_engine(result, metadata)