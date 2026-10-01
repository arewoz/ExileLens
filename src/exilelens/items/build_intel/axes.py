"""Multi-axis deltas from exact PoB metrics. Profiles may rank; axes stay raw."""

from __future__ import annotations

from typing import Any

from exilelens.items.build_intel.models import AxisDelta, AxisId


def _entry(profile: dict[str, Any], key: str) -> dict[str, Any]:
    return dict(profile.get(key) or {})


def _raw(metrics: dict[str, Any], field: str) -> float | None:
    if field not in metrics:
        return None
    value = metrics.get(field)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pair(current: float | None, candidate: float | None) -> tuple[float | None, float | None]:
    if current is None or candidate is None:
        return None, None
    absolute = candidate - current
    percent = None
    if current not in (0, 0.0):
        # Relative to the size of the baseline: a sustain of -30.5 improving to -29.7 is +2.6%, not -2.6%.
        # (The old `candidate / current - 1` inverted the sign for every negative baseline.)
        percent = (candidate - current) / abs(current) * 100.0
    return absolute, percent


def _axis_from_metric(
    *,
    axis: str,
    label: str,
    metric: dict[str, Any],
    default_kind: str = "MEASURED",
) -> AxisDelta:
    availability = str(metric.get("availability") or "available")
    if availability == "missing":
        return AxisDelta(axis=axis, label=label, availability="missing", delta_kind="MISSING")
    current = metric.get("current")
    candidate = metric.get("candidate")
    return AxisDelta(
        axis=axis,
        current=float(current) if current is not None else None,
        candidate=float(candidate) if candidate is not None else None,
        absolute_delta=float(metric["absolute_delta"]) if metric.get("absolute_delta") is not None else None,
        percent_delta=float(metric["percent_delta"]) if metric.get("percent_delta") is not None else None,
        availability=availability,
        delta_kind=str(metric.get("delta_kind") or default_kind),
        label=label,
    )


def _movement_pct(metric: dict[str, Any]) -> float | None:
    current = metric.get("current")
    candidate = metric.get("candidate")
    if current is None or candidate is None:
        return metric.get("percent_delta") if metric.get("percent_delta") is not None else None
    cur = float(current)
    cand = float(candidate)
    if 0 < cur <= 8 and 0 < cand <= 8:
        return (cand - cur) * 100.0
    return float(metric["percent_delta"]) if metric.get("percent_delta") is not None else None


def build_axes(
    metric_profile: dict[str, Any],
    *,
    raw_current: dict[str, Any] | None = None,
    raw_candidate: dict[str, Any] | None = None,
    score_delta: float | None = None,
) -> dict[str, AxisDelta]:
    raw_current = raw_current or {}
    raw_candidate = raw_candidate or {}
    offense = _axis_from_metric(
        axis=AxisId.OFFENSE.value,
        label="Offense",
        metric=_entry(metric_profile, "primary_offense"),
    )
    ehp = _axis_from_metric(axis=AxisId.DEFENCE.value, label="Defence", metric=_entry(metric_profile, "ehp"))
    move_metric = _entry(metric_profile, "movement_speed")
    move = _axis_from_metric(axis=AxisId.MOBILITY.value, label="Mobility", metric=move_metric)
    move_pct = _movement_pct(move_metric)
    if move_pct is not None:
        move.percent_delta = move_pct

    cur_cost = _raw(raw_current, "ManaPerSecondCost")
    cand_cost = _raw(raw_candidate, "ManaPerSecondCost")
    cur_regen = _raw(raw_current, "ManaRegenRecovery")
    cand_regen = _raw(raw_candidate, "ManaRegenRecovery")
    resource_kind = "UNMEASURED"
    resource_avail = "missing"
    sustain_cur = None
    sustain_cand = None
    if cur_cost is not None and cand_cost is not None and cur_regen is not None and cand_regen is not None:
        resource_kind = "MEASURED"
        resource_avail = "available"
        sustain_cur = cur_regen - cur_cost
        sustain_cand = cand_regen - cand_cost
    abs_res, pct_res = _pair(sustain_cur, sustain_cand)
    resource = AxisDelta(
        axis=AxisId.RESOURCE.value,
        current=sustain_cur,
        candidate=sustain_cand,
        absolute_delta=abs_res,
        percent_delta=pct_res,
        availability=resource_avail,
        delta_kind=resource_kind,
        label="Resource",
    )

    cur_life_regen = _raw(raw_current, "LifeRegenRecovery")
    cand_life_regen = _raw(raw_candidate, "LifeRegenRecovery")
    if cur_life_regen is None:
        cur_life_regen = _raw(raw_current, "LifeRecovery")
    if cand_life_regen is None:
        cand_life_regen = _raw(raw_candidate, "LifeRecovery")
    cur_es_regen = _raw(raw_current, "EnergyShieldRegenRecovery")
    cand_es_regen = _raw(raw_candidate, "EnergyShieldRegenRecovery")

    def recovery_component(label: str, before: float | None, after: float | None) -> AxisDelta:
        absolute, percent = _pair(before, after)
        return AxisDelta(
            axis=AxisId.RECOVERY.value,
            current=before,
            candidate=after,
            absolute_delta=absolute,
            percent_delta=percent,
            availability="available" if before is not None and after is not None else "missing",
            delta_kind="MEASURED" if before is not None and after is not None else "UNMEASURED",
            label=label,
        )

    # Recovery has no honest common unit: retain Life and ES regeneration as named, independent values.
    recovery = AxisDelta(
        axis=AxisId.RECOVERY.value,
        availability="available",
        delta_kind="COMPOSITE",
        label="Recovery",
        components={
            "life_regen": recovery_component("Life Regen", cur_life_regen, cand_life_regen),
            "energy_shield_regen": recovery_component("Energy Shield Regen", cur_es_regen, cand_es_regen),
        },
    )

    mana = _entry(metric_profile, "mana")
    utility = AxisDelta(
        axis=AxisId.UTILITY.value,
        current=mana.get("current"),
        candidate=mana.get("candidate"),
        absolute_delta=float(mana["absolute_delta"]) if mana.get("absolute_delta") is not None else None,
        percent_delta=float(mana["percent_delta"]) if metric_profile.get("mana") and mana.get("percent_delta") is not None else None,
        availability=str(mana.get("availability") or "missing"),
        delta_kind="MEASURED" if mana.get("availability") != "missing" else "MISSING",
        label="Utility",
    )

    overall = AxisDelta(
        axis=AxisId.OVERALL.value,
        current=50.0,
        candidate=(50.0 + float(score_delta)) if score_delta is not None else None,
        absolute_delta=score_delta,
        percent_delta=score_delta,
        availability="available" if score_delta is not None else "missing",
        delta_kind="WEIGHTED" if score_delta is not None else "MISSING",
        label="Build Value",
    )
    return {
        AxisId.OVERALL.value: overall,
        AxisId.OFFENSE.value: offense,
        AxisId.DEFENCE.value: ehp,
        AxisId.RECOVERY.value: recovery,
        AxisId.RESOURCE.value: resource,
        AxisId.MOBILITY.value: move,
        AxisId.UTILITY.value: utility,
    }


def pareto_status(axes: dict[str, AxisDelta], *, hard_break: bool) -> str:
    if hard_break:
        return "HARD_CONSTRAINT"
    tracked = (AxisId.OFFENSE.value, AxisId.DEFENCE.value, AxisId.RECOVERY.value, AxisId.RESOURCE.value, AxisId.MOBILITY.value)
    ups = 0
    downs = 0
    for key in tracked:
        axis = axes.get(key)
        if not axis or axis.delta_kind in {"UNMEASURED", "UNSUPPORTED", "MISSING", "ESTIMATED"}:
            continue
        pct = axis.percent_delta
        abs_delta = axis.absolute_delta or 0.0
        if pct is None:
            if abs_delta > 0.01:
                ups += 1
            elif abs_delta < -0.01:
                downs += 1
            continue
        if pct >= 0.5:
            ups += 1
        elif pct <= -0.5:
            downs += 1
    if ups and not downs:
        return "DOMINATES"
    if downs and not ups:
        return "DOMINATED"
    if ups and downs:
        return "TRADEOFF"
    return "NEITHER_DOMINATES"
