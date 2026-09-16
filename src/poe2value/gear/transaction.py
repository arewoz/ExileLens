from __future__ import annotations

from typing import Any

from poe2value.gear.models import GearPlan, GearPlanEvaluation, GearPlanReplacement
from poe2value.items.primary_metric import resolve_primary_metric
from poe2value.items.ranking import enrich_slot_comparison
from poe2value.items.value_layer import parse_profile
from poe2value.market.engine import _price_for_listing
from poe2value.market.currency import CurrencyRateTable


def _plan_wire(plan: GearPlan) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for replacement in plan.active_replacements():
        rows.append({"slot": replacement.pob_slot, "item_raw": replacement.item_raw})
    return rows


def evaluate_gear_plan(
    engine: Any,
    plan: GearPlan,
    *,
    build_path: str,
    context: str = "MAP",
    profile: str = "BALANCED",
    loadout: str = "",
    item_set: str = "",
    budget_currency: str | None = None,
    currency_rates: CurrencyRateTable | None = None,
    primary_field: str | None = None,
    primary_confidence: str = "high",
    cache: Any | None = None,
) -> GearPlanEvaluation:
    if hasattr(engine, "ensure_build_ready"):
        loaded = engine.ensure_build_ready(build_path, context=context)
    else:
        loaded = engine.load_build(build_path, context=context)
    from poe2value.baseline import apply_engine_identity

    apply_engine_identity(engine, loadout=loadout, item_set=item_set)
    baseline_metrics = engine.get_metrics(context)
    fingerprint = str(baseline_metrics.get("fingerprint_hash") or loaded.get("fingerprint_hash") or "")
    build_info = loaded.get("build") or {}
    primary = resolve_primary_metric(build_info, baseline_metrics)
    primary_field = primary_field or primary.pob_field
    selected_profile = parse_profile(profile)

    cache_key = None
    if cache is not None:
        cache_key = cache.make_key(
            baseline_fingerprint=fingerprint,
            context=context,
            canonical_id=plan.canonical_id,
            profile=selected_profile.value,
        )
        cached = cache.get(cache_key)
        if cached:
            return cached

    wire = _plan_wire(plan)
    if not wire:
        comparison = {
            "product_slot": "GEAR_PLAN",
            "pob_slot": "multi",
            "baseline": {"metrics": baseline_metrics.get("raw") or {}, "fingerprint_hash": fingerprint},
            "candidate": {"metrics": baseline_metrics.get("raw") or {}, "fingerprint_hash": fingerprint},
            "restored": {"metrics": baseline_metrics.get("raw") or {}, "fingerprint_hash": fingerprint},
            "restore": {"pass": True},
            "delta": {},
        }
        enriched = enrich_slot_comparison(
            comparison,
            profile=selected_profile,
            primary_field=primary_field,
            primary_confidence=primary_confidence,
            price=None,
        )
        evaluation = GearPlanEvaluation(
            plan=plan,
            baseline_metrics=baseline_metrics.get("raw") or {},
            final_metrics=baseline_metrics.get("raw") or {},
            baseline_fingerprint=fingerprint,
            final_fingerprint=fingerprint,
            comparison=enriched,
            build_value_delta=0.0,
            offense_delta=0.0,
            defense_delta=0.0,
            verdict=str(enriched.get("verdict") or "NO_CHANGE"),
            warnings=list(enriched.get("warnings") or []),
            restore_pass=True,
            total_price=plan.total_price,
            price_currency=budget_currency or "",
        )
        if cache is not None and cache_key is not None:
            cache.put(cache_key, evaluation)
        return evaluation

    try:
        result = engine.evaluate_gear_plan(wire, context=context)
    except Exception as exc:
        return GearPlanEvaluation(
            plan=plan,
            baseline_metrics=baseline_metrics.get("raw") or {},
            final_metrics={},
            baseline_fingerprint=fingerprint,
            final_fingerprint="",
            comparison={},
            build_value_delta=0.0,
            offense_delta=0.0,
            defense_delta=0.0,
            verdict="UNRESOLVED",
            restore_pass=False,
            status="error",
            error=str(exc),
            total_price=plan.total_price,
            price_currency=budget_currency or "",
        )

    final_metrics = engine.get_metrics(context)
    if fingerprint and final_metrics.get("fingerprint_hash") != fingerprint:
        from poe2value.errors import EvaluationInvalidBuildState

        raise EvaluationInvalidBuildState(
            "build fingerprint changed after gear plan evaluation",
            {"baseline": fingerprint, "final": final_metrics.get("fingerprint_hash")},
        )

    comparison = {
        "product_slot": "GEAR_PLAN",
        "pob_slot": "multi",
        "baseline": result["baseline"],
        "candidate": result["final"],
        "restored": result["restored"],
        "restore": result["restore"],
        "delta": result["delta"],
        "primary_metric_field": primary_field,
    }
    total_price = plan.total_price
    price_obj = None
    if budget_currency and total_price > 0:
        from poe2value.items.price import ManualPrice

        price_obj = ManualPrice(amount=total_price, currency=budget_currency, source="PLAN_TOTAL")
    enriched = enrich_slot_comparison(
        comparison,
        profile=selected_profile,
        primary_field=primary_field,
        primary_confidence=primary_confidence,
        price=price_obj,
    )
    metric_profile = enriched.get("metric_profile") or {}
    offense = float((metric_profile.get("primary_offense") or {}).get("absolute_delta") or 0.0)
    defense = float((metric_profile.get("ehp") or {}).get("absolute_delta") or 0.0)
    value = float((enriched.get("value") or {}).get("score_delta") or 0.0)
    evaluation = GearPlanEvaluation(
        plan=plan,
        baseline_metrics=result["baseline"].get("metrics") or {},
        final_metrics=result["final"].get("metrics") or {},
        baseline_fingerprint=fingerprint,
        final_fingerprint=str(result["final"].get("fingerprint_hash") or result["final"].get("fingerprint") or ""),
        comparison=enriched,
        build_value_delta=value,
        offense_delta=offense,
        defense_delta=defense,
        verdict=str(enriched.get("verdict") or "UNRESOLVED"),
        warnings=list(enriched.get("warnings") or []),
        restore_pass=bool((result.get("restore") or {}).get("pass", True)),
        total_price=total_price,
        price_currency=budget_currency or "",
    )
    if cache is not None and cache_key is not None:
        cache.put(cache_key, evaluation)
    return evaluation


def rescore_plan_evaluation(evaluation: GearPlanEvaluation, *, profile: str) -> GearPlanEvaluation:
    """Profile-only re-score from cached raw metrics — no PoB recalc."""
    selected = parse_profile(profile)
    comparison = dict(evaluation.comparison)
    comparison["baseline"] = {"metrics": evaluation.baseline_metrics}
    comparison["candidate"] = {"metrics": evaluation.final_metrics}
    comparison["restored"] = {"metrics": evaluation.baseline_metrics}
    comparison["restore"] = {"pass": evaluation.restore_pass}
    enriched = enrich_slot_comparison(
        comparison,
        profile=selected,
        primary_field=comparison.get("primary_metric_field") or "CombinedDPS",
        primary_confidence="high",
        price=None,
    )
    metric_profile = enriched.get("metric_profile") or {}
    offense = float((metric_profile.get("primary_offense") or {}).get("absolute_delta") or 0.0)
    defense = float((metric_profile.get("ehp") or {}).get("absolute_delta") or 0.0)
    value = float((enriched.get("value") or {}).get("score_delta") or 0.0)
    return GearPlanEvaluation(
        plan=evaluation.plan,
        baseline_metrics=evaluation.baseline_metrics,
        final_metrics=evaluation.final_metrics,
        baseline_fingerprint=evaluation.baseline_fingerprint,
        final_fingerprint=evaluation.final_fingerprint,
        comparison=enriched,
        build_value_delta=value,
        offense_delta=offense,
        defense_delta=defense,
        verdict=str(enriched.get("verdict") or evaluation.verdict),
        warnings=list(enriched.get("warnings") or []),
        constraint_violations=list(evaluation.constraint_violations),
        restore_pass=evaluation.restore_pass,
        cache_hit=True,
        status=evaluation.status,
        error=evaluation.error,
        total_price=evaluation.total_price,
        price_currency=evaluation.price_currency,
    )


def normalized_listing_price(
    listing: Any,
    budget_currency: str,
    rates: CurrencyRateTable | None,
) -> Any | None:
    return _price_for_listing(listing, budget_currency, rates)
