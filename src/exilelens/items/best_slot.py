"""Best replacement slot selection with guardrail-aware ordering."""

from __future__ import annotations

from typing import Any

from exilelens.items.evaluation_outcome import VERDICT_ORDER as OUTCOME_VERDICT_ORDER
from exilelens.items.ranking import Verdict, _VERDICT_ORDER

_GUARDRAIL_CODES = frozenset(
    {
        "RES_CAP_LOST",
        "RESOURCE_FAILURE",
        "MAIN_SKILL_INVALID",
        "BUILD_INVALID",
    }
)


def _guardrail_penalty(comparison: dict[str, Any]) -> int:
    warnings = comparison.get("warnings") or []
    codes = {str(item.get("code")) for item in warnings}
    penalty = 0
    if "RES_CAP_LOST" in codes:
        penalty += 1000
    if "RESOURCE_FAILURE" in codes:
        penalty += 500
    if codes & {"MAIN_SKILL_INVALID", "BUILD_INVALID"}:
        penalty += 2000
    if "RES_DEFICIT_WORSENED" in codes:
        penalty += 200
    restore = comparison.get("restore") or {}
    # A deferred restore (PERF-02) reports `pass: None` -- pending, not failed.
    if restore.get("pass") is False:
        penalty += 5000
    return penalty


def _rating(comparison: dict[str, Any]) -> float:
    value = comparison.get("value") or {}
    rating = value.get("rating")
    if rating is None:
        return 50.0
    return float(rating)


def _verdict_rank(comparison: dict[str, Any]) -> int:
    outcome = comparison.get("evaluation_outcome")
    if outcome:
        return OUTCOME_VERDICT_ORDER.get(str(outcome.get("verdict") or ""), 99)
    # Legacy comparisons built without an outcome (older fixtures / callers).
    return _VERDICT_ORDER.get(str(comparison.get("verdict") or Verdict.UNRESOLVED.value), 99)


def best_slot_sort_key(comparison: dict[str, Any]) -> tuple:
    """Lower is better. Guardrails, then the public verdict, then the final score."""
    guardrail = _guardrail_penalty(comparison)
    rating = _rating(comparison)
    profile = comparison.get("metric_profile") or {}
    offense = float((profile.get("primary_offense") or {}).get("absolute_delta") or 0.0)
    ehp = float((profile.get("ehp") or {}).get("absolute_delta") or 0.0)
    return (
        guardrail,
        _verdict_rank(comparison),
        -rating,
        -(offense + ehp * 0.001),
        str(comparison.get("pob_slot") or ""),
    )


def select_best_comparison(comparisons: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not comparisons:
        return None
    return min(comparisons, key=best_slot_sort_key)


def best_slot_label(comparison: dict[str, Any] | None) -> str:
    if not comparison:
        return ""
    slot = comparison.get("pob_slot") or comparison.get("product_slot") or ""
    if not slot:
        return ""
    return f"Replace {slot}"


def rank_comparisons_guardrail_first(comparisons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = list(comparisons)
    ranked.sort(key=best_slot_sort_key)
    return ranked
