from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from exilelens.build_sources import BuildSourceRef


class BuildState(str, Enum):
    NO_BUILD = "NO_BUILD"
    LOADING = "LOADING"
    RELOADING = "RELOADING"
    READY = "READY"
    FAILED = "FAILED"
    # Historical alias used by older diagnostics.
    ERROR = "FAILED"


@dataclass
class BuildInfo:
    path: str = ""
    source_ref: BuildSourceRef | None = None
    name: str = ""
    context: str = "MAP"
    state: BuildState = BuildState.NO_BUILD
    error_message: str = ""

    @property
    def is_ready(self) -> bool:
        return self.state == BuildState.READY and bool(self.source_ref or self.path)

    @property
    def is_failed(self) -> bool:
        return self.state == BuildState.FAILED

    @property
    def allows_tree_analysis(self) -> bool:
        return self.is_ready


@dataclass
class BaselineState:
    """Canonical PoB baseline identity. READY means loaded and recalculated."""

    state: BuildState = BuildState.NO_BUILD
    build_path: str = ""
    source_ref: BuildSourceRef | None = None
    source_revision: str = ""
    build_name: str = ""
    loadout_id: str = ""
    loadout_name: str = ""
    item_set_id: str | int = ""
    item_set_name: str = ""
    tree_set_id: str = ""
    tree_set_name: str = ""
    context: str = "MAP"
    generation: int = 0
    fingerprint: str = ""
    tree_fingerprint: str = ""
    equipment_fingerprint: str = ""
    error: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    equipped_items: dict[str, Any] = field(default_factory=dict)
    reload_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "build_path": self.build_path,
            "source_ref": self.source_ref.key if self.source_ref else "",
            "source_revision": self.source_revision,
            "build_name": self.build_name,
            "loadout_id": self.loadout_id,
            "loadout_name": self.loadout_name,
            "item_set_id": self.item_set_id,
            "item_set_name": self.item_set_name,
            "tree_set_id": self.tree_set_id,
            "tree_set_name": self.tree_set_name,
            "context": self.context,
            "generation": self.generation,
            "fingerprint": self.fingerprint,
            "tree_fingerprint": self.tree_fingerprint,
            "equipment_fingerprint": self.equipment_fingerprint,
            "error": self.error,
            "metrics": self.metrics,
            "equipped_items": self.equipped_items,
            "reload_ms": self.reload_ms,
        }

    def status_lines(self) -> list[str]:
        if self.state == BuildState.RELOADING:
            return ["RELOADING BUILD...", "PoB build changed on disk — reloading..."]
        if self.state == BuildState.LOADING:
            return ["LOADING BUILD..."]
        if self.state == BuildState.FAILED:
            return ["BASELINE FAILED", self.error or "unknown error"]
        if self.state == BuildState.NO_BUILD:
            return ["NO BUILD"]
        item = self.item_set_name or (
            f"Item Set {self.item_set_id}" if self.item_set_id not in ("", None) else "—"
        )
        tree = self.tree_set_name or (
            f"Tree Set {self.tree_set_id}" if self.tree_set_id not in ("", None) else "—"
        )
        fp = (self.fingerprint or "")[:8]
        return [
            f"Build       {self.build_name or '—'}",
            f"Loadout     {self.loadout_name or self.loadout_id or '—'}",
            f"Item Set    {item}",
            f"Tree Set    {tree}",
            f"Context     {self.context or '—'}",
            f"PoB State   {self.state.value}",
            f"Generation  {self.generation}",
            f"Fingerprint {fp}{'...' if self.fingerprint else ''}",
        ]
