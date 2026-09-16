from __future__ import annotations

from typing import Any, Callable

from poe2value.items.value_layer import parse_profile
from poe2value.items.value_profiles import ValueProfile
from poe2value.tree.graph import get_frontier_nodes, get_targets_within_cost
from poe2value.tree.models import EvalStatus, PassiveTreeSnapshot, RankingMode
from poe2value.tree.mutations import TreeProbeEngine

YieldFn = Callable[[], bool]
ProgressFn = Callable[[dict[str, Any]], None]


def _drivers(evaluation: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    metrics = evaluation.get("metrics") or {}
    rows = []
    for key in ("primary_offense", "ehp", "worst_max_hit", "movement_speed"):
        metric = metrics.get(key) or {}
        pct = metric.get("percent_delta")
        if pct is None:
            continue
        rows.append({"key": key, "percent_delta": round(float(pct), 3), "label": key})
    rows.sort(key=lambda row: abs(float(row["percent_delta"])), reverse=True)
    return rows[:limit]


def _to_recommendation(evaluation: dict[str, Any], rank: int) -> dict[str, Any]:
    target = evaluation.get("target") or {}
    return {
        "rank": rank,
        "node_id": target.get("node_id"),
        "name": target.get("name"),
        "type": target.get("type"),
        "cost": evaluation.get("cost"),
        "build_value_delta": evaluation.get("path_value") if evaluation.get("path_value") is not None else evaluation.get("build_value_delta"),
        "value_per_point": evaluation.get("value_per_point"),
        "node_value": evaluation.get("node_value"),
        "path_value": evaluation.get("path_value"),
        "path": evaluation.get("path") or [],
        "top_metric_drivers": _drivers(evaluation),
        "breakpoints": evaluation.get("breakpoints") or [],
        "warnings": evaluation.get("warnings") or [],
        "confidence": evaluation.get("confidence"),
        "status": evaluation.get("status"),
        "restore_verified": evaluation.get("restore_verified"),
        "cache_hit": evaluation.get("cache_hit", False),
        "metrics": evaluation.get("metrics"),
        "resist_caps": evaluation.get("resist_caps"),
        "value": evaluation.get("value"),
        "baseline_raw": evaluation.get("baseline_raw"),
        "candidate_raw": evaluation.get("candidate_raw"),
    }


def _sort_key(row: dict[str, Any], mode: RankingMode) -> tuple:
    value = float(row.get("build_value_delta") or 0)
    vpp = row.get("value_per_point")
    vpp_f = float(vpp) if vpp is not None else value
    cost = int(row.get("cost") or 0)
    node_id = int(row.get("node_id") or 0)
    if mode == RankingMode.EFFICIENCY:
        return (-vpp_f, -value, cost, node_id)
    return (-value, cost, -vpp_f, node_id)


def rank_next_passive_points(
    snapshot: PassiveTreeSnapshot,
    probes: TreeProbeEngine,
    *,
    profile: str | ValueProfile,
    primary_field: str = "CombinedDPS",
    primary_confidence: str = "high",
    should_yield: YieldFn | None = None,
    limit: int | None = None,
    max_evaluations: int = 120,
    node_ids: set[int] | None = None,
    on_progress: ProgressFn | None = None,
    prefer_node_ids: set[int] | None = None,
    visible_only: bool = False,
) -> dict[str, Any]:
    selected = parse_profile(profile)
    frontier = get_frontier_nodes(snapshot)
    preferred = set()
    if node_ids is not None:
        preferred.update(int(n) for n in node_ids)
    if prefer_node_ids is not None:
        preferred.update(int(n) for n in prefer_node_ids)
    if preferred:
        visible = [row for row in frontier if int(row["node_id"]) in preferred]
        rest = [row for row in frontier if int(row["node_id"]) not in preferred]
        frontier = visible if visible_only or node_ids is not None and prefer_node_ids is None else visible + rest
        if visible_only:
            frontier = visible
    evaluations = []
    omitted = []
    budget = max(1, int(max_evaluations))
    valid_rows = [row for row in frontier if str(row.get("status")) == EvalStatus.VALID.value]
    total = min(len(valid_rows), budget)
    done = 0
    for row in frontier:
        status = str(row.get("status"))
        if status != EvalStatus.VALID.value:
            omitted.append(row)
            continue
        if len(evaluations) >= budget:
            omitted.append({**row, "status": "BUDGET_SKIPPED"})
            continue
        evaluation = probes.evaluate_node(
            snapshot,
            int(row["node_id"]),
            profile=selected,
            primary_field=primary_field,
            primary_confidence=primary_confidence,
            context=snapshot.baseline.context,
            should_yield=should_yield,
        )
        evaluations.append(evaluation)
        done += 1
        if on_progress:
            on_progress(
                {
                    "stage": "frontier",
                    "done": done,
                    "total": total,
                    "scope": "frontier",
                    "cache_hit": bool(evaluation.get("cache_hit")),
                }
            )
    recs = [_to_recommendation(ev, 0) for ev in evaluations if ev.get("status") == EvalStatus.VALID.value]
    recs.sort(key=lambda row: _sort_key(row, RankingMode.TOTAL))
    if limit is not None:
        recs = recs[: int(limit)]
    for index, rec in enumerate(recs, start=1):
        rec["rank"] = index
    return {
        "mode": RankingMode.TOTAL.value,
        "recommendations": recs,
        "omitted": omitted,
        "evaluated": len(evaluations),
        "frontier_count": len(frontier),
    }


def rank_targets(
    snapshot: PassiveTreeSnapshot,
    probes: TreeProbeEngine,
    *,
    max_points: int,
    profile: str | ValueProfile,
    mode: RankingMode | str = RankingMode.TOTAL,
    primary_field: str = "CombinedDPS",
    primary_confidence: str = "high",
    should_yield: YieldFn | None = None,
    max_evaluations: int = 40,
    node_ids: set[int] | None = None,
    on_progress: ProgressFn | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    selected = parse_profile(profile)
    ranking_mode = mode if isinstance(mode, RankingMode) else RankingMode(str(mode).lower())
    targets = get_targets_within_cost(snapshot, max_points)
    if node_ids is not None:
        targets = [row for row in targets if int(row["node_id"]) in node_ids]
    evaluations = []
    omitted = []
    budget = max(1, int(max_evaluations))
    valid_rows = [row for row in targets if str(row.get("status")) == EvalStatus.VALID.value]
    total = min(len(valid_rows), budget)
    done = 0
    label = scope or f"radius{max_points}"
    for row in targets:
        if str(row.get("status")) != EvalStatus.VALID.value:
            omitted.append(row)
            continue
        if len(evaluations) >= budget:
            omitted.append({**row, "status": "BUDGET_SKIPPED"})
            continue
        evaluation = probes.evaluate_path(
            snapshot,
            list(row["path"]),
            profile=selected,
            primary_field=primary_field,
            primary_confidence=primary_confidence,
            context=snapshot.baseline.context,
            should_yield=should_yield,
        )
        evaluations.append(evaluation)
        done += 1
        if on_progress:
            on_progress(
                {
                    "stage": "targets",
                    "done": done,
                    "total": total,
                    "scope": label,
                    "max_points": int(max_points),
                    "cache_hit": bool(evaluation.get("cache_hit")),
                }
            )
    recs = [_to_recommendation(ev, 0) for ev in evaluations if ev.get("status") == EvalStatus.VALID.value]
    recs.sort(key=lambda row: _sort_key(row, ranking_mode))
    for index, rec in enumerate(recs, start=1):
        rec["rank"] = index
    return {
        "mode": ranking_mode.value,
        "max_points": int(max_points),
        "recommendations": recs,
        "omitted": omitted,
        "evaluated": len(evaluations),
        "target_count": len(targets),
    }


def rescore_tree_results(result: dict[str, Any], profile: str | ValueProfile) -> dict[str, Any]:
    """Re-score stored raw metrics. Does not call Path of Building."""
    from poe2value.tree.value import score_tree_metrics

    selected = parse_profile(profile)

    def _rescore(ev: dict[str, Any]) -> dict[str, Any]:
        if not ev.get("baseline_raw") or not ev.get("candidate_raw"):
            value = ev.get("value")
            if value and ev.get("metrics") is not None:
                from poe2value.items.value_profiles import score_profile

                scored_value = score_profile(
                    ev["metrics"],
                    ev.get("resist_caps") or {},
                    ev.get("warnings") or [],
                    selected,
                )
                updated = dict(ev)
                updated["value"] = scored_value
                updated["build_value_delta"] = scored_value["score_delta"]
                updated["path_value"] = scored_value["score_delta"]
                cost = int(updated.get("cost") or 0)
                updated["value_per_point"] = round(scored_value["score_delta"] / cost, 4) if cost else None
                if cost == 1:
                    updated["node_value"] = scored_value["score_delta"]
                updated["pob_recalc"] = False
                return updated
            return ev
        scored = score_tree_metrics(
            ev["baseline_raw"],
            ev["candidate_raw"],
            selected,
            cost=int(ev.get("cost") or 1),
        )
        updated = dict(ev)
        updated.update(
            {
                "metrics": scored.get("metric_profile"),
                "resist_caps": scored.get("resist_caps"),
                "warnings": scored.get("warnings"),
                "value": scored.get("value"),
                "breakpoints": scored.get("breakpoints"),
                "build_value_delta": scored.get("build_value_delta"),
                "path_value": scored.get("build_value_delta"),
                "value_per_point": scored.get("value_per_point"),
                "pob_recalc": False,
            }
        )
        if int(updated.get("cost") or 0) == 1:
            updated["node_value"] = scored.get("build_value_delta")
        return updated

    updated = dict(result)
    updated["profile"] = selected.value
    if "next_passive" in updated:
        nxt = dict(updated["next_passive"])
        recs = []
        for rec in nxt.get("recommendations") or []:
            recs.append(_rescore(dict(rec)))
        recs.sort(key=lambda row: _sort_key(row, RankingMode.TOTAL))
        for index, rec in enumerate(recs, start=1):
            rec["rank"] = index
        nxt["recommendations"] = recs
        updated["next_passive"] = nxt
    if "targets" in updated:
        tgt = dict(updated["targets"])
        mode = RankingMode(str(tgt.get("mode") or "total").lower())
        recs = [_rescore(dict(rec)) for rec in tgt.get("recommendations") or []]
        recs.sort(key=lambda row: _sort_key(row, mode))
        for index, rec in enumerate(recs, start=1):
            rec["rank"] = index
        tgt["recommendations"] = recs
        updated["targets"] = tgt
    if "evaluation" in updated:
        updated["evaluation"] = _rescore(dict(updated["evaluation"]))
    updated["pob_recalc"] = False
    return updated
