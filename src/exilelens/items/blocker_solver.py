"""ITEM-PRO-01B blocker-first upgrade path domain and analysis (no PoB)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from exilelens.items.resist_caps import AT_CAP_EPSILON, analyze_resistances


class UpgradeBlockerType(str, Enum):
    RESISTANCE_REGRESSION = "RESISTANCE_REGRESSION"
    CAP_LOST = "CAP_LOST"
    BELOW_CAP_WORSENED = "BELOW_CAP_WORSENED"
    ATTRIBUTE_REQUIREMENT_BROKEN = "ATTRIBUTE_REQUIREMENT_BROKEN"
    RESOURCE_REGRESSION = "RESOURCE_REGRESSION"
    MAIN_SKILL_INVALID = "MAIN_SKILL_INVALID"
    EHP_REGRESSION = "EHP_REGRESSION"
    MAX_HIT_REGRESSION = "MAX_HIT_REGRESSION"
    LIFE_REGRESSION = "LIFE_REGRESSION"
    ENERGY_SHIELD_REGRESSION = "ENERGY_SHIELD_REGRESSION"
    OFFENSE_SHORTFALL = "OFFENSE_SHORTFALL"


class RepairMode(str, Enum):
    RESTORE_BASELINE = "RESTORE_BASELINE"
    REACH_CAP = "REACH_CAP"


class UpgradePathResultKind(str, Enum):
    ALREADY_UPGRADE = "ALREADY_UPGRADE"
    SINGLE_REPAIR_UPGRADE = "SINGLE_REPAIR_UPGRADE"
    REPAIR_PLUS_SECONDARY = "REPAIR_PLUS_SECONDARY"
    MULTI_BLOCKER_REPAIR_UPGRADE = "MULTI_BLOCKER_REPAIR_UPGRADE"
    NOT_CLOSE = "NOT_CLOSE"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


_BLOCKER_PRIORITY = {
    UpgradeBlockerType.MAIN_SKILL_INVALID: 0,
    UpgradeBlockerType.ATTRIBUTE_REQUIREMENT_BROKEN: 1,
    UpgradeBlockerType.CAP_LOST: 2,
    UpgradeBlockerType.BELOW_CAP_WORSENED: 3,
    UpgradeBlockerType.RESISTANCE_REGRESSION: 4,
    UpgradeBlockerType.RESOURCE_REGRESSION: 5,
    UpgradeBlockerType.MAX_HIT_REGRESSION: 6,
    UpgradeBlockerType.EHP_REGRESSION: 7,
    UpgradeBlockerType.LIFE_REGRESSION: 8,
    UpgradeBlockerType.ENERGY_SHIELD_REGRESSION: 9,
    UpgradeBlockerType.OFFENSE_SHORTFALL: 10,
}

_ELEMENT_PROBE = {
    "fire": "FIRE_RES",
    "cold": "COLD_RES",
    "lightning": "LIGHTNING_RES",
    "chaos": "CHAOS_RES",
}

_RESOURCE_FIELDS = (
    ("Life", "LIFE", "Maximum Life", UpgradeBlockerType.LIFE_REGRESSION, 8.0),
    ("EnergyShield", "ENERGY_SHIELD", "Energy Shield", UpgradeBlockerType.ENERGY_SHIELD_REGRESSION, 8.0),
    ("Mana", "MANA", "Mana", UpgradeBlockerType.RESOURCE_REGRESSION, 15.0),
)

_METRIC_FIELDS = (
    ("TotalEHP", UpgradeBlockerType.EHP_REGRESSION, 3.0),
    ("MaximumHitTaken", UpgradeBlockerType.MAX_HIT_REGRESSION, 3.0),
)

_MAX_STRUCTURAL_REPAIRS = 4


@dataclass
class UpgradeBlocker:
    blocker_type: str
    severity: str
    metric: str
    baseline: float | None
    candidate: float | None
    delta: float | None
    repair_target: float
    repair_mode: str = RepairMode.RESTORE_BASELINE.value
    probe_id: str = ""
    label: str = ""
    element: str | None = None
    repairable: bool = True
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocker_type": self.blocker_type,
            "severity": self.severity,
            "metric": self.metric,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "delta": self.delta,
            "repair_target": self.repair_target,
            "repair_mode": self.repair_mode,
            "probe_id": self.probe_id,
            "label": self.label,
            "element": self.element,
            "repairable": self.repairable,
            "reason": self.reason,
        }


@dataclass
class RepairVector:
    repairs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"repairs": list(self.repairs)}

    def mod_lines(self, catalog: Any) -> list[str]:
        lines: list[str] = []
        for item in self.repairs:
            probe_id = str(item.get("probe_id") or "")
            magnitude = float(item.get("magnitude") or 0.0)
            if magnitude <= 0 or not probe_id:
                continue
            definition = catalog.get(probe_id)
            if definition is None:
                continue
            lines.append(definition.line(magnitude))
        return lines

    def path_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for item in self.repairs:
            probe_id = str(item.get("probe_id") or "")
            magnitude = item.get("magnitude")
            label = str(item.get("label") or probe_id)
            unit = str(item.get("unit") or "")
            if probe_id.endswith("_RES"):
                unit = unit or "percent"
            entries.append(
                {
                    "probe_id": probe_id,
                    "label": label,
                    "unit": unit,
                    "magnitude": magnitude,
                    "step": 1,
                    "kind": "repair",
                }
            )
        return entries


def analyze_blockers(
    recommendation: dict[str, Any],
    baseline_raw: dict[str, Any],
    candidate_raw: dict[str, Any],
) -> list[UpgradeBlocker]:
    blockers: list[UpgradeBlocker] = []
    warning_codes = {str(item.get("code")) for item in recommendation.get("warnings") or []}

    for warning in recommendation.get("warnings") or []:
        code = str(warning.get("code") or "")
        if code == "MAIN_SKILL_INVALID":
            blockers.append(
                UpgradeBlocker(
                    blocker_type=UpgradeBlockerType.MAIN_SKILL_INVALID.value,
                    severity="critical",
                    metric=str(warning.get("metric") or "primary_offense"),
                    baseline=_float_or_none(warning.get("before")),
                    candidate=_float_or_none(warning.get("after")),
                    delta=_delta(warning.get("before"), warning.get("after")),
                    repair_target=0.0,
                    repairable=False,
                    reason=str(warning.get("detail") or "Primary offense collapsed"),
                )
            )

    resist = analyze_resistances(baseline_raw, candidate_raw)
    for element, info in (resist.get("elements") or {}).items():
        current = info.get("current")
        candidate = info.get("candidate")
        if current is None or candidate is None:
            continue
        probe_id = _ELEMENT_PROBE.get(element, "")
        label = f"{element.title()} Resistance"
        state = str(info.get("state") or "")
        delta = float(candidate) - float(current)
        if state == "CAP_LOST":
            cap = info.get("cap_current") or info.get("effective_cap") or current
            repair = max(0.0, float(cap) - float(candidate))
            blockers.append(
                UpgradeBlocker(
                    blocker_type=UpgradeBlockerType.CAP_LOST.value,
                    severity="critical",
                    metric=f"{element}_res",
                    baseline=float(current),
                    candidate=float(candidate),
                    delta=delta,
                    repair_target=round(repair, 1),
                    repair_mode=RepairMode.REACH_CAP.value,
                    probe_id=probe_id,
                    label=label,
                    element=element,
                    reason=f"{label} cap lost",
                )
            )
        elif delta < -AT_CAP_EPSILON:
            repair = max(0.0, float(current) - float(candidate))
            blocker_type = (
                UpgradeBlockerType.BELOW_CAP_WORSENED.value
                if state == "BELOW_CAP_WORSENED" or "RES_DEFICIT_WORSENED" in warning_codes
                else UpgradeBlockerType.RESISTANCE_REGRESSION.value
            )
            blockers.append(
                UpgradeBlocker(
                    blocker_type=blocker_type,
                    severity="critical" if state == "BELOW_CAP_WORSENED" else "high",
                    metric=f"{element}_res",
                    baseline=float(current),
                    candidate=float(candidate),
                    delta=delta,
                    repair_target=round(repair, 1),
                    repair_mode=RepairMode.RESTORE_BASELINE.value,
                    probe_id=probe_id,
                    label=label,
                    element=element,
                    reason=f"{label} lost vs current item",
                )
            )

    for field_name, probe_id, label, blocker_type, min_loss in _RESOURCE_FIELDS:
        before = float(baseline_raw.get(field_name) or 0)
        after = float(candidate_raw.get(field_name) or 0)
        loss = before - after
        if loss >= min_loss:
            blockers.append(
                UpgradeBlocker(
                    blocker_type=blocker_type.value,
                    severity="high" if loss >= min_loss * 2 else "medium",
                    metric=field_name.lower(),
                    baseline=before,
                    candidate=after,
                    delta=after - before,
                    repair_target=round(loss, 1),
                    repair_mode=RepairMode.RESTORE_BASELINE.value,
                    probe_id=probe_id,
                    label=label,
                    reason=f"{label} lost vs current item",
                )
            )

    metrics = recommendation.get("normalized_metrics") or recommendation.get("metric_profile") or {}
    for field_name, blocker_type, min_pct in _METRIC_FIELDS:
        info = metrics.get(field_name.lower()) or metrics.get(field_name) or {}
        pct = float(info.get("percent_delta") or 0.0)
        if pct <= -min_pct:
            blockers.append(
                UpgradeBlocker(
                    blocker_type=blocker_type.value,
                    severity="medium",
                    metric=field_name.lower(),
                    baseline=_float_or_none(info.get("current")),
                    candidate=_float_or_none(info.get("candidate")),
                    delta=pct,
                    repair_target=0.0,
                    repairable=False,
                    reason=f"{field_name} regressed {pct:.1f}%",
                )
            )

    deduped: list[UpgradeBlocker] = []
    seen: set[str] = set()
    for blocker in sorted(blockers, key=_blocker_sort_key):
        key = blocker.probe_id or blocker.metric
        if key in seen and blocker.repairable:
            continue
        seen.add(key)
        deduped.append(blocker)
    return deduped


def build_repair_vector(blockers: list[UpgradeBlocker], *, catalog: Any) -> RepairVector:
    repairs: list[dict[str, Any]] = []
    for blocker in blockers:
        if not blocker.repairable or blocker.repair_target <= 0:
            continue
        if not blocker.probe_id or catalog.get(blocker.probe_id) is None:
            continue
        definition = catalog.get(blocker.probe_id)
        repairs.append(
            {
                "probe_id": blocker.probe_id,
                "label": blocker.label or definition.label,
                "unit": definition.unit,
                "magnitude": blocker.repair_target,
                "element": blocker.element,
                "repair_mode": blocker.repair_mode,
                "blocker_type": blocker.blocker_type,
                "blocker": blocker.to_dict(),
                "blocker_reason": blocker.reason,
            }
        )
        if len(repairs) >= _MAX_STRUCTURAL_REPAIRS:
            break
    return RepairVector(repairs=repairs)


def blocker_why_lines(blockers: list[UpgradeBlocker], *, slot_label: str = "item") -> list[dict[str, Any]]:
    resist_losses = [
        item
        for item in blockers
        if item.repairable
        and item.blocker_type
        in {
            UpgradeBlockerType.RESISTANCE_REGRESSION.value,
            UpgradeBlockerType.BELOW_CAP_WORSENED.value,
            UpgradeBlockerType.CAP_LOST.value,
        }
    ]
    if not resist_losses:
        return []
    if len(resist_losses) == 1:
        item = resist_losses[0]
        amount = abs(float(item.delta or 0))
        element = (item.element or item.label or "resistance").title()
        return [
            {
                "explanation": f"Your current {slot_label.lower()} provides {amount:g} more {element} Resistance.",
                "severity": item.severity,
                "code": item.blocker_type,
            }
        ]
    parts: list[str] = []
    for item in resist_losses[:3]:
        amount = abs(float(item.delta or 0))
        element = (item.element or "resistance").title()
        parts.append(f"{amount:g} more {element}")
    joined = " and ".join(parts)
    return [
        {
            "explanation": f"Your current {slot_label.lower()} provides {joined} Resistance.",
            "severity": "high",
            "code": "MULTI_RES_REGRESSION",
        }
    ]


def format_not_close_reason(
    *,
    repair_vector: RepairVector | None,
    repaired_rating: float | None,
    repaired_verdict: str | None,
    secondary_attempted: list[str],
    remaining_losses: list[str],
) -> str:
    repair_bits = []
    for item in (repair_vector.repairs if repair_vector else []):
        label = str(item.get("label") or item.get("probe_id") or "stat")
        mag = item.get("magnitude")
        if mag is not None:
            repair_bits.append(f"+{mag:g} {label}")
    repair_text = ", ".join(repair_bits) if repair_bits else "structural repairs"
    if repaired_rating is not None and repaired_verdict:
        head = f"After {repair_text}: {repaired_verdict.replace('_', ' ').title()} · Build Value {repaired_rating:g}."
    elif repair_bits:
        head = f"Restoring {repair_text} is not enough."
    else:
        head = "No supported repair path found."
    if remaining_losses:
        tail = f" The item also loses {', '.join(remaining_losses)}."
        return head + tail
    if secondary_attempted:
        dims = ", ".join(secondary_attempted[:3])
        return f"{head} No reasonable {dims} improvement reached a clean upgrade."
    return head


def _blocker_sort_key(blocker: UpgradeBlocker) -> tuple[int, float]:
    try:
        blocker_type = UpgradeBlockerType(blocker.blocker_type)
    except ValueError:
        blocker_type = None
    priority = _BLOCKER_PRIORITY.get(blocker_type, 50) if blocker_type else 50
    return (priority, -abs(float(blocker.repair_target or 0)))


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _delta(before: Any, after: Any) -> float | None:
    if before is None or after is None:
        return None
    return float(after) - float(before)
