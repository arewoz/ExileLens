from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DisplayThresholds:
    """Visual suppression only — raw calculation results are never discarded."""

    offense_percent: float = 0.5
    defense_percent: float = 0.5
    resistance_points: float = 0.5
    movement_percent: float = 0.4
    max_hit_percent: float = 0.5
    resource_percent: float = 1.0
    max_overlay_rows: int = 6


DEFAULT_DISPLAY_THRESHOLDS = DisplayThresholds()


def is_display_worthy(
    *,
    key: str,
    absolute_delta: float,
    percent_delta: float | None,
    forced: bool = False,
    thresholds: DisplayThresholds = DEFAULT_DISPLAY_THRESHOLDS,
) -> bool:
    if forced:
        return True
    abs_delta = abs(absolute_delta)
    pct = abs(percent_delta) if percent_delta is not None else None
    if key == "primary_offense":
        if pct is None:
            return abs_delta > 0
        return pct >= thresholds.offense_percent or abs_delta >= 1
    if key in {"ehp", "life", "energy_shield", "physical_max_hit", "fire_max_hit", "cold_max_hit", "lightning_max_hit", "chaos_max_hit", "worst_max_hit"}:
        if pct is not None:
            return pct >= thresholds.defense_percent or abs_delta >= 1
        return abs_delta >= 1
    if key.endswith("_res") or key.endswith("_resist"):
        return abs_delta >= thresholds.resistance_points
    if key == "movement_speed":
        if pct is not None:
            return pct >= thresholds.movement_percent
        return abs_delta >= 0.004
    if pct is not None:
        return pct >= thresholds.resource_percent
    return abs_delta >= 1
