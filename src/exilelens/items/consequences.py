from __future__ import annotations

import math
from typing import Any

from exilelens.items.requirement_gates import attribute_requirement_warnings
from exilelens.items.display_thresholds import DEFAULT_DISPLAY_THRESHOLDS, DisplayThresholds


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _pct(metric: dict[str, Any] | None) -> float:
    if not metric:
        return 0.0
    value = metric.get("percent_delta")
    if value is None:
        return 0.0
    return _number(value) or 0.0


def _abs(metric: dict[str, Any] | None) -> float:
    if not metric:
        return 0.0
    return _number(metric.get("absolute_delta")) or 0.0


def build_warnings(
    metrics: dict[str, Any],
    resist: dict[str, Any],
    raw_current: dict[str, Any],
    raw_candidate: dict[str, Any],
    *,
    thresholds: DisplayThresholds = DEFAULT_DISPLAY_THRESHOLDS,
    restore_failed: bool = False,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if restore_failed:
        warnings.append(
            {
                "code": "BUILD_INVALID",
                "severity": "critical",
                "metric": "restore",
                "before": None,
                "after": None,
                "detail": "baseline restore failed",
            }
        )

    offense = metrics.get("primary_offense") or {}
    offense_current = _number(offense.get("current"))
    offense_candidate = _number(offense.get("candidate"))
    if offense_current is not None and offense_candidate is not None and offense_current > 1 and offense_candidate <= 1:
        warnings.append(
            {
                "code": "MAIN_SKILL_INVALID",
                "severity": "critical",
                "metric": "primary_offense",
                "before": offense.get("current"),
                "after": offense.get("candidate"),
                "detail": "primary offense collapsed to ~0",
            }
        )

    for element, info in (resist.get("elements") or {}).items():
        if info.get("effective_cap_lost"):
            warnings.append(
                {
                    "code": "RES_CAP_LOST",
                    "severity": "critical",
                    "metric": f"{element}_res",
                    "before": info.get("current"),
                    "after": info.get("candidate"),
                    "detail": f"{element} resistance cap lost",
                    "cap_state": info.get("state"),
                }
            )
        elif info.get("state") == "BELOW_CAP_WORSENED":
            warnings.append(
                {
                    "code": "RES_DEFICIT_WORSENED",
                    "severity": "warning",
                    "metric": f"{element}_res",
                    "before": info.get("current"),
                    "after": info.get("candidate"),
                    "detail": f"{element} resistance already below cap → worse",
                    "cap_state": info.get("state"),
                    "baseline_deficit": info.get("baseline_deficit"),
                    "candidate_deficit": info.get("candidate_deficit"),
                    "deficit_delta": info.get("deficit_delta"),
                }
            )
        elif info.get("state") == "BELOW_CAP_IMPROVED":
            warnings.append(
                {
                    "code": "RES_DEFICIT_IMPROVED",
                    "severity": "info",
                    "metric": f"{element}_res",
                    "before": info.get("current"),
                    "after": info.get("candidate"),
                    "detail": f"{element} resistance below cap improved",
                    "cap_state": info.get("state"),
                }
            )
        elif info.get("state") == "CAP_REACHED":
            warnings.append(
                {
                    "code": "RES_CAP_REACHED",
                    "severity": "info",
                    "metric": f"{element}_res",
                    "before": info.get("current"),
                    "after": info.get("candidate"),
                    "detail": f"{element} resistance cap reached",
                    "cap_state": info.get("state"),
                }
            )

    ehp = metrics.get("ehp") or {}
    if _abs(ehp) < 0 and abs(_pct(ehp)) >= thresholds.defense_percent:
        warnings.append(
            {
                "code": "EHP_DOWN",
                "severity": "warning",
                "metric": "ehp",
                "before": ehp.get("current"),
                "after": ehp.get("candidate"),
                "detail": "effective hit pool decreased",
            }
        )

    worst = metrics.get("worst_max_hit") or {}
    if _abs(worst) < 0 and abs(_pct(worst)) >= thresholds.max_hit_percent:
        warnings.append(
            {
                "code": "MAX_HIT_DOWN",
                "severity": "warning",
                "metric": "worst_max_hit",
                "before": worst.get("current"),
                "after": worst.get("candidate"),
                "detail": "critical max hit decreased",
            }
        )

    life = metrics.get("life") or {}
    if _abs(life) < 0 and (abs(_pct(life)) >= thresholds.defense_percent or abs(_abs(life)) >= 10):
        warnings.append(
            {
                "code": "LIFE_DOWN",
                "severity": "warning",
                "metric": "life",
                "before": life.get("current"),
                "after": life.get("candidate"),
                "detail": "life decreased",
            }
        )

    es = metrics.get("energy_shield") or {}
    if _abs(es) < 0 and (abs(_pct(es)) >= thresholds.defense_percent or abs(_abs(es)) >= 10):
        warnings.append(
            {
                "code": "ENERGY_SHIELD_DOWN",
                "severity": "warning",
                "metric": "energy_shield",
                "before": es.get("current"),
                "after": es.get("candidate"),
                "detail": "energy shield decreased",
            }
        )

    chaos = (resist.get("elements") or {}).get("chaos") or {}
    chaos_metric = metrics.get("chaos_res") or {}
    if _abs(chaos_metric) < 0 and abs(_abs(chaos_metric)) >= thresholds.resistance_points:
        warnings.append(
            {
                "code": "CHAOS_RES_WORSE",
                "severity": "warning" if not chaos.get("effective_cap_lost") else "critical",
                "metric": "chaos_res",
                "before": chaos_metric.get("current"),
                "after": chaos_metric.get("candidate"),
                "detail": "chaos resistance decreased",
            }
        )

    move = metrics.get("movement_speed") or {}
    move_pct = _pct(move)
    if move_pct == 0 and _abs(move) != 0:
        current = _number(move.get("current"))
        candidate = _number(move.get("candidate"))
        if current is not None and candidate is not None and 0 < current <= 8 and 0 < candidate <= 8:
            move_pct = (candidate - current) * 100.0
    if move_pct < 0 and abs(move_pct) >= thresholds.movement_percent:
        warnings.append(
            {
                "code": "MOVEMENT_LOSS",
                "severity": "info",
                "metric": "movement_speed",
                "before": move.get("current"),
                "after": move.get("candidate"),
                "detail": "movement speed decreased",
            }
        )

    current_cost = _number(raw_current.get("ManaPerSecondCost"))
    candidate_cost = _number(raw_candidate.get("ManaPerSecondCost"))
    current_regen = _number(raw_current.get("ManaRegenRecovery"))
    candidate_regen = _number(raw_candidate.get("ManaRegenRecovery"))
    if (
        current_cost is not None
        and candidate_cost is not None
        and current_regen is not None
        and candidate_regen is not None
        and candidate_cost > 0
        and "ManaPerSecondCost" in raw_candidate
        and "ManaRegenRecovery" in raw_candidate
    ):
        current_ok = current_cost <= current_regen + 0.01
        candidate_fail = candidate_cost > candidate_regen + 0.01
        if current_ok and candidate_fail:
            warnings.append(
                {
                    "code": "RESOURCE_FAILURE",
                    "severity": "critical",
                    "metric": "mana_sustain",
                    "before": current_regen - current_cost,
                    "after": candidate_regen - candidate_cost,
                    "detail": "mana cost per second exceeds regen",
                }
            )

    warnings.extend(attribute_requirement_warnings(raw_current, raw_candidate))

    return warnings
