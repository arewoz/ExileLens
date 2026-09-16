"""Hard constraints beat scalar Build Value. Profile-independent."""

from __future__ import annotations

from poe2value.items.build_intel.models import ConstraintSeverity, HardConstraint, ThresholdEvent

BLOCKING_CODES = frozenset(
    {
        "MAIN_SKILL_INVALID",
        "BUILD_INVALID",
        "ATTRIBUTE_REQUIREMENT_LOST",
        "RESOURCE_SUSTAIN_LOST",
        "RESOURCE_FAILURE",
    }
)
UNSAFE_CODES = frozenset(
    {
        "RES_CAP_LOST",
        "REQUIRED_DEFENCE_THRESHOLD",
    }
)


def constraints_from_thresholds(events: list[ThresholdEvent]) -> list[HardConstraint]:
    found: list[HardConstraint] = []
    for event in events:
        if event.code in BLOCKING_CODES or (event.is_hard_break and event.code in {"MAIN_SKILL_INVALID", "BUILD_INVALID", "ATTRIBUTE_REQUIREMENT_LOST"}):
            if event.code in BLOCKING_CODES:
                found.append(
                    HardConstraint(
                        code=event.code,
                        severity=ConstraintSeverity.BLOCKING.value,
                        metric=event.metric,
                        before=event.before,
                        after=event.after,
                        detail=event.detail,
                    )
                )
                continue
        if event.code in UNSAFE_CODES and event.direction == "down":
            found.append(
                HardConstraint(
                    code=event.code,
                    severity=ConstraintSeverity.UNSAFE.value,
                    metric=event.metric,
                    before=event.before,
                    after=event.after,
                    detail=event.detail,
                )
            )
    return found


def blocking_problems(problems: list[HardConstraint]) -> list[HardConstraint]:
    return [item for item in problems if item.severity == ConstraintSeverity.BLOCKING.value]


def unsafe_problems(problems: list[HardConstraint]) -> list[HardConstraint]:
    return [item for item in problems if item.severity == ConstraintSeverity.UNSAFE.value]
