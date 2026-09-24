from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    SMALL = "SMALL"
    NOTABLE = "NOTABLE"
    KEYSTONE = "KEYSTONE"
    SOCKET = "SOCKET"
    CLASS_START = "CLASS_START"
    ASCEND_START = "ASCEND_START"
    MASTERY = "MASTERY"
    OTHER = "OTHER"


class EvalStatus(str, Enum):
    VALID = "VALID"
    UNREACHABLE = "UNREACHABLE"
    ALREADY_ALLOCATED = "ALREADY_ALLOCATED"
    UNSUPPORTED_SPECIAL_NODE = "UNSUPPORTED_SPECIAL_NODE"
    INVALID_NODE = "INVALID_NODE"


class RankingMode(str, Enum):
    TOTAL = "total"
    EFFICIENCY = "efficiency"


class HeatmapMetric(str, Enum):
    VALUE_PER_POINT = "value_per_point"
    TOTAL_VALUE = "total_value"


class HeatmapSource(str, Enum):
    MY_BUILD_VALUE = "MY_BUILD_VALUE"


class AnalysisScope(str, Enum):
    SNAPSHOT = "snapshot"
    FRONTIER = "frontier"
    RADIUS_3 = "radius3"
    RADIUS_5 = "radius5"
    VISIBLE = "visible"


class HeatmapBand(str, Enum):
    UNKNOWN = "UNKNOWN"
    PENDING = "PENDING"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    LOW = "LOW"
    USEFUL = "USEFUL"
    HIGH = "HIGH"
    EXCEPTIONAL = "EXCEPTIONAL"


@dataclass(frozen=True)
class TreeNode:
    id: int
    name: str
    type: NodeType
    allocated: bool
    neighbors: tuple[int, ...]
    x: float | None = None
    y: float | None = None
    pob_type: str = "Normal"
    alloc_mode: int = 0
    ascendancy: str | None = None
    is_attribute: bool = False
    support: str = "SUPPORTED"
    support_reason: str | None = None
    path_dist: int | None = None
    unlock_constraint: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["type"] = self.type.value
        payload["neighbors"] = list(self.neighbors)
        payload["unlock_constraint"] = list(self.unlock_constraint)
        return payload


@dataclass(frozen=True)
class TreeBaseline:
    build_path: str
    build_name: str
    loadout: str
    tree_set: str
    item_set: str
    context: str
    profile: str
    generation: int
    fingerprint: str
    tree_fingerprint: str

    def identity_key(self) -> str:
        return "|".join(
            [
                self.fingerprint,
                self.tree_fingerprint,
                self.build_path,
                self.loadout,
                self.tree_set,
                self.item_set,
                self.context,
                str(self.generation),
            ]
        )

    def raw_cache_prefix(self) -> str:
        """Raw PoB tree evals are valid across profile-only changes."""
        return "|".join(
            [
                self.fingerprint,
                self.tree_fingerprint,
                self.build_path,
                self.loadout,
                self.tree_set,
                self.item_set,
                self.context,
                str(self.generation),
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_tree_stale(result_baseline: TreeBaseline | dict[str, Any], current: TreeBaseline) -> bool:
    if isinstance(result_baseline, dict):
        result_baseline = TreeBaseline(**{k: result_baseline[k] for k in TreeBaseline.__dataclass_fields__})
    return (
        result_baseline.fingerprint != current.fingerprint
        or result_baseline.tree_fingerprint != current.tree_fingerprint
        or result_baseline.generation != current.generation
        or result_baseline.context != current.context
        or result_baseline.build_path != current.build_path
        or result_baseline.loadout != current.loadout
        or result_baseline.tree_set != current.tree_set
        or result_baseline.item_set != current.item_set
    )


@dataclass
class PassiveTreeSnapshot:
    baseline: TreeBaseline
    nodes: dict[int, TreeNode]
    edges: list[tuple[int, int]]
    class_name: str | None = None
    ascendancy: str | None = None
    tree_set: dict[str, Any] = field(default_factory=dict)
    jewels: list[dict[str, Any]] = field(default_factory=list)
    mastery: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def node(self, node_id: int) -> TreeNode | None:
        return self.nodes.get(int(node_id))

    def allocated_ids(self) -> set[int]:
        return {nid for nid, node in self.nodes.items() if node.allocated}

    def to_graph_export(self) -> dict[str, Any]:
        return {
            "tree_set": self.tree_set,
            "class": self.class_name,
            "ascendancy": self.ascendancy,
            "baseline": self.baseline.to_dict(),
            "stats": self.stats,
            "jewels": self.jewels,
            "nodes": [node.to_dict() for node in sorted(self.nodes.values(), key=lambda n: n.id)],
            "edges": [list(edge) for edge in self.edges],
        }


def parse_node(raw: dict[str, Any]) -> TreeNode:
    node_id = int(raw["id"])
    type_name = str(raw.get("type") or "SMALL")
    try:
        ntype = NodeType(type_name)
    except ValueError:
        ntype = NodeType.OTHER
    neighbors = tuple(int(n) for n in (raw.get("neighbors") or []))
    constraints = tuple(int(n) for n in (raw.get("unlock_constraint") or []))
    path_dist = raw.get("path_dist")
    return TreeNode(
        id=node_id,
        name=str(raw.get("name") or ""),
        type=ntype,
        allocated=bool(raw.get("allocated")),
        neighbors=neighbors,
        x=float(raw["x"]) if raw.get("x") is not None else None,
        y=float(raw["y"]) if raw.get("y") is not None else None,
        pob_type=str(raw.get("pob_type") or "Normal"),
        alloc_mode=int(raw.get("alloc_mode") or 0),
        ascendancy=raw.get("ascendancy"),
        is_attribute=bool(raw.get("is_attribute")),
        support=str(raw.get("support") or "SUPPORTED"),
        support_reason=raw.get("support_reason"),
        path_dist=int(path_dist) if path_dist is not None else None,
        unlock_constraint=constraints,
    )


def snapshot_from_payload(
    payload: dict[str, Any],
    *,
    baseline: TreeBaseline,
) -> PassiveTreeSnapshot:
    parsed = [parse_node(raw) for raw in payload.get("nodes") or []]
    nodes = {node.id: node for node in parsed}
    edges = []
    for edge in payload.get("edges") or []:
        if len(edge) >= 2:
            edges.append((int(edge[0]), int(edge[1])))
    return PassiveTreeSnapshot(
        baseline=baseline,
        nodes=nodes,
        edges=edges,
        class_name=payload.get("class"),
        ascendancy=payload.get("ascendancy"),
        tree_set=dict(payload.get("tree_set") or {}),
        jewels=list(payload.get("jewels") or []),
        mastery=list(payload.get("mastery") or []),
        stats=dict(payload.get("stats") or {}),
    )
