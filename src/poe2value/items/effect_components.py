"""Semantic references for independently calculable PoB active effects.

Selectors are deliberately operational metadata.  ``semantic_id`` and
``cache_identity`` never depend on display-list position.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping


MAX_EFFECTS = 8


def _hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ComponentReference:
    """One PoB-native calculation component inside a socket group."""

    semantic_id: str
    group_id: str
    effect_id: str
    source_gem_id: str = ""
    source_gem_index: int | None = None
    owner: str = "PLAYER"
    stat_set_key: str = ""
    part_key: str = ""
    stage_count: int | None = None
    calculation_mode: str = "DIRECT"
    output_table: str = "mainOutput"
    group_selector: int | None = None
    effect_selector: int | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComponentReference":
        required = ("semantic_id", "group_id", "effect_id")
        if any(not isinstance(value.get(key), str) or not value.get(key) for key in required):
            raise ValueError("effect reference is missing semantic identity")
        stage = value.get("stage_count")
        if stage is not None and (isinstance(stage, bool) or not isinstance(stage, (int, float))):
            raise ValueError("effect reference has invalid stage_count")
        source_index = value.get("source_gem_index")
        if source_index is not None and (
            isinstance(source_index, bool)
            or not isinstance(source_index, (int, float))
            or int(source_index) < 1
        ):
            raise ValueError("effect reference has invalid source_gem_index")
        return cls(
            semantic_id=str(value["semantic_id"]),
            group_id=str(value["group_id"]),
            effect_id=str(value["effect_id"]),
            source_gem_id=str(value.get("source_gem_id") or ""),
            source_gem_index=int(source_index) if source_index is not None else None,
            owner=str(value.get("owner") or "PLAYER"),
            stat_set_key=str(value.get("stat_set_key") or ""),
            part_key=str(value.get("part_key") or ""),
            stage_count=int(stage) if stage is not None else None,
            calculation_mode=str(value.get("calculation_mode") or "DIRECT"),
            output_table=str(value.get("output_table") or "mainOutput"),
            group_selector=int(value["group_selector"]) if value.get("group_selector") is not None else None,
            effect_selector=int(value["effect_selector"]) if value.get("effect_selector") is not None else None,
        )

    @property
    def cache_identity(self) -> str:
        """Effect-qualified cache token; selectors are intentionally excluded."""
        return _hash(
            {
                "semantic_id": self.semantic_id,
                "group_id": self.group_id,
                "effect_id": self.effect_id,
                "source_gem_id": self.source_gem_id,
                "source_gem_index": self.source_gem_index,
                "owner": self.owner,
                "stat_set_key": self.stat_set_key,
                "part_key": self.part_key,
                "stage_count": self.stage_count,
                "calculation_mode": self.calculation_mode,
                "output_table": self.output_table,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "cache_identity": self.cache_identity}


def normalize_effect_catalog(payload: Mapping[str, Any], *, maximum: int = MAX_EFFECTS) -> dict[str, Any]:
    """Validate and bound a bridge catalog without manufacturing missing rows."""
    limit = max(1, min(int(maximum), MAX_EFFECTS))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    malformed = 0
    for raw in list(payload.get("effects") or [])[:limit]:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("reference"), Mapping):
            malformed += 1
            continue
        try:
            reference = ComponentReference.from_dict(raw["reference"])
        except (TypeError, ValueError):
            malformed += 1
            continue
        if reference.semantic_id in seen:
            malformed += 1
            continue
        seen.add(reference.semantic_id)
        rows.append({**dict(raw), "reference": reference.to_dict()})
    total = int(payload.get("total_effects") or len(list(payload.get("effects") or [])))
    return {
        **dict(payload),
        "effects": rows,
        "max_effects": limit,
        "total_effects": total,
        "truncated": bool(payload.get("truncated") or total > limit),
        "malformed_count": malformed,
    }
