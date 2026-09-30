"""Interpret one exact PoB whole-item comparison without another worker call.

The weighted Build Value is a ranking/diagnostic signal. These axes describe
measured build-state changes and keep requirements separate from that number.
Optional outputs never become evidence merely because PoB names a field.

Three questions are kept apart (SCORING-01a):

* direction   - which way an axis moved (unchanged labels);
* materiality - whether that movement is big enough to count as a real gain or loss;
* conflict    - whether a material gain and a material loss both exist. Only then is there a
                two-sided conflict (``ConflictAssessment.kind == "MATERIAL"``); opposing but
                non-material changes are recorded as ``negligible_opposition`` and stay
                explanatory. ``pattern`` remains the descriptive, backward-compatible label.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable, Iterable, Mapping

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
    # Recovery is material only when its change is also a real part of the life pool, not just a large
    # percentage of a tiny regeneration: |change in life regeneration per second| as a percentage of the
    # baseline maximum Life. 0.5 (% of maximum Life per second) restores, over a short ~6 second
    # engagement, the same 3% of the pool that `defense_pct` treats as a significant defensive change.
    # A provisional value chosen from that gameplay meaning; it is deliberately not fitted to the corpus.
    recovery_pool_pct: float = 0.5
    movement_pct: float = CONTRIBUTION_SCALES["movement"]
    resistance_deficit_points: float = RES_MATERIAL_DEFICIT_POINTS
    noise_pct: float = 0.25


IMPACT_THRESHOLDS = ImpactThresholds()


# Life pools at or below this are not a real pool to regenerate (Chaos Inoculation builds report 1).
MIN_LIFE_POOL = 1.0

CONFLICT_NONE = "NONE"
CONFLICT_MATERIAL = "MATERIAL"


@dataclass(frozen=True)
class ImpactMetric:
    key: str
    current: float | None
    candidate: float | None
    percent_delta: float | None
    support: str
    absolute_delta: float | None = None
    reason: str = ""
    # Size of the change as a percentage of the baseline pool per second (recovery only).
    pool_pct: float | None = None


@dataclass(frozen=True)
class ImpactAxis:
    axis: str
    support: str
    direction: str
    magnitude_pct: float | None
    significant: bool
    metrics: tuple[ImpactMetric, ...]
    reasons: tuple[str, ...] = ()
    # Materiality (SCORING-01a). A MIXED axis is material in a direction only if a component of that
    # direction reaches the axis threshold (and, for recovery, the pool gate).
    material_positive: bool = False
    material_negative: bool = False

    @property
    def materiality(self) -> str:
        return "MATERIAL" if self.material_positive or self.material_negative else "NEGLIGIBLE"


@dataclass(frozen=True)
class ImpactConstraint:
    code: str
    support: str
    status: str
    metric: str
    detail: str
    critical: bool = False


@dataclass(frozen=True)
class NegligibleOpposition:
    """A measured change that runs against the material effects but is not big enough to offset them."""

    axis: str
    metric: str
    direction: str
    percent_delta: float | None
    absolute_delta: float | None
    pool_pct: float | None
    why: str
    text: str


@dataclass(frozen=True)
class ConflictAssessment:
    kind: str = CONFLICT_NONE
    positive_axes: tuple[str, ...] = ()
    negative_axes: tuple[str, ...] = ()
    # The material drivers only, for the "Meaningful trade-off" wording.
    reasons: tuple[str, ...] = ()
    negligible_opposition: tuple[NegligibleOpposition, ...] = ()


@dataclass(frozen=True)
class ItemImpact:
    axes: dict[str, ImpactAxis]
    constraints: tuple[ImpactConstraint, ...]
    pattern: str
    reasons: tuple[str, ...]
    conflict: ConflictAssessment = ConflictAssessment()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for name, axis in self.axes.items():
            payload["axes"][name]["materiality"] = axis.materiality
        return payload


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


def _recovery_metric(current: dict[str, Any], candidate: dict[str, Any]) -> ImpactMetric:
    """Life regeneration per second, with its change expressed against the baseline Life pool.

    ``pool_pct`` stays None when PoB gave no usable Life pool (missing, or a Chaos Inoculation style
    pool of 1): nothing is invented, and the recovery change then cannot be material.
    """
    metric = _raw_metric(current, candidate, "LifeRegenRecovery")
    life = _raw(current, "Life")
    if metric.absolute_delta is None or life is None or life <= MIN_LIFE_POOL:
        return metric
    return replace(metric, pool_pct=abs(metric.absolute_delta) * 100.0 / life)


def _axis(axis: str, metrics: tuple[ImpactMetric, ...], threshold: float, reasons: tuple[str, ...] = (),
          noise: float = IMPACT_THRESHOLDS.noise_pct,
          gate: Callable[[ImpactMetric], bool] | None = None) -> ImpactAxis:
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
    material_positive = any(_is_material(metric, 1, threshold, gate) for metric in measured)
    material_negative = any(_is_material(metric, -1, threshold, gate) for metric in measured)
    return ImpactAxis(axis, "MEASURED", direction, round(magnitude, 4), significant, metrics, reasons,
                      material_positive, material_negative)


def _is_material(metric: ImpactMetric, sign: int, threshold: float,
                 gate: Callable[[ImpactMetric], bool] | None) -> bool:
    """One metric counts as a real gain (sign +1) or loss (-1): it clears the axis threshold and any absolute gate."""
    pct = metric.percent_delta
    if pct is None or sign * pct < threshold:
        return False
    return gate is None or gate(metric)


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


def _resistance_direction(resist: dict[str, Any], material_points: float) -> tuple[str, bool, bool, bool]:
    """(direction, any material, material gain, material loss) of the resistance target states."""
    ups = downs = material = material_up = material_down = False
    for info in (resist.get("elements") or {}).values():
        state = str((info or {}).get("state") or "UNKNOWN")
        is_material = False
        if state in {"CAP_REACHED", "BELOW_CAP_IMPROVED"}:
            ups = True
        elif state in {"CAP_LOST", "BELOW_CAP_WORSENED"}:
            downs = True
        if state in {"CAP_REACHED", "CAP_LOST"}:
            is_material = True
        elif state in {"BELOW_CAP_IMPROVED", "BELOW_CAP_WORSENED"}:
            change = _number((info or {}).get("deficit_delta"))
            is_material = change is not None and abs(change) >= material_points
        if is_material:
            material = True
            if state in {"CAP_REACHED", "BELOW_CAP_IMPROVED"}:
                material_up = True
            elif state in {"CAP_LOST", "BELOW_CAP_WORSENED"}:
                material_down = True
    direction = "MIXED" if ups and downs else "POSITIVE" if ups else "NEGATIVE" if downs else "NEUTRAL"
    return direction, material, material_up, material_down


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


_METRIC_LABELS = {
    "primary_offense": "offense",
    "ehp": "EHP",
    "worst_max_hit": "max hit",
    "movement_speed": "movement",
    "LifeRegenRecovery": "recovery",
}


def _metric_text(metric: ImpactMetric) -> str:
    label = _METRIC_LABELS.get(metric.key, metric.key)
    if metric.key == "LifeRegenRecovery" and metric.absolute_delta is not None:
        text = f"{label} {metric.absolute_delta:+.1f} life/s"
        if metric.pool_pct is not None:
            text += f" ({metric.pool_pct:.2f}% of max Life per second)"
        return text
    return f"{label} {metric.percent_delta:+.1f}%" if metric.percent_delta is not None else label


def _axis_threshold(axis: str, thresholds: ImpactThresholds) -> float:
    return {"OFFENSE": thresholds.offense_pct, "DEFENSE": thresholds.defense_pct,
            "RECOVERY": thresholds.recovery_pct, "UTILITY": thresholds.movement_pct}.get(axis, 0.0)


def _axis_reasons(axis: ImpactAxis, thresholds: ImpactThresholds, *, material_only: bool = False) -> list[str]:
    """Human-readable movement of one axis. ``material_only`` lists just the components that count."""
    if material_only:
        if not (axis.material_positive or axis.material_negative):
            return []
    elif not axis.significant:
        return []
    if axis.direction == "MIXED":
        limit = _axis_threshold(axis.axis, thresholds) if material_only else thresholds.noise_pct
        rows = [f"{metric.key} {metric.percent_delta:+.1f}%" for metric in axis.metrics
                if metric.support == "MEASURED" and metric.percent_delta is not None
                and abs(metric.percent_delta) > thresholds.noise_pct and abs(metric.percent_delta) >= limit]
        return rows + list(axis.reasons)
    if axis.magnitude_pct is not None and abs(axis.magnitude_pct) > thresholds.noise_pct:
        return [f"{axis.axis.lower()} {axis.magnitude_pct:+.1f}%"]
    return list(axis.reasons)


def _recovery_gate(thresholds: ImpactThresholds) -> Callable[[ImpactMetric], bool]:
    def gate(metric: ImpactMetric) -> bool:
        return metric.pool_pct is not None and metric.pool_pct >= thresholds.recovery_pool_pct

    return gate


_EXPLANATORY_ONLY = frozenset({"life", "energy_shield"})


def _assess_conflict(core: tuple[ImpactAxis, ...], thresholds: ImpactThresholds) -> ConflictAssessment:
    positive = tuple(axis.axis for axis in core if axis.material_positive)
    negative = tuple(axis.axis for axis in core if axis.material_negative)
    kind = CONFLICT_MATERIAL if positive and negative else CONFLICT_NONE

    # A measured change that opposes a material effect but is not material itself is kept, not dropped.
    negligible: list[NegligibleOpposition] = []
    for axis in core:
        gate = _recovery_gate(thresholds) if axis.axis == "RECOVERY" else None
        limit = _axis_threshold(axis.axis, thresholds)
        for metric in axis.metrics:
            pct = metric.percent_delta
            if metric.key in _EXPLANATORY_ONLY:
                continue  # Life / Energy Shield explain the defence change but never decide direction
            if metric.support != "MEASURED" or pct is None or abs(pct) <= thresholds.noise_pct:
                continue
            sign = 1 if pct > 0 else -1
            if _is_material(metric, sign, limit, gate):
                continue
            if not (negative if sign > 0 else positive):
                continue  # nothing material on the other side for it to oppose
            negligible.append(NegligibleOpposition(
                axis=axis.axis, metric=metric.key, direction="POSITIVE" if sign > 0 else "NEGATIVE",
                percent_delta=round(pct, 4), absolute_delta=metric.absolute_delta,
                pool_pct=None if metric.pool_pct is None else round(metric.pool_pct, 4),
                why="BELOW_AXIS_THRESHOLD" if abs(pct) < limit else "BELOW_POOL_FLOOR",
                text=_metric_text(metric),
            ))
    reasons: list[str] = []
    if kind == CONFLICT_MATERIAL:
        for axis in core:
            reasons.extend(_axis_reasons(axis, thresholds, material_only=True))
    return ConflictAssessment(kind, positive, negative, tuple(reasons), tuple(negligible))


def negligible_opposition_note(records: Iterable[Mapping[str, Any]]) -> str:
    """One truthful sentence for opposing changes that were measured but cannot offset the main effects."""
    texts = [str(record.get("text") or "") for record in records if record.get("text")]
    if not texts:
        return ""
    return "Small opposing change not large enough to offset: " + ", ".join(texts[:2]) + "."


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
    # Recovery is material only when the change is also a real part of the Life pool per second.
    recovery = _axis("RECOVERY", (_recovery_metric(raw_current, raw_candidate),),
                     thresholds.recovery_pct, noise=thresholds.noise_pct, gate=_recovery_gate(thresholds))
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
    target_direction, target_significant, target_up, target_down = _resistance_direction(
        resist, thresholds.resistance_deficit_points)
    if resistance.support == "MEASURED" and target_direction != "NEUTRAL":
        direction = "MIXED" if utility.direction not in {"NEUTRAL", target_direction} else target_direction
        utility = ImpactAxis("UTILITY", "MEASURED", direction,
                             utility.magnitude_pct, utility.significant or target_significant,
                             utility.metrics, utility.reasons,
                             utility.material_positive or target_up, utility.material_negative or target_down)

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
    # `pattern` is the descriptive, backward-compatible label ("there is a trade-off"). Whether the
    # opposition is real is `conflict`, which is what decides the public verdict.
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
    reasons_list: list[str] = []
    for axis in core:
        reasons_list.extend(_axis_reasons(axis, thresholds))
    return ItemImpact(axes, tuple(constraints), pattern, tuple(reasons_list), _assess_conflict(core, thresholds))
