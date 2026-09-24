from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from exilelens.items.resist_caps import AT_CAP_EPSILON, RESIST_ELEMENTS, effective_cap

NEED_CODES = (
    "RES_CAP_MISSING",
    "LOW_CHAOS_RES",
    "LOW_EHP",
    "LOW_MAX_HIT",
    "OFFENSE_OPPORTUNITY",
    "MOVEMENT_OPPORTUNITY",
    "RESOURCE_PRESSURE",
    "ATTRIBUTE_REQUIREMENT",
)


def _num(raw: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in raw and raw[key] is not None:
            return float(raw[key])
    return None


@dataclass
class CapAudit:
    element: str
    metric: str
    current: float | None
    cap: float | None
    missing: float | None
    overcap: float | None
    state: str  # CAPPED | BELOW_CAP | OVER_CAPPED | UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BuildNeed:
    code: str
    severity: str
    metric: str
    current: float | None
    target: float | None
    deficit: float | None
    explanation: str
    confidence: str
    breakpoint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BuildStateAudit:
    offense: dict[str, Any]
    defense: dict[str, Any]
    resistances: dict[str, CapAudit]
    utility: dict[str, Any]
    needs: list[BuildNeed] = field(default_factory=list)
    primary_field: str = "CombinedDPS"
    primary_confidence: str = "high"

    def to_dict(self) -> dict[str, Any]:
        return {
            "offense": self.offense,
            "defense": self.defense,
            "resistances": {key: value.to_dict() for key, value in self.resistances.items()},
            "utility": self.utility,
            "needs": [need.to_dict() for need in self.needs],
            "primary_field": self.primary_field,
            "primary_confidence": self.primary_confidence,
        }


def _cap_state(current: float | None, cap: float | None, overcap: float | None) -> str:
    if current is None or cap is None:
        return "UNKNOWN"
    if current >= cap - AT_CAP_EPSILON:
        if overcap is not None and overcap > AT_CAP_EPSILON:
            return "OVER_CAPPED"
        return "CAPPED"
    return "BELOW_CAP"


def audit_resistances(raw: dict[str, Any]) -> dict[str, CapAudit]:
    result: dict[str, CapAudit] = {}
    for element in RESIST_ELEMENTS:
        prefix = element.title()
        current = _num(raw, f"{prefix}Resist")
        cap = effective_cap(raw, element)
        missing = _num(raw, f"Missing{prefix}Resist", f"{prefix}Missing")
        overcap = _num(raw, f"{prefix}ResistOverCap") or 0.0
        if missing is None and current is not None and cap is not None:
            missing = max(0.0, cap - current)
        result[element] = CapAudit(
            element=element,
            metric=f"{element}_res",
            current=current,
            cap=cap,
            missing=missing,
            overcap=overcap,
            state=_cap_state(current, cap, overcap),
        )
    return result


def _worst_max_hit(raw: dict[str, Any]) -> tuple[float | None, str | None]:
    best: tuple[float, str] | None = None
    for metric_field in (
        "PhysicalMaximumHitTaken",
        "FireMaximumHitTaken",
        "ColdMaximumHitTaken",
        "LightningMaximumHitTaken",
        "ChaosMaximumHitTaken",
    ):
        value = _num(raw, metric_field)
        if value is None:
            continue
        if best is None or value < best[0]:
            best = (value, metric_field)
    if best is None:
        return None, None
    return best


def detect_needs(
    audit: BuildStateAudit,
    raw: dict[str, Any],
    *,
    include_probe_needs: bool = False,
) -> list[BuildNeed]:
    needs: list[BuildNeed] = []
    for element, cap in audit.resistances.items():
        if cap.state == "BELOW_CAP" and cap.missing is not None and cap.missing > AT_CAP_EPSILON:
            severity = "critical" if element != "chaos" else "high"
            code = "LOW_CHAOS_RES" if element == "chaos" else "RES_CAP_MISSING"
            needs.append(
                BuildNeed(
                    code=code,
                    severity=severity,
                    metric=cap.metric,
                    current=cap.current,
                    target=cap.cap,
                    deficit=round(cap.missing, 2),
                    explanation=f"{element.title()} resistance below cap.",
                    confidence="high",
                    breakpoint="RESISTANCE_CAP",
                )
            )

    ehp = audit.defense.get("ehp")
    if ehp is not None and float(ehp) <= 0:
        needs.append(
            BuildNeed(
                code="LOW_EHP",
                severity="critical",
                metric="ehp",
                current=float(ehp),
                target=None,
                deficit=None,
                explanation="Effective hit pool is collapsed or unavailable.",
                confidence="high",
            )
        )

    max_hit = audit.defense.get("worst_max_hit")
    if max_hit is not None and float(max_hit) <= 0:
        needs.append(
            BuildNeed(
                code="LOW_MAX_HIT",
                severity="high",
                metric="worst_max_hit",
                current=float(max_hit),
                target=None,
                deficit=None,
                explanation="Worst maximum hit taken is collapsed.",
                confidence="high",
            )
        )

    mana_cost = _num(raw, "ManaPerSecondCost")
    mana_regen = _num(raw, "ManaRegenRecovery")
    if mana_cost is not None and mana_regen is not None and mana_cost > mana_regen + 0.05:
        needs.append(
            BuildNeed(
                code="RESOURCE_PRESSURE",
                severity="medium",
                metric="mana",
                current=mana_regen,
                target=mana_cost,
                deficit=round(mana_cost - mana_regen, 2),
                explanation="Mana cost exceeds regen on the current skill snapshot.",
                confidence="medium",
            )
        )

    if include_probe_needs:
        needs.extend(audit.needs)
    return needs


def build_state_audit(
    raw: dict[str, Any],
    *,
    primary_field: str = "CombinedDPS",
    primary_confidence: str = "high",
) -> BuildStateAudit:
    worst, worst_field = _worst_max_hit(raw)
    resistances = audit_resistances(raw)
    # Do not substitute another damage field for an unresolved semantic metric.
    # FullDPS is valid only when the caller selected a configured PoB aggregate.
    offense_value = _num(raw, primary_field)
    audit = BuildStateAudit(
        offense={
            "primary": offense_value,
            "metric": primary_field,
            "confidence": primary_confidence if offense_value is not None else "low",
            "availability": "available" if offense_value is not None else "missing",
        },
        defense={
            "ehp": _num(raw, "TotalEHP"),
            "worst_max_hit": worst,
            "worst_max_hit_field": worst_field,
            "life": _num(raw, "Life"),
            "energy_shield": _num(raw, "EnergyShield"),
            "mana": _num(raw, "Mana"),
            "armour": _num(raw, "Armour"),
            "evasion": _num(raw, "Evasion"),
        },
        resistances=resistances,
        utility={
            "movement_speed": _num(raw, "MovementSpeedMod"),
            "mana_cost_per_second": _num(raw, "ManaPerSecondCost"),
            "mana_regen": _num(raw, "ManaRegenRecovery"),
        },
        primary_field=primary_field,
        primary_confidence=primary_confidence,
    )
    audit.needs = detect_needs(audit, raw)
    return audit
