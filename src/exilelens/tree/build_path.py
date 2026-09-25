"""PoB BUILD PATH — allocated target tree, independent of heatmap / value evals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from exilelens.tree.models import NodeType, PassiveTreeSnapshot, TreeNode

MIN_ANCHOR_SEPARATION = 80.0


@dataclass(frozen=True)
class BuildPathNode:
    node_id: int
    name: str
    x: float
    y: float
    node_type: str
    notable: bool
    keystone: bool
    unsupported: bool


@dataclass(frozen=True)
class BuildPathEdge:
    a: int
    b: int
    ax: float
    ay: float
    bx: float
    by: float


@dataclass
class BuildPathModel:
    nodes: list[BuildPathNode] = field(default_factory=list)
    edges: list[BuildPathEdge] = field(default_factory=list)
    allocated_count: int = 0
    skipped_no_coords: int = 0
    skipped_unsupported_safe: int = 0
    layout_identity: str = ""

    def node_ids(self) -> set[int]:
        return {n.node_id for n in self.nodes}


def layout_identity(snapshot: PassiveTreeSnapshot | None) -> str:
    if snapshot is None:
        return ""
    parts = []
    for node in sorted(snapshot.nodes.values(), key=lambda n: n.id):
        if node.x is None or node.y is None:
            continue
        parts.append(f"{node.id}:{round(float(node.x), 1)}:{round(float(node.y), 1)}")
    version = ""
    if isinstance(snapshot.tree_set, dict):
        version = str(snapshot.tree_set.get("treeVersion") or snapshot.tree_set.get("version") or "")
    return version + "|" + "|".join(parts)


def _usable_allocated(node: TreeNode) -> BuildPathNode | None:
    if not node.allocated:
        return None
    if node.x is None or node.y is None:
        return None
    unsupported = node.support != "SUPPORTED"
    return BuildPathNode(
        node_id=node.id,
        name=node.name or f"Node {node.id}",
        x=float(node.x),
        y=float(node.y),
        node_type=node.type.value,
        notable=node.type is NodeType.NOTABLE,
        keystone=node.type is NodeType.KEYSTONE,
        unsupported=unsupported,
    )


def build_path_from_snapshot(snapshot: PassiveTreeSnapshot | None) -> BuildPathModel:
    """Allocated PoB nodes + edges where both ends are allocated. No value calc."""
    if snapshot is None:
        return BuildPathModel()
    nodes: list[BuildPathNode] = []
    skipped_no_coords = 0
    skipped_unsupported_safe = 0
    for node in snapshot.nodes.values():
        if not node.allocated:
            continue
        mapped = _usable_allocated(node)
        if mapped is None:
            skipped_no_coords += 1
            continue
        if mapped.unsupported:
            skipped_unsupported_safe += 1
        nodes.append(mapped)
    allocated_ids = {n.node_id for n in nodes}
    coord = {n.node_id: (n.x, n.y) for n in nodes}
    edges: list[BuildPathEdge] = []
    seen: set[tuple[int, int]] = set()
    pairs: Iterable[tuple[int, int]] = snapshot.edges or []
    if not pairs:
        pairs = []
        for node in snapshot.nodes.values():
            for nb in node.neighbors:
                pairs.append((node.id, int(nb)))
    for a, b in pairs:
        a_id, b_id = int(a), int(b)
        if a_id not in allocated_ids or b_id not in allocated_ids:
            continue
        key = (a_id, b_id) if a_id < b_id else (b_id, a_id)
        if key in seen:
            continue
        seen.add(key)
        ax, ay = coord[a_id]
        bx, by = coord[b_id]
        edges.append(BuildPathEdge(a=a_id, b=b_id, ax=ax, ay=ay, bx=bx, by=by))
    nodes.sort(key=lambda n: n.node_id)
    edges.sort(key=lambda e: (e.a, e.b))
    return BuildPathModel(
        nodes=nodes,
        edges=edges,
        allocated_count=len(nodes),
        skipped_no_coords=skipped_no_coords,
        skipped_unsupported_safe=skipped_unsupported_safe,
        layout_identity=layout_identity(snapshot),
    )


def tree_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def anchors_too_close(a: tuple[float, float], b: tuple[float, float], *, minimum: float = MIN_ANCHOR_SEPARATION) -> bool:
    return tree_distance(a, b) < minimum
