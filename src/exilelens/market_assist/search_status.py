"""Explainable market search status for capture sessions."""

from __future__ import annotations

from enum import Enum
from typing import Any

from exilelens.market_assist.models import CaptureQueueState, MarketCaptureSession


class MarketSearchStatus(str, Enum):
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    KEEP_SEARCHING = "KEEP_SEARCHING"
    REFINE_SEARCH = "REFINE_SEARCH"
    STRONG_RESULT_FOUND = "STRONG_RESULT_FOUND"
    DIMINISHING_RETURNS = "DIMINISHING_RETURNS"


def compute_search_status(session: MarketCaptureSession) -> dict[str, Any]:
    evaluated = [
        row
        for row in session.observations
        if row.queue_state is CaptureQueueState.EVALUATED and row.evaluation and row.slot_match
    ]
    count = len(evaluated)
    if count < 3:
        return {
            "status": MarketSearchStatus.INSUFFICIENT_SAMPLE.value,
            "reason": f"Only {count} evaluated — need more samples before guidance is reliable.",
            "evaluated": count,
            "claim_global_optimum": False,
        }

    deltas = [float(row.evaluation.get("build_value_delta") or 0.0) for row in evaluated]
    best = max(deltas)
    recent = deltas[-5:]
    recent_best = max(recent) if recent else best

    strong = [row for row in evaluated if float(row.evaluation.get("build_value_delta") or 0.0) >= 5.0]
    if strong and best >= 8.0:
        return {
            "status": MarketSearchStatus.STRONG_RESULT_FOUND.value,
            "reason": (
                f"Strong session result (+{best:.1f} Build Value). "
                "This is the best seen in this capture session — not a global market optimum."
            ),
            "evaluated": count,
            "best_delta": best,
            "claim_global_optimum": False,
        }

    if count >= 8 and recent_best <= best * 0.25 and best > 2.0:
        return {
            "status": MarketSearchStatus.DIMINISHING_RETURNS.value,
            "reason": "Recent captures are weaker than session best — marginal gains are tapering.",
            "evaluated": count,
            "best_delta": best,
            "claim_global_optimum": False,
        }

    if count >= 5 and best < 3.0:
        return {
            "status": MarketSearchStatus.REFINE_SEARCH.value,
            "reason": "Samples are weak — refine filters using NEXT SEARCH guidance.",
            "evaluated": count,
            "best_delta": best,
            "claim_global_optimum": False,
        }

    return {
        "status": MarketSearchStatus.KEEP_SEARCHING.value,
        "reason": "Keep copying market listings — session still gathering evidence.",
        "evaluated": count,
        "best_delta": best,
        "claim_global_optimum": False,
    }
