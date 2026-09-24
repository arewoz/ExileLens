"""Slice 4C focused gate: composition eligibility (fake engine, deterministic)."""

from __future__ import annotations

import copy
import pathlib

import pytest

from exilelens.items.contextual_composition import (
    CATALOG_ENUMERATED,
    CompositionEligibility,
    CompositionScope,
    assess_composition_eligibility,
    derive_required_scope,
)
from exilelens.items.contextual_evidence import EvidenceObservation, collect_candidate_evidence
from exilelens.items.contextual_proof import (
    ContextualMeasurement,
    ContextualRelationship,
    classify_relationship,
)

pytestmark = pytest.mark.itemcheck


def _reference(effect_id: str) -> dict:
    return {
        "semantic_id": f"group|{effect_id}|gem|set|part||DIRECT||",
        "group_id": "group",
        "effect_id": effect_id,
        "source_gem_id": "Metadata/Items/Gems/SkillGemExample",
        "source_gem_index": 1,
        "owner": "PLAYER",
        "stat_set_key": "set",
        "part_key": "part",
        "stage_count": None,
        "calculation_mode": "DIRECT",
        "output_table": "mainOutput",
        "group_selector": 3,
        "effect_selector": 1,
    }


def _catalog(effect_ids: list[str], *, truncated: bool = False) -> dict:
    return {
        "effects": [{"reference": _reference(effect_id), "status": "MEASURED"} for effect_id in effect_ids],
        "total_effects": len(effect_ids),
        "max_effects": 8,
        "truncated": truncated,
    }


class _Revision:
    def __init__(self, token: str) -> None:
        self.token = token


class _SourceRef:
    def __init__(self, key: str) -> None:
        self.key = key


class FakeEngine:
    def __init__(
        self,
        outputs: dict[tuple[str, int], tuple[dict, dict] | None],
        *,
        revision: str = "rev-token-1",
        source_key: str = "LOCAL_POB:/build.xml",
        generation: int = 7,
    ) -> None:
        self._outputs = outputs
        self.loaded_revision = _Revision(revision)
        self.loaded_source_ref = _SourceRef(source_key)
        self.source_generation = generation

    def evaluate_effect_candidate(self, reference, *, weapon_set, physical_slot, item_raw):
        pair = self._outputs.get((reference["effect_id"], int(weapon_set)))
        if pair is None:
            return {"status": "UNAVAILABLE", "reason": "NOT_VALID_IN_CONTEXT"}
        before, after = pair
        return {
            "status": "MEASURED",
            "requested_weapon_set": int(weapon_set),
            "baseline": {"status": "MEASURED", "output": dict(before), "source": "GLOBAL_CACHE"},
            "candidate": {"status": "MEASURED", "output": dict(after), "source": "GLOBAL_CACHE"},
            "delta": None,
            "context": {"weapon_set": int(weapon_set), "active_skill_set_id": 1},
            "frames": {"context_settle": 1, "candidate_settle": 1, "restore_settle": 1},
            "restore": {"status": "OK", "pass": True},
            "physical_target": {
                "logical_product_slot": "WEAPON_1",
                "physical_pob_slot": physical_slot,
                "weapon_set": int(weapon_set),
            },
        }


TEXT = "Rarity: Rare\nTest Item\n+10 to Strength\n"
DOUBLE = {
    ("EffectAPlayer", 1): ({"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
    ("EffectAPlayer", 2): ({"CombinedDPS": 50.0}, {"CombinedDPS": 100.0}),
}


def _observation(effect_id: str, weapon_set: int) -> EvidenceObservation:
    return EvidenceObservation(
        reference=_reference(effect_id), weapon_set=weapon_set, logical_product_slot="WEAPON_1"
    )


def _eligible_bundle(engine: FakeEngine | None = None) -> dict:
    engine = engine or FakeEngine(DOUBLE)
    return collect_candidate_evidence(
        engine,
        candidate_text=TEXT,
        observations=[_observation("EffectAPlayer", 1), _observation("EffectAPlayer", 2)],
    )


def _scope_for(*catalogs: tuple[int, dict], skill_set: str = "1") -> CompositionScope:
    return derive_required_scope(
        {weapon_set: payload for weapon_set, payload in catalogs},
        active_skill_set_id=skill_set,
    )


def _measured(reference, context, *, fingerprint="candX", source="LOCAL_POB:/build.xml",
              revision="rev-token-1", generation=7) -> dict:
    return {
        "status": "MEASURED",
        "baseline": {"output": {"CombinedDPS": 100.0}},
        "candidate": {"output": {"CombinedDPS": 200.0}},
        "_reference": reference,
        "_context": context,
        "_provenance": {
            "candidate_fingerprint": fingerprint,
            "source_identity": source,
            "source_revision": revision,
            "build_generation": generation,
        },
    }


def _classify_direct(entries: list[dict]) -> object:
    measurements = [
        ContextualMeasurement.from_candidate_result(
            entry,
            reference=entry["_reference"],
            context=entry["_context"],
            candidate_fingerprint=entry["_provenance"]["candidate_fingerprint"],
            source_identity=entry["_provenance"]["source_identity"],
            source_revision=entry["_provenance"]["source_revision"],
            build_generation=entry["_provenance"]["build_generation"],
        )
        for entry in entries
    ]
    return classify_relationship(measurements)


def test_same_full_provenance_is_comparable_and_eligible() -> None:
    bundle = _eligible_bundle()
    scope = _scope_for((1, _catalog(["EffectAPlayer"])), (2, _catalog(["EffectAPlayer"])))
    assert scope.basis == CATALOG_ENUMERATED
    assert scope.catalog_truncated is False
    assessment = assess_composition_eligibility(bundle, scope=scope).to_dict()
    assert assessment["eligibility"] == CompositionEligibility.ELIGIBLE.value
    assert assessment["reason"] == "SCOPE_COMPLETE_AND_CONSISTENT"
    assert assessment["whole_build"] is False
    assert assessment["coverage"] == "CATALOG_BOUNDED"
    assert assessment["checked_observations"] == 2
    assert assessment["proof_classification"] == ContextualRelationship.COMMON_RESPONSE.value
    assert assessment["proof_exact"] is False


def test_source_identity_mismatch_is_non_comparable() -> None:
    entries = [
        _measured(_reference("EffectAPlayer"), {"weapon_set": 1}),
        _measured(_reference("EffectAPlayer"), {"weapon_set": 2}),
    ]
    entries[1]["_provenance"]["source_identity"] = "LOCAL_POB:/other.xml"
    proof = _classify_direct(entries)
    assert proof.classification == ContextualRelationship.NOT_COMPARABLE
    assert proof.reason == "PROVENANCE_MISMATCH"


def test_same_revision_different_source_is_still_non_comparable() -> None:
    entries = [
        _measured(_reference("EffectAPlayer"), {"weapon_set": 1}),
        _measured(_reference("EffectAPlayer"), {"weapon_set": 2}),
    ]
    # Identical revision tokens, identical everything else -- only the
    # canonical source identity differs. Must still fail closed.
    entries[0]["_provenance"]["source_revision"] = "same-rev"
    entries[1]["_provenance"]["source_revision"] = "same-rev"
    entries[1]["_provenance"]["source_identity"] = "LOCAL_POB:/other.xml"
    proof = _classify_direct(entries)
    assert proof.classification == ContextualRelationship.NOT_COMPARABLE
    assert proof.reason == "PROVENANCE_MISMATCH"


def test_candidate_generation_revision_mismatch() -> None:
    base = _measured(_reference("EffectAPlayer"), {"weapon_set": 1})
    other = _measured(_reference("EffectAPlayer"), {"weapon_set": 2})
    for key, value in (
        ("candidate_fingerprint", "candY"),
        ("build_generation", 8),
        ("source_revision", "rev-two"),
    ):
        first = dict(base["_provenance"])
        second = dict(other["_provenance"])
        second[key] = value
        measurements = [
            ContextualMeasurement.from_candidate_result(
                {k: v for k, v in base.items() if not k.startswith("_")},
                reference=base["_reference"],
                context=base["_context"],
                **{k: v for k, v in first.items()},
            ),
            ContextualMeasurement.from_candidate_result(
                {k: v for k, v in other.items() if not k.startswith("_")},
                reference=other["_reference"],
                context=other["_context"],
                **{k: v for k, v in second.items()},
            ),
        ]
        proof = classify_relationship(measurements)
        assert proof.classification == ContextualRelationship.NOT_COMPARABLE
        assert proof.reason == "PROVENANCE_MISMATCH"


def test_common_response_with_unproven_coverage_is_insufficient() -> None:
    bundle = _eligible_bundle()
    narrow = CompositionScope(
        weapon_sets=(1, 2),
        required_cache_identities=frozenset(
            row["cache_identity"] for row in bundle["observations"]
        ),
        basis="CALLER_ASSERTED",
        catalog_truncated=False,
    )
    assert assess_composition_eligibility(bundle, scope=narrow).reason == "COVERAGE_UNPROVEN"

    truncated_scope = _scope_for((1, _catalog(["EffectAPlayer"], truncated=True)), (2, _catalog([])))
    assert truncated_scope.catalog_truncated is True
    assert (
        assess_composition_eligibility(bundle, scope=truncated_scope).reason == "COVERAGE_UNPROVEN"
    )


def test_common_response_over_subset_is_insufficient() -> None:
    bundle = _eligible_bundle()
    scope = _scope_for((1, _catalog(["EffectAPlayer", "EffectBPlayer"])), (2, _catalog(["EffectAPlayer"])))
    assert len(scope.required_cache_identities) == 3
    assessment = assess_composition_eligibility(bundle, scope=scope)
    assert assessment.eligibility == CompositionEligibility.INSUFFICIENT_EVIDENCE
    assert assessment.reason == "SUBSET_INCOMPLETE"


def test_unavailable_required_observation_is_not_eligible() -> None:
    engine = FakeEngine({("EffectAPlayer", 1): ({"CombinedDPS": 100.0}, {"CombinedDPS": 200.0})})
    bundle = collect_candidate_evidence(
        engine,
        candidate_text=TEXT,
        observations=[_observation("EffectAPlayer", 1), _observation("EffectAPlayer", 2)],
    )
    scope = _scope_for((1, _catalog(["EffectAPlayer"])), (2, _catalog(["EffectAPlayer"])))
    assessment = assess_composition_eligibility(bundle, scope=scope)
    assert assessment.eligibility == CompositionEligibility.NOT_ELIGIBLE
    assert "OBSERVATION_NOT_MEASURED" in assessment.reason


def test_near_zero_and_divergent_proofs_propagate() -> None:
    near_zero = FakeEngine(
        {
            ("EffectAPlayer", 1): ({"CombinedDPS": 0.2}, {"CombinedDPS": 40.0}),
            ("EffectAPlayer", 2): ({"CombinedDPS": 0.1}, {"CombinedDPS": 20.0}),
        }
    )
    bundle = collect_candidate_evidence(
        near_zero,
        candidate_text=TEXT,
        observations=[_observation("EffectAPlayer", 1), _observation("EffectAPlayer", 2)],
    )
    scope = _scope_for((1, _catalog(["EffectAPlayer"])), (2, _catalog(["EffectAPlayer"])))
    assessment = assess_composition_eligibility(bundle, scope=scope)
    assert assessment.eligibility == CompositionEligibility.INSUFFICIENT_EVIDENCE
    assert "NEAR_ZERO" in assessment.reason

    divergent = FakeEngine(
        {
            ("EffectAPlayer", 1): ({"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
            ("EffectAPlayer", 2): ({"CombinedDPS": 100.0}, {"CombinedDPS": 110.0}),
        }
    )
    divergent_bundle = collect_candidate_evidence(
        divergent,
        candidate_text=TEXT,
        observations=[_observation("EffectAPlayer", 1), _observation("EffectAPlayer", 2)],
    )
    divergent_assessment = assess_composition_eligibility(divergent_bundle, scope=scope)
    assert divergent_assessment.eligibility == CompositionEligibility.NOT_ELIGIBLE
    assert divergent_assessment.reason == "PROOF_DIVERGENT"


def test_restore_failure_never_becomes_an_assessment() -> None:
    bundle = _eligible_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["observations"][0]["restore_pass"] = False
    scope = _scope_for((1, _catalog(["EffectAPlayer"])), (2, _catalog(["EffectAPlayer"])))
    assessment = assess_composition_eligibility(tampered, scope=scope)
    assert assessment.eligibility == CompositionEligibility.NOT_ELIGIBLE
    assert assessment.reason == "RESTORE_UNVERIFIED"

    tampered_provenance = copy.deepcopy(bundle)
    tampered_provenance["provenance"]["candidate_fingerprint"] = "other"
    mismatch = assess_composition_eligibility(tampered_provenance, scope=scope)
    assert mismatch.eligibility == CompositionEligibility.NOT_ELIGIBLE
    assert mismatch.reason == "PROVENANCE_MISMATCH"


def test_derive_required_scope_validates_enumeration() -> None:
    scope = _scope_for((1, _catalog(["EffectAPlayer"])), (2, _catalog(["EffectAPlayer"])))
    assert scope.weapon_sets == (1, 2)
    assert len(scope.required_cache_identities) == 2
    with pytest.raises(ValueError):
        derive_required_scope({})
    with pytest.raises(ValueError):
        derive_required_scope({1: {"effects": [{"status": "MEASURED"}]}})
    with pytest.raises(ValueError):
        derive_required_scope({3: _catalog(["EffectAPlayer"])})
    empty = CompositionScope(
        weapon_sets=(1, 2), required_cache_identities=frozenset(),
        basis=CATALOG_ENUMERATED, catalog_truncated=False,
    )
    bundle = _eligible_bundle()
    assert assess_composition_eligibility(bundle, scope=empty).reason == "NO_REQUIRED_OBSERVATIONS"


def test_scope_skill_set_mismatch_is_incomplete() -> None:
    bundle = _eligible_bundle()
    scope = derive_required_scope({1: _catalog(["EffectAPlayer"]), 2: _catalog(["EffectAPlayer"])})
    assert assess_composition_eligibility(bundle, scope=scope).reason == "SUBSET_INCOMPLETE"


def _all_keys(payload: object, *, skip_outputs: bool = False) -> set[str]:
    found: set[str] = set()

    def visit(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                found.add(str(key).lower())
                if skip_outputs and str(key).lower() in {"baseline_output", "candidate_output"}:
                    continue
                visit(value)
        elif isinstance(node, list):
            for entry in node:
                visit(entry)

    visit(payload)
    return found


def test_assessment_has_no_verdict_or_aggregation() -> None:
    bundle = _eligible_bundle()
    scope = _scope_for((1, _catalog(["EffectAPlayer"])), (2, _catalog(["EffectAPlayer"])))
    assessment = assess_composition_eligibility(bundle, scope=scope).to_dict()
    keys = _all_keys(assessment, skip_outputs=True)
    assert {"verdict", "recommendation", "score", "ranking", "upgrade", "sidegrade", "downgrade"}.isdisjoint(keys)
    assert {"total", "sum", "average", "aggregate", "whole_build_dps", "rotation"}.isdisjoint(keys)
    # The representative factor is retained proof metadata, never multiplied.
    assert assessment["representative_factor"] == pytest.approx(2.0)
    assert any("never summed" in limitation.lower() or "never be added" in limitation.lower()
               for limitation in assessment["limitations"])
    assert any("grouping" in limitation.lower() for limitation in assessment["limitations"])


def _module_source(name: str) -> str:
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "exilelens"
    return (root / name).read_text(encoding="utf-8")


def test_ordinary_item_check_does_not_consume_composition() -> None:
    for module in ("items/evaluation.py", "items/ranking.py", "items/evaluation_outcome.py"):
        source = _module_source(module)
        assert "contextual_composition" not in source
        assert "contextual_evidence" not in source
        assert "contextual_proof" not in source
        assert "contextual_evaluation" not in source
    evaluation_source = _module_source("items/evaluation.py")
    assert "evaluate_effect_candidate" not in evaluation_source
    assert "get_weapon_set_context" not in evaluation_source
    assert "read_effect_metrics" not in evaluation_source
