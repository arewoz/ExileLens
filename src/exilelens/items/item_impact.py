"""Interpret one exact PoB whole-item comparison without another worker call.

The weighted Build Value is a ranking/diagnostic signal. These axes describe
measured build-state changes and keep requirements separate from that number.
Optional outputs never become evidence merely because PoB names a field.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Any

from exilelens.items.requirement_gates import ATTR_FIELDS
from exilelens.items.guardrails import RES_MATERIAL_DEFICIT_POINTS
from exilelens.items.value_profiles import CONTRIBUTION_SCALES


@dataclass(frozen=True)
class ImpactThresholds:
    # The 3% offense edge is ranking's clear-change edge. A 3% EHP movement
    # contributes about 2.5 Balanced score points (10% saturation, 0.25 weight,
    # 67.5 point multiplier), near the existing three-point minor-verdict edge.
    # Recovery is optional and uses that same conservative change edge.
    offense_pct: float = 3.0
    defense_pct: float = 3.0
    recovery_pct: float = 3.0
    movement_pct: float = CONTRIBUTION_SCALES["movement"]
    resistance_deficit_points: float = RES_MATERIAL_DEFICIT_POINTS
    noise_pct: float = 0.25


IMPACT_THRESHOLDS = ImpactThresholds()


@dataclass(frozen=True)
class ImpactMetric:
    key: str
    current: float | None
    candidate: float | None
    percent_delta: float | None
    support: str
    absolute_delta: float | None = None
    reason: str = ""


@dataclass(frozen=True)
class ImpactAxis:
    axis: str
    support: str
    direction: str
    magnitude_pct: float | None
    significant: bool
    metrics: tuple[ImpactMetric, ...]
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImpactConstraint:
    code: str
    support: str
    status: str
    metric: str
    detail: str
    critical: bool = False


@dataclass(frozen=True)
class ItemImpact:
    axes: dict[str, ImpactAxis]
    constraints: tuple[ImpactConstraint, ...]
    pattern: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_UNMEASURED_OFFENSE = frozenset({"MISSING", "UNMEASURED", "UNSUPPORTED", "ESTIMATED"})


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _raw(raw: dict[str, Any], key: str) -> float | None:
    return _number(raw[key]) if key in raw else None


def _metric(profile: dict[str, Any], key: str) -> ImpactMetric:
    entry = profile.get(key) or {}
    current = _number(entry.get("current"))
    candidate = _number(entry.get("candidate"))
    kind = str(entry.get("delta_kind") or "MEASURED")
    if kind == "UNSUPPORTED":
        support = "UNSUPPORTED"
    elif kind in _UNMEASURED_OFFENSE or current is None or candidate is None or entry.get("availability") == "missing":
        support = "UNMEASURED"
    else:
        support = "MEASURED"
    return ImpactMetric(key, current, candidate, _number(entry.get("percent_delta")), support,
                        _number(entry.get("absolute_delta")))


def _raw_metric(current: dict[str, Any], candidate: dict[str, Any], key: str) -> ImpactMetric:
    before, after = _raw(current, key), _raw(candidate, key)
    pct = (after / before - 1.0) * 100.0 if before not in (None, 0.0) and after is not None else None
    return ImpactMetric(key, before, after, pct, "MEASURED" if before is not None and after is not None else "UNMEASURED",
                        after - before if before is not None and after is not None else None)


def _axis(axis: str, metrics: tuple[ImpactMetric, ...], threshold: float, reasons: tuple[str, ...] = (),
          noise: float = IMPACT_THRESHOLDS.noise_pct) -> ImpactAxis:
    measured = [metric for metric in metrics if metric.support == "MEASURED"]
    if not measured:
        support = "UNSUPPORTED" if any(metric.support == "UNSUPPORTED" for metric in metrics) else "UNMEASURED"
        return ImpactAxis(axis, support, "UNKNOWN", None, False, metrics, reasons)
    pct_values = [metric.percent_delta for metric in measured if metric.percent_delta is not None]
    if not pct_values:
        return ImpactAxis(axis, "MEASURED", "NEUTRAL", None, False, metrics, reasons)
    positive = [pct for pct in pct_values if pct > noise]
    negative = [pct for pct in pct_values if pct < -noise]
    direction = "MIXED" if positive and negative else "POSITIVE" if positive else "NEGATIVE" if negative else "NEUTRAL"
    magnitude = max(pct_values, key=abs)
    significant = any(abs(pct) >= threshold for pct in pct_values)
    return ImpactAxis(axis, "MEASURED", direction, round(magnitude, 4), significant, metrics, reasons)


def _resistance_reasons(resist: dict[str, Any]) -> tuple[str, ...]:
    reasons = []
    for element, info in (resist.get("elements") or {}).items():
        state = str((info or {}).get("state") or "UNKNOWN")
        if state in {"CAP_REACHED", "BELOW_CAP_IMPROVED"}:
            reasons.append(f"{element} resistance helps close a deficit ({state})")
        elif state in {"CAP_LOST", "BELOW_CAP_WORSENED"}:
            reasons.append(f"{element} resistance leaves or deepens a deficit ({state})")
        elif state in {"CAPPED_STAYS_CAPPED", "OVER_CAP_REDUCED_BUT_STILL_CAPPED"}:
            reasons.append(f"{element} resistance remains capped; buffer is flexibility only")
    return tuple(reasons)


def _resistance_metric(resist: dict[str, Any]) -> ImpactMetric:
    # The resistance state, rather than uncapped affix points, decides utility.
    states = [str((info or {}).get("state") or "UNKNOWN") for info in (resist.get("elements") or {}).values()]
    if not states or "UNKNOWN" in states:
        return ImpactMetric("resistance_target", None, None, None, "UNMEASURED")
    helpful = {"CAP_REACHED", "BELOW_CAP_IMPROVED"}
    harmful = {"CAP_LOST", "BELOW_CAP_WORSENED"}
    before = 0.0
    after = 1.0 if any(state in helpful for state in states) else -1.0 if any(state in harmful for state in states) else 0.0
    return ImpactMetric("resistance_target", before, after, None, "MEASURED", after)


def _resistance_direction(resist: dict[str, Any], material_points: float) -> tuple[str, bool]:
    ups = downs = material = False
    for info in (resist.get("elements") or {}).values():
        state = str((info or {}).get("state") or "UNKNOWN")
        if state in {"CAP_REACHED", "BELOW_CAP_IMPROVED"}:
            ups = True
        elif state in {"CAP_LOST", "BELOW_CAP_WORSENED"}:
            downs = True
        if state in {"CAP_REACHED", "CAP_LOST"}:
            material = True
        elif state in {"BELOW_CAP_IMPROVED", "BELOW_CAP_WORSENED"}:
            change = _number((info or {}).get("deficit_delta"))
            material |= change is not None and abs(change) >= material_points
    direction = "MIXED" if ups and downs else "POSITIVE" if ups else "NEGATIVE" if downs else "NEUTRAL"
    return direction, material


def _requirement_constraints(before: dict[str, Any], after: dict[str, Any]) -> tuple[ImpactConstraint, ...]:
    rows = []
    seen: set[str] = set()
    for field, name in ATTR_FIELDS:
        if name in seen:
            continue
        current, candidate = _raw(before, field), _raw(after, field)
        required = _raw(after, f"{field}Req")
        if required is None:
            required = _raw(after, f"Required{field}")
        if required is None:
            required = _raw(before, f"{field}Req")
        if required is None:
            required = _raw(before, f"Required{field}")
        missing = _raw(after, f"Missing{field}")
        if required is None and missing is None:
            continue
        if candidate is None and missing is None:
            continue
        seen.add(name)
        deficit = missing if missing is not None else max(0.0, required - candidate)
        status = "BROKEN" if deficit > 0.05 else "SATISFIED"
        detail = f"{name.title()} requirement {'not met' if status == 'BROKEN' else 'met'}"
        if required is not None and candidate is not None:
            detail += f" ({candidate:g}/{required:g})"
        rows.append(ImpactConstraint("ATTRIBUTE_REQUIREMENT", "MEASURED", status, name, detail,
                                     critical=status == "BROKEN"))
    return tuple(rows)


def interpret_item_impact(
    metric_profile: dict[str, Any], resist: dict[str, Any],
    raw_current: dict[str, Any], raw_candidate: dict[str, Any],
    *, guardrails: list[dict[str, Any]] = (), thresholds: ImpactThresholds = IMPACT_THRESHOLDS,
) -> ItemImpact:
    offense = _axis("OFFENSE", (_metric(metric_profile, "primary_offense"),), thresholds.offense_pct,
                    noise=thresholds.noise_pct)
    # Life and ES explain the change, but EHP and max hit are the established
    # survivability decision metrics. A life gain cannot erase an EHP collapse.
    defense = _axis("DEFENSE", tuple(_metric(metric_profile, key) for key in ("ehp", "worst_max_hit")),
                    thresholds.defense_pct, noise=thresholds.noise_pct)
    defense = replace(defense, metrics=defense.metrics +
                      tuple(_metric(metric_profile, key) for key in ("life", "energy_shield")))
    recovery = _axis("RECOVERY", (_raw_metric(raw_current, raw_candidate, "LifeRegenRecovery"),),
                     thresholds.recovery_pct, noise=thresholds.noise_pct)
    movement = _metric(metric_profile, "movement_speed")
    if movement.support == "MEASURED" and movement.current is not None and movement.candidate is not None:
        if 0 < movement.current <= 8 and 0 < movement.candidate <= 8:
            movement = ImpactMetric(movement.key, movement.current, movement.candidate,
                                    round((movement.candidate - movement.current) * 100.0, 4), movement.support,
                                    movement.absolute_delta)
    resistance = _resistance_metric(resist)
    utility = _axis("UTILITY", (movement, resistance), thresholds.movement_pct, _resistance_reasons(resist),
                    noise=thresholds.noise_pct)
    # Resistance target movement is categorical. A capped buffer is not a target gain.
    target_direction, target_significant = _resistance_direction(resist, thresholds.resistance_deficit_points)
    if resistance.support == "MEASURED" and target_direction != "NEUTRAL":
        direction = "MIXED" if utility.direction not in {"NEUTRAL", target_direction} else target_direction
        utility = ImpactAxis("UTILITY", "MEASURED", direction,
                             utility.magnitude_pct, utility.significant or target_significant,
                             utility.metrics, utility.reasons)

    constraints = list(_requirement_constraints(raw_current, raw_candidate))
    for row in guardrails:
        code = str(row.get("code") or "")
        if code in {"MAIN_SKILL_INVALID", "RESOURCE_SUSTAIN_LOST", "ATTRIBUTE_REQUIREMENT_LOST"}:
            supported = True
            if code == "MAIN_SKILL_INVALID":
                supported = offense.support == "MEASURED"
            elif code == "RESOURCE_SUSTAIN_LOST":
                supported = all(_raw(raw, key) is not None for raw in (raw_current, raw_candidate)
                                for key in ("ManaPerSecondCost", "ManaRegenRecovery"))
            elif code == "ATTRIBUTE_REQUIREMENT_LOST":
                supported = any(item.code == "ATTRIBUTE_REQUIREMENT" and item.status == "BROKEN"
                                for item in constraints)
            constraints.append(ImpactConstraint(code, "MEASURED" if supported else "UNMEASURED",
                                                "BROKEN" if supported else "UNKNOWN", str(row.get("metric") or ""),
                                                str(row.get("reason") or code), critical=supported))
    axes = {axis.axis: axis for axis in (offense, defense, recovery, utility)}
    core = (offense, defense)
    if recovery.support == "MEASURED":
        core += (recovery,)
    if utility.support == "MEASURED":
        core += (utility,)
    ups = [axis for axis in core if axis.significant and axis.direction == "POSITIVE"]
    downs = [axis for axis in core if axis.significant and axis.direction == "NEGATIVE"]
    if any(axis.significant and axis.direction == "MIXED" for axis in core) or (ups and downs):
        pattern = "TRADEOFF"
    elif ups and not downs:
        pattern = "BROAD_UPGRADE" if len(ups) > 1 else "SINGLE_AXIS_UPGRADE"
    elif downs and not ups:
        pattern = "BROAD_DOWNGRADE" if len(downs) > 1 else "SINGLE_AXIS_DOWNGRADE"
    elif any(axis.direction not in {"NEUTRAL", "UNKNOWN"} for axis in core):
        pattern = "MINOR_CHANGE"
    else:
        pattern = "NEUTRAL"
    reasons_list = []
    for axis in core:
        if not axis.significant:
            continue
        if axis.direction == "MIXED":
            reasons_list.extend(f"{metric.key} {metric.percent_delta:+.1f}%" for metric in axis.metrics
                                if metric.support == "MEASURED" and metric.percent_delta is not None
                                and abs(metric.percent_delta) > thresholds.noise_pct)
            reasons_list.extend(axis.reasons)
        elif axis.magnitude_pct is not None and abs(axis.magnitude_pct) > thresholds.noise_pct:
            reasons_list.append(f"{axis.axis.lower()} {axis.magnitude_pct:+.1f}%")
        elif axis.reasons:
            reasons_list.extend(axis.reasons)
    reasons = tuple(reasons_list)
    return ItemImpact(axes, tuple(constraints), pattern, reasons)
