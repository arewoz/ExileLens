from __future__ import annotations

from poe2value.gear.models import GearPlanEvaluation


def build_budget_curve(evaluations: list[GearPlanEvaluation]) -> list[dict[str, float | str]]:
    """Budget curve from evaluated plans only — no interpolation."""
    rows = [
        row
        for row in evaluations
        if row.status == "ok" and row.restore_pass and not row.constraint_violations
    ]
    rows.sort(key=lambda r: (r.total_price, -r.build_value_delta))
    curve: list[dict[str, float | str]] = []
    best_value = float("-inf")
    for row in rows:
        if row.build_value_delta <= best_value:
            continue
        best_value = row.build_value_delta
        curve.append(
            {
                "canonical_id": row.plan.canonical_id,
                "price": float(row.total_price),
                "build_value_delta": float(row.build_value_delta),
                "purchase_count": float(row.plan.purchase_count),
            }
        )
    return curve
