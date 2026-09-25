"""ITEM-PRO-01 decision intelligence — deterministic WHY layer on top of verdicts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from exilelens.items.evaluation_outcome import authoritative_public_verdict, authoritative_verdict_reason


class ReasonCategory(str, Enum):
    BREAKPOINT = "BREAKPOINT"
    DAMAGE = "DAMAGE"
    DEFENSE = "DEFENSE"
    RESIST = "RESIST"
    RESOURCE = "RESOURCE"
    ATTRIBUTE = "ATTRIBUTE"
    SKILL = "SKILL"
    CURRENT_PROTECTION = "CURRENT_PROTECTION"
    BUILD_REPAIR = "BUILD_REPAIR"


class ReasonSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    POSITIVE = "positive"


class ReasonDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class EvaluationConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SwapRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


def derive_swap_risk(
    comparison: dict[str, Any],
    *,
    decision: dict[str, Any] | None = None,
    offense_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """How dangerous swapping would be — distinct from evaluation confidence."""
    decision = decision or {}
    offense_coverage = offense_coverage or {}
    verdict = authoritative_public_verdict(comparison)
    warnings = comparison.get("warnings") or []
    codes = {str(item.get("code") or "") for item in warnings}
    offense_state = str(offense_coverage.get("state") or "")
    details: list[str] = []
    score = 0

    if offense_state in {"LIMITED", "UNAVAILABLE", "INSENSITIVE", "PARTIAL"}:
        score += 1
        details.append("offense coverage limited")
    if "RES_CAP_LOST" in codes:
        score += 2
        details.append("resistance cap loss")
    if "RES_DEFICIT_WORSENED" in codes:
        score += 1
        details.append("resistance deficit worsens")
    if verdict in {"DOWNGRADE", "STRONG_DOWNGRADE", "MINOR_DOWNGRADE", "MEANINGFUL_DOWNGRADE", "NOT_VIABLE"}:
        score += 1
        details.append("overall downgrade")
    if codes & {"RESOURCE_FAILURE", "MAIN_SKILL_INVALID", "BUILD_INVALID"}:
        score += 2
        details.append("build-breaking regression")
    repair_vector = list((comparison.get("upgrade_potential") or {}).get("repair_vector") or [])
    if len(repair_vector) >= 2:
        score += 1
        details.append("multiple repairs required")

    if score >= 3:
        level = SwapRiskLevel.HIGH.value
    elif score >= 1:
        level = SwapRiskLevel.MEDIUM.value
    else:
        level = SwapRiskLevel.LOW.value

    detail = " · ".join(details[:3])
    label = level.title()
    if detail:
        label = f"{label} · {detail}"
    return {
        "level": level,
        "detail": detail,
        "label": label,
        "confidence": str(decision.get("confidence") or EvaluationConfidence.HIGH.value),
    }


class RecommendationStyle(str, Enum):
    STRICT = "STRICT"
    BALANCED = "BALANCED"
    AGGRESSIVE = "AGGRESSIVE"


_BREAKPOINT_CODES = {
    "RES_CAP_LOST": ("RES_CAP_LOST", ReasonCategory.BREAKPOINT, ReasonSeverity.CRITICAL, ReasonDirection.DOWN, 0),
    "RES_CAP_REACHED": ("RES_CAP_REACHED", ReasonCategory.BREAKPOINT, ReasonSeverity.POSITIVE, ReasonDirection.UP, 5),
    "RES_DEFICIT_IMPROVED": ("BELOW_CAP_IMPROVED", ReasonCategory.BREAKPOINT, ReasonSeverity.POSITIVE, ReasonDirection.UP, 15),
    "RES_DEFICIT_WORSENED": ("BELOW_CAP_WORSENED", ReasonCategory.BREAKPOINT, ReasonSeverity.HIGH, ReasonDirection.DOWN, 8),
    "RESOURCE_FAILURE": ("RESOURCE_PRESSURE_FAILURE", ReasonCategory.RESOURCE, ReasonSeverity.CRITICAL, ReasonDirection.DOWN, 3),
    "MAIN_SKILL_INVALID": ("MAIN_SKILL_INVALID", ReasonCategory.SKILL, ReasonSeverity.CRITICAL, ReasonDirection.DOWN, 1),
    "BUILD_INVALID": ("MAIN_SKILL_INVALID", ReasonCategory.SKILL, ReasonSeverity.CRITICAL, ReasonDirection.DOWN, 1),
}


@dataclass(frozen=True)
class DecisionReason:
    category: str
    severity: str
    direction: str
    metric: str
    baseline: float | None
    candidate: float | None
    delta: float | None
    explanation: str
    code: str = ""
    priority: int = 50

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "direction": self.direction,
            "metric": self.metric,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "delta": self.delta,
            "explanation": self.explanation,
            "code": self.code,
            "priority": self.priority,
        }


@dataclass
class ItemDecisionSummary:
    headline: str
    recommendation_tag: str
    verdict: str
    why_reasons: list[DecisionReason] = field(default_factory=list)
    confidence: str = EvaluationConfidence.HIGH.value
    confidence_reasons: list[str] = field(default_factory=list)
    build_repair: bool = False
    keep_current_reasons: list[DecisionReason] = field(default_factory=list)
    best_slot_label: str = ""
    recommendation_style: str = RecommendationStyle.BALANCED.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "recommendation_tag": self.recommendation_tag,
            "verdict": self.verdict,
            "why_reasons": [item.to_dict() for item in self.why_reasons],
            "confidence": self.confidence,
            "confidence_reasons": self.confidence_reasons,
            "build_repair": self.build_repair,
            "keep_current_reasons": [item.to_dict() for item in self.keep_current_reasons],
            "best_slot_label": self.best_slot_label,
            "recommendation_style": self.recommendation_style,
        }


_VERDICT_HEADLINES = {
    "MEANINGFUL_UPGRADE": "Meaningful upgrade",
    "MINOR_UPGRADE": "Minor upgrade",
    "STRONG_UPGRADE": "Strong upgrade",
    "CLEAR_UPGRADE": "Clear upgrade",
    "OFFENSE_UPGRADE": "Offense upgrade",
    "DEFENSE_UPGRADE": "Defense upgrade",
    "TRADEOFF": "Tradeoff",
    "SIDEGRADE": "Sidegrade",
    "MINOR_DOWNGRADE": "Minor downgrade",
    "MEANINGFUL_DOWNGRADE": "Meaningful downgrade",
    "NOT_VIABLE": "Not viable",
    "UNCERTAIN": "Uncertain",
    "UNSUPPORTED": "Unsupported",
    "NOT_EVALUATED": "Couldn't evaluate",
    "DOWNGRADE": "Downgrade",
    "STRONG_DOWNGRADE": "Strong downgrade",
    "UNRESOLVED": "Unresolved",
    "NO_CHANGE": "No change",
}

_STYLE_TAGS = {
    RecommendationStyle.STRICT: {
        "upgrade": "Take only if clean",
        "tradeoff": "Avoid unless desperate",
        "downgrade": "Do not take",
        "repair": "Repair only if needed",
    },
    RecommendationStyle.BALANCED: {
        "upgrade": "Good fit",
        "tradeoff": "Weigh tradeoffs",
        "downgrade": "Skip",
        "repair": "Build repair",
    },
    RecommendationStyle.AGGRESSIVE: {
        "upgrade": "Take it",
        "tradeoff": "Worth the risk",
        "downgrade": "Probably skip",
        "repair": "Fix the build",
    },
}


def _metric_info(profile: dict[str, Any], key: str) -> tuple[float | None, float | None, float | None]:
    metric = profile.get(key) or {}
    current = metric.get("current")
    candidate = metric.get("candidate")
    delta = metric.get("absolute_delta")
    return (
        float(current) if current is not None else None,
        float(candidate) if candidate is not None else None,
        float(delta) if delta is not None else None,
    )


def _reason_from_warning(warning: dict[str, Any]) -> DecisionReason | None:
    code = str(warning.get("code") or "")
    mapping = _BREAKPOINT_CODES.get(code)
    if mapping:
        bp_code, category, severity, direction, priority = mapping
        metric = str(warning.get("metric") or code)
        return DecisionReason(
            category=category.value,
            severity=severity.value,
            direction=direction.value,
            metric=metric,
            baseline=_float_or_none(warning.get("before")),
            candidate=_float_or_none(warning.get("after")),
            delta=_delta(warning.get("before"), warning.get("after")),
            explanation=str(warning.get("detail") or code.replace("_", " ").lower()),
            code=bp_code,
            priority=priority,
        )
    if code in {"EHP_DOWN", "MAX_HIT_DOWN", "LIFE_DOWN", "ENERGY_SHIELD_DOWN"}:
        return DecisionReason(
            category=ReasonCategory.DEFENSE.value,
            severity=ReasonSeverity.HIGH.value if code in {"EHP_DOWN", "MAX_HIT_DOWN"} else ReasonSeverity.MEDIUM.value,
            direction=ReasonDirection.DOWN.value,
            metric=str(warning.get("metric") or "defense"),
            baseline=_float_or_none(warning.get("before")),
            candidate=_float_or_none(warning.get("after")),
            delta=_delta(warning.get("before"), warning.get("after")),
            explanation=str(warning.get("detail") or code.replace("_", " ").lower()),
            code=code,
            priority=20,
        )
    if code == "CHAOS_RES_WORSE":
        return DecisionReason(
            category=ReasonCategory.RESIST.value,
            severity=str(warning.get("severity") or ReasonSeverity.MEDIUM.value),
            direction=ReasonDirection.DOWN.value,
            metric="chaos_res",
            baseline=_float_or_none(warning.get("before")),
            candidate=_float_or_none(warning.get("after")),
            delta=_delta(warning.get("before"), warning.get("after")),
            explanation="Chaos resistance decreased",
            code="CHAOS_RES_WORSE",
            priority=25,
        )
    if code == "MOVEMENT_LOSS":
        return DecisionReason(
            category=ReasonCategory.DEFENSE.value,
            severity=ReasonSeverity.LOW.value,
            direction=ReasonDirection.DOWN.value,
            metric="movement_speed",
            baseline=_float_or_none(warning.get("before")),
            candidate=_float_or_none(warning.get("after")),
            delta=_delta(warning.get("before"), warning.get("after")),
            explanation="Movement speed decreased",
            code="MOVEMENT_LOSS",
            priority=40,
        )
    return None


def _damage_reasons(profile: dict[str, Any]) -> list[DecisionReason]:
    current, candidate, delta = _metric_info(profile, "primary_offense")
    if delta is None or abs(delta) < 0.5:
        return []
    direction = ReasonDirection.UP if delta > 0 else ReasonDirection.DOWN
    pct = (profile.get("primary_offense") or {}).get("percent_delta")
    if pct is not None and abs(float(pct)) >= 8:
        severity = ReasonSeverity.CRITICAL if delta > 0 else ReasonSeverity.HIGH
        priority = 12 if delta > 0 else 14
    elif pct is not None and abs(float(pct)) >= 3:
        severity = ReasonSeverity.HIGH
        priority = 18
    else:
        severity = ReasonSeverity.MEDIUM
        priority = 22
    label = "Damage improves" if delta > 0 else "Damage decreases"
    return [
        DecisionReason(
            category=ReasonCategory.DAMAGE.value,
            severity=severity.value,
            direction=direction.value,
            metric="primary_offense",
            baseline=current,
            candidate=candidate,
            delta=delta,
            explanation=label,
            code="PRIMARY_OFFENSE_DELTA",
            priority=priority,
        )
    ]


def _defense_reasons(profile: dict[str, Any]) -> list[DecisionReason]:
    reasons: list[DecisionReason] = []
    for key, label, priority in (
        ("ehp", "EHP", 16),
        ("worst_max_hit", "Max hit", 17),
        ("life", "Life", 28),
        ("energy_shield", "Energy shield", 29),
    ):
        current, candidate, delta = _metric_info(profile, key)
        if delta is None or abs(delta) < 0.5:
            continue
        direction = ReasonDirection.UP if delta > 0 else ReasonDirection.DOWN
        severity = ReasonSeverity.HIGH if key in {"ehp", "worst_max_hit"} else ReasonSeverity.MEDIUM
        reasons.append(
            DecisionReason(
                category=ReasonCategory.DEFENSE.value,
                severity=severity.value if delta < 0 else ReasonSeverity.POSITIVE.value,
                direction=direction.value,
                metric=key,
                baseline=current,
                candidate=candidate,
                delta=delta,
                explanation=f"{label} {'improves' if delta > 0 else 'decreases'}",
                code=f"{key.upper()}_DELTA",
                priority=priority,
            )
        )
    return reasons


def _cap_breakpoint_reasons(resist: dict[str, Any]) -> list[DecisionReason]:
    reasons: list[DecisionReason] = []
    for element, info in (resist.get("elements") or {}).items():
        state = info.get("state")
        current = _float_or_none(info.get("current"))
        candidate = _float_or_none(info.get("candidate"))
        cap = _float_or_none(info.get("cap_candidate") or info.get("cap_current"))
        if state == "CAP_LOST":
            reasons.append(
                DecisionReason(
                    category=ReasonCategory.BREAKPOINT.value,
                    severity=ReasonSeverity.CRITICAL.value,
                    direction=ReasonDirection.DOWN.value,
                    metric=f"{element}_res",
                    baseline=current,
                    candidate=candidate,
                    delta=_delta(current, candidate),
                    explanation=f"{element.title()} resistance cap lost",
                    code="RES_CAP_LOST",
                    priority=0,
                )
            )
        elif state == "CAP_REACHED":
            reasons.append(
                DecisionReason(
                    category=ReasonCategory.BREAKPOINT.value,
                    severity=ReasonSeverity.POSITIVE.value,
                    direction=ReasonDirection.UP.value,
                    metric=f"{element}_res",
                    baseline=current,
                    candidate=candidate,
                    delta=_delta(current, candidate),
                    explanation=f"{element.title()} resistance cap reached",
                    code="RES_CAP_REACHED",
                    priority=5,
                )
            )
        elif state == "BELOW_CAP_IMPROVED":
            reasons.append(
                DecisionReason(
                    category=ReasonCategory.BREAKPOINT.value,
                    severity=ReasonSeverity.POSITIVE.value,
                    direction=ReasonDirection.UP.value,
                    metric=f"{element}_res",
                    baseline=current,
                    candidate=candidate,
                    delta=_float_or_none(info.get("deficit_delta")),
                    explanation=f"{element.title()} below-cap resistance improved",
                    code="BELOW_CAP_IMPROVED",
                    priority=15,
                )
            )
        elif state == "BELOW_CAP_WORSENED":
            reasons.append(
                DecisionReason(
                    category=ReasonCategory.BREAKPOINT.value,
                    severity=ReasonSeverity.HIGH.value,
                    direction=ReasonDirection.DOWN.value,
                    metric=f"{element}_res",
                    baseline=current,
                    candidate=candidate,
                    delta=_float_or_none(info.get("deficit_delta")),
                    explanation=f"{element.title()} already below cap gets worse",
                    code="BELOW_CAP_WORSENED",
                    priority=8,
                )
            )
    return reasons


def _keep_current_reasons(
    comparison: dict[str, Any],
    candidate_reasons: list[DecisionReason],
) -> list[DecisionReason]:
    """WHY KEEP CURRENT when candidate loses important baseline properties."""
    reasons: list[DecisionReason] = []
    warnings = comparison.get("warnings") or []
    codes = {str(item.get("code")) for item in warnings}
    profile = comparison.get("metric_profile") or {}
    if "RES_CAP_LOST" in codes:
        reasons.append(
            DecisionReason(
                category=ReasonCategory.CURRENT_PROTECTION.value,
                severity=ReasonSeverity.CRITICAL.value,
                direction=ReasonDirection.DOWN.value,
                metric="res_cap",
                baseline=None,
                candidate=None,
                delta=None,
                explanation="Current item keeps a resistance cap the candidate would break",
                code="KEEP_CURRENT_CAP",
                priority=2,
            )
        )
    offense_current, _, offense_delta = _metric_info(profile, "primary_offense")
    ehp_current, _, ehp_delta = _metric_info(profile, "ehp")
    if offense_delta is not None and offense_delta < -0.5 and offense_current and offense_current > 1000:
        reasons.append(
            DecisionReason(
                category=ReasonCategory.CURRENT_PROTECTION.value,
                severity=ReasonSeverity.HIGH.value,
                direction=ReasonDirection.UP.value,
                metric="primary_offense",
                baseline=offense_current,
                candidate=None,
                delta=offense_delta,
                explanation="Current item protects meaningful damage",
                code="KEEP_CURRENT_DAMAGE",
                priority=11,
            )
        )
    if ehp_delta is not None and ehp_delta < -0.5 and ehp_current and ehp_current > 5000:
        reasons.append(
            DecisionReason(
                category=ReasonCategory.CURRENT_PROTECTION.value,
                severity=ReasonSeverity.HIGH.value,
                direction=ReasonDirection.UP.value,
                metric="ehp",
                baseline=ehp_current,
                candidate=None,
                delta=ehp_delta,
                explanation="Current item protects meaningful EHP",
                code="KEEP_CURRENT_EHP",
                priority=13,
            )
        )
    if not reasons and any(item.direction == ReasonDirection.DOWN.value for item in candidate_reasons):
        reasons.append(
            DecisionReason(
                category=ReasonCategory.CURRENT_PROTECTION.value,
                severity=ReasonSeverity.MEDIUM.value,
                direction=ReasonDirection.NEUTRAL.value,
                metric="baseline",
                baseline=None,
                candidate=None,
                delta=None,
                explanation="Current item avoids the candidate's main losses",
                code="KEEP_CURRENT_GENERAL",
                priority=30,
            )
        )
    return reasons[:3]


def _is_build_repair(reasons: list[DecisionReason], verdict: str) -> bool:
    repair_codes = {"RES_CAP_REACHED", "BELOW_CAP_IMPROVED", "RES_DEFICIT_IMPROVED"}
    has_repair = any(item.code in repair_codes for item in reasons)
    has_new_problem = any(
        item.code in {"RES_CAP_LOST", "BELOW_CAP_WORSENED", "RESOURCE_PRESSURE_FAILURE", "MAIN_SKILL_INVALID"}
        for item in reasons
    )
    if has_repair and not has_new_problem:
        return True
    if verdict in {"DEFENSE_UPGRADE", "CLEAR_UPGRADE", "OFFENSE_UPGRADE"} and has_repair:
        return has_repair and not has_new_problem
    return False


def assess_confidence(
    comparison: dict[str, Any],
    *,
    primary_metric: dict[str, Any] | None = None,
) -> tuple[EvaluationConfidence, list[str]]:
    evidence: list[str] = []
    outcome = comparison.get("evaluation_outcome") or {}
    quality = str(outcome.get("evaluation_quality") or "")
    if quality and quality != "FULL":
        evidence.append(f"Evaluation quality {quality}")
    primary = primary_metric or {}
    if primary.get("confidence") == "low" or primary.get("low_confidence"):
        evidence.append("Primary offense metric unresolved")
    restore = comparison.get("restore") or {}
    # A deferred restore (PERF-02) reports `pass: None` -- pending, not failed.
    if restore.get("pass") is False:
        evidence.append("Restore check failed")
    warnings = comparison.get("warnings") or []
    if any(item.get("code") == "BUILD_INVALID" for item in warnings):
        evidence.append("Build invalid during comparison")
    profile = comparison.get("metric_profile") or {}
    offense = profile.get("primary_offense") or {}
    if offense.get("availability") == "missing":
        evidence.append("Primary offense unavailable")
    if quality and quality != "FULL":
        return EvaluationConfidence.LOW, evidence
    if len(evidence) >= 2:
        return EvaluationConfidence.LOW, evidence
    if evidence:
        return EvaluationConfidence.MEDIUM, evidence
    return EvaluationConfidence.HIGH, ["PoB metrics and restore verified"]


def _style_bucket(verdict: str, build_repair: bool) -> str:
    if build_repair:
        return "repair"
    if verdict in {
        "STRONG_UPGRADE", "CLEAR_UPGRADE", "OFFENSE_UPGRADE", "DEFENSE_UPGRADE",
        "MEANINGFUL_UPGRADE", "MINOR_UPGRADE",
    }:
        return "upgrade"
    if verdict == "TRADEOFF":
        return "tradeoff"
    if verdict in {"DOWNGRADE", "STRONG_DOWNGRADE", "MINOR_DOWNGRADE", "MEANINGFUL_DOWNGRADE", "NOT_VIABLE"}:
        return "downgrade"
    return "tradeoff"


def build_decision_summary(
    comparison: dict[str, Any],
    *,
    style: str | RecommendationStyle = RecommendationStyle.BALANCED,
    primary_metric: dict[str, Any] | None = None,
    best_slot_label: str = "",
) -> ItemDecisionSummary:
    try:
        selected = style if isinstance(style, RecommendationStyle) else RecommendationStyle(str(style).upper())
    except ValueError:
        selected = RecommendationStyle.BALANCED

    verdict = authoritative_public_verdict(comparison)
    profile = comparison.get("metric_profile") or {}
    resist = comparison.get("resist_caps") or {}
    warnings = comparison.get("warnings") or []

    collected: list[DecisionReason] = []
    for warning in warnings:
        reason = _reason_from_warning(warning)
        if reason:
            collected.append(reason)
    collected.extend(_cap_breakpoint_reasons(resist))
    collected.extend(_damage_reasons(profile))
    collected.extend(_defense_reasons(profile))

    # Deduplicate by code+metric, keep best priority
    seen: set[tuple[str, str]] = set()
    unique: list[DecisionReason] = []
    for item in sorted(collected, key=lambda r: (r.priority, r.metric)):
        key = (item.code, item.metric)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    why = unique[:4]
    authoritative_explanation = authoritative_verdict_reason(comparison)
    if len(why) < 2 and authoritative_explanation:
        for line in authoritative_explanation.split(". "):
            line = line.strip()
            if not line:
                continue
            why.append(
                DecisionReason(
                    category=ReasonCategory.DAMAGE.value,
                    severity=ReasonSeverity.MEDIUM.value,
                    direction=ReasonDirection.NEUTRAL.value,
                    metric="summary",
                    baseline=None,
                    candidate=None,
                    delta=None,
                    explanation=line.rstrip("."),
                    code="VERDICT_EXPLANATION",
                    priority=50,
                )
            )
            if len(why) >= 2:
                break

    non_directional = verdict in {"UNCERTAIN", "UNSUPPORTED", "NOT_EVALUATED"}
    build_repair = False if non_directional else _is_build_repair(unique, verdict)
    if build_repair:
        why.insert(
            0,
            DecisionReason(
                category=ReasonCategory.BUILD_REPAIR.value,
                severity=ReasonSeverity.POSITIVE.value,
                direction=ReasonDirection.UP.value,
                metric="build_repair",
                baseline=None,
                candidate=None,
                delta=None,
                explanation="Repairs an existing build problem",
                code="BUILD_REPAIR",
                priority=4,
            ),
        )
        why = why[:4]

    keep_current = _keep_current_reasons(comparison, unique)
    confidence, confidence_reasons = assess_confidence(comparison, primary_metric=primary_metric)
    bucket = _style_bucket(verdict, build_repair)
    tag_map = _STYLE_TAGS[selected]
    headline = _VERDICT_HEADLINES.get(verdict, verdict.replace("_", " ").title())
    if build_repair and verdict not in {"DOWNGRADE", "STRONG_DOWNGRADE"}:
        headline = "Build repair"
    recommendation_tag = "" if non_directional else tag_map.get(bucket, tag_map["tradeoff"])

    slot = best_slot_label or comparison.get("pob_slot") or comparison.get("product_slot") or ""
    if slot and not best_slot_label:
        best_slot_label = f"Replace {slot}"

    return ItemDecisionSummary(
        headline=headline,
        recommendation_tag=recommendation_tag,
        verdict=verdict,
        why_reasons=why,
        confidence=confidence.value,
        confidence_reasons=confidence_reasons,
        build_repair=build_repair,
        keep_current_reasons=keep_current,
        best_slot_label=best_slot_label,
        recommendation_style=selected.value,
    )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta(before: Any, after: Any) -> float | None:
    b = _float_or_none(before)
    a = _float_or_none(after)
    if b is None or a is None:
        return None
    return a - b
