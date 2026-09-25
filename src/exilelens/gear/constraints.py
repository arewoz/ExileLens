from __future__ import annotations

from typing import Any

from exilelens.gear.models import GearPlanEvaluation, PlanConstraint


def _warning_codes(evaluation: GearPlanEvaluation) -> set[str]:
    return {str(row.get("code") or "") for row in evaluation.warnings}


def _metric_profile(evaluation: GearPlanEvaluation) -> dict[str, Any]:
    return (evaluation.comparison.get("metric_profile") or evaluation.comparison.get("normalized_metrics") or {})


def check_plan_constraints(
    evaluation: GearPlanEvaluation,
    *,
    constraints: tuple[PlanConstraint, ...],
    baseline_metrics: dict[str, Any] | None = None,
    min_dps_floor: float | None = None,
    min_max_hit_floor: float | None = None,
    max_purchases: int | None = None,
) -> list[str]:
    violations: list[str] = []
    codes = _warning_codes(evaluation)
    profile = _metric_profile(evaluation)
    baseline = baseline_metrics or evaluation.baseline_metrics
    final = evaluation.final_metrics

    if PlanConstraint.MAIN_SKILL_MUST_REMAIN_VALID in constraints:
        if "MAIN_SKILL_INVALID" in codes:
            violations.append(PlanConstraint.MAIN_SKILL_MUST_REMAIN_VALID.value)
        offense = profile.get("primary_offense") or {}
        if float(offense.get("current") or baseline.get("CombinedDPS") or 0) > 1 and float(
            offense.get("candidate") or final.get("CombinedDPS") or 0
        ) <= 1:
            violations.append(PlanConstraint.MAIN_SKILL_MUST_REMAIN_VALID.value)

    if PlanConstraint.KEEP_ELEMENTAL_RES_CAPS in constraints:
        if "RES_CAP_LOST" in codes:
            violations.append(PlanConstraint.KEEP_ELEMENTAL_RES_CAPS.value)

    if PlanConstraint.EHP_NOT_BELOW_CURRENT in constraints:
        ehp = profile.get("ehp") or {}
        if float(ehp.get("absolute_delta") or 0.0) < 0:
            violations.append(PlanConstraint.EHP_NOT_BELOW_CURRENT.value)

    if PlanConstraint.RESOURCE_STATE_NOT_WORSE in constraints:
        if "RESOURCE_FAILURE" in codes:
            violations.append(PlanConstraint.RESOURCE_STATE_NOT_WORSE.value)

    if PlanConstraint.MIN_DPS_FLOOR in constraints and min_dps_floor is not None:
        dps = float(final.get("CombinedDPS") or 0.0)
        if dps < float(min_dps_floor):
            violations.append(PlanConstraint.MIN_DPS_FLOOR.value)

    if PlanConstraint.MIN_MAX_HIT_FLOOR in constraints and min_max_hit_floor is not None:
        worst = min(
            float(final.get("PhysicalMaximumHitTaken") or 0.0),
            float(final.get("FireMaximumHitTaken") or 0.0),
            float(final.get("ColdMaximumHitTaken") or 0.0),
            float(final.get("LightningMaximumHitTaken") or 0.0),
            float(final.get("ChaosMaximumHitTaken") or 0.0),
        )
        if worst < float(min_max_hit_floor):
            violations.append(PlanConstraint.MIN_MAX_HIT_FLOOR.value)

    if PlanConstraint.MAX_PURCHASES in constraints and max_purchases is not None:
        if evaluation.plan.purchase_count > int(max_purchases):
            violations.append(PlanConstraint.MAX_PURCHASES.value)

    evaluation.constraint_violations = violations
    return violations


def safe_partial_prune(
    *,
    total_price: float,
    budget: float,
    listing_ids: set[str],
    canonical_id: str,
    seen_canonical: set[str],
    purchase_count: int,
    max_purchases: int | None,
) -> str | None:
    if total_price > budget:
        return "over_budget"
    if max_purchases is not None and purchase_count > max_purchases:
        return "max_purchases"
    if len(listing_ids) != len(set(listing_ids)):
        return "duplicate_listing"
    if canonical_id in seen_canonical:
        return "canonical_duplicate"
    return None
