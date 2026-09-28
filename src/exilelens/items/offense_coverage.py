"""ITEM-PRO-01C — baseline offense coverage audit and dimension eligibility."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from exilelens.analysis.catalog import ProbeCatalog
from exilelens.items.primary_metric import DamageOwner, DamageQuantity, PrimaryMetricSelection, resolve_primary_metric
from exilelens.items.value_profiles import ValueProfile

OFFENSE_COVERAGE_VERSION = 2
RESPONSE_ABS_EPS = 0.5
RESPONSE_PCT_EPS = 0.05
CONTROL_OFFENSE_PCT_MAX = 0.15


class OffenseCoverageState(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    LIMITED = "LIMITED"
    UNAVAILABLE = "UNAVAILABLE"
    INSENSITIVE = "INSENSITIVE"


class PotentialDimensionEvidence(str, Enum):
    SUPPORTED = "SUPPORTED"
    RESPONSIVE = "RESPONSIVE"
    INSENSITIVE = "INSENSITIVE"
    UNSUPPORTED = "UNSUPPORTED"


class OffenseDeltaKind(str, Enum):
    MEASURED = "MEASURED"
    MEASURED_ZERO = "MEASURED_ZERO"
    # PoB produced a number for the identified main skill, but coverage probes have not
    # confirmed it tracks offense. Shown as an estimate; never scored.
    ESTIMATED = "ESTIMATED"
    MISSING = "MISSING"
    UNSUPPORTED = "UNSUPPORTED"
    UNMEASURED = "UNMEASURED"


# Offense delta kinds that must not drive the score, verdict or "damage" claims.
NON_AUTHORITATIVE_OFFENSE_KINDS = frozenset(
    {
        OffenseDeltaKind.ESTIMATED.value,
        OffenseDeltaKind.MISSING.value,
        OffenseDeltaKind.UNSUPPORTED.value,
        OffenseDeltaKind.UNMEASURED.value,
    }
)


OFFENSE_AUDIT_PROBES: tuple[tuple[str, float], ...] = (
    ("CAST_SPEED", 10.0),
    ("CAST_SPEED", 20.0),
    ("SPELL_SKILL_LEVELS", 1.0),
    ("SPELL_DAMAGE", 10.0),
    ("MOVEMENT_SPEED", 10.0),
)

MINION_OFFENSE_AUDIT_PROBES: tuple[tuple[str, float], ...] = (
    ("MINION_DAMAGE", 20.0),
    ("MINION_ATTACK_SPEED", 10.0),
    ("MINION_CAST_SPEED", 10.0),
    ("MINION_SKILL_LEVELS", 1.0),
    # Player spell damage is an actor-isolation control for a minion metric.
    ("SPELL_DAMAGE", 20.0),
    ("MOVEMENT_SPEED", 10.0),
)

# These are *observed* on C11/C14/C15, not text-based guesses about the skill.
AILMENT_AUDIT_PROBES: dict[str, tuple[tuple[str, float], ...]] = {
    "IGNITE": (("IGNITE_MAGNITUDE", 100.0), ("SPELL_DAMAGE", 20.0), ("POISON_MAGNITUDE", 100.0)),
    "POISON": (("ATTACK_SPEED", 10.0), ("PROJECTILE_SKILL_LEVELS", 1.0),
               ("POISON_DURATION", 20.0), ("SPELL_DAMAGE", 20.0)),
}


# CORPUS-02D1: the probe that proves PoB derives an ailment's active-stack count
# from the build (application rate x duration) rather than a fixed configured count.
# PoB2 CalcOffence: <Ailment>DPS = per-application DPS x min(stacks, max stacks), and
# stacks = hit chance x ailment chance x duration x hit rate unless the enemy config
# "Multiplier:<Ailment>Stacks" overrides them. A duration change moves the ailment
# DPS only in the derived case. Ignite does not stack, and its selected-stage scope
# has no equivalent single-probe proof, so it has no entry and stays PARTIAL.
AILMENT_STACK_SCOPE_PROBES: dict[str, str] = {
    "POISON": "POISON_DURATION",
}

# Specific, player-facing reasons an ailment comparison remains partial.
AILMENT_SCOPE_GAP_DETAILS: dict[str, str] = {
    "AILMENT_STACK_SCOPE_UNPROVEN": (
        "Path of Building's active {ailment} stack count did not respond to {ailment} duration "
        "(it may be fixed by the build's configuration), so changes to application rate or "
        "duration are not measured"
    ),
    "AILMENT_SCOPE_UNVERIFIED": (
        "Path of Building's {ailment} damage is measured for the selected skill, but "
        "ExileLens has no verified check that it covers every {ailment} source and stage"
    ),
    "AILMENT_RESPONSE_UNVERIFIED": (
        "Path of Building's {ailment} damage did not respond to the offense checks, "
        "or a control check changed it"
    ),
}


@dataclass
class OffenseCoverage:
    state: str
    selected_metric: str
    baseline_value: float | None
    offense_trustworthy: bool = False
    reason: str = ""
    probes: list[dict[str, Any]] = field(default_factory=list)
    dimension_evidence: dict[str, str] = field(default_factory=dict)
    pob_recalcs: int = 0
    carrier_slot: str = ""
    coverage_version: int = OFFENSE_COVERAGE_VERSION
    # CORPUS-02D1: why an ailment metric is not fully measured (empty when it is).
    scope_gap: str = ""
    scope_gap_detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "selected_metric": self.selected_metric,
            "baseline_value": self.baseline_value,
            "offense_trustworthy": self.offense_trustworthy,
            "reason": self.reason,
            "probes": list(self.probes),
            "dimension_evidence": dict(self.dimension_evidence),
            "pob_recalcs": self.pob_recalcs,
            "carrier_slot": self.carrier_slot,
            "coverage_version": self.coverage_version,
            "scope_gap": self.scope_gap,
            "scope_gap_detail": self.scope_gap_detail,
        }


def _num(metrics: dict[str, Any] | None, field_name: str) -> float | None:
    if not metrics:
        return None
    value = metrics.get(field_name)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct_delta(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    if abs(before) <= RESPONSE_ABS_EPS:
        return None
    return (after / before - 1.0) * 100.0


def _responsive(abs_delta: float | None, pct_delta: float | None) -> bool:
    if abs_delta is not None and abs(abs_delta) > RESPONSE_ABS_EPS:
        return True
    if pct_delta is not None and abs(float(pct_delta)) > RESPONSE_PCT_EPS:
        return True
    return False


def infer_offense_coverage(
    primary: dict[str, Any] | PrimaryMetricSelection | None,
    baseline_metrics: dict[str, Any] | None,
) -> OffenseCoverage:
    """Static inference from PoB outputs — no extra recalcs."""
    if isinstance(primary, PrimaryMetricSelection):
        primary_field = primary.pob_field
        confidence = primary.confidence.value
        selected = primary.selected.value
        damage_owner = primary.damage_owner.value
        source_fields = primary.raw_source_fields
    else:
        primary = primary or {}
        primary_field = str(primary.get("metric_path") or primary.get("pob_field") or "CombinedDPS")
        confidence = str(primary.get("confidence") or "high")
        selected = str(primary.get("selected") or "PRIMARY_DPS")
        damage_owner = str(primary.get("metric_source") or DamageOwner.PLAYER.value)
        source_fields = tuple(primary.get("raw_source_fields") or (primary_field,))

    raw = baseline_metrics or {}
    baseline_value = _num(raw, primary_field)
    offense_values = [
        value
        for value in (_num(raw, field) for field in source_fields)
        if value is not None and value > RESPONSE_ABS_EPS
    ]

    if not offense_values:
        return OffenseCoverage(
            state=OffenseCoverageState.UNAVAILABLE.value,
            selected_metric=primary_field,
            baseline_value=None,
            offense_trustworthy=False,
            reason="No usable offensive PoB outputs on baseline.",
            dimension_evidence={
                "CAST_SPEED": PotentialDimensionEvidence.UNSUPPORTED.value,
                "SPELL_SKILL_LEVELS": PotentialDimensionEvidence.UNSUPPORTED.value,
                "SPELL_DAMAGE": PotentialDimensionEvidence.UNSUPPORTED.value,
            },
        )

    if selected == "UNRESOLVED" or confidence == "low":
        return OffenseCoverage(
            state=OffenseCoverageState.LIMITED.value,
            selected_metric=primary_field,
            baseline_value=baseline_value,
            offense_trustworthy=False,
            reason="Primary offense metric has low resolver confidence.",
            dimension_evidence={
                "CAST_SPEED": PotentialDimensionEvidence.SUPPORTED.value,
                "SPELL_SKILL_LEVELS": PotentialDimensionEvidence.SUPPORTED.value,
                "SPELL_DAMAGE": PotentialDimensionEvidence.SUPPORTED.value,
            },
        )

    if damage_owner == DamageOwner.MINION.value and baseline_value is not None:
        return OffenseCoverage(
            state=OffenseCoverageState.PARTIAL.value,
            selected_metric=primary_field,
            baseline_value=baseline_value,
            offense_trustworthy=False,
            reason="PoB identifies mainOutput.Minion; minion response and actor-isolation probes pending.",
            dimension_evidence={
                "MINION_DAMAGE": PotentialDimensionEvidence.SUPPORTED.value,
                "MINION_ATTACK_SPEED": PotentialDimensionEvidence.SUPPORTED.value,
                "MINION_CAST_SPEED": PotentialDimensionEvidence.SUPPORTED.value,
                "MINION_SKILL_LEVELS": PotentialDimensionEvidence.SUPPORTED.value,
                "SPELL_DAMAGE": PotentialDimensionEvidence.SUPPORTED.value,
            },
        )

    return OffenseCoverage(
        state=OffenseCoverageState.PARTIAL.value,
        selected_metric=primary_field,
        baseline_value=baseline_value,
        offense_trustworthy=False,
        reason="Offense probes pending — static baseline metric only.",
        dimension_evidence={
            "CAST_SPEED": PotentialDimensionEvidence.SUPPORTED.value,
            "SPELL_SKILL_LEVELS": PotentialDimensionEvidence.SUPPORTED.value,
            "SPELL_DAMAGE": PotentialDimensionEvidence.SUPPORTED.value,
        },
    )


def apply_offense_coverage_to_profile(
    metric_profile: dict[str, dict[str, Any]],
    coverage: dict[str, Any] | OffenseCoverage | None,
    *,
    comparison: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    if coverage is None:
        return metric_profile
    payload = coverage.to_dict() if isinstance(coverage, OffenseCoverage) else dict(coverage)
    offense = dict(metric_profile.get("primary_offense") or {})
    state = str(payload.get("state") or "")
    trustworthy = bool(payload.get("offense_trustworthy"))
    abs_delta = offense.get("absolute_delta")
    pct = offense.get("percent_delta")
    stable = abs_delta is not None and abs(float(abs_delta)) <= 0.5
    if pct is not None:
        stable = stable and abs(float(pct)) <= 0.05

    if offense.get("availability") == "missing" or state == OffenseCoverageState.UNAVAILABLE.value:
        offense["delta_kind"] = OffenseDeltaKind.MISSING.value
        offense["coverage_state"] = state or OffenseCoverageState.UNAVAILABLE.value
    elif state == OffenseCoverageState.PARTIAL.value and not trustworthy and _has_offense_values(offense):
        # The main skill's PoB field has numbers on both sides, but probes have not
        # confirmed it tracks offense: an estimate, not a measurement and not "unknown".
        offense["delta_kind"] = OffenseDeltaKind.ESTIMATED.value
        offense["coverage_state"] = state
    elif not trustworthy or state in {
        OffenseCoverageState.LIMITED.value,
        OffenseCoverageState.INSENSITIVE.value,
        OffenseCoverageState.UNAVAILABLE.value,
    }:
        offense["delta_kind"] = OffenseDeltaKind.UNMEASURED.value
        offense["coverage_state"] = state
    elif stable and (
        _has_offense_values(offense)
        or (
            _zero_offense_both_sides(offense)
            and trustworthy
            and state == OffenseCoverageState.FULL.value
            and not _meaningful_offense_elsewhere(comparison or {}, str(offense.get("pob_field") or ""))
        )
    ):
        offense["delta_kind"] = OffenseDeltaKind.MEASURED_ZERO.value
        offense["coverage_state"] = state or OffenseCoverageState.FULL.value
    elif stable:
        offense["delta_kind"] = OffenseDeltaKind.MISSING.value
        offense["coverage_state"] = state or OffenseCoverageState.UNAVAILABLE.value
    else:
        offense["delta_kind"] = OffenseDeltaKind.MEASURED.value
        offense["coverage_state"] = state or OffenseCoverageState.FULL.value
    metric_profile = dict(metric_profile)
    metric_profile["primary_offense"] = offense
    return metric_profile


def _has_offense_values(offense: dict[str, Any]) -> bool:
    current = _num(offense, "current")
    candidate = _num(offense, "candidate")
    return current is not None and candidate is not None and current > RESPONSE_ABS_EPS


def _zero_offense_both_sides(offense: dict[str, Any]) -> bool:
    current = _finite_number(offense.get("current"))
    candidate = _finite_number(offense.get("candidate"))
    if current is None or candidate is None:
        return False
    return abs(current) <= RESPONSE_ABS_EPS and abs(candidate) <= RESPONSE_ABS_EPS


def _meaningful_offense_elsewhere(comparison: dict[str, Any], primary_field: str) -> bool:
    metrics = (comparison.get("baseline") or {}).get("metrics") or {}
    for metric_field in ("CombinedDPS", "TotalDPS", "TotalDot", "FullDotDPS", "FullDPS"):
        if metric_field == primary_field:
            continue
        value = _num(metrics, metric_field)
        if value is not None and value > RESPONSE_ABS_EPS:
            return True
    return False


def _skill_identity_key(identity: dict[str, Any]) -> tuple[Any, ...]:
    source = str(identity.get("source") or "")
    item_granted = bool(source) and source != "gem"
    return (
        str(identity.get("skill_id") or ""),
        item_granted,
        str(identity.get("slot") or ""),
        str(identity.get("stat_set_key") or identity.get("stat_set") or ""),
    )


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _primary_metric_semantics_equivalent(
    before: dict[str, Any],
    after: dict[str, Any],
    comparison: dict[str, Any],
) -> bool:
    """Whether two resolver selections still denote one comparable PoB signal.

    PoB can report a fractional incidental ailment below our response epsilon.  If
    an item swap removes that fraction, the resolver crosses from
    CombinedDPS/HIT_PLUS_AILMENT to TotalDPS/HIT_DPS even though those fields are
    numerically identical for comparison purposes.  Do not let that resolver
    boundary manufacture a semantic-identity failure.  Material ailment changes
    remain guarded by the same field/quantity/scope checks as before.
    """
    dimensions = (
        "metric_source", "output_table", "source_field", "semantic_quantity",
        "metric_scope", "value_type", "ailment",
    )
    if all(before.get(key) == after.get(key) for key in dimensions):
        return True

    stable_dimensions = ("metric_source", "output_table", "value_type", "ailment")
    if any(before.get(key) != after.get(key) for key in stable_dimensions):
        return False

    def signature(metric: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(metric.get("source_field") or metric.get("pob_field") or ""),
            str(metric.get("semantic_quantity") or ""),
            str(metric.get("metric_scope") or ""),
        )

    hit = ("TotalDPS", "HIT_DPS", "PRIMARY_SKILL")
    hit_plus_ailment = ("CombinedDPS", "HIT_PLUS_AILMENT", "STAT_SET_PART")
    if {signature(before), signature(after)} != {hit, hit_plus_ailment}:
        return False

    for phase in (comparison.get("baseline") or {}, comparison.get("candidate") or {}):
        metrics = phase.get("metrics") or {}
        combined = _finite_number(metrics.get("CombinedDPS"))
        total = _finite_number(metrics.get("TotalDPS"))
        if combined is None or total is None or abs(combined - total) > RESPONSE_ABS_EPS:
            return False
    return True


def offense_delta_comparable(
    comparison: dict[str, Any],
    offense: dict[str, Any],
    *,
    primary_field: str,
    primary_confidence: str,
) -> bool:
    """True when PoB produced a valid same-skill comparison on the pinned metric.

    Coverage probes may not recognize every archetype, but a concrete baseline vs
    candidate delta on the resolved main-skill field is authoritative for verdicts.
    """
    candidate_block = comparison.get("candidate") or {}
    if candidate_block.get("item_present") is False:
        return False
    if candidate_block.get("primary_skill_changed"):
        return False
    if str(primary_confidence or "").lower() == "low":
        return False
    if offense.get("availability") == "missing":
        return False
    pob_field = str(offense.get("pob_field") or primary_field)
    if pob_field != primary_field:
        return False

    baseline_skill = (comparison.get("baseline") or {}).get("primary_skill") or {}
    candidate_skill = candidate_block.get("primary_skill") or {}
    if selected_part_guard_state(baseline_skill, candidate_skill):
        return False
    if baseline_skill and candidate_skill and _skill_identity_key(baseline_skill) != _skill_identity_key(candidate_skill):
        return False

    current = _finite_number(offense.get("current"))
    candidate = _finite_number(offense.get("candidate"))
    if current is None or candidate is None:
        return False
    if abs(current) <= RESPONSE_ABS_EPS:
        return False

    pct = offense.get("percent_delta")
    abs_delta = offense.get("absolute_delta")
    if pct is None and abs_delta is None:
        return False
    if pct is not None and not math.isfinite(float(pct)):
        return False
    if abs_delta is not None and not math.isfinite(float(abs_delta)):
        return False
    return True


def offense_secondary_mechanics_partial(coverage: dict[str, Any] | OffenseCoverage | None) -> bool:
    """Secondary probe dimensions are incomplete, but primary damage may still be measured."""
    if coverage is None:
        return False
    payload = coverage.to_dict() if isinstance(coverage, OffenseCoverage) else dict(coverage)
    state = str(payload.get("state") or "")
    if state in {OffenseCoverageState.FULL.value} and bool(payload.get("offense_trustworthy")):
        return False
    return state in {
        OffenseCoverageState.PARTIAL.value,
        OffenseCoverageState.LIMITED.value,
        OffenseCoverageState.INSENSITIVE.value,
    }


OFFENSE_NOISE_FLOOR_PCT = 1.0


def clamp_primary_offense_noise(metric_profile: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Treat sub-threshold CombinedDPS drift as stable when no real offense changed."""
    offense = dict(metric_profile.get("primary_offense") or {})
    pct = offense.get("percent_delta")
    if pct is None:
        return metric_profile
    if abs(float(pct)) >= OFFENSE_NOISE_FLOOR_PCT:
        return metric_profile
    if str(offense.get("delta_kind") or "") in NON_AUTHORITATIVE_OFFENSE_KINDS:
        return metric_profile
    offense["delta_kind"] = OffenseDeltaKind.MEASURED_ZERO.value
    metric_profile = dict(metric_profile)
    metric_profile["primary_offense"] = offense
    return metric_profile


def promote_pob_measured_offense_delta(
    metric_profile: dict[str, dict[str, Any]],
    comparison: dict[str, Any],
    coverage: dict[str, Any] | OffenseCoverage | None = None,
    *,
    primary_field: str = "CombinedDPS",
    primary_confidence: str = "high",
) -> dict[str, dict[str, Any]]:
    """Trust PoB's same-skill offense delta when the comparison is genuinely comparable.

    Coverage probes can lag behind a concrete item swap or miss non-spell archetypes.
    When the main skill and metric semantic are unchanged and PoB moved the selected
    offense field, do not downgrade that delta to ESTIMATED/UNMEASURED solely because
    the generic coverage classifier is LIMITED/INSENSITIVE/PARTIAL.
    """
    offense = dict(metric_profile.get("primary_offense") or {})
    delta_kind = str(offense.get("delta_kind") or "")
    if delta_kind not in {
        OffenseDeltaKind.ESTIMATED.value,
        OffenseDeltaKind.UNMEASURED.value,
    }:
        return metric_profile
    if str(offense.get("coverage_state") or "") in {
        "PRIMARY_SKILL_CHANGED", "DAMAGE_OWNER_CHANGED", "SEMANTIC_METRIC_CHANGED",
        "STAT_SET_CHANGED", "STAT_SET_IDENTITY_UNRESOLVED",
        "SKILL_PART_CHANGED", "SKILL_PART_UNRESOLVED",
        "STAGE_CONFIGURATION_CHANGED", "STAGE_CONFIGURATION_UNRESOLVED",
        "CALCULATION_MODE_CHANGED", "CALCULATION_MODE_UNRESOLVED",
        "FULL_DPS_CONFIG_CHANGED",
    }:
        return metric_profile
    if not offense_delta_comparable(
        comparison,
        offense,
        primary_field=primary_field,
        primary_confidence=primary_confidence,
    ):
        return metric_profile

    abs_delta = abs(float(offense.get("absolute_delta") or 0))
    pct = offense.get("percent_delta")
    stable = abs_delta <= RESPONSE_ABS_EPS
    if pct is not None:
        stable = stable and abs(float(pct)) <= RESPONSE_PCT_EPS

    payload = coverage.to_dict() if isinstance(coverage, OffenseCoverage) else dict(coverage or {})
    state = str(payload.get("state") or "")
    if stable and not (_has_offense_values(offense) or _zero_offense_both_sides(offense)):
        return metric_profile
    offense["delta_kind"] = (
        OffenseDeltaKind.MEASURED_ZERO.value if stable else OffenseDeltaKind.MEASURED.value
    )
    offense["coverage_state"] = state or offense.get("coverage_state") or OffenseCoverageState.PARTIAL.value
    metric_profile = dict(metric_profile)
    metric_profile["primary_offense"] = offense
    return metric_profile
def selected_part_guard_state(baseline_skill: dict[str, Any], candidate_skill: dict[str, Any]) -> str:
    """Resolve PoB's selected semantic part, never a label or raw list position.

    Older synthetic comparisons may not carry structural IDs. They remain
    comparable only when no multi-set or multi-part selection is indicated.
    """
    if not baseline_skill or not candidate_skill:
        return ""
    for prefix, changed, unresolved in (
        ("stat_set", "STAT_SET_CHANGED", "STAT_SET_IDENTITY_UNRESOLVED"),
        ("part", "SKILL_PART_CHANGED", "SKILL_PART_UNRESOLVED"),
    ):
        before_key = str(baseline_skill.get(f"{prefix}_key") or "")
        after_key = str(candidate_skill.get(f"{prefix}_key") or "")
        count = max(int(baseline_skill.get(f"{prefix}_count") or 0),
                    int(candidate_skill.get(f"{prefix}_count") or 0))
        if (before_key or after_key or count > 1) and (not before_key or not after_key):
            return unresolved
        if before_key and before_key != after_key:
            return changed
        if count > 1 and (not baseline_skill.get(f"{prefix}_resolved") or not candidate_skill.get(f"{prefix}_resolved")):
            return unresolved
        if prefix == "stat_set" and not before_key and baseline_skill.get("stat_set") != candidate_skill.get("stat_set"):
            return changed
    before_stage = baseline_skill.get("stage_count")
    after_stage = candidate_skill.get("stage_count")
    if before_stage != after_stage:
        return "STAGE_CONFIGURATION_CHANGED" if before_stage is not None and after_stage is not None else "STAGE_CONFIGURATION_UNRESOLVED"
    before_mode = str(baseline_skill.get("calculation_mode") or "")
    after_mode = str(candidate_skill.get("calculation_mode") or "")
    if (before_mode or after_mode) and before_mode != after_mode:
        return "CALCULATION_MODE_CHANGED" if before_mode and after_mode else "CALCULATION_MODE_UNRESOLVED"
    return ""


def apply_primary_skill_guard(
    metric_profile: dict[str, dict[str, Any]],
    comparison: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Never compare different main skills as one damage delta.

    The worker re-pins PoB's main skill to the baseline's skill after the swap. If the
    skill no longer exists in the candidate build (e.g. it was granted by the replaced
    item), the damage delta compares two different skills and is unmeasured.
    """
    if comparison.get("unmodeled_item_transform"):
        # PoB compares the item untransformed (e.g. Way of the Stonefist gloves), so
        # its damage delta does not describe the in-game item.
        offense = dict(metric_profile.get("primary_offense") or {})
        offense["delta_kind"] = OffenseDeltaKind.UNSUPPORTED.value
        offense["coverage_state"] = "ITEM_TRANSFORM_UNMODELED"
        return {**metric_profile, "primary_offense": offense}
    baseline = comparison.get("baseline") or {}
    candidate = comparison.get("candidate") or {}
    baseline_skill = baseline.get("primary_skill") or {}
    candidate_skill = candidate.get("primary_skill") or {}
    actor_changed = bool(
        baseline_skill
        and candidate_skill
        and (
            baseline_skill.get("damage_owner") != candidate_skill.get("damage_owner")
            or baseline_skill.get("output_table") != candidate_skill.get("output_table")
            or baseline_skill.get("actor_id") != candidate_skill.get("actor_id")
            or baseline_skill.get("actor_skill") != candidate_skill.get("actor_skill")
        )
    )
    before_metric = comparison.get("baseline_primary_metric") or {}
    after_metric = comparison.get("candidate_primary_metric") or {}
    semantic_changed = bool(
        before_metric
        and after_metric
        and not _primary_metric_semantics_equivalent(before_metric, after_metric, comparison)
    )
    full_aggregate = str(before_metric.get("provenance") or "") == "POB_FULL_BUILD"
    before_config = (baseline.get("semantic") or {}).get("full_dps_config")
    after_config = (candidate.get("semantic") or {}).get("full_dps_config")
    full_config_changed = full_aggregate and (
        not isinstance(before_config, list) or not before_config
        or not isinstance(after_config, list) or before_config != after_config
    )
    part_state = selected_part_guard_state(baseline_skill, candidate_skill)
    skill_changed = bool(baseline_skill and candidate_skill and any(
        baseline_skill.get(k) != candidate_skill.get(k)
        for k in ("skill_id", "source", "actor_id", "actor_skill", "show_average")
    ))
    if not candidate.get("primary_skill_changed") and not actor_changed and not semantic_changed and not skill_changed and not part_state and not full_config_changed:
        return metric_profile
    offense = dict(metric_profile.get("primary_offense") or {})
    offense["delta_kind"] = OffenseDeltaKind.UNMEASURED.value
    offense["coverage_state"] = (
        "DAMAGE_OWNER_CHANGED" if actor_changed else
        "PRIMARY_SKILL_CHANGED" if candidate.get("primary_skill_changed") or skill_changed else
        "FULL_DPS_CONFIG_CHANGED" if full_config_changed else
        part_state if part_state else
        "SEMANTIC_METRIC_CHANGED"
    )
    metric_profile = dict(metric_profile)
    metric_profile["primary_offense"] = offense
    return metric_profile


def offense_claim_allowed(
    coverage: dict[str, Any] | OffenseCoverage | None,
    *,
    delta_kind: str,
) -> bool:
    """Whether compact copy may claim measured-zero offense stability."""
    if coverage is None:
        return delta_kind == OffenseDeltaKind.MEASURED_ZERO.value
    payload = coverage.to_dict() if isinstance(coverage, OffenseCoverage) else dict(coverage)
    if not payload.get("offense_trustworthy"):
        return False
    state = str(payload.get("state") or "")
    if state != OffenseCoverageState.FULL.value:
        return False
    return delta_kind == OffenseDeltaKind.MEASURED_ZERO.value


def offense_comparison_limited(
    coverage: dict[str, Any] | OffenseCoverage | None,
    *,
    delta_kind: str,
) -> bool:
    """Whether offense should be presented as limited / not confidently measured."""
    if coverage is None:
        return delta_kind in NON_AUTHORITATIVE_OFFENSE_KINDS
    payload = coverage.to_dict() if isinstance(coverage, OffenseCoverage) else dict(coverage)
    state = str(payload.get("state") or "")
    if state in {
        OffenseCoverageState.LIMITED.value,
        OffenseCoverageState.UNAVAILABLE.value,
        OffenseCoverageState.INSENSITIVE.value,
        OffenseCoverageState.PARTIAL.value,
    }:
        return True
    if delta_kind in NON_AUTHORITATIVE_OFFENSE_KINDS:
        return True
    return not bool(payload.get("offense_trustworthy"))


def dimension_eligible(coverage: dict[str, Any] | None, probe_id: str) -> tuple[bool, str]:
    if not coverage:
        return True, ""
    state = str(coverage.get("state") or "")
    evidence = str((coverage.get("dimension_evidence") or {}).get(probe_id) or PotentialDimensionEvidence.SUPPORTED.value)
    label = probe_id.replace("_", " ").title()
    if evidence == PotentialDimensionEvidence.RESPONSIVE.value:
        return True, ""
    if evidence == PotentialDimensionEvidence.INSENSITIVE.value:
        return False, f"{label} was not tested because offense signal is not responsive"
    if evidence == PotentialDimensionEvidence.UNSUPPORTED.value:
        return False, f"{label} is unsupported for this baseline"
    if state in {
        OffenseCoverageState.LIMITED.value,
        OffenseCoverageState.UNAVAILABLE.value,
        OffenseCoverageState.INSENSITIVE.value,
        OffenseCoverageState.PARTIAL.value,
    }:
        return False, f"Offense comparison limited — {label} not evaluated"
    return True, ""


def _equipment_carriers(equipment_payload: Any) -> list[tuple[str, str]]:
    if isinstance(equipment_payload, dict):
        rows = equipment_payload.get("equipment") or equipment_payload.get("slots") or []
    else:
        rows = equipment_payload or []
    mapping: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("slot"):
            mapping[str(row["slot"])] = row
    carriers: list[tuple[str, str]] = []
    for slot in ("Ring 1", "Ring 2", "Amulet", "Belt", "Helmet", "Gloves", "Boots", "Body Armour"):
        row = mapping.get(slot)
        raw = (row or {}).get("raw") or ""
        if row and row.get("equipped") and raw.strip():
            carriers.append((slot, raw))
    return carriers


def _probes_inert(rows: list[dict[str, Any]]) -> bool:
    """Every measured probe left both the selected output and CombinedDPS exactly unchanged."""
    measured = [row for row in rows if row.get("status") == "ok"]
    return bool(measured) and all(
        not row.get("primary_offense_abs") and not row.get("combined_dps_pct") for row in measured
    )


class OffenseCoverageAuditor:
    def __init__(
        self,
        engine: Any,
        *,
        catalog: ProbeCatalog | None = None,
        cache: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        from exilelens.analysis.probes import ProbeEngine

        self.engine = engine
        self.catalog = catalog or ProbeCatalog()
        self.probe_engine = ProbeEngine(engine, catalog=self.catalog)
        self._cache = cache if cache is not None else {}

    def cache_key(
        self,
        *,
        fingerprint: str,
        context: str,
        primary_field: str,
        weapon_set: int | str = 1,
        active_skill_set_id: int | str = "",
    ) -> str:
        return f"{fingerprint}|{context}|{primary_field}|ws{weapon_set}|ss{active_skill_set_id}|v{OFFENSE_COVERAGE_VERSION}"

    def get_cached(
        self,
        *,
        fingerprint: str,
        context: str,
        primary_field: str,
        weapon_set: int | str = 1,
        active_skill_set_id: int | str = "",
    ) -> OffenseCoverage | None:
        payload = self._cache.get(self.cache_key(fingerprint=fingerprint, context=context, primary_field=primary_field, weapon_set=weapon_set, active_skill_set_id=active_skill_set_id))
        if payload is None:
            return None
        return OffenseCoverage(**payload)

    def ensure(
        self,
        *,
        build_info: dict[str, Any] | None,
        baseline_metrics: dict[str, Any],
        fingerprint: str,
        context: str = "MAP",
        generation: int = 0,
        force: bool = False,
        weapon_set: int | str = 1,
        active_skill_set_id: int | str = "",
    ) -> OffenseCoverage:
        primary = resolve_primary_metric(build_info, baseline_metrics)
        info = build_info or {}
        weapon_set = info.get("weapon_set", weapon_set)
        active_skill_set_id = info.get("active_skill_set_id", active_skill_set_id)
        key = self.cache_key(fingerprint=fingerprint, context=context, primary_field=primary.pob_field, weapon_set=weapon_set, active_skill_set_id=active_skill_set_id)
        if not force:
            cached = self._cache.get(key)
            if cached is not None:
                return OffenseCoverage(**cached)

        static = infer_offense_coverage(primary, baseline_metrics)
        if static.state == OffenseCoverageState.UNAVAILABLE.value:
            self._cache[key] = static.__dict__
            return static

        carriers = _equipment_carriers(self.engine.get_equipment())
        if not carriers:
            limited = OffenseCoverage(
                state=OffenseCoverageState.LIMITED.value,
                selected_metric=primary.pob_field,
                baseline_value=_num(baseline_metrics, primary.pob_field),
                offense_trustworthy=False,
                reason="No safe carrier item for offense probes.",
                dimension_evidence=dict(static.dimension_evidence),
            )
            self._cache[key] = limited.__dict__
            return limited

        from exilelens.analysis.probes import clone_item_with_mods, score_probe_metrics

        minion_metric = primary.damage_owner == DamageOwner.MINION
        ailment_metric = primary.semantic_quantity == DamageQuantity.AILMENT_DPS
        audit_probes = (MINION_OFFENSE_AUDIT_PROBES if minion_metric else
                        AILMENT_AUDIT_PROBES.get(primary.ailment, ()) if ailment_metric else OFFENSE_AUDIT_PROBES)
        actor_controls = ({"SPELL_DAMAGE", "MOVEMENT_SPEED"} if minion_metric else
                          {"POISON_MAGNITUDE"} if primary.ailment == "IGNITE" else
                          {"SPELL_DAMAGE"} if ailment_metric else {"MOVEMENT_SPEED"})

        def carrier_is_inert(carrier_slot: str, carrier_raw: str) -> bool:
            # CORPUS-02D1: some equipped items ignore lines added to them in PoB (e.g.
            # Kalandra's Touch, "Reflects opposite Ring", which PoB replaces with the
            # opposite ring's modifiers). Every probe on such a carrier is a no-op.
            definition = self.catalog.get("MOVEMENT_SPEED")
            if definition is None:
                return False
            try:
                evaluation = self.engine.evaluate_candidate(
                    carrier_slot, clone_item_with_mods(carrier_raw, [definition.line(10.0)]), context=context,
                )
            except Exception:
                return False
            self.probe_engine.pob_recalcs += 1
            before = _num(evaluation["baseline"]["metrics"], "MovementSpeedMod")
            after = _num(evaluation["candidate"]["metrics"], "MovementSpeedMod")
            return before is not None and after is not None and before == after

        skipped_carriers: list[str] = []
        for carrier_index, (carrier_slot, carrier_raw) in enumerate(carriers):
            probe_rows = self._run_probes(
                carrier_slot, carrier_raw, primary, audit_probes, actor_controls, context,
                clone_item_with_mods, score_probe_metrics,
            )
            if (
                carrier_index + 1 < len(carriers)
                and _probes_inert(probe_rows)
                and carrier_is_inert(carrier_slot, carrier_raw)
            ):
                skipped_carriers.append(carrier_slot)
                continue
            break

        coverage = _classify_from_probes(primary, baseline_metrics, probe_rows, carrier_slot=carrier_slot)
        if skipped_carriers:
            coverage.reason = f"{coverage.reason} Inert probe carriers skipped: {', '.join(skipped_carriers)}."
        coverage.pob_recalcs = self.probe_engine.pob_recalcs
        self._cache[key] = coverage.__dict__
        return coverage

    def _run_probes(
        self,
        carrier_slot: str,
        carrier_raw: str,
        primary: PrimaryMetricSelection,
        audit_probes: tuple[tuple[str, float], ...],
        actor_controls: set[str],
        context: str,
        clone_item_with_mods: Any,
        score_probe_metrics: Any,
    ) -> list[dict[str, Any]]:
        probe_rows: list[dict[str, Any]] = []
        for probe_id, magnitude in audit_probes:
            definition = self.catalog.get(probe_id)
            if definition is None:
                continue
            probed_item = clone_item_with_mods(carrier_raw, [definition.line(magnitude)])
            try:
                evaluation = self.engine.evaluate_candidate(carrier_slot, probed_item, context=context)
            except Exception as exc:
                probe_rows.append(
                    {
                        "probe_id": probe_id,
                        "magnitude": magnitude,
                        "status": "REJECTED",
                        "error": str(exc),
                        "control": probe_id in actor_controls,
                    }
                )
                continue
            self.probe_engine.pob_recalcs += 1
            restore = evaluation.get("restore") or {}
            if not restore.get("pass"):
                probe_rows.append(
                    {
                        "probe_id": probe_id,
                        "magnitude": magnitude,
                        "status": "RESTORE_FAILED",
                        "control": probe_id in actor_controls,
                    }
                )
                continue
            before = evaluation["baseline"]["metrics"]
            after = evaluation["candidate"]["metrics"]
            scored = score_probe_metrics(
                before,
                after,
                ValueProfile.BALANCED,
                primary_field=primary.pob_field,
                primary_confidence=primary.confidence.value,
            )
            offense = scored["metric_profile"].get("primary_offense") or {}
            primary_pct = offense.get("percent_delta")
            probe_rows.append(
                {
                    "probe_id": probe_id,
                    "magnitude": magnitude,
                    "status": "ok",
                    "primary_offense_pct": primary_pct,
                    "primary_offense_abs": offense.get("absolute_delta"),
                    "combined_dps_pct": _pct_delta(_num(before, "CombinedDPS"), _num(after, "CombinedDPS")),
                    "build_value_rating": (scored.get("value") or {}).get("rating"),
                    "build_value_delta": (scored.get("value") or {}).get("score_delta"),
                    "responsive": _responsive(offense.get("absolute_delta"), primary_pct),
                    "control": probe_id in actor_controls,
                    "fingerprint_match": evaluation["baseline"]["fingerprint_hash"] == evaluation["restored"]["fingerprint_hash"],
                }
            )
        return probe_rows


def _classify_from_probes(
    primary: PrimaryMetricSelection,
    baseline_metrics: dict[str, Any],
    probes: list[dict[str, Any]],
    *,
    carrier_slot: str,
) -> OffenseCoverage:
    baseline_value = _num(baseline_metrics, primary.pob_field)
    dimension_evidence: dict[str, str] = {}
    if primary.semantic_quantity == DamageQuantity.AILMENT_DPS:
        for probe_id, _magnitude in AILMENT_AUDIT_PROBES.get(primary.ailment, ()):
            rows = [row for row in probes if row.get("probe_id") == probe_id and row.get("status") == "ok"]
            dimension_evidence[probe_id] = (
                PotentialDimensionEvidence.UNSUPPORTED.value if not rows else
                PotentialDimensionEvidence.RESPONSIVE.value if any(row.get("responsive") for row in rows) else
                PotentialDimensionEvidence.INSENSITIVE.value
            )
    if primary.damage_owner == DamageOwner.MINION:
        actor_probe_ids = ("MINION_DAMAGE", "MINION_ATTACK_SPEED", "MINION_CAST_SPEED", "MINION_SKILL_LEVELS")
        for probe_id in actor_probe_ids:
            rows = [row for row in probes if row.get("probe_id") == probe_id and row.get("status") == "ok"]
            if not rows:
                dimension_evidence[probe_id] = PotentialDimensionEvidence.UNSUPPORTED.value
            else:
                dimension_evidence[probe_id] = (
                    PotentialDimensionEvidence.RESPONSIVE.value
                    if any(row.get("responsive") for row in rows)
                    else PotentialDimensionEvidence.INSENSITIVE.value
                )
        spell_rows = [row for row in probes if row.get("probe_id") == "SPELL_DAMAGE" and row.get("status") == "ok"]
        dimension_evidence["SPELL_DAMAGE"] = (
            PotentialDimensionEvidence.RESPONSIVE.value
            if any(row.get("responsive") for row in spell_rows)
            else PotentialDimensionEvidence.INSENSITIVE.value
        )
    else:
        actor_probe_ids = ()
    cast_rows = [row for row in probes if row.get("probe_id") == "CAST_SPEED" and row.get("status") == "ok"]
    cast_responsive = any(row.get("responsive") for row in cast_rows)
    if primary.damage_owner != DamageOwner.MINION:
        dimension_evidence["CAST_SPEED"] = (
            PotentialDimensionEvidence.RESPONSIVE.value
            if cast_responsive
            else PotentialDimensionEvidence.INSENSITIVE.value
        )

    for probe_id in (() if primary.damage_owner == DamageOwner.MINION else ("SPELL_SKILL_LEVELS", "SPELL_DAMAGE")):
        rows = [row for row in probes if row.get("probe_id") == probe_id and row.get("status") == "ok"]
        if not rows:
            dimension_evidence[probe_id] = PotentialDimensionEvidence.UNSUPPORTED.value
        else:
            dimension_evidence[probe_id] = (
                PotentialDimensionEvidence.RESPONSIVE.value
                if any(row.get("responsive") for row in rows)
                else PotentialDimensionEvidence.INSENSITIVE.value
            )

    control_rows = [row for row in probes if row.get("control") and row.get("status") == "ok"]
    control_leaked = any(
        abs(float(row.get("primary_offense_pct") or 0)) > CONTROL_OFFENSE_PCT_MAX
        or (primary.semantic_quantity != DamageQuantity.AILMENT_DPS
            and abs(float(row.get("combined_dps_pct") or 0)) > CONTROL_OFFENSE_PCT_MAX)
        for row in control_rows
    )
    offense_rows = [row for row in probes if not row.get("control") and row.get("status") == "ok"]
    any_offense_response = any(row.get("responsive") for row in offense_rows)

    actor_responsive = any(
        row.get("responsive")
        for row in probes
        if row.get("probe_id") in actor_probe_ids and row.get("status") == "ok"
    )
    scope_gap = ""
    if primary.semantic_quantity == DamageQuantity.AILMENT_DPS:
        trustworthy = False
        stack_probe = AILMENT_STACK_SCOPE_PROBES.get(primary.ailment, "")
        scaling_responsive = any(
            row.get("responsive") for row in offense_rows if row.get("probe_id") != stack_probe
        )
        if not any_offense_response or control_leaked or primary.confidence.value == "low":
            state = OffenseCoverageState.LIMITED.value
            reason = "Selected ailment output lacks responsive probes or its negative control leaked."
            scope_gap = "AILMENT_RESPONSE_UNVERIFIED"
        elif not stack_probe:
            state = OffenseCoverageState.PARTIAL.value
            reason = "PoB ailment response verified for selected stat set; no stack/stage scope proof for this ailment."
            scope_gap = "AILMENT_SCOPE_UNVERIFIED"
        elif dimension_evidence.get(stack_probe) != PotentialDimensionEvidence.RESPONSIVE.value:
            state = OffenseCoverageState.PARTIAL.value
            reason = f"{primary.pob_field} did not respond to {stack_probe}; the active stack count is not derived by PoB."
            scope_gap = "AILMENT_STACK_SCOPE_UNPROVEN"
        elif not scaling_responsive:
            state = OffenseCoverageState.PARTIAL.value
            reason = f"{primary.pob_field} responds only to {stack_probe}; hit-rate/damage scaling is unverified."
            scope_gap = "AILMENT_RESPONSE_UNVERIFIED"
        else:
            # PoB derives the stacks from application rate and duration, scales the
            # ailment with the skill's hit rate/damage, and the actor control is clean:
            # the selected ailment output is PoB's complete measurement of that ailment.
            state = OffenseCoverageState.FULL.value
            reason = (f"{primary.pob_field} responds to {stack_probe} (PoB-derived stacks) and to "
                      "hit-rate/damage probes; the actor control did not move it.")
            trustworthy = True
    elif not any_offense_response and not cast_responsive:
        state = OffenseCoverageState.INSENSITIVE.value
        reason = f"{primary.pob_field} did not respond to cast speed / skill / damage probes."
        trustworthy = False
    elif primary.confidence.value == "low" or control_leaked:
        state = OffenseCoverageState.LIMITED.value
        reason = "Offense probes are ambiguous for this baseline."
        trustworthy = False
    elif primary.damage_owner == DamageOwner.MINION and actor_responsive and primary.confidence.value == "high":
        state = OffenseCoverageState.FULL.value
        reason = f"{primary.pob_field} responds to minion-specific offense probes."
        trustworthy = True
    elif cast_responsive and primary.confidence.value == "high":
        state = OffenseCoverageState.FULL.value
        reason = f"{primary.pob_field} responds to offense probes."
        trustworthy = True
    else:
        state = OffenseCoverageState.PARTIAL.value
        reason = "Offense partially measurable — some dimensions insensitive."
        trustworthy = bool(any_offense_response and primary.confidence.value == "high")

    return OffenseCoverage(
        state=state,
        selected_metric=primary.pob_field,
        baseline_value=baseline_value,
        offense_trustworthy=trustworthy,
        reason=reason,
        probes=probes,
        dimension_evidence=dimension_evidence,
        carrier_slot=carrier_slot,
        scope_gap=scope_gap,
        scope_gap_detail=(
            AILMENT_SCOPE_GAP_DETAILS[scope_gap].format(ailment=(primary.ailment or "ailment").lower())
            if scope_gap else ""
        ),
    )
