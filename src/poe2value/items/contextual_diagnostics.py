"""Slice 4D internal: read-only diagnostic consumer over Slices 3-4C.

Exercises the complete contextual evaluation pipeline on real PoB state
(candidate -> measurements -> evidence -> proof -> required scope ->
eligibility) and reports what the engine can actually prove and why it
cannot prove more. Explicit invocation only: no normal product consumer
exists, and ordinary Item Check behavior is unchanged.

The diagnostic never switches the build's active weapon set persistently,
never mutates product state, and performs no metric arithmetic. Catalog
enumeration uses the existing zero-frame cache-backed list API for the
currently active set only: other sets' catalogs cannot be enumerated
without a context switch (``list_calculable_effects`` has no weapon-set
parameter), so a scope spanning an unenumerated set fails closed with an
explicit reason instead of guessing completeness.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from poe2value.errors import RestoreFailed
from poe2value.items.contextual_composition import (
    CompositionScope,
    assess_composition_eligibility,
    derive_required_scope,
)
from poe2value.items.contextual_evidence import (
    EvidenceObservation,
    collect_candidate_evidence,
)
from poe2value.items.contextual_proof import COMMON_RESPONSE_RELATIVE_TOLERANCE

__all__ = [
    "SET_CATALOG_UNAVAILABLE",
    "run_contextual_diagnostic",
]

#: Reported when a requested weapon set's effect catalog cannot be
#: enumerated (only the active set is listable with the current API).
SET_CATALOG_UNAVAILABLE = "SET_CATALOG_UNAVAILABLE"


def _skill_group_count(engine: Any) -> int:
    try:
        info = engine.get_build_info()
    except Exception:
        return 0
    if not isinstance(info, Mapping):
        return 0
    build = info.get("build")
    if not isinstance(build, Mapping):
        return 0
    try:
        return int(build.get("skill_group_count") or 0)
    except (TypeError, ValueError):
        return 0


def _enumerate_current_catalog(engine: Any) -> dict[str, Any]:
    """Enumerate the active set's full effect catalog, per socket group.

    Per-group calls avoid the per-call effect cap hiding rows; truncation
    flags are preserved verbatim. Cache-backed reads only (no candidate,
    no context switch).
    """
    count = _skill_group_count(engine)
    if count <= 0:
        payload = engine.list_calculable_effects()
        return payload if isinstance(payload, Mapping) else {}
    effects: list[dict[str, Any]] = []
    truncated = False
    total = 0
    for index in range(1, count + 1):
        payload = engine.list_calculable_effects(indices=[index])
        if not isinstance(payload, Mapping):
            continue
        rows = payload.get("effects")
        if isinstance(rows, list):
            effects.extend(dict(row) for row in rows if isinstance(row, Mapping))
        truncated = truncated or bool(payload.get("truncated"))
        try:
            total += int(payload.get("total_effects") or 0)
        except (TypeError, ValueError):
            pass
    return {"effects": effects, "total_effects": total, "truncated": truncated}


def run_contextual_diagnostic(
    engine: Any,
    *,
    candidate_text: str,
    observations: list[EvidenceObservation],
    field_name: str | None = None,
    tolerance: float = COMMON_RESPONSE_RELATIVE_TOLERANCE,
    catalog_by_weapon_set: Mapping[Any, Any] | None = None,
) -> dict[str, Any]:
    """Run the full contextual chain and return a structured report.

    ``observations`` are explicit caller-supplied contextual references;
    ``catalog_by_weapon_set`` optionally supplies caller-enumerated catalog
    payloads for non-active sets (the diagnostic itself can only enumerate
    the active set). Restore failures propagate; a post-run baseline
    mismatch raises ``RestoreFailed``.
    """
    if not observations:
        raise ValueError("contextual diagnostic requires at least one observation")

    baseline_metrics = engine.get_metrics()
    baseline_context = engine.get_weapon_set_context()
    baseline_fingerprint = str((baseline_metrics or {}).get("fingerprint_hash") or "")
    baseline_weapons = dict((baseline_context or {}).get("physical_weapons") or {})
    active_set = int((baseline_context or {}).get("weapon_set") or 0)
    requested_sets = sorted({int(observation.weapon_set) for observation in observations})

    catalogs: dict[int, Any] = {}
    if isinstance(catalog_by_weapon_set, Mapping):
        for weapon_set, payload in catalog_by_weapon_set.items():
            catalogs[int(weapon_set)] = payload
    catalog_status: dict[str, Any] = {}
    for weapon_set in requested_sets:
        if weapon_set in catalogs:
            payload = catalogs[weapon_set]
            catalog_status[str(weapon_set)] = {
                "enumerated": True,
                "caller_supplied": True,
                "truncated": bool(payload.get("truncated")) if isinstance(payload, Mapping) else None,
            }
        elif weapon_set == active_set:
            payload = _enumerate_current_catalog(engine)
            catalogs[weapon_set] = payload
            catalog_status[str(weapon_set)] = {
                "enumerated": True,
                "caller_supplied": False,
                "truncated": bool(payload.get("truncated")),
                "total_effects": int(payload.get("total_effects") or 0),
            }
        else:
            catalog_status[str(weapon_set)] = {
                "enumerated": False,
                "reason": SET_CATALOG_UNAVAILABLE,
            }
    missing_catalog_sets = [ws for ws in requested_sets if ws not in catalogs]

    bundle = collect_candidate_evidence(
        engine,
        candidate_text=candidate_text,
        observations=list(observations),
        field_name=field_name,
        tolerance=tolerance,
    )

    if missing_catalog_sets:
        scope = CompositionScope(
            weapon_sets=tuple(requested_sets),
            required_cache_identities=frozenset(
                row["cache_identity"] for row in bundle["observations"]
            ),
            basis="",
            catalog_truncated=False,
        )
    else:
        skill_set = ""
        rows = bundle["observations"]
        if rows:
            context = (rows[0].get("qualified_reference") or {}).get("context") or {}
            skill_set = context.get("active_skill_set_id", "")
        scope = derive_required_scope(catalogs, active_skill_set_id=skill_set)
    assessment = assess_composition_eligibility(bundle, scope=scope)

    final_metrics = engine.get_metrics()
    final_context = engine.get_weapon_set_context()
    final_fingerprint = str((final_metrics or {}).get("fingerprint_hash") or "")
    final_weapons = dict((final_context or {}).get("physical_weapons") or {})
    restore_pass = (
        bool(final_fingerprint)
        and final_fingerprint == baseline_fingerprint
        and final_weapons == baseline_weapons
        and int((final_context or {}).get("weapon_set") or 0) == active_set
    )
    if not restore_pass:
        raise RestoreFailed(
            "contextual diagnostic post-state differs from baseline",
            {
                "baseline_fingerprint": baseline_fingerprint,
                "final_fingerprint": final_fingerprint,
                "weapon_set_changed": int((final_context or {}).get("weapon_set") or 0) != active_set,
            },
        )

    proof = bundle["proof"]
    assessment_dict = assessment.to_dict()
    required = scope.required_cache_identities
    observed = {str(row.get("cache_identity") or "") for row in bundle["observations"]}
    limitations = list(proof.get("limitations") or []) + list(assessment_dict.get("limitations") or [])
    limitations.append(
        "Catalog enumeration covers only explicitly enumerated weapon sets; "
        "other sets cannot be listed without a context switch under the current API."
    )
    return {
        "candidate": dict(bundle["candidate"]),
        "provenance": dict(bundle["provenance"]),
        "source_identity": str(bundle["provenance"].get("source_identity") or ""),
        "source_revision": str(bundle["provenance"].get("source_revision") or ""),
        "build_generation": bundle["provenance"].get("build_generation"),
        "requested_contexts": list(requested_sets),
        "observations": list(bundle["observations"]),
        "unavailable": list(bundle["unavailable"]),
        "physical_targets": [
            row.get("physical_target") for row in bundle["observations"]
        ],
        "proof": dict(proof),
        "proof_scope": str(proof.get("scope") or ""),
        "proof_exact": bool(proof.get("exact")),
        "completeness": {
            "basis": scope.basis,
            "required_identities_count": len(required),
            "observed_identities_count": len(observed & set(required)),
            "missing_identities": sorted(set(required) - observed),
            "catalog_truncated": {key: value.get("truncated") for key, value in catalog_status.items()},
            "catalog_status": catalog_status,
            "missing_catalog_sets": list(missing_catalog_sets),
        },
        "assessment": assessment_dict,
        "composition_eligibility": str(assessment_dict.get("eligibility") or ""),
        "eligibility_reason": str(assessment_dict.get("reason") or ""),
        "frames_total": dict(bundle["frames_total"]),
        "restore": {
            "pass": True,
            "baseline_fingerprint": baseline_fingerprint,
            "final_fingerprint": final_fingerprint,
        },
        "baseline_state": {"fingerprint": baseline_fingerprint, "weapon_set": active_set},
        "final_state": {"fingerprint": final_fingerprint, "weapon_set": active_set},
        "limitations": limitations,
        "warnings": list(proof.get("warnings") or []) + list(assessment_dict.get("warnings") or []),
        "whole_build": False,
        "public_verdict_affected": False,
    }
