"""Canonical build-intelligence types. No market fields."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class BuildRole(str, Enum):
    CORE = "CORE"
    IMPORTANT = "IMPORTANT"
    USEFUL = "USEFUL"
    REDUNDANT = "REDUNDANT"
    NEUTRAL = "NEUTRAL"
    HARMFUL = "HARMFUL"


class ContributionKind(str, Enum):
    DAMAGE = "DAMAGE"
    DEFENCE = "DEFENCE"
    RECOVERY = "RECOVERY"
    RESOURCE = "RESOURCE"
    MOBILITY = "MOBILITY"
    ATTRIBUTE = "ATTRIBUTE"
    REQUIREMENT = "REQUIREMENT"
    RESISTANCE = "RESISTANCE"
    UTILITY = "UTILITY"
    ENABLER = "ENABLER"
    BASE = "BASE"


class ModSource(str, Enum):
    IMPLICIT = "implicit"
    EXPLICIT = "explicit"
    RUNE = "rune"
    PROPERTY = "property"
    PSEUDO = "pseudo"
    ENCHANT = "enchant"
    UNKNOWN = "unknown"


class BuildVerdict(str, Enum):
    MAJOR_UPGRADE = "MAJOR_UPGRADE"
    STRONG_UPGRADE = "STRONG_UPGRADE"
    MEANINGFUL_UPGRADE = "MEANINGFUL_UPGRADE"
    MINOR_UPGRADE = "MINOR_UPGRADE"
    SIDEGRADE = "SIDEGRADE"
    TRADEOFF = "TRADEOFF"
    DOWNGRADE = "DOWNGRADE"
    BUILD_FIX = "BUILD_FIX"
    BLOCKED = "BLOCKED"
    UNSAFE = "UNSAFE"


class Significance(str, Enum):
    MAJOR = "MAJOR"
    MEANINGFUL = "MEANINGFUL"
    MINOR = "MINOR"
    TRIVIAL = "TRIVIAL"
    STRATEGIC = "STRATEGIC"


class BuildConfidence(str, Enum):
    HIGH = "HIGH"
    ASSISTED = "ASSISTED"
    LOW = "LOW"


class ThresholdCode(str, Enum):
    RES_CAP_REACHED = "RES_CAP_REACHED"
    RES_CAP_LOST = "RES_CAP_LOST"
    ATTRIBUTE_REQUIREMENT_REACHED = "ATTRIBUTE_REQUIREMENT_REACHED"
    ATTRIBUTE_REQUIREMENT_LOST = "ATTRIBUTE_REQUIREMENT_LOST"
    RESOURCE_SUSTAIN_REACHED = "RESOURCE_SUSTAIN_REACHED"
    RESOURCE_SUSTAIN_LOST = "RESOURCE_SUSTAIN_LOST"
    MAIN_SKILL_VALID = "MAIN_SKILL_VALID"
    MAIN_SKILL_INVALID = "MAIN_SKILL_INVALID"
    REQUIRED_DEFENCE_THRESHOLD = "REQUIRED_DEFENCE_THRESHOLD"
    BELOW_CAP_IMPROVED = "BELOW_CAP_IMPROVED"
    BELOW_CAP_WORSENED = "BELOW_CAP_WORSENED"


class ConstraintSeverity(str, Enum):
    BLOCKING = "BLOCKING"
    UNSAFE = "UNSAFE"
    SOFT = "SOFT"


class SynergyKind(str, Enum):
    POSITIVE_SYNERGY = "POSITIVE_SYNERGY"
    DIMINISHING_OVERLAP = "DIMINISHING_OVERLAP"
    UNMEASURED = "UNMEASURED"


class AxisId(str, Enum):
    OVERALL = "OVERALL"
    OFFENSE = "OFFENSE"
    DEFENCE = "DEFENCE"
    RECOVERY = "RECOVERY"
    RESOURCE = "RESOURCE"
    MOBILITY = "MOBILITY"
    UTILITY = "UTILITY"


UPGRADE_VERDICTS = frozenset(
    {
        BuildVerdict.MAJOR_UPGRADE.value,
        BuildVerdict.STRONG_UPGRADE.value,
        BuildVerdict.MEANINGFUL_UPGRADE.value,
        BuildVerdict.MINOR_UPGRADE.value,
        BuildVerdict.BUILD_FIX.value,
    }
)

HARD_BREAK_CODES = frozenset(
    {
        ThresholdCode.MAIN_SKILL_INVALID.value,
        ThresholdCode.RESOURCE_SUSTAIN_LOST.value,
        ThresholdCode.ATTRIBUTE_REQUIREMENT_LOST.value,
        ThresholdCode.RES_CAP_LOST.value,
        "BUILD_INVALID",
    }
)


def _as_dict(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Enum):
        return value.value
    return value


@dataclass
class ItemModFact:
    """Neutral semantic identity shared with market later. No scores."""

    family: str
    source: str
    raw_text: str
    raw_value: float | None = None
    base_related: bool = False
    group: str = ""
    slot_hint: str = ""
    synergy_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ItemSemanticModel:
    base_type: str = ""
    item_class: str = ""
    rarity: str = ""
    properties: list[ItemModFact] = field(default_factory=list)
    mods: list[ItemModFact] = field(default_factory=list)
    groups: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_type": self.base_type,
            "item_class": self.item_class,
            "rarity": self.rarity,
            "properties": [item.to_dict() for item in self.properties],
            "mods": [item.to_dict() for item in self.mods],
            "groups": {key: list(value) for key, value in self.groups.items()},
        }


@dataclass
class BuildMod:
    family: str
    source: str
    raw_text: str
    raw_value: float | None = None
    base_related: bool = False
    build_role: str = BuildRole.NEUTRAL.value
    contribution_kind: str = ContributionKind.UTILITY.value
    contribution_strength: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    threshold_relation: str = ""
    synergy_tags: list[str] = field(default_factory=list)
    redundancy_group: str = ""
    confidence: str = BuildConfidence.ASSISTED.value
    group: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AxisDelta:
    axis: str
    current: float | None = None
    candidate: float | None = None
    absolute_delta: float | None = None
    percent_delta: float | None = None
    availability: str = "available"
    delta_kind: str = "MEASURED"
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ThresholdEvent:
    code: str
    metric: str
    before: float | None
    after: float | None
    threshold: float | None
    direction: str
    severity: str
    detail: str = ""
    is_build_fix: bool = False
    is_hard_break: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HardConstraint:
    code: str
    severity: str
    metric: str
    before: float | None
    after: float | None
    detail: str
    profile_independent: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SynergyFinding:
    groups: list[str]
    kind: str
    measured: bool
    impact_a: float | None = None
    impact_b: float | None = None
    impact_ab: float | None = None
    additive_expect: float | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GroupContribution:
    group: str
    label: str
    whole_score_delta: float | None
    without_group_score_delta: float | None
    marginal: float | None
    measured: bool
    pob_recalcs: int = 0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BuildImpactExplanation:
    headline: str
    primary_reasons: list[dict[str, Any]] = field(default_factory=list)
    build_fixes: list[dict[str, Any]] = field(default_factory=list)
    improvements: list[dict[str, Any]] = field(default_factory=list)
    tradeoffs: list[dict[str, Any]] = field(default_factory=list)
    hard_problems: list[dict[str, Any]] = field(default_factory=list)
    mod_contributions: list[dict[str, Any]] = field(default_factory=list)
    synergy_findings: list[dict[str, Any]] = field(default_factory=list)
    confidence: str = BuildConfidence.HIGH.value
    profile_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SlotComparisonNote:
    pob_slot: str
    product_slot: str
    product_verdict: str
    score_delta: float | None
    selected: bool = False
    blocked: bool = False
    # EvaluationOutcome public verdict + final score for this slot (player-facing).
    verdict: str = ""
    final_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BuildComparisonResult:
    """Reusable comparator output. Price is metadata for later, never upgrade truth."""

    product_verdict: str
    ranking_verdict: str
    significance: str
    confidence: str
    confidence_reasons: list[str]
    axes: dict[str, AxisDelta]
    thresholds: list[ThresholdEvent]
    build_fixes: list[ThresholdEvent]
    hard_problems: list[HardConstraint]
    mods: list[BuildMod]
    explanation: BuildImpactExplanation
    slot_notes: list[SlotComparisonNote] = field(default_factory=list)
    best_slot: str = ""
    slot_opportunity: str = ""
    pareto_status: str = ""
    contribution: list[GroupContribution] = field(default_factory=list)
    synergy: list[SynergyFinding] = field(default_factory=list)
    decomposition_status: str = "PENDING"
    profile: str = "BALANCED"
    score_delta: float | None = None
    rating: float | None = None
    semantic: dict[str, Any] = field(default_factory=dict)
    economics_seam: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_verdict": self.product_verdict,
            "ranking_verdict": self.ranking_verdict,
            "significance": self.significance,
            "confidence": self.confidence,
            "confidence_reasons": list(self.confidence_reasons),
            "axes": {key: axis.to_dict() for key, axis in self.axes.items()},
            "thresholds": [item.to_dict() for item in self.thresholds],
            "build_fixes": [item.to_dict() for item in self.build_fixes],
            "hard_problems": [item.to_dict() for item in self.hard_problems],
            "mods": [item.to_dict() for item in self.mods],
            "explanation": self.explanation.to_dict(),
            "slot_notes": [item.to_dict() for item in self.slot_notes],
            "best_slot": self.best_slot,
            "slot_opportunity": self.slot_opportunity,
            "pareto_status": self.pareto_status,
            "contribution": [item.to_dict() for item in self.contribution],
            "synergy": [item.to_dict() for item in self.synergy],
            "decomposition_status": self.decomposition_status,
            "profile": self.profile,
            "score_delta": self.score_delta,
            "rating": self.rating,
            "semantic": dict(self.semantic),
            "economics_seam": dict(self.economics_seam),
        }
