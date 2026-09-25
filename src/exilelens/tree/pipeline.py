from __future__ import annotations

import time
from typing import Any, Callable

from exilelens.items.value_layer import parse_profile
from exilelens.tree.cache import TreeEvalCache
from exilelens.tree.contract import next_passive_recommendation, tree_heatmap_data
from exilelens.tree.graph import get_frontier_nodes, get_targets_within_cost
from exilelens.tree.models import AnalysisScope, RankingMode
from exilelens.tree.mutations import TreeProbeEngine, load_tree_snapshot, primary_from_engine
from exilelens.tree.ranking import rank_next_passive_points, rank_targets

YieldFn = Callable[[], bool]
ProgressFn = Callable[[dict[str, Any]], None]


def _heatmap_rows(snapshot, *blocks: dict[str, Any] | None) -> list[dict[str, Any]]:
    seen: set[int] = set()
    heatmap = []
    for block in blocks:
        if not block:
            continue
        for row in block.get("recommendations") or []:
            nid = row.get("node_id")
            if nid is None or int(nid) in seen:
                continue
            seen.add(int(nid))
            node = snapshot.node(int(nid))
            heatmap.append(tree_heatmap_data(row, node.to_dict() if node else row))
    return heatmap


def _graph_bundle(snapshot) -> dict[str, Any]:
    export = snapshot.to_graph_export()
    export["frontier"] = get_frontier_nodes(snapshot)
    export["targets_radius3"] = get_targets_within_cost(snapshot, 3)
    export["targets_radius5"] = get_targets_within_cost(snapshot, 5)
    return export


def analyze_tree(
    engine: Any,
    *,
    build_path: str,
    context: str = "MAP",
    profile: str = "BALANCED",
    generation: int = 0,
    loadout: str = "",
    item_set: str = "",
    max_points: int = 3,
    include_radius5: bool = False,
    scope: str | None = None,
    visible_node_ids: list[int] | None = None,
    cache: TreeEvalCache | None = None,
    should_yield: YieldFn | None = None,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    selected = parse_profile(profile)
    cache = cache or TreeEvalCache()
    probes = TreeProbeEngine(engine, cache=cache)
    snapshot = load_tree_snapshot(
        engine,
        build_path=build_path,
        context=context,
        profile=selected.value,
        generation=generation,
        loadout=loadout,
        item_set=item_set,
    )
    primary_field, primary_confidence = primary_from_engine(engine)
    graph = _graph_bundle(snapshot)

    def progress(stage: str, **extra: Any) -> None:
        if on_progress:
            on_progress({"stage": stage, **extra})

    next_passive = None
    nearby = None
    radius5 = None
    visible = {int(n) for n in visible_node_ids} if visible_node_ids is not None else None
    chosen = scope or "legacy"

    if chosen == AnalysisScope.SNAPSHOT.value:
        elapsed = (time.perf_counter() - started) * 1000
        return {
            "kind": "tree_snapshot",
            "scope": AnalysisScope.SNAPSHOT.value,
            "baseline": snapshot.baseline.to_dict(),
            "tree_set": snapshot.tree_set,
            "stats": snapshot.stats,
            "graph": graph,
            "nodes": graph["nodes"],
            "edges": graph["edges"],
            "performance": {"elapsed_ms": round(elapsed, 2), "cache": cache.stats()},
            "pob_recalc": False,
        }

    common = dict(
        profile=selected,
        primary_field=primary_field,
        primary_confidence=primary_confidence,
        should_yield=should_yield,
        on_progress=on_progress,
    )

    if chosen in {"legacy", AnalysisScope.FRONTIER.value, AnalysisScope.VISIBLE.value}:
        progress("frontier")
        next_passive = rank_next_passive_points(
            snapshot,
            probes,
            node_ids=visible if chosen == AnalysisScope.VISIBLE.value else None,
            prefer_node_ids=visible if chosen == AnalysisScope.FRONTIER.value else None,
            visible_only=chosen == AnalysisScope.VISIBLE.value,
            **common,
        )
    if chosen in {"legacy", AnalysisScope.RADIUS_3.value}:
        pts = int(max_points) if chosen == "legacy" else 3
        progress("targets", max_points=pts)
        nearby = rank_targets(snapshot, probes, max_points=pts, mode=RankingMode.TOTAL, scope="radius3", **common)
    if chosen == AnalysisScope.RADIUS_5.value or (chosen == "legacy" and include_radius5 and int(max_points) < 5):
        progress("targets", max_points=5)
        radius5 = rank_targets(snapshot, probes, max_points=5, mode=RankingMode.TOTAL, scope="radius5", **common)
        if chosen == AnalysisScope.RADIUS_5.value:
            nearby = radius5
            radius5 = None
    if chosen == AnalysisScope.VISIBLE.value:
        progress("targets", max_points=5)
        nearby = rank_targets(
            snapshot,
            probes,
            max_points=5,
            mode=RankingMode.TOTAL,
            node_ids=visible,
            scope="visible",
            max_evaluations=40,
            **common,
        )

    elapsed = (time.perf_counter() - started) * 1000
    recs = [next_passive_recommendation(row) for row in (next_passive or {}).get("recommendations") or []]
    scope_out = {
        "legacy": AnalysisScope.FRONTIER.value,
        AnalysisScope.FRONTIER.value: AnalysisScope.FRONTIER.value,
        AnalysisScope.RADIUS_3.value: AnalysisScope.RADIUS_3.value,
        AnalysisScope.RADIUS_5.value: AnalysisScope.RADIUS_5.value,
        AnalysisScope.VISIBLE.value: AnalysisScope.VISIBLE.value,
    }.get(chosen, chosen)
    return {
        "kind": "tree",
        "scope": scope_out,
        "baseline": snapshot.baseline.to_dict(),
        "tree_set": snapshot.tree_set,
        "stats": snapshot.stats,
        "graph": graph,
        "nodes": graph["nodes"],
        "edges": graph["edges"],
        "next_passive": next_passive,
        "targets": nearby,
        "targets_radius5": radius5,
        "recommendations": recs,
        "heatmap_data": _heatmap_rows(snapshot, next_passive, nearby, radius5),
        "performance": {
            "elapsed_ms": round(elapsed, 2),
            "frontier_count": (next_passive or {}).get("frontier_count"),
            "average_node_ms": round(sum(probes.times_ms) / len(probes.times_ms), 2) if probes.times_ms else 0.0,
            "cache": cache.stats(),
            "pob_recalcs": cache.pob_recalcs,
        },
        "pob_recalc": cache.pob_recalcs > 0,
    }


def tree_info_payload(engine: Any, **kwargs: Any) -> dict[str, Any]:
    snapshot = load_tree_snapshot(engine, **kwargs)
    export = _graph_bundle(snapshot)
    export["kind"] = "tree_snapshot"
    export["scope"] = AnalysisScope.SNAPSHOT.value
    return export
