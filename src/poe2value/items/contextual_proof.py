"""Slice 4A internal: deterministic evidence/proof layer across weapon-set contexts.

Built only on Slice 3 contextual measurements
(:mod:`poe2value.items.contextual_evaluation`); it introduces no evaluation
path of its own and performs no PoB calculation.

Three layers stay separate:

- ``measurement`` -- one candidate evaluated for one contextual component
  reference (Slice 3 output, reused unchanged);
- ``relationship/proof`` -- what several measurements jointly show
  (this module);
- ``public verdict`` -- untouched. Nothing here feeds ranking, scoring, or
  verdict code, and nothing here may promote a component observation to
  ``UPGRADE``/``SIDEGRADE``/``DOWNGRADE``.

The one relationship signal implemented is a common-ratio/common-response
check: several measured outputs changing by approximately the same
proportional factor may be different observations of the same underlying
change rather than independent additive damage. That is evidence only:

- a match never authorizes adding component values across weapon sets;
- a match never establishes causality, trigger chains, projectile counts,
  snapshot behavior, or practical/rotation DPS;
- insufficient or ambiguous evidence classifies as such explicitly.

Safety mirrors Slice 3: unavailable data is never converted to zero, and
no ratio or percentage is claimed on a near-zero baseline (same 0.5
absolute threshold the rest of the pipeline uses).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from collections.abc import Mapping

from poe2value.items.effect_components import ContextualComponentReference
from poe2value.items.offense_coverage import RESPONSE_ABS_EPS

__all__ = [
    "COMMON_RESPONSE_RELATIVE_TOLERANCE",
    "ContextualMeasurement",
    "ContextualRelationship",
    "ContextualProof",
    "collect_measurements",
    "classify_relationship",
    "prove_candidate_relationship",
]

#: Maximum relative spread of per-observation response factors that still
#: counts as "approximately the same proportional factor". Deterministic and
#: documented: (max - min) / max(|mean|, tiny) <= this value.
COMMON_RESPONSE_RELATIVE_TOLERANCE = 0.05

#: Minimum absolute baseline magnitude for a ratio to be claimed. Reuses the
#: pipeline-wide response epsilon (also used by Slice 3's component delta and
#: the offense-coverage probes): at or below this, a reliable ratio cannot be
#: calculated and classification must refuse.
RATIO_MIN_BASELINE = RESPONSE_ABS_EPS

#: Minimum absolute change for a response to count as a measurable change at
#: all. Uniform no-change agreement carries no information about a shared
#: underlying change, so it is insufficient evidence rather than a match.
RESPONSE_MIN_CHANGE = RESPONSE_ABS_EPS


class ContextualRelationship(str, Enum):
    """Exact relationship classifications supported by Slice 4A."""

    #: Several measured outputs changed by approximately the same
    #: proportional factor. Evidence of a shared response only -- not
    #: causation, not authorization to add values across contexts.
    COMMON_RESPONSE = "COMMON_RESPONSE"
    #: Measured outputs changed by clearly different factors.
    DIVERGENT_RESPONSE = "DIVERGENT_RESPONSE"
    #: Too little usable evidence to decide (single observation, near-zero
    #: baselines everywhere, or agreement on no measurable change).
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    #: Comparison is not valid (an observation is unavailable/invalid in its
    #: context, outputs are missing, or values are non-finite).
    NOT_COMPARABLE = "NOT_COMPARABLE"


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _numeric_outputs(output: Any) -> dict[str, float]:
    """Finite numeric fields of one PoB-native output table, else empty."""
    if not isinstance(output, Mapping):
        return {}
    result: dict[str, float] = {}
    for key, value in output.items():
        number = _finite_number(value)
        if number is not None:
            result[str(key)] = number
    return result


@dataclass(frozen=True)
class ContextualMeasurement:
    """One Slice 3 candidate measurement, lifted into proof inputs.

    ``qualified`` preserves full context identity (component + weapon set +
    skill set); ``physical_target`` records where the candidate was placed;
    ``baseline_output``/``candidate_output`` are the exact PoB-native tables;
    ``source``/``frames`` carry provenance for explanation.
    Unavailable observations are representable (``status`` other than
    ``MEASURED``) but never given synthetic zero outputs.
    """

    qualified: ContextualComponentReference
    physical_target: Mapping[str, Any] | None
    status: str
    reason: str = ""
    baseline_output: Mapping[str, float] | None = None
    candidate_output: Mapping[str, float] | None = None
    source: str = ""
    frames: Mapping[str, Any] | None = None
    restore_pass: bool | None = None

    @property
    def cache_identity(self) -> str:
        return self.qualified.cache_identity

    @classmethod
    def from_candidate_result(
        cls,
        result: Mapping[str, Any],
        *,
        reference: Mapping[str, Any],
        context: Mapping[str, Any],
        physical_target: Mapping[str, Any] | None = None,
    ) -> "ContextualMeasurement":
        """Lift one Slice 3 ``evaluate_effect_candidate`` result.

        ``reference``/``context``/``physical_target`` are the inputs the
        measurement was requested with (the result itself carries the
        measured outputs). Raises ``ValueError`` on malformed identity, so a
        proof can never be built on an unidentified observation.
        """
        qualified = ContextualComponentReference.from_dict(
            {"component": dict(reference), "context": dict(context)}
        )
        if not isinstance(result, Mapping):
            raise ValueError("contextual measurement result must be a mapping")
        status = str(result.get("status") or "UNAVAILABLE")
        baseline_block = result.get("baseline")
        candidate_block = result.get("candidate")
        baseline_output = None
        candidate_output = None
        if status == "MEASURED":
            baseline_output = _numeric_outputs(
                baseline_block.get("output") if isinstance(baseline_block, Mapping) else None
            )
            candidate_output = _numeric_outputs(
                candidate_block.get("output") if isinstance(candidate_block, Mapping) else None
            )
        baseline_source = (
            baseline_block.get("source") if isinstance(baseline_block, Mapping) else ""
        )
        candidate_source = (
            candidate_block.get("source") if isinstance(candidate_block, Mapping) else ""
        )
        restore = result.get("restore")
        return cls(
            qualified=qualified,
            physical_target=dict(physical_target) if isinstance(physical_target, Mapping) else None,
            status=status,
            reason=str(result.get("reason") or ""),
            baseline_output=baseline_output,
            candidate_output=candidate_output,
            source=str(candidate_source or baseline_source or ""),
            frames=dict(result["frames"]) if isinstance(result.get("frames"), Mapping) else None,
            restore_pass=bool(restore.get("pass")) if isinstance(restore, Mapping) and "pass" in restore else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "qualified_reference": self.qualified.to_dict(),
            "cache_identity": self.cache_identity,
            "physical_target": dict(self.physical_target) if self.physical_target is not None else None,
            "status": self.status,
            "reason": self.reason,
            "baseline_output": dict(self.baseline_output) if self.baseline_output is not None else None,
            "candidate_output": dict(self.candidate_output) if self.candidate_output is not None else None,
            "source": self.source,
            "frames": dict(self.frames) if self.frames is not None else None,
            "restore_pass": self.restore_pass,
        }


def collect_measurements(
    results: list[Mapping[str, Any]],
    *,
    references: list[Mapping[str, Any]],
    contexts: list[Mapping[str, Any]],
    physical_targets: list[Mapping[str, Any] | None] | None = None,
) -> list[ContextualMeasurement]:
    """Pair Slice 3 results with the identities they were requested with.

    Length mismatch is a caller error (fail closed), never silent truncation.
    """
    targets = list(physical_targets) if physical_targets is not None else [None] * len(results)
    if not (len(results) == len(references) == len(contexts) == len(targets)):
        raise ValueError("results, references, contexts and physical targets must align one-to-one")
    return [
        ContextualMeasurement.from_candidate_result(
            result, reference=reference, context=context, physical_target=target
        )
        for result, reference, context, target in zip(results, references, contexts, targets)
    ]


@dataclass
class ContextualProof:
    """Inspectable structured evidence for Slice 4B consumption.

    Never a verdict: no ranking/scoring input, no directional claim, no
    summed cross-context value anywhere in this structure.
    """

    classification: ContextualRelationship
    reason: str
    measurements: list[ContextualMeasurement] = field(default_factory=list)
    compared_fields: list[str] = field(default_factory=list)
    factors: dict[str, float] = field(default_factory=dict)
    representative_factor: float | None = None
    tolerance: float = COMMON_RESPONSE_RELATIVE_TOLERANCE
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "reason": self.reason,
            "measurements": [measurement.to_dict() for measurement in self.measurements],
            "compared_fields": list(self.compared_fields),
            "factors": dict(self.factors),
            "representative_factor": self.representative_factor,
            "tolerance": self.tolerance,
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "warnings": list(self.warnings),
        }


_BASE_ASSUMPTIONS = (
    "Each input measurement was produced by Slice 3 transactional evaluation: PoB computed, ExileLens compared.",
    "Compared outputs are PoB-native tables for the exact qualified component identity; identity match was enforced at measurement time.",
    "Restoration of weapon set, physical slots, and calculation state was verified per measurement (see each input's restore record).",
)

_BASE_LIMITATIONS = (
    "A common proportional response is evidence of a shared response only; it does not establish causality, trigger chains, projectile counts, snapshot behavior, or practical/rotation DPS.",
    "Component values from different weapon sets must never be added together on the basis of this proof.",
)


def classify_relationship(
    measurements: list[ContextualMeasurement],
    *,
    field_name: str | None = None,
    tolerance: float = COMMON_RESPONSE_RELATIVE_TOLERANCE,
) -> ContextualProof:
    """Deterministically classify the relationship across measurements.

    ``field_name`` restricts comparison to one PoB output field; otherwise
    every numeric field with a significant baseline in *all* observations is
    compared (deterministic sorted order). Degrades safely: unavailable or
    non-finite data yields ``NOT_COMPARABLE``; near-zero baselines or
    agreement on no measurable change yields ``INSUFFICIENT_EVIDENCE``.
    """
    if tolerance <= 0:
        raise ValueError("tolerance must be positive")
    if len(measurements) < 2:
        return ContextualProof(
            classification=ContextualRelationship.INSUFFICIENT_EVIDENCE,
            reason="NEED_AT_LEAST_TWO_OBSERVATIONS",
            measurements=list(measurements),
            tolerance=tolerance,
            assumptions=list(_BASE_ASSUMPTIONS),
            limitations=list(_BASE_LIMITATIONS),
        )

    for measurement in measurements:
        if measurement.status != "MEASURED":
            return ContextualProof(
                classification=ContextualRelationship.NOT_COMPARABLE,
                reason=f"OBSERVATION_NOT_MEASURED:{measurement.status}"
                + (f":{measurement.reason}" if measurement.reason else ""),
                measurements=list(measurements),
                tolerance=tolerance,
                assumptions=list(_BASE_ASSUMPTIONS),
                limitations=list(_BASE_LIMITATIONS),
            )
        if not measurement.baseline_output or not measurement.candidate_output:
            return ContextualProof(
                classification=ContextualRelationship.NOT_COMPARABLE,
                reason="OBSERVATION_MISSING_OUTPUT",
                measurements=list(measurements),
                tolerance=tolerance,
                assumptions=list(_BASE_ASSUMPTIONS),
                limitations=list(_BASE_LIMITATIONS),
            )

    if field_name is not None:
        candidate_fields = [str(field_name)]
    else:
        shared = set(measurements[0].baseline_output or {})
        for measurement in measurements[1:]:
            shared &= set(measurement.baseline_output or {})
            shared &= set(measurement.candidate_output or {})
        shared &= set(measurements[0].candidate_output or {})
        candidate_fields = sorted(shared)

    usable_fields: list[str] = []
    for compared in candidate_fields:
        baselines = [
            (measurement.baseline_output or {}).get(compared) for measurement in measurements
        ]
        afters = [
            (measurement.candidate_output or {}).get(compared) for measurement in measurements
        ]
        if any(value is None for value in baselines + afters):
            continue
        if any(abs(float(value)) <= RATIO_MIN_BASELINE for value in baselines):
            continue
        usable_fields.append(compared)

    if not usable_fields:
        reason = "FIELD_NOT_COMPARABLE" if field_name is not None else "NEAR_ZERO_BASELINE_REFUSES_RATIO"
        return ContextualProof(
            classification=ContextualRelationship.INSUFFICIENT_EVIDENCE,
            reason=reason,
            measurements=list(measurements),
            compared_fields=candidate_fields if field_name is None else [str(field_name)],
            tolerance=tolerance,
            assumptions=list(_BASE_ASSUMPTIONS),
            limitations=list(_BASE_LIMITATIONS),
        )

    factors: dict[str, float] = {}
    material_change = False
    for index, measurement in enumerate(measurements):
        ratios: list[float] = []
        for compared in usable_fields:
            before = float((measurement.baseline_output or {})[compared])
            after = float((measurement.candidate_output or {})[compared])
            ratios.append(after / before)
            if abs(after - before) > RESPONSE_MIN_CHANGE:
                material_change = True
        # One factor per observation: the mean ratio across compared fields.
        # Multi-field observations must first agree with themselves; a wide
        # internal spread means the observation has no single response.
        internal_spread = (max(ratios) - min(ratios)) / max(abs(sum(ratios) / len(ratios)), 1e-9)
        if internal_spread > tolerance:
            return ContextualProof(
                classification=ContextualRelationship.DIVERGENT_RESPONSE,
                reason="OBSERVATION_FIELDS_DISAGREE",
                measurements=list(measurements),
                compared_fields=usable_fields,
                tolerance=tolerance,
                assumptions=list(_BASE_ASSUMPTIONS),
                limitations=list(_BASE_LIMITATIONS),
            )
        factors[measurement.cache_identity] = sum(ratios) / len(ratios)

    values = list(factors.values())
    mean = sum(values) / len(values)
    spread = (max(values) - min(values)) / max(abs(mean), 1e-9)
    if spread > tolerance:
        return ContextualProof(
            classification=ContextualRelationship.DIVERGENT_RESPONSE,
            reason="RESPONSE_FACTORS_DIVERGE",
            measurements=list(measurements),
            compared_fields=usable_fields,
            factors=factors,
            representative_factor=mean,
            tolerance=tolerance,
            assumptions=list(_BASE_ASSUMPTIONS),
            limitations=list(_BASE_LIMITATIONS),
        )
    if not material_change:
        return ContextualProof(
            classification=ContextualRelationship.INSUFFICIENT_EVIDENCE,
            reason="NO_MEASURABLE_CHANGE",
            measurements=list(measurements),
            compared_fields=usable_fields,
            factors=factors,
            representative_factor=mean,
            tolerance=tolerance,
            assumptions=list(_BASE_ASSUMPTIONS),
            limitations=list(_BASE_LIMITATIONS),
        )
    return ContextualProof(
        classification=ContextualRelationship.COMMON_RESPONSE,
        reason="SHARED_PROPORTIONAL_RESPONSE",
        measurements=list(measurements),
        compared_fields=usable_fields,
        factors=factors,
        representative_factor=mean,
        tolerance=tolerance,
        assumptions=list(_BASE_ASSUMPTIONS),
        limitations=list(_BASE_LIMITATIONS),
        warnings=[
            "Common response is shared-response evidence only: it does not establish causality.",
            "Do not add component values across weapon sets on the basis of this proof.",
        ],
    )


def prove_candidate_relationship(
    results: list[Mapping[str, Any]],
    *,
    references: list[Mapping[str, Any]],
    contexts: list[Mapping[str, Any]],
    physical_targets: list[Mapping[str, Any] | None] | None = None,
    field_name: str | None = None,
    tolerance: float = COMMON_RESPONSE_RELATIVE_TOLERANCE,
) -> dict[str, Any]:
    """One-call helper: lift Slice 3 results, classify, return proof dict."""
    measurements = collect_measurements(
        results,
        references=references,
        contexts=contexts,
        physical_targets=physical_targets,
    )
    return classify_relationship(measurements, field_name=field_name, tolerance=tolerance).to_dict()
