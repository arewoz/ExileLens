from __future__ import annotations

import time
from typing import Any, Callable

from poe2value.app.build_revision import BuildFileRevision, read_build_revision
from poe2value.errors import EvaluationInvalidBuildState
from poe2value.gear.cache import GearPlanEvalCache
from poe2value.gear.slots import GEAR_OPTIMIZER_SLOTS
from poe2value.gear.models import (
    GearOptimizationProgress,
    GearOptimizationRequest,
    GearOptimizationResult,
    GearSearchPreset,
    PoolState,
)
from poe2value.gear.optimizer import optimize_plans
from poe2value.gear.registry import CandidatePoolRegistry
from poe2value.gear.slots import pob_slot_for_product
from poe2value.market.currency import CurrencyRateTable

YieldFn = Callable[[], bool]
ProgressFn = Callable[[dict[str, Any]], None]


def _baseline_equipment(engine: Any) -> dict[str, str]:
    equipment_payload = engine.get_equipment()
    rows = equipment_payload.get("equipment") if isinstance(equipment_payload, dict) else equipment_payload
    if not isinstance(rows, list):
        return {}
    mapping: dict[str, str] = {}
    for row in rows:
        slot = row.get("slot") or row.get("pob_slot")
        raw = row.get("item_raw") or row.get("raw")
        if slot and raw:
            mapping[str(slot)] = str(raw)
    return mapping


def run_gear_optimization(
    engine: Any,
    request: GearOptimizationRequest,
    *,
    build_path: str,
    loadout: str = "",
    item_set: str = "",
    registry: CandidatePoolRegistry | None = None,
    cache: GearPlanEvalCache | None = None,
    currency_rates: CurrencyRateTable | None = None,
    should_yield: YieldFn | None = None,
    on_progress: ProgressFn | None = None,
) -> GearOptimizationResult:
    started = time.perf_counter()
    cache = cache or GearPlanEvalCache()
    registry = registry or CandidatePoolRegistry()
    for slot, pool in request.pools.items():
        registry.register(
            pool,
            baseline_fingerprint=request.baseline_fingerprint,
            baseline_generation=request.baseline_generation,
            profile=request.profile,
        )

    enabled = request.enabled_slots or tuple(slot.value for slot in GEAR_OPTIMIZER_SLOTS)
    pool_status = registry.status(
        baseline_fingerprint=request.baseline_fingerprint,
        baseline_generation=request.baseline_generation,
        profile=request.profile,
        enabled_slots=enabled,
    )

    def progress(phase: str, message: str, **extra: Any) -> None:
        payload = GearOptimizationProgress(phase=phase, message=message, **extra).to_dict()
        if on_progress:
            on_progress(payload)

    revision = read_build_revision(build_path)
    if request.build_revision and revision:
        prior = BuildFileRevision(
            path=str(request.build_revision.get("path") or build_path),
            mtime_ns=int(request.build_revision.get("mtime_ns") or 0),
            size=int(request.build_revision.get("size") or 0),
        )
        if revision.changed_from(prior):
            progress("stale", "Build file changed since optimization was requested")
            return GearOptimizationResult(
                request=request,
                label="STALE BUILD REVISION",
                search_mode="",
                best_plan=None,
                pool_status=pool_status,
                progress=GearOptimizationProgress("stale", "Build file changed — refresh baseline"),
                stale=True,
            )

    ready = registry.ready_pools(
        baseline_fingerprint=request.baseline_fingerprint,
        baseline_generation=request.baseline_generation,
        profile=request.profile,
        enabled_slots=enabled,
    )
    if not ready:
        progress("pools", "No ready candidate pools")
        return GearOptimizationResult(
            request=request,
            label="MISSING CANDIDATE POOLS",
            search_mode="",
            best_plan=None,
            pool_status=pool_status,
            progress=GearOptimizationProgress("pools", "Populate pools from Market search"),
        )

    if hasattr(engine, "ensure_build_ready"):
        loaded = engine.ensure_build_ready(build_path, context=request.context)
    else:
        loaded = engine.load_build(build_path, context=request.context)
    from poe2value.baseline import apply_engine_identity

    apply_engine_identity(engine, loadout=loadout, item_set=item_set)
    metrics = engine.get_metrics(request.context)
    fingerprint = str(metrics.get("fingerprint_hash") or loaded.get("fingerprint_hash") or "")
    if fingerprint and fingerprint != request.baseline_fingerprint:
        progress("stale", "Baseline fingerprint mismatch")
        return GearOptimizationResult(
            request=request,
            label="STALE BASELINE",
            search_mode="",
            best_plan=None,
            pool_status=pool_status,
            progress=GearOptimizationProgress("stale", "Baseline changed — reload build"),
            stale=True,
        )

    baseline_equipment = _baseline_equipment(engine)
    for slot, pool in ready.items():
        if not pool.pob_slot:
            pool.pob_slot = pob_slot_for_product(slot)

    progress("optimize", f"Optimizing {len(ready)} slot pools under budget")
    outcome = optimize_plans(
        engine,
        build_path=build_path,
        context=request.context,
        profile=request.profile,
        pools=ready,
        enabled_slots=enabled,
        budget_amount=float(request.budget_amount),
        budget_currency=request.budget_currency,
        preset=request.search_preset,
        constraints=request.constraints,
        max_purchases=request.max_purchases,
        min_dps_floor=request.min_dps_floor,
        min_max_hit_floor=request.min_max_hit_floor,
        baseline_equipment=baseline_equipment,
        cache=cache,
        currency_rates=currency_rates,
        should_yield=should_yield,
        on_progress=on_progress,
    )

    if outcome.get("restore_failed"):
        return GearOptimizationResult(
            request=request,
            label="RESTORE_FAILED",
            search_mode=str(outcome.get("search_mode") or ""),
            best_plan=None,
            pool_status=pool_status,
            progress=GearOptimizationProgress("error", str(outcome.get("error") or "RESTORE_FAILED")),
            performance=dict(outcome.get("performance") or {}),
        )

    final_metrics = engine.get_metrics(request.context)
    if fingerprint and final_metrics.get("fingerprint_hash") != fingerprint:
        raise EvaluationInvalidBuildState(
            "build fingerprint changed after gear optimization sequence",
            {"baseline": fingerprint, "final": final_metrics.get("fingerprint_hash")},
        )

    elapsed_ms = (time.perf_counter() - started) * 1000
    perf = dict(outcome.get("performance") or {})
    perf["elapsed_ms"] = elapsed_ms
    return GearOptimizationResult(
        request=request,
        label="BEST FOUND IN AVAILABLE CANDIDATE POOLS",
        search_mode=str(outcome.get("search_mode") or ""),
        best_plan=outcome.get("best_plan"),
        alternatives=list(outcome.get("alternatives") or []),
        pareto_frontier=list(outcome.get("pareto_frontier") or []),
        categories=dict(outcome.get("categories") or {}),
        budget_curve=list(outcome.get("budget_curve") or []),
        best_single_purchase=outcome.get("best_single_purchase"),
        opportunity_cost=outcome.get("opportunity_cost"),
        pool_status=pool_status,
        progress=GearOptimizationProgress(
            phase="complete",
            message="Gear optimization complete",
            evaluated=len(outcome.get("evaluated") or []),
            total=len(outcome.get("evaluated") or []),
        ),
        performance=perf,
    )
