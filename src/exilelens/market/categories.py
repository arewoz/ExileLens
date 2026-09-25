from __future__ import annotations

from typing import Any

from exilelens.market.models import CandidateEvaluation, MarketCandidateResult

MEANINGFUL_VERDICTS = {
    "STRONG_UPGRADE",
    "CLEAR_UPGRADE",
    "OFFENSE_UPGRADE",
    "DEFENSE_UPGRADE",
    "TRADEOFF",
}


def assign_categories(rows: list[MarketCandidateResult]) -> dict[str, str]:
    ok = [row for row in rows if row.evaluation.status == "ok" and row.evaluation.restore_pass]
    meaningful = [row for row in ok if row.evaluation.verdict in MEANINGFUL_VERDICTS and row.evaluation.build_value_delta > 0]

    categories: dict[str, str] = {}

    def _best(key: str, items: list[MarketCandidateResult], metric) -> None:
        if not items:
            return
        winner = max(items, key=metric)
        categories[key] = winner.evaluation.listing.identity.listing_id
        winner.categories.append(key)

    _best("BEST_ABSOLUTE", meaningful or ok, lambda r: r.evaluation.build_value_delta)
    _best("BEST_OFFENSIVE", meaningful or ok, lambda r: r.evaluation.offense_delta)
    _best("BEST_DEFENSIVE", meaningful or ok, lambda r: r.evaluation.defense_delta)

    ppc_rows = [row for row in meaningful if row.evaluation.power_per_currency]
    if ppc_rows:
        _best(
            "BEST_VALUE",
            ppc_rows,
            lambda r: float((r.evaluation.power_per_currency or {}).get("power_per_currency") or 0.0),
        )

    priced = [row for row in meaningful if row.evaluation.listing.price is not None]
    if priced:
        _best("CHEAPEST_MEANINGFUL", priced, lambda r: -float(r.evaluation.listing.price.amount))

    return categories
