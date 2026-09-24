"""Tree Coach view-model. Consumes Phase 5A.5 snapshot + evaluations. No PoB."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from exilelens.items.value_profiles import ValueProfile
from exilelens.tree.contract import tree_heatmap_data
from exilelens.tree.graph import get_frontier_nodes, unallocated_costs
from exilelens.tree.heatmap import BAND_FILL_HEX, DEFAULT_SCALE, HeatmapScale, map_evaluation
from exilelens.tree.models import (
    AnalysisScope,
    EvalStatus,
    HeatmapBand,
    HeatmapMetric,
    HeatmapSource,
    NodeType,
    PassiveTreeSnapshot,
    RankingMode,
    TreeBaseline,
    is_tree_stale,
)
from exilelens.tree.ranking import _sort_key, rescore_tree_results
from exilelens.tree.value import score_tree_metrics


@dataclass
class TreeCoachFilters:
    show_allocated: bool = True
    show_frontier: bool = True
    show_evaluated: bool = True
    show_unevaluated: bool = True
    show_notables: bool = True
    show_keystones: bool = True
    show_small: bool = True


@dataclass
class NodePresentation:
    node_id: int
    name: str
    type: str
    x: float
    y: float
    allocated: bool
    frontier: bool
    best_next: bool
    breakpoint: bool
    unsupported: bool
    unreachable: bool
    evaluated: bool
    band: HeatmapBand
    heat_value: float | None
    fill_hex: str
    cost: int | None
    path: tuple[int, ...]
    breakpoints: tuple[dict[str, Any], ...]
    evaluation_status: str | None
    size_class: str
    visible: bool = True
    pending: bool = False


@dataclass
class AnalysisCoverage:
    frontier_done: int = 0
    frontier_total: int = 0
    radius3_done: int = 0
    radius3_total: int = 0
    radius5_done: int = 0
    radius5_total: int = 0
    scopes: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        return {
            "next_points": f"{self.frontier_done} / {self.frontier_total}",
            "targets_le3": f"{self.radius3_done} / {self.radius3_total}",
            "targets_le5": f"{self.radius5_done} / {self.radius5_total}",
            "scopes": sorted(self.scopes),
        }


def _size_class(ntype: str) -> str:
    if ntype == NodeType.KEYSTONE.value:
        return "keystone"
    if ntype in {NodeType.NOTABLE.value, NodeType.CLASS_START.value, NodeType.ASCEND_START.value}:
        return "notable"
    return "small"


def geometry_map(snapshot: PassiveTreeSnapshot, *, scene_span: float = 10000.0) -> dict[int, tuple[float, float]]:
    """Normalize PoB x/y into a bounded scene. Does not invent a fake layout."""
    coords: dict[int, tuple[float, float]] = {}
    xs: list[float] = []
    ys: list[float] = []
    for node in snapshot.nodes.values():
        if node.x is None or node.y is None:
            continue
        xs.append(float(node.x))
        ys.append(float(node.y))
        coords[node.id] = (float(node.x), float(node.y))
    if not coords:
        return {}
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span = max(max_x - min_x, max_y - min_y, 1.0)
    scale = scene_span / span
    mid_x = (min_x + max_x) / 2.0
    mid_y = (min_y + max_y) / 2.0
    return {nid: ((x - mid_x) * scale, (y - mid_y) * scale) for nid, (x, y) in coords.items()}


def allocated_bounds(geom: dict[int, tuple[float, float]], allocated: Iterable[int]) -> tuple[float, float, float, float] | None:
    points = [geom[i] for i in allocated if i in geom]
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def cached_profile_scores(evaluation: dict[str, Any]) -> dict[str, float] | None:
    """Re-score stored raw metrics for hover comparison. Zero PoB recalcs."""
    if evaluation.get("profile_scores"):
        return dict(evaluation["profile_scores"])
    baseline_raw = evaluation.get("baseline_raw")
    candidate_raw = evaluation.get("candidate_raw")
    if not baseline_raw or not candidate_raw:
        return None
    cost = int(evaluation.get("cost") or 1)
    scores: dict[str, float] = {}
    for profile in ValueProfile:
        scored = score_tree_metrics(baseline_raw, candidate_raw, profile, cost=cost)
        scores[profile.value] = float(scored["build_value_delta"])
    return scores


class TreeCoachViewModel:
    def __init__(
        self,
        *,
        heatmap_metric: HeatmapMetric | str = HeatmapMetric.VALUE_PER_POINT,
        ranking_mode: RankingMode | str = RankingMode.EFFICIENCY,
        profile: str = "BALANCED",
        scale: HeatmapScale = DEFAULT_SCALE,
        filters: TreeCoachFilters | None = None,
    ) -> None:
        self.snapshot: PassiveTreeSnapshot | None = None
        self.geometry: dict[int, tuple[float, float]] = {}
        self.evaluations: dict[int, dict[str, Any]] = {}
        self.heatmap_metric = (
            heatmap_metric if isinstance(heatmap_metric, HeatmapMetric) else HeatmapMetric(str(heatmap_metric))
        )
        self.ranking_mode = ranking_mode if isinstance(ranking_mode, RankingMode) else RankingMode(str(ranking_mode))
        self.profile = str(profile)
        self.scale = scale
        self.filters = filters or TreeCoachFilters()
        self.stale = False
        self.heatmap_source = HeatmapSource.MY_BUILD_VALUE
        self.analyzed_scopes: set[str] = set()
        self._frontier_ids: set[int] = set()
        self._frontier_valid: set[int] = set()
        self._targets3: set[int] = set()
        self._targets5: set[int] = set()
        self._pob_recalcs_on_rescore = 0
        self.pending_ids: set[int] = set()
        self.tree_analysis_generation: int = 0
        self.tracking_snapshot: PassiveTreeSnapshot | None = None
        self.tracking_geometry: dict[int, tuple[float, float]] = {}

    def graph_snapshot(self) -> PassiveTreeSnapshot | None:
        return self.tracking_snapshot or self.snapshot

    def set_tracking_snapshot(self, snapshot: PassiveTreeSnapshot | None) -> None:
        self.tracking_snapshot = snapshot
        self.tracking_geometry = geometry_map(snapshot) if snapshot is not None else {}

    def ingest_graph_payload(self, payload: dict[str, Any]) -> None:
        from exilelens.tree.models import snapshot_from_payload

        source = dict(payload.get("graph") or payload)
        baseline_raw = source.get("baseline") or payload.get("baseline")
        if not baseline_raw:
            return
        fields = TreeBaseline.__dataclass_fields__
        kwargs = {key: baseline_raw.get(key) for key in fields}
        kwargs.setdefault("build_path", "")
        kwargs.setdefault("build_name", "")
        kwargs.setdefault("loadout", "")
        kwargs.setdefault("tree_set", "Default")
        kwargs.setdefault("item_set", "")
        kwargs.setdefault("context", "MAP")
        kwargs.setdefault("profile", self.profile)
        kwargs.setdefault("generation", 0)
        kwargs.setdefault("fingerprint", "")
        kwargs.setdefault("tree_fingerprint", "")
        baseline = TreeBaseline(**kwargs)
        self.ingest_snapshot(snapshot_from_payload(source, baseline=baseline))

    def ingest_snapshot(self, snapshot: PassiveTreeSnapshot) -> None:
        previous = self.snapshot
        if previous is not None and is_tree_stale(previous.baseline, snapshot.baseline):
            self.evaluations.clear()
            self.analyzed_scopes.clear()
            self.pending_ids.clear()
            self.stale = False
        self.snapshot = snapshot
        self.geometry = geometry_map(snapshot)
        self.profile = snapshot.baseline.profile
        frontier = get_frontier_nodes(snapshot)
        self._frontier_ids = {int(r["node_id"]) for r in frontier}
        self._frontier_valid = {
            int(r["node_id"]) for r in frontier if r.get("status") == EvalStatus.VALID.value
        }
        costs = unallocated_costs(snapshot)
        self._targets3 = set()
        self._targets5 = set()
        for node in snapshot.nodes.values():
            if node.allocated or node.type not in {NodeType.NOTABLE, NodeType.KEYSTONE}:
                continue
            if node.support != "SUPPORTED":
                continue
            cost = costs.get(node.id)
            if cost is None or cost <= 0:
                continue
            if cost <= 3:
                self._targets3.add(node.id)
            if cost <= 5:
                self._targets5.add(node.id)

    def reset_for_baseline(self) -> None:
        self.snapshot = None
        self.geometry = {}
        self.tracking_snapshot = None
        self.tracking_geometry = {}
        self.evaluations.clear()
        self.analyzed_scopes.clear()
        self.pending_ids.clear()
        self.stale = False
        self._frontier_ids.clear()
        self._frontier_valid.clear()
        self._targets3.clear()
        self._targets5.clear()
        self.tree_analysis_generation += 1

    def mark_pending(self, node_ids: Iterable[int]) -> None:
        self.pending_ids.update(int(n) for n in node_ids)

    def clear_pending(self, node_ids: Iterable[int] | None = None) -> None:
        if node_ids is None:
            self.pending_ids.clear()
            return
        for nid in node_ids:
            self.pending_ids.discard(int(nid))

    def mark_stale(self) -> None:
        self.stale = True

    def ingest_analysis(self, result: dict[str, Any], *, scope: str | None = None) -> None:
        if self.snapshot is None:
            return
        baseline = result.get("baseline")
        if baseline and is_tree_stale(baseline, self.snapshot.baseline):
            self.stale = True
            return
        self.stale = False
        rows: list[dict[str, Any]] = []
        for key in ("next_passive", "targets", "targets_radius5"):
            block = result.get(key) or {}
            rows.extend(block.get("recommendations") or [])
        if result.get("evaluation"):
            rows.append(result["evaluation"])
        for extra in result.get("heatmap_data") or []:
            if extra.get("node_id") is not None:
                rows.append(extra)
        for row in rows:
            nid = row.get("node_id") or (row.get("target") or {}).get("node_id") or row.get("id")
            if nid is None:
                continue
            merged = dict(self.evaluations.get(int(nid)) or {})
            merged.update(row)
            merged["node_id"] = int(nid)
            scores = cached_profile_scores(merged)
            if scores:
                merged["profile_scores"] = scores
            self.evaluations[int(nid)] = merged
            self.pending_ids.discard(int(nid))
        detected = scope or result.get("scope")
        if detected:
            self.analyzed_scopes.add(str(detected))
        elif result.get("next_passive"):
            self.analyzed_scopes.add(AnalysisScope.FRONTIER.value)
        if result.get("targets"):
            max_pts = int((result.get("targets") or {}).get("max_points") or 3)
            self.analyzed_scopes.add(AnalysisScope.RADIUS_3.value if max_pts <= 3 else AnalysisScope.RADIUS_5.value)
        if result.get("targets_radius5"):
            self.analyzed_scopes.add(AnalysisScope.RADIUS_5.value)

    def set_heatmap_metric(self, metric: HeatmapMetric | str) -> None:
        self.heatmap_metric = metric if isinstance(metric, HeatmapMetric) else HeatmapMetric(str(metric))

    def set_ranking_mode(self, mode: RankingMode | str) -> None:
        self.ranking_mode = mode if isinstance(mode, RankingMode) else RankingMode(str(mode))

    def rescore_profile(self, profile: str) -> int:
        """Re-score cached raw metrics. Returns additional PoB recalc count (always 0)."""
        self.profile = profile
        if not self.evaluations:
            self._pob_recalcs_on_rescore = 0
            return 0
        payload = {
            "kind": "tree",
            "next_passive": {"recommendations": [dict(v) for v in self.evaluations.values() if int(v.get("cost") or 0) == 1]},
            "targets": {"recommendations": [dict(v) for v in self.evaluations.values()], "mode": self.ranking_mode.value},
        }
        updated = rescore_tree_results(payload, profile)
        self.evaluations.clear()
        self.ingest_analysis(updated)
        self._pob_recalcs_on_rescore = 0
        if self.snapshot is not None:
            base = self.snapshot.baseline
            self.snapshot = replace(
                self.snapshot,
                baseline=TreeBaseline(
                    build_path=base.build_path,
                    build_name=base.build_name,
                    loadout=base.loadout,
                    tree_set=base.tree_set,
                    item_set=base.item_set,
                    context=base.context,
                    profile=profile,
                    generation=base.generation,
                    fingerprint=base.fingerprint,
                    tree_fingerprint=base.tree_fingerprint,
                ),
            )
        return 0

    def coverage(self) -> AnalysisCoverage:
        evaluated = {
            nid
            for nid, ev in self.evaluations.items()
            if str(ev.get("status") or ev.get("evaluation_status") or "") == EvalStatus.VALID.value
            or ev.get("build_value_delta") is not None
            or ev.get("path_value") is not None
            or ev.get("build_value") is not None
        }
        return AnalysisCoverage(
            frontier_done=len(evaluated & self._frontier_valid),
            frontier_total=len(self._frontier_valid) or len(self._frontier_ids),
            radius3_done=len(evaluated & self._targets3),
            radius3_total=len(self._targets3),
            radius5_done=len(evaluated & self._targets5),
            radius5_total=len(self._targets5),
            scopes=set(self.analyzed_scopes),
        )

    def frontier_complete(self) -> bool:
        cov = self.coverage()
        return cov.frontier_total > 0 and cov.frontier_done >= cov.frontier_total

    def frontier_cached(self) -> bool:
        cov = self.coverage()
        return cov.frontier_total > 0 and cov.frontier_done >= cov.frontier_total

    def relevant_node_ids(self) -> set[int]:
        graph = self.graph_snapshot()
        if graph is None:
            return set()
        ids = set(graph.allocated_ids())
        ids |= self._frontier_ids
        ids |= {int(k) for k in self.evaluations.keys()}
        return ids

    def _eval_for(self, node_id: int) -> dict[str, Any] | None:
        return self.evaluations.get(int(node_id))

    def presentation(self, node_id: int, *, best_id: int | None = None) -> NodePresentation | None:
        graph = self.graph_snapshot()
        if graph is None:
            return None
        node = graph.node(int(node_id))
        if node is None:
            return None
        geom = self.tracking_geometry if self.tracking_snapshot is not None else self.geometry
        xy = geom.get(node.id, (0.0, 0.0) if node.x is None else (float(node.x), float(node.y)))
        ev = self._eval_for(node.id)
        unsupported = node.support != "SUPPORTED" or (
            ev is not None and str(ev.get("status") or ev.get("evaluation_status")) == EvalStatus.UNSUPPORTED_SPECIAL_NODE.value
        )
        unreachable = ev is not None and str(ev.get("status") or ev.get("evaluation_status")) == EvalStatus.UNREACHABLE.value
        evaluated = False
        pending = int(node_id) in self.pending_ids
        value = None
        band = HeatmapBand.PENDING if pending else HeatmapBand.UNKNOWN
        fill = BAND_FILL_HEX[band]
        cost = node.path_dist
        path: tuple[int, ...] = ()
        breakpoints: tuple[dict[str, Any], ...] = ()
        status = None
        if unsupported:
            band = HeatmapBand.UNKNOWN
            fill = "#5a5360"
        elif ev is not None:
            status = str(ev.get("status") or ev.get("evaluation_status") or "")
            mapped = map_evaluation(
                {
                    **ev,
                    "evaluation_status": status or "VALID",
                    "build_value": ev.get("build_value_delta", ev.get("path_value", ev.get("build_value"))),
                    "value_per_point": ev.get("value_per_point"),
                },
                metric=self.heatmap_metric,
                scale=self.scale,
            )
            value = mapped["heat_value"]
            if status == EvalStatus.VALID.value or value is not None:
                evaluated = status in {"", EvalStatus.VALID.value} and value is not None
            if self.stale:
                band = HeatmapBand.UNKNOWN
                fill = "#3a3a3c"
                evaluated = False
            elif unsupported:
                band = HeatmapBand.UNKNOWN
            else:
                band = HeatmapBand(mapped["band"])
                fill = mapped["fill_hex"]
            cost = ev.get("cost", cost)
            path = tuple(int(n) for n in (ev.get("path") or ()))
            breakpoints = tuple(ev.get("breakpoints") or ())
        else:
            fill = BAND_FILL_HEX[HeatmapBand.UNKNOWN]
        frontier = node.id in self._frontier_ids
        if best_id is None:
            ranked = self.ranked_rows()
            best_id = int(ranked[0]["node_id"]) if ranked else None
        visible = self._node_visible(
            allocated=node.allocated,
            frontier=frontier,
            evaluated=evaluated,
            ntype=node.type.value,
        )
        return NodePresentation(
            node_id=node.id,
            name=node.name,
            type=node.type.value,
            x=xy[0],
            y=xy[1],
            allocated=node.allocated,
            frontier=frontier,
            best_next=best_id == node.id and not self.stale,
            breakpoint=bool(breakpoints) and not self.stale,
            unsupported=unsupported,
            unreachable=unreachable,
            evaluated=evaluated,
            band=band,
            heat_value=None if self.stale else value,
            fill_hex="#3a3a3c" if self.stale and not node.allocated else fill,
            cost=None if cost is None else int(cost),
            path=path,
            breakpoints=breakpoints,
            evaluation_status=status,
            size_class=_size_class(node.type.value),
            visible=visible,
            pending=pending and not evaluated,
        )

    def _node_visible(self, *, allocated: bool, frontier: bool, evaluated: bool, ntype: str) -> bool:
        f = self.filters
        if allocated and not f.show_allocated:
            return False
        if frontier and not allocated and not f.show_frontier:
            return False
        if evaluated and not allocated and not f.show_evaluated:
            return False
        if not evaluated and not allocated and not frontier and not f.show_unevaluated:
            return False
        if ntype == NodeType.NOTABLE.value and not f.show_notables:
            return False
        if ntype == NodeType.KEYSTONE.value and not f.show_keystones:
            return False
        if ntype == NodeType.SMALL.value and not f.show_small:
            return False
        return True

    def all_presentations(self) -> list[NodePresentation]:
        graph = self.graph_snapshot()
        if graph is None:
            return []
        ranked = self.ranked_rows()
        best_id = int(ranked[0]["node_id"]) if ranked else None
        rows = []
        for nid in graph.nodes:
            item = self.presentation(nid, best_id=best_id)
            if item is not None:
                rows.append(item)
        return rows

    def ranked_rows(self) -> list[dict[str, Any]]:
        rows = []
        for nid, ev in self.evaluations.items():
            status = str(ev.get("status") or ev.get("evaluation_status") or EvalStatus.VALID.value)
            if status not in {"", EvalStatus.VALID.value}:
                continue
            if self.snapshot and self.snapshot.node(nid) and self.snapshot.node(nid).allocated:
                continue
            value = ev.get("build_value_delta")
            if value is None:
                value = ev.get("path_value", ev.get("build_value"))
            vpp = ev.get("value_per_point")
            row = {
                "node_id": nid,
                "name": ev.get("name") or (self.snapshot.node(nid).name if self.snapshot and self.snapshot.node(nid) else ""),
                "type": ev.get("type"),
                "cost": ev.get("cost"),
                "build_value_delta": value,
                "value_per_point": vpp,
                "path": ev.get("path") or [],
                "breakpoints": ev.get("breakpoints") or [],
                "top_metric_drivers": ev.get("top_metric_drivers") or [],
                "warnings": ev.get("warnings") or [],
                "confidence": ev.get("confidence"),
                "metrics": ev.get("metrics"),
                "profile_scores": ev.get("profile_scores"),
                "status": status,
            }
            rows.append(row)
        rows.sort(key=lambda item: _sort_key(item, self.ranking_mode))
        for index, row in enumerate(rows, start=1):
            row["rank"] = index
        return rows

    def best_next(self) -> dict[str, Any] | None:
        if AnalysisScope.FRONTIER.value not in self.analyzed_scopes and not any(
            int(r.get("cost") or 0) == 1 for r in self.evaluations.values()
        ):
            return None
        cost1 = [r for r in self.ranked_rows() if int(r.get("cost") or 0) == 1]
        if not cost1:
            return None
        row = dict(cost1[0])
        row["complete"] = self.frontier_complete()
        row["label"] = "BEST NEXT POINT" if row["complete"] else "BEST ANALYZED NEXT POINT"
        return row

    def best_target_within(self, max_points: int) -> dict[str, Any] | None:
        scope = AnalysisScope.RADIUS_3.value if max_points <= 3 else AnalysisScope.RADIUS_5.value
        if scope not in self.analyzed_scopes:
            nearby_done = any(1 < int(r.get("cost") or 0) <= max_points for r in self.evaluations.values())
            if not nearby_done:
                return None
        rows = [r for r in self.ranked_rows() if 0 < int(r.get("cost") or 0) <= max_points]
        return rows[0] if rows else None

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        if self.snapshot is None or not query.strip():
            return []
        needle = query.strip().lower()
        hits = []
        for node in self.snapshot.nodes.values():
            if needle in (node.name or "").lower() or needle == str(node.id):
                hits.append({"node_id": node.id, "name": node.name, "type": node.type.value})
            if len(hits) >= limit:
                break
        return hits

    def heatmap_rows(self) -> list[dict[str, Any]]:
        if self.snapshot is None:
            return []
        rows = []
        for node in self.snapshot.nodes.values():
            ev = self.evaluations.get(node.id) or {}
            payload = tree_heatmap_data(
                {
                    "status": ev.get("status") or ev.get("evaluation_status"),
                    "cost": ev.get("cost"),
                    "path_value": ev.get("path_value", ev.get("build_value_delta")),
                    "build_value_delta": ev.get("build_value_delta"),
                    "value_per_point": ev.get("value_per_point"),
                    "profile_scores": ev.get("profile_scores"),
                    "breakpoints": ev.get("breakpoints") or [],
                    "confidence": ev.get("confidence"),
                },
                node.to_dict(),
            )
            payload.update(map_evaluation(payload, metric=self.heatmap_metric, scale=self.scale))
            rows.append(payload)
        return rows

    def selected_detail(self, node_id: int) -> dict[str, Any] | None:
        pres = self.presentation(node_id)
        if pres is None or self.snapshot is None:
            return None
        node = self.snapshot.node(int(node_id))
        ev = self.evaluations.get(int(node_id)) or {}
        metrics = ev.get("metrics") or {}

        def pct(key: str) -> float | None:
            row = metrics.get(key) or {}
            val = row.get("percent_delta")
            return None if val is None else float(val)

        role = "allocated" if pres.allocated else "frontier" if pres.frontier else "target"
        return {
            "name": pres.name,
            "type": pres.type,
            "node_id": pres.node_id,
            "status": pres.evaluation_status or ("ALLOCATED" if pres.allocated else "UNEVALUATED"),
            "role": role,
            "cost": pres.cost,
            "path": list(pres.path),
            "path_value": ev.get("path_value", ev.get("build_value_delta")),
            "value_per_point": ev.get("value_per_point"),
            "build_value": ev.get("build_value_delta", ev.get("path_value")),
            "primary_offense_pct": pct("primary_offense"),
            "ehp_pct": pct("ehp"),
            "max_hit_pct": pct("worst_max_hit"),
            "breakpoints": list(pres.breakpoints),
            "warnings": ev.get("warnings") or [],
            "profile_scores": ev.get("profile_scores"),
            "confidence": ev.get("confidence"),
            "band": pres.band.value,
            "unsupported": pres.unsupported,
            "stale": self.stale,
            "path_includes_travel": int(pres.cost or 0) > 1,
        }
