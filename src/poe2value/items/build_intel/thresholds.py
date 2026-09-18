"""Threshold / breakpoint engine on exact PoB before/after values."""

from __future__ import annotations

import math
from typing import Any

from poe2value.items.build_intel.models import ThresholdCode, ThresholdEvent
from poe2value.items.resist_caps import CapState

AT_CAP_EPSILON = 0.05
SKILL_COLLAPSE = 1.0
RESOURCE_EPS = 0.01
from poe2value.items.requirement_gates import attribute_requirement_warnings


def _num(raw: dict[str, Any], field: str) -> float | None:
    if field not in raw:
        return None
    value = raw.get(field)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _metric(profile: dict[str, Any], key: str) -> dict[str, Any]:
    return dict(profile.get(key) or {})


def assess_thresholds(
    metric_profile: dict[str, Any],
    resist: dict[str, Any],
    raw_current: dict[str, Any],
    raw_candidate: dict[str, Any],
    *,
    restore_failed: bool = False,
) -> list[ThresholdEvent]:
    events: list[ThresholdEvent] = []
    if restore_failed:
        events.append(
            ThresholdEvent(
                code="BUILD_INVALID",
                metric="restore",
                before=None,
                after=None,
                threshold=None,
                direction="down",
                severity="critical",
                detail="baseline restore failed",
                is_hard_break=True,
            )
        )

    offense = _metric(metric_profile, "primary_offense")
    cur_off = offense.get("current")
    cand_off = offense.get("candidate")
    if cur_off is not None and cand_off is not None:
        if float(cur_off) > SKILL_COLLAPSE and float(cand_off) <= SKILL_COLLAPSE:
            events.append(
                ThresholdEvent(
                    code=ThresholdCode.MAIN_SKILL_INVALID.value,
                    metric="primary_offense",
                    before=float(cur_off),
                    after=float(cand_off),
                    threshold=SKILL_COLLAPSE,
                    direction="down",
                    severity="critical",
                    detail="main skill became invalid",
                    is_hard_break=True,
                )
            )
        elif float(cur_off) <= SKILL_COLLAPSE and float(cand_off) > SKILL_COLLAPSE:
            events.append(
                ThresholdEvent(
                    code=ThresholdCode.MAIN_SKILL_VALID.value,
                    metric="primary_offense",
                    before=float(cur_off),
                    after=float(cand_off),
                    threshold=SKILL_COLLAPSE,
                    direction="up",
                    severity="positive",
                    detail="main skill became usable",
                    is_build_fix=True,
                )
            )

    for element, info in (resist.get("elements") or {}).items():
        state = str(info.get("state") or "")
        before = info.get("current")
        after = info.get("candidate")
        cap = info.get("cap_candidate") if info.get("cap_candidate") is not None else info.get("cap_current")
        metric = f"{element}_res"
        if state == CapState.CAP_REACHED.value:
            events.append(
                ThresholdEvent(
                    code=ThresholdCode.RES_CAP_REACHED.value,
                    metric=metric,
                    before=float(before) if before is not None else None,
                    after=float(after) if after is not None else None,
                    threshold=float(cap) if cap is not None else None,
                    direction="up",
                    severity="positive",
                    detail=f"{element} resistance reaches cap",
                    is_build_fix=True,
                )
            )
        elif state == CapState.CAP_LOST.value:
            events.append(
                ThresholdEvent(
                    code=ThresholdCode.RES_CAP_LOST.value,
                    metric=metric,
                    before=float(before) if before is not None else None,
                    after=float(after) if after is not None else None,
                    threshold=float(cap) if cap is not None else None,
                    direction="down",
                    severity="critical",
                    detail=f"{element} resistance cap lost",
                    is_hard_break=True,
                )
            )
        elif state == CapState.BELOW_CAP_IMPROVED.value:
            events.append(
                ThresholdEvent(
                    code=ThresholdCode.BELOW_CAP_IMPROVED.value,
                    metric=metric,
                    before=float(before) if before is not None else None,
                    after=float(after) if after is not None else None,
                    threshold=float(cap) if cap is not None else None,
                    direction="up",
                    severity="positive",
                    detail=f"{element} resistance below cap improved",
                    is_build_fix=True,
                )
            )
        elif state == CapState.BELOW_CAP_WORSENED.value:
            events.append(
                ThresholdEvent(
                    code=ThresholdCode.BELOW_CAP_WORSENED.value,
                    metric=metric,
                    before=float(before) if before is not None else None,
                    after=float(after) if after is not None else None,
                    threshold=float(cap) if cap is not None else None,
                    direction="down",
                    severity="high",
                    detail=f"{element} resistance already below cap gets worse",
                )
            )

    cur_cost = _num(raw_current, "ManaPerSecondCost")
    cand_cost = _num(raw_candidate, "ManaPerSecondCost")
    cur_regen = _num(raw_current, "ManaRegenRecovery")
    cand_regen = _num(raw_candidate, "ManaRegenRecovery")
    if cur_cost is not None and cand_cost is not None and cur_regen is not None and cand_regen is not None:
        current_ok = cur_cost <= cur_regen + RESOURCE_EPS
        candidate_ok = cand_cost <= cand_regen + RESOURCE_EPS
        before = cur_regen - cur_cost
        after = cand_regen - cand_cost
        if current_ok and not candidate_ok:
            events.append(
                ThresholdEvent(
                    code=ThresholdCode.RESOURCE_SUSTAIN_LOST.value,
                    metric="mana_sustain",
                    before=before,
                    after=after,
                    threshold=0.0,
                    direction="down",
                    severity="critical",
                    detail="resource sustain became negative",
                    is_hard_break=True,
                )
            )
        elif (not current_ok) and candidate_ok:
            events.append(
                ThresholdEvent(
                    code=ThresholdCode.RESOURCE_SUSTAIN_REACHED.value,
                    metric="mana_sustain",
                    before=before,
                    after=after,
                    threshold=0.0,
                    direction="up",
                    severity="positive",
                    detail="resource sustain became positive",
                    is_build_fix=True,
                )
            )

    seen_attr: set[str] = set()
    for warning in attribute_requirement_warnings(raw_current, raw_candidate):
        metric = str(warning.get("metric") or "")
        if metric in seen_attr:
            continue
        seen_attr.add(metric)
        code = str(warning.get("code") or "")
        if code == ThresholdCode.ATTRIBUTE_REQUIREMENT_REACHED.value:
            events.append(
                ThresholdEvent(
                    code=code,
                    metric=metric,
                    before=warning.get("before"),
                    after=warning.get("after"),
                    threshold=None,
                    direction="up",
                    severity="positive",
                    detail=str(warning.get("detail") or ""),
                    is_build_fix=True,
                )
            )
        elif code == ThresholdCode.ATTRIBUTE_REQUIREMENT_LOST.value:
            events.append(
                ThresholdEvent(
                    code=code,
                    metric=metric,
                    before=warning.get("before"),
                    after=warning.get("after"),
                    threshold=None,
                    direction="down",
                    severity="critical",
                    detail=str(warning.get("detail") or ""),
                    is_hard_break=True,
                )
            )

    ehp = _metric(metric_profile, "ehp")
    # Optional defence floor: if current EHP was below a recorded floor and candidate restores it.
    floor = _num(raw_current, "RequiredEHP") or _num(raw_candidate, "RequiredEHP")
    if floor is not None and ehp.get("current") is not None and ehp.get("candidate") is not None:
        cur_ehp = float(ehp["current"])
        cand_ehp = float(ehp["candidate"])
        if cur_ehp < floor - 0.5 <= cand_ehp:
            events.append(
                ThresholdEvent(
                    code=ThresholdCode.REQUIRED_DEFENCE_THRESHOLD.value,
                    metric="ehp",
                    before=cur_ehp,
                    after=cand_ehp,
                    threshold=floor,
                    direction="up",
                    severity="positive",
                    detail="required defence threshold restored",
                    is_build_fix=True,
                )
            )
        elif cand_ehp < floor - 0.5 <= cur_ehp:
            events.append(
                ThresholdEvent(
                    code=ThresholdCode.REQUIRED_DEFENCE_THRESHOLD.value,
                    metric="ehp",
                    before=cur_ehp,
                    after=cand_ehp,
                    threshold=floor,
                    direction="down",
                    severity="high",
                    detail="required defence threshold lost",
                    is_hard_break=True,
                )
            )

    return events
