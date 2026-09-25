"""Slice 4B focused gate: evidence orchestration (fake engine, deterministic)."""

from __future__ import annotations

import pathlib

import pytest

from exilelens.errors import RestoreFailed
from exilelens.items.contextual_evidence import (
    EvidenceObservation,
    ProvenanceUnestablished,
    collect_candidate_evidence,
)
from exilelens.items.contextual_proof import (
    ContextualRelationship,
    classify_relationship,
    collect_measurements,
)
from exilelens.items.evaluation_identity import candidate_fingerprint

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


def _observation(effect_id: str, weapon_set: int, slot: str = "WEAPON_1") -> EvidenceObservation:
    return EvidenceObservation(
        reference=_reference(effect_id), weapon_set=weapon_set, logical_product_slot=slot
    )


class _Revision:
    def __init__(self, token: str) -> None:
        self.token = token


class _SourceRef:
    def __init__(self, key: str) -> None:
        self.key = key


class FakeEngine:
    """Deterministic stand-in exposing the real provenance surface."""

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
        self.calls: list[dict] = []
        self.fail_on_call: int | None = None
        self.bump_generation_after: int | None = None

    def evaluate_effect_candidate(self, reference, *, weapon_set, physical_slot, item_raw):
        self.calls.append(
            {"effect_id": reference["effect_id"], "weapon_set": weapon_set, "slot": physical_slot}
        )
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise RestoreFailed("restore failed", {"reason": "TEST"})
        if self.bump_generation_after is not None and len(self.calls) == self.bump_generation_after:
            self.source_generation += 1
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


DOUBLE = {
    ("EffectAPlayer", 1): ({"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
    ("EffectAPlayer", 2): ({"CombinedDPS": 50.0}, {"CombinedDPS": 100.0}),
}

TEXT = "Rarity: Rare\nTest Item\n+10 to Strength\n"


def test_one_candidate_two_observations_with_matching_provenance() -> None:
    engine = FakeEngine(DOUBLE)
    bundle = collect_candidate_evidence(
        engine,
        candidate_text=TEXT,
        observations=[_observation("EffectAPlayer", 1), _observation("EffectAPlayer", 2)],
    )
    assert bundle["candidate"] == {"fingerprint": candidate_fingerprint(TEXT)}
    assert bundle["provenance"] == {
        "candidate_fingerprint": candidate_fingerprint(TEXT),
        "source_identity": "LOCAL_POB:/build.xml",
        "source_revision": "rev-token-1",
        "build_generation": 7,
    }
    assert bundle["proof"]["classification"] == ContextualRelationship.COMMON_RESPONSE.value
    assert bundle["proof"]["representative_factor"] == pytest.approx(2.0)
    assert bundle["unavailable"] == []
    assert bundle["frames_total"] == {"context_settle": 2, "candidate_settle": 2, "restore_settle": 2}
    assert bundle["scope"] == "OBSERVED_RESPONSE_CONSISTENCY"
    assert bundle["exact"] is False


def test_cross_bundle_provenance_mismatch_is_not_comparable() -> None:
    from exilelens.items.contextual_proof import ContextualMeasurement

    first = collect_candidate_evidence(
        FakeEngine(DOUBLE),
        candidate_text="Rarity: Rare\nItem One\n+10 to Strength\n",
        observations=[_observation("EffectAPlayer", 1), _observation("EffectAPlayer", 2)],
    )
    second = collect_candidate_evidence(
        FakeEngine(DOUBLE, generation=8),
        candidate_text="Rarity: Rare\nItem Two\n+10 to Strength\n",
        observations=[_observation("EffectAPlayer", 1), _observation("EffectAPlayer", 2)],
    )
    assert first["provenance"]["candidate_fingerprint"] != second["provenance"]["candidate_fingerprint"]
    assert first["provenance"]["build_generation"] != second["provenance"]["build_generation"]

    def _measured() -> dict:
        return {
            "status": "MEASURED",
            "baseline": {"output": {"CombinedDPS": 100.0}},
            "candidate": {"output": {"CombinedDPS": 200.0}},
        }

    crossed = [
        ContextualMeasurement.from_candidate_result(
            _measured(),
            reference=_reference("EffectAPlayer"),
            context={"weapon_set": 1},
            candidate_fingerprint=first["provenance"]["candidate_fingerprint"],
            source_revision=first["provenance"]["source_revision"],
            build_generation=first["provenance"]["build_generation"],
        ),
        ContextualMeasurement.from_candidate_result(
            _measured(),
            reference=_reference("EffectAPlayer"),
            context={"weapon_set": 2},
            candidate_fingerprint=second["provenance"]["candidate_fingerprint"],
            source_revision=second["provenance"]["source_revision"],
            build_generation=second["provenance"]["build_generation"],
        ),
    ]
    proof = classify_relationship(crossed)
    assert proof.classification == ContextualRelationship.NOT_COMPARABLE
    assert proof.reason == "PROVENANCE_MISMATCH"


def test_bundle_revision_mismatch_is_not_comparable() -> None:
    from exilelens.items.contextual_proof import ContextualMeasurement

    def _measured() -> dict:
        return {
            "status": "MEASURED",
            "baseline": {"output": {"CombinedDPS": 100.0}},
            "candidate": {"output": {"CombinedDPS": 200.0}},
        }

    measurements = [
        ContextualMeasurement.from_candidate_result(
            _measured(),
            reference=_reference("EffectAPlayer"),
            context={"weapon_set": 1},
            candidate_fingerprint="candX",
            source_revision="rev-one",
            build_generation=7,
        ),
        ContextualMeasurement.from_candidate_result(
            _measured(),
            reference=_reference("EffectAPlayer"),
            context={"weapon_set": 2},
            candidate_fingerprint="candX",
            source_revision="rev-two",
            build_generation=7,
        ),
    ]
    proof = classify_relationship(measurements)
    assert proof.classification == ContextualRelationship.NOT_COMPARABLE
    assert proof.reason == "PROVENANCE_MISMATCH"


def test_unavailable_observation_stays_unavailable() -> None:
    engine = FakeEngine({("EffectAPlayer", 1): ({"CombinedDPS": 100.0}, {"CombinedDPS": 200.0})})
    bundle = collect_candidate_evidence(
        engine,
        candidate_text=TEXT,
        observations=[_observation("EffectAPlayer", 1), _observation("EffectAPlayer", 2)],
    )
    assert bundle["proof"]["classification"] == ContextualRelationship.NOT_COMPARABLE.value
    assert len(bundle["unavailable"]) == 1
    assert bundle["unavailable"][0]["status"] == "UNAVAILABLE"
    missing = next(row for row in bundle["observations"] if row["status"] == "UNAVAILABLE")
    assert missing["baseline_output"] is None
    assert missing["candidate_output"] is None
    assert "output" not in missing


def test_near_zero_observation_is_excluded_by_proof_policy() -> None:
    engine = FakeEngine(
        {
            ("EffectAPlayer", 1): ({"CombinedDPS": 0.2}, {"CombinedDPS": 40.0}),
            ("EffectAPlayer", 2): ({"CombinedDPS": 0.1}, {"CombinedDPS": 20.0}),
        }
    )
    bundle = collect_candidate_evidence(
        engine,
        candidate_text=TEXT,
        observations=[_observation("EffectAPlayer", 1), _observation("EffectAPlayer", 2)],
    )
    assert bundle["proof"]["classification"] == ContextualRelationship.INSUFFICIENT_EVIDENCE.value
    assert bundle["proof"]["reason"] == "NEAR_ZERO_BASELINE_REFUSES_RATIO"


def test_siblings_and_contexts_remain_distinct() -> None:
    outputs = {
        (effect, ws): ({"CombinedDPS": 100.0}, {"CombinedDPS": 200.0})
        for effect in ("EffectAPlayer", "EffectBPlayer")
        for ws in (1, 2)
    }
    bundle = collect_candidate_evidence(
        FakeEngine(outputs),
        candidate_text=TEXT,
        observations=[
            _observation("EffectAPlayer", 1),
            _observation("EffectAPlayer", 2),
            _observation("EffectBPlayer", 1),
            _observation("EffectBPlayer", 2),
        ],
    )
    identities = [row["cache_identity"] for row in bundle["observations"]]
    assert len(set(identities)) == 4
    tokens = [row["qualified_reference"]["context"]["token"] for row in bundle["observations"]]
    assert tokens[0] != tokens[1]
    assert bundle["proof"]["classification"] == ContextualRelationship.COMMON_RESPONSE.value


def test_physical_target_and_context_preserved() -> None:
    engine = FakeEngine(DOUBLE)
    bundle = collect_candidate_evidence(
        engine,
        candidate_text=TEXT,
        observations=[_observation("EffectAPlayer", 2)],
    )
    # Single observation: insufficient, but the row must still carry identity.
    assert bundle["proof"]["classification"] == ContextualRelationship.INSUFFICIENT_EVIDENCE.value
    row = bundle["observations"][0]
    assert row["physical_target"]["weapon_set"] == 2
    assert row["physical_target"]["physical_pob_slot"] == engine.calls[0]["slot"]
    assert row["qualified_reference"]["context"]["weapon_set"] == 2
    assert row["qualified_reference"]["component"]["effect_id"] == "EffectAPlayer"


def test_restore_failure_stops_orchestration() -> None:
    engine = FakeEngine(
        {
            ("EffectAPlayer", 1): ({"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
            ("EffectAPlayer", 2): ({"CombinedDPS": 50.0}, {"CombinedDPS": 100.0}),
            ("EffectBPlayer", 1): ({"CombinedDPS": 60.0}, {"CombinedDPS": 120.0}),
        }
    )
    engine.fail_on_call = 2
    with pytest.raises(RestoreFailed):
        collect_candidate_evidence(
            engine,
            candidate_text=TEXT,
            observations=[
                _observation("EffectAPlayer", 1),
                _observation("EffectAPlayer", 2),
                _observation("EffectBPlayer", 1),
            ],
        )
    assert len(engine.calls) == 2


def test_unestablished_or_drifting_provenance_fails_closed() -> None:
    observations = [_observation("EffectAPlayer", 1), _observation("EffectAPlayer", 2)]

    with pytest.raises(ProvenanceUnestablished):
        collect_candidate_evidence(
            FakeEngine(DOUBLE), candidate_text="  \n ", observations=observations
        )

    engine = FakeEngine(DOUBLE)
    engine.loaded_revision = None
    with pytest.raises(ProvenanceUnestablished):
        collect_candidate_evidence(engine, candidate_text=TEXT, observations=observations)
    assert engine.calls == []

    drifting = FakeEngine(DOUBLE)
    drifting.bump_generation_after = 1
    with pytest.raises(ProvenanceUnestablished):
        collect_candidate_evidence(drifting, candidate_text=TEXT, observations=observations)

    with pytest.raises(ValueError):
        collect_candidate_evidence(FakeEngine(DOUBLE), candidate_text=TEXT, observations=[])
    with pytest.raises(ValueError):
        collect_candidate_evidence(
            FakeEngine(DOUBLE),
            candidate_text=TEXT,
            observations=[_observation("EffectAPlayer", 3)],
        )


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


def test_evidence_never_sums_and_carries_no_verdict() -> None:
    bundle = collect_candidate_evidence(
        FakeEngine(DOUBLE),
        candidate_text=TEXT,
        observations=[_observation("EffectAPlayer", 1), _observation("EffectAPlayer", 2)],
    )
    assert {"total", "sum", "aggregate"}.isdisjoint(_all_keys(bundle, skip_outputs=True))
    assert {"verdict", "recommendation", "score", "ranking", "upgrade", "sidegrade", "downgrade"}.isdisjoint(
        _all_keys(bundle, skip_outputs=True)
    )
    assert bundle["proof"]["classification"] == ContextualRelationship.COMMON_RESPONSE.value
    assert any("not add" in warning.lower() for warning in bundle["proof"]["warnings"])
    assert bundle["automatic_grouping"] == "UNSUPPORTED"


def _module_source(name: str) -> str:
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "exilelens"
    return (root / name).read_text(encoding="utf-8")


def test_ordinary_item_check_does_not_consume_orchestration() -> None:
    for module in ("items/evaluation.py", "items/ranking.py", "items/evaluation_outcome.py"):
        source = _module_source(module)
        assert "contextual_evidence" not in source
        assert "contextual_proof" not in source
        assert "contextual_evaluation" not in source
    evaluation_source = _module_source("items/evaluation.py")
    assert "evaluate_effect_candidate" not in evaluation_source
    assert "get_weapon_set_context" not in evaluation_source
    assert "read_effect_metrics" not in evaluation_source
