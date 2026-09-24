from __future__ import annotations

import time
from typing import Any, Callable

from exilelens.errors import EngineError, RestoreFailed, WorkerUnhealthy
from exilelens.items.primary_metric import resolve_primary_metric
from exilelens.items.value_layer import parse_profile
from exilelens.items.value_profiles import ValueProfile
from exilelens.tree.cache import TreeEvalCache
from exilelens.tree.fingerprint import path_identity, tree_fingerprint_from_components
from exilelens.tree.graph import classify_target, shortest_path
from exilelens.tree.models import EvalStatus, PassiveTreeSnapshot, TreeBaseline
from exilelens.tree.value import evaluation_payload, score_tree_metrics

YieldFn = Callable[[], bool]


def decorate_tree_evaluation(result: dict[str, Any]) -> dict[str, Any]:
    from exilelens.worker import decorate_evaluation

    if "baseline" in result and "candidate" in result and "restored" in result:
        decorated = decorate_evaluation(result)
        decorated["status"] = result.get("status") or "VALID"
        decorated["path"] = [int(n) for n in (result.get("path") or [])]
        decorated["cost"] = int(result.get("cost") or len(decorated["path"]))
        decorated["target_id"] = result.get("target_id")
        return decorated
    return result


def _target_info(snapshot: PassiveTreeSnapshot, node_id: int) -> dict[str, Any]:
    node = snapshot.node(int(node_id))
    if node is None:
        return {"node_id": int(node_id), "name": None, "type": None}
    return {"node_id": node.id, "name": node.name, "type": node.type.value}


class TreeProbeEngine:
    def __init__(self, engine: Any, cache: TreeEvalCache | None = None) -> None:
        self.engine = engine
        self.cache = cache or TreeEvalCache()
        self.times_ms: list[float] = []

    def evaluate_path(
        self,
        snapshot: PassiveTreeSnapshot,
        node_ids: list[int],
        *,
        profile: str | ValueProfile,
        primary_field: str = "CombinedDPS",
        primary_confidence: str = "high",
        context: str | None = None,
        should_yield: YieldFn | None = None,
    ) -> dict[str, Any]:
        selected = profile if isinstance(profile, ValueProfile) else parse_profile(profile)
        if should_yield and should_yield():
            from exilelens.analysis.pipeline import AnalysisYielded

            raise AnalysisYielded({"stage": "tree_eval"})
        if not node_ids:
            target_id = 0
            status = EvalStatus.INVALID_NODE
            return evaluation_payload(
                status=status,
                target={"node_id": target_id, "name": None, "type": None},
                path=[],
                cost=0,
                scored=None,
                restore={"pass": True},
                baseline=snapshot.baseline.to_dict(),
                node_value=None,
                path_value=None,
                confidence="none",
            )
        target_id = int(node_ids[-1])
        status = classify_target(snapshot, target_id)
        target = _target_info(snapshot, target_id)
        resolved = shortest_path(snapshot, target_id)
        path = list(node_ids)
        cost = len(path)
        if status == EvalStatus.ALREADY_ALLOCATED:
            return evaluation_payload(
                status=status,
                target=target,
                path=[],
                cost=0,
                scored=None,
                restore={"pass": True},
                baseline=snapshot.baseline.to_dict(),
                node_value=0.0,
                path_value=0.0,
                confidence="high",
            )
        if status in {EvalStatus.INVALID_NODE, EvalStatus.UNSUPPORTED_SPECIAL_NODE, EvalStatus.UNREACHABLE}:
            return evaluation_payload(
                status=status,
                target=target,
                path=path if status != EvalStatus.UNREACHABLE else [],
                cost=0,
                scored=None,
                restore={"pass": True},
                baseline=snapshot.baseline.to_dict(),
                node_value=None,
                path_value=None,
                confidence="none",
            )
        if resolved is not None:
            path, cost = resolved
        cache_key = self.cache.key(
            prefix=snapshot.baseline.raw_cache_prefix(),
            path_identity=path_identity(path),
            context=snapshot.baseline.context,
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            scored = score_tree_metrics(
                cached["baseline_raw"],
                cached["candidate_raw"],
                selected,
                primary_field=primary_field,
                primary_confidence=primary_confidence,
                cost=cost,
            )
            payload = evaluation_payload(
                status=EvalStatus.VALID,
                target=target,
                path=path,
                cost=cost,
                scored=scored,
                restore=cached.get("restore") or {"pass": True},
                baseline=snapshot.baseline.to_dict(),
                node_value=scored["build_value_delta"] if cost == 1 else None,
                path_value=scored["build_value_delta"],
                confidence="high",
            )
            payload["cache_hit"] = True
            payload["pob_recalc"] = False
            payload["baseline_raw"] = cached["baseline_raw"]
            payload["candidate_raw"] = cached["candidate_raw"]
            return payload

        started = time.perf_counter()
        try:
            raw = self.engine.evaluate_tree_path(path, target_id=target_id, context=context)
        except RestoreFailed:
            raise
        except WorkerUnhealthy:
            raise
        except EngineError:
            raise
        elapsed = (time.perf_counter() - started) * 1000
        self.times_ms.append(elapsed)
        self.cache.pob_recalcs += 1
        lua_status = str(raw.get("status") or "VALID")
        restore = raw.get("restore") or {}
        try:
            status_enum = EvalStatus(lua_status)
        except ValueError:
            status_enum = EvalStatus.UNREACHABLE
        if status_enum != EvalStatus.VALID:
            return evaluation_payload(
                status=status_enum,
                target=target,
                path=[int(n) for n in (raw.get("path") or path)],
                cost=int(raw.get("cost") or 0),
                scored=None,
                restore=restore,
                baseline=snapshot.baseline.to_dict(),
                node_value=None,
                path_value=None,
                confidence="none",
            )
        scored = score_tree_metrics(
            raw["baseline"]["metrics"],
            raw["candidate"]["metrics"],
            selected,
            primary_field=primary_field,
            primary_confidence=primary_confidence,
            cost=int(raw.get("cost") or cost or 1),
        )
        self.cache.put(
            cache_key,
            {
                "baseline_raw": raw["baseline"]["metrics"],
                "candidate_raw": raw["candidate"]["metrics"],
                "restore": restore,
            },
        )
        payload = evaluation_payload(
            status=EvalStatus.VALID,
            target=target,
            path=[int(n) for n in (raw.get("path") or path)],
            cost=int(raw.get("cost") or cost),
            scored=scored,
            restore=restore,
            baseline=snapshot.baseline.to_dict(),
            node_value=scored["build_value_delta"] if int(raw.get("cost") or cost) == 1 else None,
            path_value=scored["build_value_delta"],
            confidence="high",
        )
        payload["cache_hit"] = False
        payload["pob_recalc"] = True
        payload["elapsed_ms"] = elapsed
        payload["fingerprint"] = {
            "baseline": raw["baseline"]["fingerprint_hash"],
            "restored": raw["restored"]["fingerprint_hash"],
            "match": raw["baseline"]["fingerprint_hash"] == raw["restored"]["fingerprint_hash"],
            "tree": tree_fingerprint_from_components(raw["baseline"].get("fingerprint") or {}),
        }
        payload["baseline_raw"] = raw["baseline"]["metrics"]
        payload["candidate_raw"] = raw["candidate"]["metrics"]
        return payload

    def evaluate_node(self, snapshot: PassiveTreeSnapshot, node_id: int, **kwargs: Any) -> dict[str, Any]:
        node_id = int(node_id)
        resolved = shortest_path(snapshot, node_id)
        if resolved is None:
            status = classify_target(snapshot, node_id)
            return evaluation_payload(
                status=status,
                target=_target_info(snapshot, node_id),
                path=[],
                cost=0,
                scored=None,
                restore={"pass": True},
                baseline=snapshot.baseline.to_dict(),
                node_value=None,
                path_value=None,
                confidence="none",
            )
        path, _cost = resolved
        if not path:
            path = [node_id]
        return self.evaluate_path(snapshot, path, **kwargs)


def load_tree_snapshot(
    engine: Any,
    *,
    build_path: str,
    context: str,
    profile: str,
    generation: int = 0,
    loadout: str = "",
    item_set: str = "",
) -> PassiveTreeSnapshot:
    from exilelens.tree.models import snapshot_from_payload

    if hasattr(engine, "ensure_build_ready"):
        loaded = engine.ensure_build_ready(build_path, context=context)
    else:
        loaded = engine.load_build(build_path, context=context)
    from exilelens.baseline import apply_engine_identity

    apply_engine_identity(engine, loadout=loadout, item_set=item_set)
    metrics = engine.get_metrics(context)
    payload = engine.get_tree_snapshot()
    fingerprint = str(metrics.get("fingerprint_hash") or loaded.get("fingerprint_hash") or "")
    tree_fp = tree_fingerprint_from_components(metrics.get("fingerprint") or loaded.get("fingerprint") or {})
    build_blob = loaded.get("build") if isinstance(loaded.get("build"), dict) else loaded
    tree_set = (payload.get("tree_set") or {}).get("title") or loadout or "Default"
    baseline = TreeBaseline(
        build_path=str(build_path),
        build_name=str(build_blob.get("build_name") or ""),
        loadout=loadout,
        tree_set=str(tree_set),
        item_set=item_set,
        context=context,
        profile=profile,
        generation=generation,
        fingerprint=fingerprint,
        tree_fingerprint=tree_fp,
    )
    return snapshot_from_payload(payload, baseline=baseline)


def primary_from_engine(engine: Any) -> tuple[str, str]:
    try:
        info = engine.get_build_info() or {}
        metrics = engine.get_metrics()
        raw = metrics.get("raw") or metrics.get("metrics") or {}
        blob = info.get("build") if isinstance(info.get("build"), dict) else info
        primary = resolve_primary_metric(blob, raw)
        return primary.pob_field, primary.confidence.value
    except Exception:
        return "CombinedDPS", "high"
