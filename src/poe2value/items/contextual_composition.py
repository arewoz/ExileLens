"""Slice 4C internal: guarded composition-eligibility assessment.

Answers only whether a Slice 4B evidence bundle is sufficiently
comparable, complete, and internally consistent to be considered eligible
for a later guarded whole-build interpretation:

    ELIGIBLE / NOT_ELIGIBLE / INSUFFICIENT_EVIDENCE

Eligibility is NOT a product verdict, NOT whole-build DPS, and performs NO
arithmetic on contextual metrics (no sums, no averages, no projections, no
representative-factor multiplication). It is the final isolated safety
layer before later product integration, with no normal product consumer.

Completeness is backed by real enumeration evidence, never a manual flag:
the required observation set must be derived from actual per-context
effect-catalog payloads (``derive_required_scope``) with no truncation.
Anything else -- missing basis, truncated catalogs, caller-supplied
subsets -- yields ``INSUFFICIENT_EVIDENCE`` with an explicit reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from poe2value.items.effect_components import (
    CalculationContext,
    ComponentReference,
    ContextualComponentReference,
)

__all__ = [
    "CATALOG_ENUMERATED",
    "CompositionEligibility",
    "CompositionScope",
    "CompositionAssessment",
    "derive_required_scope",
    "assess_composition_eligibility",
]

#: The only coverage basis accepted for eligibility: the required set was
#: derived from real per-context effect-catalog enumeration payloads.
CATALOG_ENUMERATED = "CATALOG_ENUMERATED"


class CompositionEligibility(str, Enum):
    """Closed eligibility outcomes. Eligibility only -- never a verdict."""

    #: Comparable, complete, and internally consistent for the assessed
    #: scope. Eligible for later guarded interpretation, nothing more.
    ELIGIBLE = "ELIGIBLE"
    #: Definitively not eligible (failed comparability, validity, divergent
    #: relationship, or unavailable/restore-unsafe required observation).
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    #: Cannot decide (unproven coverage, incomplete subset, or insufficient
    #: relationship evidence). More or better evidence could change this.
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class CompositionScope:
    """The assessed scope and what makes its required set complete.

    ``required_cache_identities`` is the full contextual-observation set for
    the scope; ``basis`` names how that set was established (only
    ``CATALOG_ENUMERATED`` can support eligibility); ``catalog_truncated``
    records whether the underlying enumeration was bounded.
    """

    weapon_sets: tuple[int, ...] = (1, 2)
    required_cache_identities: frozenset[str] = frozenset()
    basis: str = ""
    catalog_truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "weapon_sets": list(self.weapon_sets),
            "required_cache_identities": sorted(self.required_cache_identities),
            "basis": self.basis,
            "catalog_truncated": self.catalog_truncated,
        }


def derive_required_scope(
    catalog_by_weapon_set: Mapping[Any, Any],
    *,
    active_skill_set_id: str | int = "",
) -> CompositionScope:
    """Derive the complete required observation set from real catalogs.

    ``catalog_by_weapon_set`` maps weapon set (1/2) to that context's actual
    effect-catalog payload (``list_calculable_effects`` /
    ``normalize_effect_catalog`` shape). Each reference is qualified with
    its own weapon set plus the shared ``active_skill_set_id`` (Slice 3
    evaluates only the active skill set, but the id participates in
    identity); the union is the required set. Malformed payloads or
    references fail closed with ``ValueError``. Truncation is recorded, not
    hidden -- a truncated catalog can never support eligibility.
    """
    if not isinstance(catalog_by_weapon_set, Mapping) or not catalog_by_weapon_set:
        raise ValueError("required scope needs at least one per-context catalog payload")
    skill_set = str(active_skill_set_id or "")
    required: set[str] = set()
    weapon_sets: list[int] = []
    truncated = False
    for weapon_set, payload in catalog_by_weapon_set.items():
        context = CalculationContext.from_dict({"weapon_set": weapon_set, "active_skill_set_id": skill_set})
        weapon_sets.append(context.weapon_set)
        if not isinstance(payload, Mapping):
            raise ValueError(f"catalog payload for weapon set {context.weapon_set} must be a mapping")
        effects = payload.get("effects")
        if not isinstance(effects, list):
            raise ValueError(f"catalog payload for weapon set {context.weapon_set} has no effect list")
        truncated = truncated or bool(payload.get("truncated"))
        for entry in effects:
            if not isinstance(entry, Mapping) or not isinstance(entry.get("reference"), Mapping):
                raise ValueError("catalog entry is missing a component reference")
            qualified = ContextualComponentReference(
                component=ComponentReference.from_dict(entry["reference"]),
                context=context,
            )
            required.add(qualified.cache_identity)
    return CompositionScope(
        weapon_sets=tuple(sorted(weapon_sets)),
        required_cache_identities=frozenset(required),
        basis=CATALOG_ENUMERATED,
        catalog_truncated=truncated,
    )


@dataclass
class CompositionAssessment:
    """Machine-readable eligibility result. Scope-bounded, never whole-build."""

    eligibility: CompositionEligibility
    reason: str
    scope: CompositionScope = field(default_factory=CompositionScope)
    proof_classification: str = ""
    proof_reason: str = ""
    proof_scope: str = ""
    proof_exact: bool = False
    representative_factor: float | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    checked_observations: int = 0
    required_observations: int = 0
    whole_build: bool = False
    coverage: str = ""
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligibility": self.eligibility.value,
            "reason": self.reason,
            "scope": self.scope.to_dict(),
            "proof_classification": self.proof_classification,
            "proof_reason": self.proof_reason,
            "proof_scope": self.proof_scope,
            "proof_exact": self.proof_exact,
            "representative_factor": self.representative_factor,
            "provenance": dict(self.provenance),
            "checked_observations": self.checked_observations,
            "required_observations": self.required_observations,
            "whole_build": self.whole_build,
            "coverage": self.coverage,
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "warnings": list(self.warnings),
        }


_BASE_ASSUMPTIONS = (
    "Assessment consumes Slice 4B evidence and the Slice 4A relationship proof unchanged; it performs no PoB calculation and no metric arithmetic.",
    "Eligibility applies to the coverage-verified supplied observation scope only, never automatically to the entire build.",
)

_BASE_LIMITATIONS = (
    "COMMON_RESPONSE means observed-response consistency only; it does not establish causality, same skill, same damage source, trigger relations, additive damage, snapshot proof, or practical DPS.",
    "Contextual metric values are never summed, averaged, or projected by this assessment; the representative factor is retained proof metadata only.",
    "Automatic semantic grouping of components into gameplay interactions remains unsupported.",
)


def _shell(
    eligibility: CompositionEligibility,
    reason: str,
    *,
    scope: CompositionScope,
    proof: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    checked: int = 0,
    coverage: str = "",
) -> CompositionAssessment:
    proof = dict(proof) if isinstance(proof, Mapping) else {}
    return CompositionAssessment(
        eligibility=eligibility,
        reason=reason,
        scope=scope,
        proof_classification=str(proof.get("classification") or ""),
        proof_reason=str(proof.get("reason") or ""),
        proof_scope=str(proof.get("scope") or ""),
        proof_exact=bool(proof.get("exact")),
        representative_factor=proof.get("representative_factor"),
        provenance=dict(provenance) if isinstance(provenance, Mapping) else {},
        checked_observations=checked,
        required_observations=len(scope.required_cache_identities),
        whole_build=False,
        coverage=coverage,
        assumptions=list(_BASE_ASSUMPTIONS),
        limitations=list(_BASE_LIMITATIONS),
        warnings=[
            "Eligibility is not a product verdict and must never be consumed as upgrade/sidegrade/downgrade evidence.",
        ] if eligibility == CompositionEligibility.ELIGIBLE else [],
    )


def assess_composition_eligibility(
    bundle: Mapping[str, Any],
    *,
    scope: CompositionScope,
) -> CompositionAssessment:
    """Assess whether an evidence bundle is eligible for later composition.

    Deterministic fail-closed ordering: bundle shape, provenance unanimity
    (candidate fingerprint, source identity, revision, generation, matched
    against bundle provenance), relationship proof, coverage basis, required
    subset presence, per-observation validity. Only set membership, equality,
    and status checks -- no metric values are read, combined, or projected.
    """
    if not isinstance(bundle, Mapping):
        raise ValueError("composition assessment requires an evidence bundle mapping")
    if not isinstance(scope, CompositionScope):
        raise ValueError("composition assessment requires a CompositionScope")
    observations = bundle.get("observations")
    proof = bundle.get("proof")
    bundle_provenance = bundle.get("provenance")
    if not isinstance(observations, list) or not isinstance(proof, Mapping):
        raise ValueError("evidence bundle is missing observations or proof")
    if not isinstance(bundle_provenance, Mapping):
        raise ValueError("evidence bundle is missing provenance")

    rows = [row for row in observations if isinstance(row, Mapping)]
    provenances = {
        (
            str(row.get("candidate_fingerprint") or ""),
            str(row.get("source_identity") or ""),
            str(row.get("source_revision") or ""),
            row.get("build_generation"),
        )
        for row in rows
    }
    expected = (
        str(bundle_provenance.get("candidate_fingerprint") or ""),
        str(bundle_provenance.get("source_identity") or ""),
        str(bundle_provenance.get("source_revision") or ""),
        bundle_provenance.get("build_generation"),
    )
    if len(provenances) != 1 or next(iter(provenances)) != expected:
        return _shell(
            CompositionEligibility.NOT_ELIGIBLE, "PROVENANCE_MISMATCH",
            scope=scope, proof=proof, provenance=bundle_provenance, checked=len(rows),
        )
    if all(key == ("", "", "", None) for key in provenances):
        return _shell(
            CompositionEligibility.INSUFFICIENT_EVIDENCE, "CANDIDATE_PROVENANCE_UNPROVEN",
            scope=scope, proof=proof, provenance=bundle_provenance, checked=len(rows),
        )

    proof_classification = str(proof.get("classification") or "")
    if proof_classification == "DIVERGENT_RESPONSE":
        return _shell(
            CompositionEligibility.NOT_ELIGIBLE, "PROOF_DIVERGENT",
            scope=scope, proof=proof, provenance=bundle_provenance, checked=len(rows),
        )
    if proof_classification == "NOT_COMPARABLE":
        return _shell(
            CompositionEligibility.NOT_ELIGIBLE, f"PROOF_{proof.get('reason') or 'NOT_COMPARABLE'}",
            scope=scope, proof=proof, provenance=bundle_provenance, checked=len(rows),
        )
    if proof_classification != "COMMON_RESPONSE":
        return _shell(
            CompositionEligibility.INSUFFICIENT_EVIDENCE,
            f"PROOF_{proof.get('reason') or 'INSUFFICIENT'}",
            scope=scope, proof=proof, provenance=bundle_provenance, checked=len(rows),
        )

    if scope.basis != CATALOG_ENUMERATED or scope.catalog_truncated:
        return _shell(
            CompositionEligibility.INSUFFICIENT_EVIDENCE, "COVERAGE_UNPROVEN",
            scope=scope, proof=proof, provenance=bundle_provenance, checked=len(rows),
        )
    if not scope.required_cache_identities:
        return _shell(
            CompositionEligibility.INSUFFICIENT_EVIDENCE, "NO_REQUIRED_OBSERVATIONS",
            scope=scope, proof=proof, provenance=bundle_provenance, checked=len(rows),
        )

    by_identity = {str(row.get("cache_identity") or ""): row for row in rows}
    missing = [identity for identity in sorted(scope.required_cache_identities) if identity not in by_identity]
    if missing:
        return _shell(
            CompositionEligibility.INSUFFICIENT_EVIDENCE, "SUBSET_INCOMPLETE",
            scope=scope, proof=proof, provenance=bundle_provenance, checked=len(rows),
        )
    for identity in sorted(scope.required_cache_identities):
        row = by_identity[identity]
        if row.get("status") != "MEASURED":
            return _shell(
                CompositionEligibility.NOT_ELIGIBLE, "REQUIRED_UNAVAILABLE",
                scope=scope, proof=proof, provenance=bundle_provenance, checked=len(rows),
            )
        if row.get("restore_pass") is not True:
            return _shell(
                CompositionEligibility.NOT_ELIGIBLE, "RESTORE_UNVERIFIED",
                scope=scope, proof=proof, provenance=bundle_provenance, checked=len(rows),
            )
        if not row.get("baseline_output") or not row.get("candidate_output"):
            return _shell(
                CompositionEligibility.NOT_ELIGIBLE, "OBSERVATION_MISSING_OUTPUT",
                scope=scope, proof=proof, provenance=bundle_provenance, checked=len(rows),
            )

    return _shell(
        CompositionEligibility.ELIGIBLE, "SCOPE_COMPLETE_AND_CONSISTENT",
        scope=scope, proof=proof, provenance=bundle_provenance,
        checked=len(scope.required_cache_identities), coverage="CATALOG_BOUNDED",
    )
