from __future__ import annotations

from exilelens.gear.models import GearPlanEvaluation

MEANINGFUL_VERDICTS = {
    "STRONG_UPGRADE",
    "CLEAR_UPGRADE",
    "OFFENSE_UPGRADE",
    "DEFENSE_UPGRADE",
    "TRADEOFF",
}


def assign_plan_categories(rows: list[GearPlanEvaluation]) -> dict[str, str]:
    ok = [row for row in rows if row.status == "ok" and row.restore_pass and not row.constraint_violations]
    meaningful = [row for row in ok if row.verdict in MEANINGFUL_VERDICTS and row.build_value_delta > 0]
    pool = meaningful or ok
    categories: dict[str, str] = {}

    def _best(key: str, items: list[GearPlanEvaluation], metric) -> None:
        if not items:
            return
        winner = max(items, key=metric)
        categories[key] = winner.plan.canonical_id

    _best("BEST_OVERALL", pool, lambda r: r.build_value_delta)
    _best("BEST_DAMAGE", pool, lambda r: r.offense_delta)
    _best("BEST_DEFENSIVE", pool, lambda r: r.defense_delta)

    priced = [row for row in pool if row.total_price > 0]
    if priced:
        _best(
            "BEST_VALUE",
            priced,
            lambda r: r.build_value_delta / max(r.total_price, 0.01),
        )
        strong = [row for row in priced if row.build_value_delta > 0]
        if strong:
            _best("CHEAPEST_STRONG", strong, lambda r: -r.total_price)

    return categories
