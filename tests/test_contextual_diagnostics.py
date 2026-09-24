"""Slice 4D focused gate: diagnostic consumer (fake engine, deterministic)."""

from __future__ import annotations

import pathlib

import pytest

from exilelens.errors import RestoreFailed
from exilelens.items.contextual_composition import CompositionEligibility
from exilelens.items.contextual_diagnostics import run_contextual_diagnostic
from exilelens.items.contextual_evidence import EvidenceObservation
from exilelens.items.contextual_proof import ContextualRelationship

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
        "truncated": truncated,
    }


class _Revision:
    def __init__(self, token: str) -> None:
        self.token = token


class _SourceRef:
    def __init__(self, key: str) -> None:
        self.key = key


class FakeEngine:
    """Deterministic stand-in with the real diagnostic surface."""

    def __init__(
        self,
        outputs: dict[tuple[str, int], tuple[dict, dict] | None],
        catalog_effects: list[str],
        *,
        weapon_set: int = 2,
        fingerprint: str = "fp-baseline",
        catalog_truncated: bool = False,
        fail_on_evaluate: bool = False,
        drift_fingerprint: bool = False,
    ) -> None:
        self._outputs = outputs
        self._catalog_effects = catalog_effects
        self._weapon_set = weapon_set
        self._fingerprint = fingerprint
        self._catalog_truncated = catalog_truncated
        self._fail_on_evaluate = fail_on_evaluate
        self._drift = drift_fingerprint
        self.loaded_revision = _Revision("rev-token-1")
        self.loaded_source_ref = _SourceRef("LOCAL_POB:/build.xml")
        self.source_generation = 7
        self.evaluate_calls = 0
        self.catalog_calls: list = []

    def get_metrics(self):
        return {"fingerprint_hash": self._fingerprint}

    def get_weapon_set_context(self):
        return {
            "weapon_set": self._weapon_set,
            "physical_weapons": {"Weapon 1 Swap": "bow-raw", "Weapon 1": "spear-raw"},
        }

    def get_build_info(self):
        return {"build": {"skill_group_count": 3}}

    def list_calculable_effects(self, indices=None, weapon_set=None):
        self.catalog_calls.append(weapon_set)
        return _catalog(self._catalog_effects, truncated=self._catalog_truncated)

    def evaluate_effect_candidate(self, reference, *, weapon_set, physical_slot, item_raw):
        self.evaluate_calls += 1
        if self._fail_on_evaluate:
            raise RestoreFailed("restore failed", {"reason": "TEST"})
        if self._drift:
            self._fingerprint = "fp-drifted"
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
            "frames": {"context_settle": 0, "candidate_settle": 1, "restore_settle": 1},
            "restore": {"status": "OK", "pass": True},
            "physical_target": {
                "logical_product_slot": "WEAPON_1",
                "physical_pob_slot": physical_slot,
                "weapon_set": int(weapon_set),
            },
        }


TEXT = "Rarity: Rare\nTest Item\n+10 to Strength\n"
DOUBLE = {
    ("EffectAPlayer", 2): ({"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
    ("EffectBPlayer", 2): ({"CombinedDPS": 50.0}, {"CombinedDPS": 100.0}),
}


def _observation(effect_id: str, weapon_set: int = 2) -> EvidenceObservation:
    return EvidenceObservation(
        reference=_reference(effect_id), weapon_set=weapon_set, logical_product_slot="WEAPON_1"
    )


def _run(engine: FakeEngine, observations, **kwargs) -> dict:
    return run_contextual_diagnostic(engine, candidate_text=TEXT, observations=observations, **kwargs)


def test_diagnostic_schema_and_eligibility_path() -> None:
    engine = FakeEngine(DOUBLE, ["EffectAPlayer", "EffectBPlayer"])
    report = _run(engine, [_observation("EffectAPlayer"), _observation("EffectBPlayer")])
    for key in (
        "candidate", "provenance", "source_identity", "source_revision", "build_generation",
        "requested_contexts", "observations", "unavailable", "physical_targets",
        "proof", "proof_scope", "proof_exact", "completeness", "assessment",
        "composition_eligibility", "eligibility_reason", "frames_total", "restore",
        "baseline_state", "final_state", "limitations", "warnings",
        "whole_build", "public_verdict_affected",
    ):
        assert key in report, key
    assert report["whole_build"] is False
    assert report["public_verdict_affected"] is False
    assert report["requested_contexts"] == [2]
    assert report["composition_eligibility"] == CompositionEligibility.ELIGIBLE.value
    assert report["proof"]["classification"] == ContextualRelationship.COMMON_RESPONSE.value
    assert report["proof_exact"] is False
    assert report["restore"] == {
        "pass": True, "baseline_fingerprint": "fp-baseline", "final_fingerprint": "fp-baseline",
    }
    assert report["frames_total"] == {"context_settle": 0, "candidate_settle": 2, "restore_settle": 2}
    assert report["completeness"]["required_identities_count"] == 2
    assert report["completeness"]["observed_identities_count"] == 2
    assert report["completeness"]["missing_identities"] == []
    assert report["completeness"]["missing_catalog_sets"] == []


def test_missing_identities_and_truncation_exposed() -> None:
    engine = FakeEngine(DOUBLE, ["EffectAPlayer", "EffectBPlayer", "EffectCPlayer"])
    report = _run(engine, [_observation("EffectAPlayer"), _observation("EffectBPlayer")])
    assert report["composition_eligibility"] == CompositionEligibility.INSUFFICIENT_EVIDENCE.value
    assert report["eligibility_reason"] == "SUBSET_INCOMPLETE"
    assert len(report["completeness"]["missing_identities"]) == 1

    truncated = FakeEngine(DOUBLE, ["EffectAPlayer", "EffectBPlayer"], catalog_truncated=True)
    truncated_report = _run(truncated, [_observation("EffectAPlayer"), _observation("EffectBPlayer")])
    assert truncated_report["eligibility_reason"] == "COVERAGE_UNPROVEN"
    assert truncated_report["completeness"]["catalog_truncated"] == {"2": True}


def test_unavailable_and_unenumerated_set_exposed() -> None:
    engine = FakeEngine(
        {("EffectAPlayer", 2): ({"CombinedDPS": 100.0}, {"CombinedDPS": 200.0})},
        ["EffectAPlayer", "EffectBPlayer"],
    )
    report = _run(engine, [_observation("EffectAPlayer"), _observation("EffectBPlayer")])
    assert len(report["unavailable"]) == 1
    assert report["unavailable"][0]["status"] == "UNAVAILABLE"
    assert report["composition_eligibility"] == CompositionEligibility.NOT_ELIGIBLE.value

def test_both_weapon_sets_enumerated_with_restore() -> None:
    outputs = {
        **DOUBLE,
        ("EffectAPlayer", 1): ({"CombinedDPS": 100.0}, {"CombinedDPS": 200.0}),
        ("EffectBPlayer", 1): ({"CombinedDPS": 50.0}, {"CombinedDPS": 100.0}),
    }
    engine = FakeEngine(outputs, ["EffectAPlayer", "EffectBPlayer"])
    report = run_contextual_diagnostic(
        engine,
        candidate_text=TEXT,
        observations=[
            _observation("EffectAPlayer", 1),
            _observation("EffectAPlayer", 2),
            _observation("EffectBPlayer", 1),
            _observation("EffectBPlayer", 2),
        ],
    )
    assert report["requested_contexts"] == [1, 2]
    assert report["completeness"]["catalog_status"]["1"]["enumerated"] is True
    assert report["completeness"]["catalog_status"]["2"]["enumerated"] is True
    assert report["completeness"]["missing_catalog_sets"] == []
    assert set(engine.catalog_calls) == {1, 2}
    assert report["completeness"]["required_identities_count"] == 4
    assert report["completeness"]["missing_identities"] == []
    assert report["composition_eligibility"] == CompositionEligibility.ELIGIBLE.value
    assert report["restore"]["pass"] is True


def test_caller_supplied_catalogs_complete_scope() -> None:
    engine = FakeEngine(
        {**DOUBLE, ("EffectAPlayer", 1): ({"CombinedDPS": 100.0}, {"CombinedDPS": 200.0})},
        ["EffectAPlayer"],
    )
    report = _run(
        engine,
        [_observation("EffectAPlayer", 1), _observation("EffectAPlayer", 2)],
        catalog_by_weapon_set={1: _catalog(["EffectAPlayer"]), 2: _catalog(["EffectAPlayer"])},
    )
    assert report["completeness"]["missing_catalog_sets"] == []
    assert report["composition_eligibility"] == CompositionEligibility.ELIGIBLE.value


def test_restore_failure_and_drift_fail_closed() -> None:
    failing = FakeEngine(DOUBLE, ["EffectAPlayer"], fail_on_evaluate=True)
    with pytest.raises(RestoreFailed):
        _run(failing, [_observation("EffectAPlayer")])

    drifting = FakeEngine(DOUBLE, ["EffectAPlayer"], drift_fingerprint=True)
    with pytest.raises(RestoreFailed):
        _run(drifting, [_observation("EffectAPlayer")])

    with pytest.raises(ValueError):
        run_contextual_diagnostic(FakeEngine(DOUBLE, ["EffectAPlayer"]), candidate_text=TEXT, observations=[])


def _module_source(name: str) -> str:
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "exilelens"
    return (root / name).read_text(encoding="utf-8")


def test_ordinary_item_check_does_not_consume_diagnostics() -> None:
    for module in ("items/evaluation.py", "items/ranking.py", "items/evaluation_outcome.py"):
        source = _module_source(module)
        assert "contextual_diagnostics" not in source
        assert "contextual_composition" not in source
        assert "contextual_evidence" not in source
        assert "contextual_proof" not in source
        assert "contextual_evaluation" not in source
    evaluation_source = _module_source("items/evaluation.py")
    assert "evaluate_effect_candidate" not in evaluation_source
    assert "get_weapon_set_context" not in evaluation_source
    assert "read_effect_metrics" not in evaluation_source
