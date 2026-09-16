from __future__ import annotations

from typing import Any

from poe2value.market.models import CandidateEvaluation, ParetoFrontier


def _objectives(row: CandidateEvaluation) -> tuple[float, float, float, float]:
    offense = float(row.offense_delta or 0.0)
    defense = float(row.defense_delta or 0.0)
    value = float(row.build_value_delta or 0.0)
    price = 0.0
    if row.listing.price is not None:
        price = float(row.listing.price.amount)
    return value, offense, defense, -price


def _dominates(left: CandidateEvaluation, right: CandidateEvaluation) -> bool:
    lval, loff, ldef, lprice = _objectives(left)
    rval, roff, rdef, rprice = _objectives(right)
    ge = lval >= rval and loff >= roff and ldef >= rdef and lprice >= rprice
    strict = (
        lval > rval
        or loff > roff
        or ldef > rdef
        or lprice > rprice
    )
    return ge and strict


def compute_pareto_frontier(rows: list[CandidateEvaluation]) -> ParetoFrontier:
    ok_rows = [row for row in rows if row.status == "ok" and row.restore_pass]
    frontier_ids: list[str] = []
    for candidate in ok_rows:
        dominated = False
        for other in ok_rows:
            if other is candidate:
                continue
            if _dominates(other, candidate):
                dominated = True
                break
        if not dominated:
            frontier_ids.append(candidate.listing.identity.listing_id)
    return ParetoFrontier(
        candidate_ids=frontier_ids,
        objectives=["build_value_delta", "offense_delta", "defense_delta", "negative_price"],
    )


def apply_pareto_flags(
    results: list[dict[str, Any]],
    frontier: ParetoFrontier,
) -> list[dict[str, Any]]:
    frontier_set = set(frontier.candidate_ids)
    for row in results:
        listing_id = row["evaluation"]["listing"]["identity"]["listing_id"]
        row["on_frontier"] = listing_id in frontier_set
    return results
