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

Same-candidate binding: every measurement carries provenance
(``candidate_fingerprint``, ``source_identity``, ``source_revision``,
``build_generation``). Callers should source the fingerprint from
``evaluation_identity.candidate_fingerprint`` (the exact candidate text
evaluated) and the identity/revision/generation from the engine that
performed the evaluation. The classifier requires unanimous provenance
where present and refuses any definitive relationship claim when no
provenance is present at all: a proof must never compare component A
measured for candidate X with component B measured for candidate Y, nor
silently compare stale measurements from different loaded builds -- and
different source identities never compare even if revision tokens happen
to match.
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
    #: Provenance binding one proof's measurements to a single candidate
    #: evaluation. Empty/absent means "unproven", never "any candidate".
    #: ``source_identity`` is the canonical loaded-source key
    #: (``loaded_source_ref.key``); different sources never compare even
    #: when revision tokens coincide.
    candidate_fingerprint: str = ""
    source_identity: str = ""
    source_revision: str = ""
    build_generation: int | None = None

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
        candidate_fingerprint: str = "",
        source_identity: str = "",
        source_revision: str = "",
        build_generation: int | None = None,
    ) -> "ContextualMeasurement":
        """Lift one Slice 3 ``evaluate_effect_candidate`` result.

        ``reference``/``context``/``physical_target`` are the inputs the
        measurement was requested with (the result itself carries the
        measured outputs). ``candidate_fingerprint`` should be
        ``evaluation_identity.candidate_fingerprint`` of the exact evaluated
        text; ``source_identity``/``source_revision``/``build_generation``
        identify the loaded build the measurement came from. Raises
        ``ValueError`` on malformed identity, so a proof can never be built
        on an unidentified observation.
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
        if build_generation is not None and isinstance(build_generation, bool):
            raise ValueError("build_generation must be an integer or None")
        try:
            generation = int(build_generation) if build_generation is not None else None
        except (TypeError, ValueError) as exc:
            raise ValueError("build_generation must be an integer or None") from exc
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
            candidate_fingerprint=str(candidate_fingerprint or ""),
            source_identity=str(source_identity or ""),
            source_revision=str(source_revision or ""),
            build_generation=generation,
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
            "candidate_fingerprint": self.candidate_fingerprint,
            "source_identity": self.source_identity,
            "source_revision": self.source_revision,
            "build_generation": self.build_generation,
        }


def collect_measurements(
    results: list[Mapping[str, Any]],
    *,
    references: list[Mapping[str, Any]],
    contexts: list[Mapping[str, Any]],
    physical_targets: list[Mapping[str, Any] | None] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> list[ContextualMeasurement]:
    """Pair Slice 3 results with the identities they were requested with.

    ``provenance`` (``candidate_fingerprint`` / ``source_identity`` /
    ``source_revision`` / ``build_generation``) is attached uniformly when
    one candidate evaluation produced every result -- the normal case.
    Length mismatch is a caller error (fail closed), never silent truncation.
    """
    targets = list(physical_targets) if physical_targets is not None else [None] * len(results)
    if not (len(results) == len(references) == len(contexts) == len(targets)):
        raise ValueError("results, references, contexts and physical targets must align one-to-one")
    proof = dict(provenance) if isinstance(provenance, Mapping) else {}
    return [
        ContextualMeasurement.from_candidate_result(
            result,
            reference=reference,
            context=context,
            physical_target=target,
            candidate_fingerprint=proof.get("candidate_fingerprint", ""),
            source_identity=proof.get("source_identity", ""),
            source_revision=proof.get("source_revision", ""),
            build_generation=proof.get("build_generation"),
        )
        for result, reference, context, target in zip(results, references, contexts, targets)
    ]


@dataclass
class ContextualProof:
    """Inspectable structured evidence for Slice 4B consumption.

    Never a verdict: no ranking/scoring input, no directional claim, no
    summed cross-context value anywhere in this structure.

    ``scope`` is a machine-readable capability label: this layer proves only
    observed response consistency, never whole-interaction deltas.
    ``exact`` is False in Slice 4A: ``COMMON_RESPONSE`` is explicitly
    approximate (empirically similar within ``tolerance``), not a
    mathematically exact common factor, and must never be consumed as one.
    """

    classification: ContextualRelationship
    reason: str
    measurements: list[ContextualMeasurement] = field(default_factory=list)
    compared_fields: list[str] = field(default_factory=list)
    factors: dict[str, float] = field(default_factory=dict)
    representative_factor: float | None = None
    tolerance: float = COMMON_RESPONSE_RELATIVE_TOLERANCE
    scope: str = "OBSERVED_RESPONSE_CONSISTENCY"
    exact: bool = False
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
            "scope": self.scope,
            "exact": self.exact,
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


def _proof_shell(
    classification: ContextualRelationship,
    reason: str,
    measurements: list[ContextualMeasurement],
    tolerance: float,
    *,
    compared_fields: list[str] | None = None,
    factors: dict[str, float] | None = None,
    representative_factor: float | None = None,
) -> ContextualProof:
    return ContextualProof(
        classification=classification,
        reason=reason,
        measurements=list(measurements),
        compared_fields=list(compared_fields or []),
        factors=dict(factors or {}),
        representative_factor=representative_factor,
        tolerance=tolerance,
        assumptions=list(_BASE_ASSUMPTIONS),
        limitations=list(_BASE_LIMITATIONS),
    )


def _provenance_key(measurement: ContextualMeasurement) -> tuple[str, str, str, int | None]:
    return (
        measurement.candidate_fingerprint,
        measurement.source_identity,
        measurement.source_revision,
        measurement.build_generation,
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
    compared independently (deterministic sorted order): the relationship is
    common only when *every* compared field's per-observation ratios agree
    within ``tolerance``. Semantically different PoB quantities are never
    averaged together; ``representative_factor`` is derived only after every
    per-field condition is satisfied.

    Fail-closed ordering: too few observations, then provenance mismatch,
    then unavailable/missing data, then unproven provenance, then field
    analysis. ``COMMON_RESPONSE`` is explicitly approximate (``exact`` is
    False): empirically similar within tolerance, not an exact common
    factor.
    """
    if tolerance <= 0:
        raise ValueError("tolerance must be positive")
    if len(measurements) < 2:
        return _proof_shell(
            ContextualRelationship.INSUFFICIENT_EVIDENCE,
            "NEED_AT_LEAST_TWO_OBSERVATIONS",
            measurements,
            tolerance,
        )

    provenances = {_provenance_key(measurement) for measurement in measurements}
    if len(provenances) > 1:
        return _proof_shell(
            ContextualRelationship.NOT_COMPARABLE,
            "PROVENANCE_MISMATCH",
            measurements,
            tolerance,
        )

    for measurement in measurements:
        if measurement.status != "MEASURED":
            return _proof_shell(
                ContextualRelationship.NOT_COMPARABLE,
                f"OBSERVATION_NOT_MEASURED:{measurement.status}"
                + (f":{measurement.reason}" if measurement.reason else ""),
                measurements,
                tolerance,
            )
        if not measurement.baseline_output or not measurement.candidate_output:
            return _proof_shell(
                ContextualRelationship.NOT_COMPARABLE,
                "OBSERVATION_MISSING_OUTPUT",
                measurements,
                tolerance,
            )

    if all(key == ("", "", "", None) for key in provenances):
        return _proof_shell(
            ContextualRelationship.INSUFFICIENT_EVIDENCE,
            "CANDIDATE_PROVENANCE_UNPROVEN",
            measurements,
            tolerance,
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
        return _proof_shell(
            ContextualRelationship.INSUFFICIENT_EVIDENCE,
            reason,
            measurements,
            tolerance,
            compared_fields=candidate_fields if field_name is None else [str(field_name)],
        )

    # Per-field ratios: one ratio per (observation, field). A field supports
    # a common response only when its own ratios agree across observations.
    field_means: dict[str, float] = {}
    material_change = False
    for compared in usable_fields:
        ratios: list[float] = []
        for measurement in measurements:
            before = float((measurement.baseline_output or {})[compared])
            after = float((measurement.candidate_output or {})[compared])
            ratios.append(after / before)
            if abs(after - before) > RESPONSE_MIN_CHANGE:
                material_change = True
        mean = sum(ratios) / len(ratios)
        spread = (max(ratios) - min(ratios)) / max(abs(mean), 1e-9)
        if spread > tolerance:
            return _proof_shell(
                ContextualRelationship.DIVERGENT_RESPONSE,
                f"FIELD_DIVERGES:{compared}",
                measurements,
                tolerance,
                compared_fields=usable_fields,
            )
        field_means[compared] = mean

    if not material_change:
        return _proof_shell(
            ContextualRelationship.INSUFFICIENT_EVIDENCE,
            "NO_MEASURABLE_CHANGE",
            measurements,
            tolerance,
            compared_fields=usable_fields,
            factors=field_means,
            representative_factor=sum(field_means.values()) / len(field_means),
        )
    representative = sum(field_means.values()) / len(field_means)
    return ContextualProof(
        classification=ContextualRelationship.COMMON_RESPONSE,
        reason="SHARED_PROPORTIONAL_RESPONSE",
        measurements=list(measurements),
        compared_fields=usable_fields,
        factors=field_means,
        representative_factor=representative,
        tolerance=tolerance,
        assumptions=list(_BASE_ASSUMPTIONS),
        limitations=list(_BASE_LIMITATIONS),
        warnings=[
            "Common response is approximately shared within tolerance: it is not an exact common factor and does not establish causality.",
            "Do not add component values across weapon sets on the basis of this proof.",
        ],
    )


def prove_candidate_relationship(
    results: list[Mapping[str, Any]],
    *,
    references: list[Mapping[str, Any]],
    contexts: list[Mapping[str, Any]],
    physical_targets: list[Mapping[str, Any] | None] | None = None,
    provenance: Mapping[str, Any] | None = None,
    field_name: str | None = None,
    tolerance: float = COMMON_RESPONSE_RELATIVE_TOLERANCE,
) -> dict[str, Any]:
    """One-call helper: lift Slice 3 results, classify, return proof dict.

    ``provenance`` binds every result to one candidate evaluation
    (``candidate_fingerprint`` / ``source_identity`` / ``source_revision`` /
    ``build_generation``); omitting it yields ``INSUFFICIENT_EVIDENCE``
    rather than an unbound claim.
    """
    measurements = collect_measurements(
        results,
        references=references,
        contexts=contexts,
        physical_targets=physical_targets,
        provenance=provenance,
    )
    return classify_relationship(measurements, field_name=field_name, tolerance=tolerance).to_dict()
