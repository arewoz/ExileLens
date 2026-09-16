from __future__ import annotations

from collections import deque
from typing import Iterable

from poe2value.tree.models import EvalStatus, NodeType, PassiveTreeSnapshot, TreeNode

NON_TRAVERSABLE_TO = {NodeType.CLASS_START, NodeType.ASCEND_START}
TARGET_TYPES = {NodeType.NOTABLE, NodeType.KEYSTONE}


def is_supported_target(node: TreeNode) -> bool:
    return node.support == "SUPPORTED"


def _constraints_met(node: TreeNode, allocated: set[int]) -> bool:
    if not node.unlock_constraint:
        return True
    return all(cid in allocated for cid in node.unlock_constraint)


def _can_visit(current: TreeNode, other: TreeNode, *, is_root: bool, allocated: set[int]) -> bool:
    if current.type == NodeType.MASTERY:
        return False
    if other.type in NON_TRAVERSABLE_TO:
        return False
    if other.alloc_mode not in (0, current.alloc_mode) and not other.allocated:
        # Unallocated nodes start at alloc_mode 0; skip foreign weapon-set-only transitions.
        if other.alloc_mode != 0:
            return False
    if not _constraints_met(other, allocated) and not other.allocated:
        return False
    if current.ascendancy == other.ascendancy:
        return True
    if is_root and not other.ascendancy:
        return True
    return False


def shortest_path(snapshot: PassiveTreeSnapshot, target_id: int) -> tuple[list[int], int] | None:
    """Return unallocated node IDs from current tree to target, and point cost.

    Already allocated target → ([], 0). Unreachable → None.
    """
    target_id = int(target_id)
    target = snapshot.node(target_id)
    if target is None:
        return None
    allocated = snapshot.allocated_ids()
    if target_id in allocated:
        return [], 0

    visited: set[int] = set()
    prev: dict[int, int] = {}
    queue: deque[int] = deque()
    roots: set[int] = set()
    for nid in allocated:
        node = snapshot.node(nid)
        if node is None or node.alloc_mode != 0:
            continue
        visited.add(nid)
        queue.append(nid)
        roots.add(nid)

    found = False
    while queue:
        current_id = queue.popleft()
        if current_id == target_id:
            found = True
            break
        current = snapshot.node(current_id)
        if current is None:
            continue
        if current.unlock_constraint and not all(cid in allocated for cid in current.unlock_constraint):
            continue
        is_root = current_id in roots and current_id not in prev
        for oid in current.neighbors:
            other = snapshot.node(oid)
            if other is None or oid in visited:
                continue
            if not _can_visit(current, other, is_root=is_root, allocated=allocated):
                continue
            visited.add(oid)
            prev[oid] = current_id
            queue.append(oid)

    if not found:
        return None

    path: list[int] = []
    cursor = target_id
    while cursor in prev:
        path.append(cursor)
        cursor = prev[cursor]
        if cursor in allocated:
            break
    path.reverse()
    unallocated = [nid for nid in path if nid not in allocated]
    return unallocated, len(unallocated)


def unallocated_costs(snapshot: PassiveTreeSnapshot) -> dict[int, int]:
    """Point cost from the allocated tree to every reachable unallocated node. One BFS."""
    allocated = snapshot.allocated_ids()
    costs: dict[int, int] = {}
    visited: set[int] = set()
    queue: deque[tuple[int, int]] = deque()
    roots: set[int] = set()
    for nid in allocated:
        node = snapshot.node(nid)
        if node is None or node.alloc_mode != 0:
            continue
        visited.add(nid)
        queue.append((nid, 0))
        roots.add(nid)
    while queue:
        current_id, dist = queue.popleft()
        current = snapshot.node(current_id)
        if current is None:
            continue
        if current.unlock_constraint and not all(cid in allocated for cid in current.unlock_constraint):
            continue
        is_root = current_id in roots and dist == 0
        for oid in current.neighbors:
            other = snapshot.node(oid)
            if other is None or oid in visited:
                continue
            if not _can_visit(current, other, is_root=is_root, allocated=allocated):
                continue
            visited.add(oid)
            next_cost = dist if oid in allocated else dist + 1
            if oid not in allocated:
                costs[oid] = next_cost
            queue.append((oid, next_cost))
    return costs


def classify_target(snapshot: PassiveTreeSnapshot, node_id: int) -> EvalStatus:
    node = snapshot.node(int(node_id))
    if node is None:
        return EvalStatus.INVALID_NODE
    if not is_supported_target(node):
        return EvalStatus.UNSUPPORTED_SPECIAL_NODE
    if node.allocated:
        return EvalStatus.ALREADY_ALLOCATED
    resolved = shortest_path(snapshot, node.id)
    if resolved is None:
        return EvalStatus.UNREACHABLE
    return EvalStatus.VALID


def get_frontier_nodes(snapshot: PassiveTreeSnapshot) -> list[dict[str, object]]:
    """Unallocated supported nodes adjacent to the allocated (alloc_mode 0) tree."""
    allocated = snapshot.allocated_ids()
    seen: set[int] = set()
    frontier: list[dict[str, object]] = []
    for nid in sorted(allocated):
        node = snapshot.node(nid)
        if node is None or node.alloc_mode != 0:
            continue
        for oid in node.neighbors:
            if oid in seen or oid in allocated:
                continue
            other = snapshot.node(oid)
            if other is None:
                continue
            is_root = True
            if not _can_visit(node, other, is_root=is_root, allocated=allocated):
                continue
            seen.add(oid)
            status = classify_target(snapshot, oid)
            frontier.append(
                {
                    "node_id": oid,
                    "name": other.name,
                    "type": other.type.value,
                    "cost": 1 if status == EvalStatus.VALID else 0,
                    "path": [oid] if status == EvalStatus.VALID else [],
                    "status": status.value,
                    "support": other.support,
                }
            )
    frontier.sort(key=lambda row: (row["status"] != EvalStatus.VALID.value, int(row["node_id"])))
    return frontier


def get_targets_within_cost(
    snapshot: PassiveTreeSnapshot,
    max_points: int,
    *,
    types: Iterable[NodeType] | None = None,
) -> list[dict[str, object]]:
    max_points = max(0, int(max_points))
    wanted = set(types or TARGET_TYPES)
    results: list[dict[str, object]] = []
    for node in snapshot.nodes.values():
        if node.allocated or node.type not in wanted:
            continue
        if not is_supported_target(node):
            results.append(
                {
                    "node_id": node.id,
                    "name": node.name,
                    "type": node.type.value,
                    "cost": None,
                    "path": [],
                    "status": EvalStatus.UNSUPPORTED_SPECIAL_NODE.value,
                    "support": node.support,
                }
            )
            continue
        resolved = shortest_path(snapshot, node.id)
        if resolved is None:
            continue
        path, cost = resolved
        if cost == 0 or cost > max_points:
            continue
        results.append(
            {
                "node_id": node.id,
                "name": node.name,
                "type": node.type.value,
                "cost": cost,
                "path": path,
                "status": EvalStatus.VALID.value,
                "support": node.support,
            }
        )
    results.sort(key=lambda row: (int(row["cost"] or 0), int(row["node_id"])))
    return results
