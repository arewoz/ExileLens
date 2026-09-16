"""Product verdict + significance. Ranking verdict stays for regression."""

from __future__ import annotations

from poe2value.items.build_intel.models import (
    AxisDelta,
    AxisId,
    BuildVerdict,
    HardConstraint,
    Significance,
    ThresholdEvent,
    UPGRADE_VERDICTS,
)
from poe2value.items.build_intel.constraints import blocking_problems, unsafe_problems


def _pct(axis: AxisDelta | None) -> float:
    if not axis or axis.percent_delta is None:
        return 0.0
    if axis.delta_kind in {"UNMEASURED", "UNSUPPORTED", "MISSING", "ESTIMATED"}:
        return 0.0
    return float(axis.percent_delta)


def _abs(axis: AxisDelta | None) -> float:
    if not axis or axis.absolute_delta is None:
        return 0.0
    return float(axis.absolute_delta)


def classify_significance(
    axes: dict[str, AxisDelta],
    *,
    build_fixes: list[ThresholdEvent],
    hard_problems: list[HardConstraint],
) -> Significance:
    if blocking_problems(hard_problems) or unsafe_problems(hard_problems):
        return Significance.STRATEGIC
    if build_fixes:
        return Significance.STRATEGIC
    offense = _pct(axes.get(AxisId.OFFENSE.value))
    defence = _pct(axes.get(AxisId.DEFENCE.value))
    mobility = _pct(axes.get(AxisId.MOBILITY.value))
    resource = _pct(axes.get(AxisId.RESOURCE.value))
    recovery = _pct(axes.get(AxisId.RECOVERY.value))
    best = max(abs(offense), abs(defence), abs(mobility), abs(resource), abs(recovery))
    if best >= 12.0 or (abs(offense) >= 8.0 and abs(defence) >= 8.0):
        return Significance.MAJOR
    if best >= 3.0:
        return Significance.MEANINGFUL
    if best >= 1.0:
        return Significance.MINOR
    return Significance.TRIVIAL


def classify_product_verdict(
    *,
    ranking_verdict: str,
    axes: dict[str, AxisDelta],
    build_fixes: list[ThresholdEvent],
    hard_problems: list[HardConstraint],
    score_delta: float | None = None,
) -> BuildVerdict:
    blocked = blocking_problems(hard_problems)
    unsafe = unsafe_problems(hard_problems)
    if blocked:
        return BuildVerdict.BLOCKED
    if unsafe:
        return BuildVerdict.UNSAFE

    significance = classify_significance(axes, build_fixes=build_fixes, hard_problems=hard_problems)
    offense = _pct(axes.get(AxisId.OFFENSE.value))
    defence = _pct(axes.get(AxisId.DEFENCE.value))
    mobility = _pct(axes.get(AxisId.MOBILITY.value))
    ranking = str(ranking_verdict or "")

    if build_fixes:
        severe_loss = offense <= -8.0 or defence <= -8.0
        if not severe_loss:
            if ranking in {"TRADEOFF", "SIDEGRADE", "NO_CHANGE", "UNRESOLVED", "DOWNGRADE"}:
                return BuildVerdict.BUILD_FIX
            if abs(offense) < 3.0 and abs(defence) < 3.0:
                return BuildVerdict.BUILD_FIX

    if ranking in {"DOWNGRADE", "STRONG_DOWNGRADE"}:
        if build_fixes and significance == Significance.STRATEGIC and offense > -3 and defence > -3:
            return BuildVerdict.BUILD_FIX
        return BuildVerdict.DOWNGRADE

    if ranking == "TRADEOFF":
        return BuildVerdict.TRADEOFF

    if ranking in {"SIDEGRADE", "NO_CHANGE", "UNRESOLVED"}:
        if build_fixes:
            return BuildVerdict.BUILD_FIX
        if mobility <= -8.0:
            return BuildVerdict.TRADEOFF
        if significance == Significance.TRIVIAL:
            return BuildVerdict.SIDEGRADE
        if significance == Significance.MINOR:
            return BuildVerdict.MINOR_UPGRADE if (offense > 0 or defence > 0 or (score_delta or 0) > 0) else BuildVerdict.SIDEGRADE
        return BuildVerdict.SIDEGRADE

    # Ranking thinks this is some upgrade flavour.
    if mobility <= -20.0:
        return BuildVerdict.TRADEOFF
    if build_fixes and significance in {Significance.TRIVIAL, Significance.MINOR, Significance.STRATEGIC}:
        if abs(offense) < 3.0 and abs(defence) < 3.0:
            return BuildVerdict.BUILD_FIX
    if significance == Significance.MAJOR or (offense >= 8.0 and defence >= 8.0):
        return BuildVerdict.MAJOR_UPGRADE
    if ranking == "STRONG_UPGRADE" or (offense >= 8.0 and defence >= 1.0) or (defence >= 8.0 and offense >= 1.0):
        return BuildVerdict.STRONG_UPGRADE
    if significance == Significance.MEANINGFUL or ranking in {"CLEAR_UPGRADE", "OFFENSE_UPGRADE", "DEFENSE_UPGRADE"}:
        if significance == Significance.MINOR:
            return BuildVerdict.MINOR_UPGRADE
        return BuildVerdict.MEANINGFUL_UPGRADE
    if significance == Significance.MINOR:
        return BuildVerdict.MINOR_UPGRADE
    if build_fixes:
        return BuildVerdict.BUILD_FIX
    return BuildVerdict.SIDEGRADE


def is_false_upgrade(verdict: BuildVerdict) -> bool:
    return verdict.value in UPGRADE_VERDICTS


def overlay_verdict_label(verdict: BuildVerdict) -> str:
    return {
        BuildVerdict.MAJOR_UPGRADE: "MAJOR UPGRADE",
        BuildVerdict.STRONG_UPGRADE: "STRONG UPGRADE",
        BuildVerdict.MEANINGFUL_UPGRADE: "MEANINGFUL UPGRADE",
        BuildVerdict.MINOR_UPGRADE: "MINOR UPGRADE",
        BuildVerdict.SIDEGRADE: "SIDEGRADE",
        BuildVerdict.TRADEOFF: "TRADE-OFF",
        BuildVerdict.DOWNGRADE: "DOWNGRADE",
        BuildVerdict.BUILD_FIX: "BUILD FIX",
        BuildVerdict.BLOCKED: "BLOCKED",
        BuildVerdict.UNSAFE: "UNSAFE DOWNGRADE",
    }.get(verdict, verdict.value.replace("_", " "))
