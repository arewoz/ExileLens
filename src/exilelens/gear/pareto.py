from __future__ import annotations

from typing import Any

from exilelens.gear.models import GearPlanEvaluation


def _objectives(row: GearPlanEvaluation) -> tuple[float, float, float, float]:
    offense = float(row.offense_delta or 0.0)
    defense = float(row.defense_delta or 0.0)
    value = float(row.build_value_delta or 0.0)
    price = -float(row.total_price or 0.0)
    return value, offense, defense, price


def _dominates(left: GearPlanEvaluation, right: GearPlanEvaluation) -> bool:
    lval, loff, ldef, lprice = _objectives(left)
    rval, roff, rdef, rprice = _objectives(right)
    ge = lval >= rval and loff >= roff and ldef >= rdef and lprice >= rprice
    strict = lval > rval or loff > roff or ldef > rdef or lprice > rprice
    return ge and strict


def compute_plan_pareto_frontier(rows: list[GearPlanEvaluation]) -> list[str]:
    ok_rows = [row for row in rows if row.status == "ok" and row.restore_pass and not row.constraint_violations]
    frontier: list[str] = []
    for candidate in ok_rows:
        dominated = False
        for other in ok_rows:
            if other.plan.canonical_id == candidate.plan.canonical_id:
                continue
            if _dominates(other, candidate):
                dominated = True
                break
        if not dominated:
            frontier.append(candidate.plan.canonical_id)
    return frontier
