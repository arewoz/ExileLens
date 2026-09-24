"""Slice 4A focused gate: contextual proof classifier (no PoB, deterministic)."""

from __future__ import annotations

import pathlib

import pytest

from exilelens.items.contextual_proof import (
    ContextualMeasurement,
    ContextualRelationship,
    classify_relationship,
    collect_measurements,
    prove_candidate_relationship,
)

pytestmark = pytest.mark.itemcheck


def _reference(effect_id: str, *, semantic_suffix: str = "") -> dict:
    return {
        "semantic_id": f"group|{effect_id}|gem|set|part||DIRECT||{semantic_suffix}",
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


def _measured_result(before: dict, after: dict, *, source: str = "GLOBAL_CACHE") -> dict:
    return {
        "status": "MEASURED",
        "baseline": {"status": "MEASURED", "output": dict(before), "source": source},
        "candidate": {"status": "MEASURED", "output": dict(after), "source": source},
        "restore": {"status": "OK", "pass": True},
        "frames": {"context_settle": 1, "candidate_settle": 1, "restore_settle": 1},
    }


def _unavailable_result(reason: str = "NOT_VALID_IN_CONTEXT") -> dict:
    return {"status": "UNAVAILABLE", "reason": reason}


def _prove(pairs: list[tuple[dict, dict, dict, dict]], **kwargs) -> dict:
    """pairs: (reference, context, before-output, after-output)."""
    results = [_measured_result(before, after) for _, _, before, after in pairs]
    kwargs.setdefault(
        "provenance",
        {"candidate_fingerprint": "candX", "source_revision": "rev1", "build_generation": 3},
    )
    return prove_candidate_relationship(
        results,
        references=[reference for reference, _, _, _ in pairs],
        contexts=[context for _, context, _, _ in pairs],
        **kwargs,
    )


def test_common_proportional_response_is_evidence_not_verdict() -> None:
    proof = _prove(
        [
            (_reference("EffectAPlayer"), {"weapon_set": 1},
             {"CombinedDPS": 100.0, "TotalDPS": 80.0}, {"CombinedDPS": 200.0, "TotalDPS": 160.0}),
            (_reference("EffectAPlayer"), {"weapon_set": 2},
             {"CombinedDPS": 50.0, "TotalDPS": 40.0}, {"CombinedDPS": 100.0, "TotalDPS": 80.0}),
        ]
    )
    assert proof["classification"] == ContextualRelationship.COMMON_RESPONSE.value
    assert proof["reason"] == "SHARED_PROPORTIONAL_RESPONSE"
    assert proof["representative_factor"] == pytest.approx(2.0)
    assert set(proof["compared_fields"]) == {"CombinedDPS", "TotalDPS"}
    assert set(proof["factors"]) == {"CombinedDPS", "TotalDPS"}
    assert all(value == pytest.approx(2.0) for value in proof["factors"].values())
    assert proof["scope"] == "OBSERVED_RESPONSE_CONSISTENCY"
    assert proof["exact"] is False
    assert any("causality" in warning.lower() for warning in proof["warnings"])
    assert any("must never be added" in limitation.lower() or "never be added" in limitation.lower()
               for limitation in proof["limitations"])
    assert proof["assumptions"]


def test_divergent_response_is_distinguished() -> None:
    proof = _prove(
        [
            (_reference("EffectAPlayer"), {"weapon_set": 1},
             {"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
            (_reference("EffectAPlayer"), {"weapon_set": 2},
             {"CombinedDPS": 100.0}, {"CombinedDPS": 110.0}),
        ]
    )
    assert proof["classification"] == ContextualRelationship.DIVERGENT_RESPONSE.value
    assert proof["reason"] == "FIELD_DIVERGES:CombinedDPS"
    assert proof["representative_factor"] is None


def test_near_zero_baseline_refuses_ratio() -> None:
    proof = _prove(
        [
            (_reference("EffectAPlayer"), {"weapon_set": 1},
             {"CombinedDPS": 0.2}, {"CombinedDPS": 40.0}),
            (_reference("EffectAPlayer"), {"weapon_set": 2},
             {"CombinedDPS": 0.1}, {"CombinedDPS": 20.0}),
        ]
    )
    assert proof["classification"] == ContextualRelationship.INSUFFICIENT_EVIDENCE.value
    assert proof["reason"] == "NEAR_ZERO_BASELINE_REFUSES_RATIO"
    assert proof["representative_factor"] is None
    assert proof["factors"] == {}


def test_unavailable_component_is_not_comparable_and_never_zero() -> None:
    proof = prove_candidate_relationship(
        [_measured_result({"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}), _unavailable_result()],
        references=[_reference("EffectAPlayer"), _reference("EffectAPlayer")],
        contexts=[{"weapon_set": 1}, {"weapon_set": 2}],
    )
    assert proof["classification"] == ContextualRelationship.NOT_COMPARABLE.value
    assert "NOT_MEASURED" in proof["reason"]
    unavailable = next(
        measurement for measurement in proof["measurements"]
        if measurement["qualified_reference"]["context"]["weapon_set"] == 2
    )
    assert unavailable["status"] == "UNAVAILABLE"
    assert unavailable["candidate_output"] is None
    assert unavailable["baseline_output"] is None


def test_sibling_components_across_two_sets_remain_distinct() -> None:
    pairs = [
        (_reference("EffectAPlayer", semantic_suffix="a"), {"weapon_set": ws},
         {"CombinedDPS": 100.0}, {"CombinedDPS": 200.0})
        for ws in (1, 2)
    ] + [
        (_reference("EffectBPlayer", semantic_suffix="b"), {"weapon_set": ws},
         {"CombinedDPS": 60.0}, {"CombinedDPS": 120.0})
        for ws in (1, 2)
    ]
    proof = _prove(pairs)
    identities = [measurement["cache_identity"] for measurement in proof["measurements"]]
    assert len(set(identities)) == 4
    assert proof["classification"] == ContextualRelationship.COMMON_RESPONSE.value


def test_context_identity_participates_in_proof_inputs() -> None:
    proof = _prove(
        [
            (_reference("EffectAPlayer"), {"weapon_set": 1},
             {"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
            (_reference("EffectAPlayer"), {"weapon_set": 2},
             {"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
        ]
    )
    tokens = [
        measurement["qualified_reference"]["context"]["token"] for measurement in proof["measurements"]
    ]
    assert tokens[0] != tokens[1]
    assert proof["measurements"][0]["cache_identity"] != proof["measurements"][1]["cache_identity"]


def test_no_additive_interpretation_anywhere_in_proof() -> None:
    proof = _prove(
        [
            (_reference("EffectAPlayer"), {"weapon_set": 1},
             {"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
            (_reference("EffectAPlayer"), {"weapon_set": 2},
             {"CombinedDPS": 50.0}, {"CombinedDPS": 100.0}),
        ]
    )
    forbidden = {"total", "sum", "aggregate", "combined_total", "cross_set_sum"}
    assert forbidden.isdisjoint({key.lower() for key in proof})
    assert all(abs(value - 2.0) < 0.001 for value in proof["factors"].values())
    assert any("not add" in warning.lower() for warning in proof["warnings"])


def test_proof_carries_no_verdict_or_ranking() -> None:
    proof = _prove(
        [
            (_reference("EffectAPlayer"), {"weapon_set": 1},
             {"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
            (_reference("EffectAPlayer"), {"weapon_set": 2},
             {"CombinedDPS": 50.0}, {"CombinedDPS": 100.0}),
        ]
    )
    for key in ("verdict", "recommendation", "score", "ranking", "upgrade", "sidegrade", "downgrade"):
        assert key not in {k.lower() for k in proof}


def test_single_observation_and_no_change_are_insufficient() -> None:
    single = prove_candidate_relationship(
        [_measured_result({"CombinedDPS": 100.0}, {"CombinedDPS": 200.0})],
        references=[_reference("EffectAPlayer")],
        contexts=[{"weapon_set": 1}],
    )
    assert single["classification"] == ContextualRelationship.INSUFFICIENT_EVIDENCE.value
    assert single["reason"] == "NEED_AT_LEAST_TWO_OBSERVATIONS"

    unchanged = _prove(
        [
            (_reference("EffectAPlayer"), {"weapon_set": 1},
             {"CombinedDPS": 100.0}, {"CombinedDPS": 100.1}),
            (_reference("EffectAPlayer"), {"weapon_set": 2},
             {"CombinedDPS": 50.0}, {"CombinedDPS": 50.05}),
        ]
    )
    assert unchanged["classification"] == ContextualRelationship.INSUFFICIENT_EVIDENCE.value
    assert unchanged["reason"] == "NO_MEASURABLE_CHANGE"


def test_non_finite_and_mismatched_inputs_fail_closed() -> None:
    nan_proof = _prove(
        [
            (_reference("EffectAPlayer"), {"weapon_set": 1},
             {"CombinedDPS": float("nan")}, {"CombinedDPS": float("nan")}),
            (_reference("EffectAPlayer"), {"weapon_set": 2},
             {"CombinedDPS": float("nan")}, {"CombinedDPS": float("nan")}),
        ]
    )
    assert nan_proof["classification"] == ContextualRelationship.NOT_COMPARABLE.value

    with pytest.raises(ValueError):
        collect_measurements(
            [_measured_result({"CombinedDPS": 1.0}, {"CombinedDPS": 2.0})],
            references=[_reference("EffectAPlayer"), _reference("EffectBPlayer", semantic_suffix="b")],
            contexts=[{"weapon_set": 1}],
        )
    with pytest.raises(ValueError):
        ContextualMeasurement.from_candidate_result(
            {"status": "MEASURED"}, reference={}, context={"weapon_set": 1}
        )
    measurements = collect_measurements(
        [_measured_result({"CombinedDPS": 100.0}, {"CombinedDPS": 200.0})] * 2,
        references=[_reference("EffectAPlayer")] * 2,
        contexts=[{"weapon_set": 1}, {"weapon_set": 2}],
    )
    with pytest.raises(ValueError):
        classify_relationship(measurements, tolerance=0.0)


def test_per_field_disagreement_diverges_with_field_named() -> None:
    proof = _prove(
        [
            (_reference("EffectAPlayer"), {"weapon_set": 1},
             {"CombinedDPS": 100.0, "TotalDPS": 100.0},
             {"CombinedDPS": 200.0, "TotalDPS": 100.0}),
            (_reference("EffectAPlayer"), {"weapon_set": 2},
             {"CombinedDPS": 100.0, "TotalDPS": 100.0},
             {"CombinedDPS": 200.0, "TotalDPS": 200.0}),
        ]
    )
    assert proof["classification"] == ContextualRelationship.DIVERGENT_RESPONSE.value
    assert proof["reason"] == "FIELD_DIVERGES:TotalDPS"


def test_averaging_trap_diverges_under_per_field_policy() -> None:
    """Values chosen so a per-observation-mean policy would pass at the
    default 5% tolerance (both internal spreads and the mean spread are
    within tolerance) while one field's own ratios diverge ~9.9%.

    obs1 ratios: CombinedDPS 2.1525, TotalDPS 2.0475 (mean 2.10);
    obs2 ratios: CombinedDPS 1.95, TotalDPS 2.05 (mean 2.00).
    """
    proof = _prove(
        [
            (_reference("EffectAPlayer"), {"weapon_set": 1},
             {"CombinedDPS": 100.0, "TotalDPS": 100.0},
             {"CombinedDPS": 215.25, "TotalDPS": 204.75}),
            (_reference("EffectAPlayer"), {"weapon_set": 2},
             {"CombinedDPS": 100.0, "TotalDPS": 100.0},
             {"CombinedDPS": 195.0, "TotalDPS": 205.0}),
        ]
    )
    assert proof["classification"] == ContextualRelationship.DIVERGENT_RESPONSE.value
    assert proof["reason"] == "FIELD_DIVERGES:CombinedDPS"
    # No per-observation mean of unlike quantities exists anywhere.
    assert set(proof["factors"]) == set()


def test_tolerance_boundary_is_deterministic() -> None:
    just_inside = _prove(
        [
            (_reference("EffectAPlayer"), {"weapon_set": 1},
             {"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
            (_reference("EffectAPlayer"), {"weapon_set": 2},
             {"CombinedDPS": 100.0}, {"CombinedDPS": 209.0}),
        ]
    )
    assert just_inside["classification"] == ContextualRelationship.COMMON_RESPONSE.value
    just_outside = _prove(
        [
            (_reference("EffectAPlayer"), {"weapon_set": 1},
             {"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
            (_reference("EffectAPlayer"), {"weapon_set": 2},
             {"CombinedDPS": 100.0}, {"CombinedDPS": 211.0}),
        ]
    )
    assert just_outside["classification"] == ContextualRelationship.DIVERGENT_RESPONSE.value


def test_exact_zero_after_nonzero_baseline_is_a_valid_zero_ratio() -> None:
    proof = _prove(
        [
            (_reference("EffectAPlayer"), {"weapon_set": 1},
             {"CombinedDPS": 100.0}, {"CombinedDPS": 0.0}),
            (_reference("EffectAPlayer"), {"weapon_set": 2},
             {"CombinedDPS": 50.0}, {"CombinedDPS": 0.0}),
        ]
    )
    assert proof["classification"] == ContextualRelationship.COMMON_RESPONSE.value
    assert proof["representative_factor"] == pytest.approx(0.0)


def test_provenance_mismatch_fails_closed() -> None:
    pairs = [
        (_reference("EffectAPlayer"), {"weapon_set": 1},
         {"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
        (_reference("EffectAPlayer"), {"weapon_set": 2},
         {"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
    ]
    results = [_measured_result(before, after) for _, _, before, after in pairs]
    references = [reference for reference, _, _, _ in pairs]
    contexts = [context for _, context, _, _ in pairs]

    other_candidate = prove_candidate_relationship(
        results,
        references=references,
        contexts=contexts,
        provenance={"candidate_fingerprint": "candX", "source_revision": "rev1", "build_generation": 3},
    )
    assert other_candidate["classification"] == ContextualRelationship.COMMON_RESPONSE.value

    measurements = collect_measurements(results, references=references, contexts=contexts)
    tampered = [
        ContextualMeasurement.from_candidate_result(
            results[0],
            reference=references[0],
            context=contexts[0],
            candidate_fingerprint="candX",
            source_revision="rev1",
            build_generation=3,
        ),
        ContextualMeasurement.from_candidate_result(
            results[1],
            reference=references[1],
            context=contexts[1],
            candidate_fingerprint="candY",
            source_revision="rev1",
            build_generation=3,
        ),
    ]
    assert measurements[0].candidate_fingerprint == ""
    mixed = classify_relationship(tampered)
    assert mixed.classification == ContextualRelationship.NOT_COMPARABLE
    assert mixed.reason == "PROVENANCE_MISMATCH"

    tampered_generation = [
        ContextualMeasurement.from_candidate_result(
            results[0],
            reference=references[0],
            context=contexts[0],
            candidate_fingerprint="candX",
            build_generation=3,
        ),
        ContextualMeasurement.from_candidate_result(
            results[1],
            reference=references[1],
            context=contexts[1],
            candidate_fingerprint="candX",
            build_generation=4,
        ),
    ]
    stale = classify_relationship(tampered_generation)
    assert stale.classification == ContextualRelationship.NOT_COMPARABLE
    assert stale.reason == "PROVENANCE_MISMATCH"


def test_unproven_provenance_is_insufficient_not_common() -> None:
    pairs = [
        (_reference("EffectAPlayer"), {"weapon_set": 1},
         {"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
        (_reference("EffectAPlayer"), {"weapon_set": 2},
         {"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
    ]
    results = [_measured_result(before, after) for _, _, before, after in pairs]
    proof = prove_candidate_relationship(
        results,
        references=[reference for reference, _, _, _ in pairs],
        contexts=[context for _, context, _, _ in pairs],
    )
    assert proof["classification"] == ContextualRelationship.INSUFFICIENT_EVIDENCE.value
    assert proof["reason"] == "CANDIDATE_PROVENANCE_UNPROVEN"
    assert proof["representative_factor"] is None


def _module_source(name: str) -> str:
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "exilelens"
    return (root / name).read_text(encoding="utf-8")


def test_proof_layer_does_not_reach_public_verdict_code() -> None:
    for module in ("items/evaluation.py", "items/ranking.py", "items/evaluation_outcome.py"):
        source = _module_source(module)
        assert "contextual_proof" not in source
        assert "contextual_evaluation" not in source


def test_ordinary_item_check_path_has_no_contextual_rpcs() -> None:
    source = _module_source("items/evaluation.py")
    assert "evaluate_effect_candidate" not in source
    assert "get_weapon_set_context" not in source
    assert "read_effect_metrics" not in source
