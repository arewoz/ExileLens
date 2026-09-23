"""Slice 4B internal: evidence orchestration from Slice 3 to Slice 4A.

Collects trustworthy real evaluation evidence for one candidate across
caller-supplied contextual component references and feeds the resulting
measurements into the Slice 4A relationship classifier, returning a
structured evidence bundle. It stops there: no verdict, no ranking, no
whole-build composition, and no normal product consumer (infrastructure
for Slice 4C).

Provenance is derived from real evaluation context only:

- ``candidate_fingerprint`` from
  ``evaluation_identity.candidate_fingerprint`` of the exact evaluated
  text -- never object identity or timestamps;
- ``source_revision`` from the engine's loaded revision token;
- ``build_generation`` from the engine's source generation.

If provenance cannot be established, or the loaded build moves
mid-collection, orchestration fails closed instead of producing evidence.
Slice 3 transactional guarantees are retained untouched: restore failures
propagate immediately and stop collection rather than risk corrupted
observations.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from poe2value.items.contextual_evaluation import evaluate_physical_candidate
from poe2value.items.contextual_proof import (
    COMMON_RESPONSE_RELATIVE_TOLERANCE,
    classify_relationship,
    collect_measurements,
)
from poe2value.items.evaluation_identity import candidate_fingerprint
from poe2value.items.slots import ProductSlot

__all__ = [
    "EvidenceObservation",
    "ProvenanceUnestablished",
    "collect_candidate_evidence",
]


class ProvenanceUnestablished(ValueError):
    """Required candidate/build provenance cannot be established. Fail closed."""


@dataclass(frozen=True)
class EvidenceObservation:
    """One caller-requested contextual observation of a candidate.

    Explicit input only: the orchestration layer never guesses which
    effects belong together. Automatic semantic grouping of components
    into gameplay interactions is unsupported -- limitations the bundle
    reports instead of inventing relations.
    """

    reference: Mapping[str, Any]
    weapon_set: int
    logical_product_slot: ProductSlot | str

    def to_dict(self) -> dict[str, Any]:
        slot = self.logical_product_slot
        return {
            "reference": dict(self.reference),
            "weapon_set": int(self.weapon_set),
            "logical_product_slot": slot.value if isinstance(slot, ProductSlot) else str(slot),
        }


def _engine_provenance(engine: Any) -> dict[str, Any]:
    """Derive proof provenance from the real loaded evaluation context."""
    revision = engine.loaded_revision
    source_ref = engine.loaded_source_ref
    token = getattr(revision, "token", "") if revision is not None else ""
    source_key = getattr(source_ref, "key", "") if source_ref is not None else ""
    try:
        generation = int(engine.source_generation)
    except (TypeError, ValueError):
        generation = None
    if not token or not source_key or generation is None:
        raise ProvenanceUnestablished(
            "candidate evidence requires a loaded build with an established "
            "revision token, source identity, and build generation"
        )
    return {
        "candidate_fingerprint": "",
        "source_identity": str(source_key),
        "source_revision": str(token),
        "build_generation": generation,
    }


def collect_candidate_evidence(
    engine: Any,
    *,
    candidate_text: str,
    observations: list[EvidenceObservation],
    field_name: str | None = None,
    tolerance: float = COMMON_RESPONSE_RELATIVE_TOLERANCE,
) -> dict[str, Any]:
    """Evaluate one candidate across contextual references; return evidence.

    Runs one Slice 3 physical-candidate measurement per observation (each
    with full context/candidate restore verification), binds every
    measurement to uniform real provenance, classifies via Slice 4A, and
    bundles everything inspectably. Restore failures propagate and stop
    collection; generation/revision drift mid-collection fails closed.
    """
    if not isinstance(candidate_text, str) or not candidate_text.strip():
        raise ProvenanceUnestablished("candidate evidence requires non-empty candidate text")
    if not observations:
        raise ValueError("candidate evidence requires at least one observation")
    fingerprint = candidate_fingerprint(candidate_text)

    provenance = _engine_provenance(engine)
    provenance["candidate_fingerprint"] = fingerprint
    generation_before = provenance["build_generation"]
    revision_before = provenance["source_revision"]

    results: list[dict[str, Any]] = []
    references: list[Mapping[str, Any]] = []
    contexts: list[Mapping[str, Any]] = []
    targets: list[Mapping[str, Any] | None] = []
    for observation in observations:
        if not isinstance(observation, EvidenceObservation):
            raise ValueError("observations must be EvidenceObservation inputs")
        # resolve_physical_target validates slot and set (fail closed on
        # non-weapon slots, bad sets, or legacy OFFHAND_2).
        result = evaluate_physical_candidate(
            engine,
            dict(observation.reference),
            observation.logical_product_slot,
            int(observation.weapon_set),
            candidate_text,
        )
        if not isinstance(result, Mapping):
            raise ValueError("contextual evaluation returned a malformed result")
        bridge_context = result.get("context")
        skill_set = bridge_context.get("active_skill_set_id") if isinstance(bridge_context, Mapping) else ""
        results.append(dict(result))
        references.append(dict(observation.reference))
        contexts.append({"weapon_set": int(observation.weapon_set), "active_skill_set_id": skill_set})
        physical = result.get("physical_target")
        targets.append(dict(physical) if isinstance(physical, Mapping) else None)

    if int(engine.source_generation) != generation_before:
        raise ProvenanceUnestablished("loaded build changed during evidence collection")
    revision_after = engine.loaded_revision
    if revision_after is None or getattr(revision_after, "token", "") != revision_before:
        raise ProvenanceUnestablished("loaded build revision changed during evidence collection")

    measurements = collect_measurements(
        results,
        references=references,
        contexts=contexts,
        physical_targets=targets,
        provenance={
            "candidate_fingerprint": fingerprint,
            "source_revision": revision_before,
            "build_generation": generation_before,
        },
    )
    proof = classify_relationship(measurements, field_name=field_name, tolerance=tolerance)

    observation_rows: list[dict[str, Any]] = []
    unavailable_rows: list[dict[str, Any]] = []
    frames_total = {"context_settle": 0, "candidate_settle": 0, "restore_settle": 0}
    for measurement, result in zip(measurements, results):
        row = measurement.to_dict()
        row["delta"] = result.get("delta")
        observation_rows.append(row)
        if measurement.status != "MEASURED":
            unavailable_rows.append(
                {
                    "cache_identity": measurement.cache_identity,
                    "status": measurement.status,
                    "reason": measurement.reason,
                }
            )
        frames = result.get("frames")
        if isinstance(frames, Mapping):
            for key in frames_total:
                value = frames.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    frames_total[key] += int(value)

    proof_dict = proof.to_dict()
    return {
        "candidate": {"fingerprint": fingerprint},
        "provenance": {
            "candidate_fingerprint": fingerprint,
            "source_identity": provenance["source_identity"],
            "source_revision": revision_before,
            "build_generation": generation_before,
        },
        "observations": observation_rows,
        "unavailable": unavailable_rows,
        "proof": proof_dict,
        "scope": proof_dict["scope"],
        "exact": proof_dict["exact"],
        "frames_total": frames_total,
        "automatic_grouping": "UNSUPPORTED",
        "grouping_note": (
            "Observations were caller-supplied; no automatic semantic grouping "
            "of components into gameplay interactions was performed."
        ),
    }
