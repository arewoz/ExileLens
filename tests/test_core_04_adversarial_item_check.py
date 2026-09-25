"""CORE-04 adversarial regression coverage for the public Item Check contract.

These tests deliberately exercise semantic boundaries using deterministic worker-shaped
payloads. Real-PoB fixture coverage belongs to the public corpus when it is published.
"""

from __future__ import annotations

import copy

import pytest

from exilelens.items.baseline_item import resolve_baseline_item
from exilelens.items.best_slot import select_best_comparison
from exilelens.items.evaluation_identity import (
    EvaluationContextIdentity,
    candidate_fingerprint,
    canonical_candidate_text,
)
from exilelens.items.evaluation_outcome import (
    EvaluationQuality,
    PublicVerdict,
    SCORED_RAW_FIELDS,
    assess_quality,
    classify_score_verdict,
    decide_verdict,
)
from exilelens.items.item_impact import interpret_item_impact
from exilelens.items.ranking import enrich_slot_comparison
from exilelens.items.resist_caps import CapState, analyze_resistance
from exilelens.items.slots import ProductSlot, pob_slot_to_product
from exilelens.items.value_profiles import SCORE_SCALE, ValueProfile, score_profile
from exilelens.metrics import build_metric_profile


pytestmark = pytest.mark.itemcheck


def _raw(**overrides: float | str | None) -> dict[str, float | str | None]:
    values: dict[str, float | str | None] = {field: 100.0 for field in SCORED_RAW_FIELDS}
    values.update(
        {
            "CombinedDPS": 100.0,
            "TotalEHP": 1_000.0,
            "Life": 500.0,
            "EnergyShield": 100.0,
            "PhysicalMaximumHitTaken": 100.0,
            "FireMaximumHitTaken": 100.0,
            "ColdMaximumHitTaken": 100.0,
            "LightningMaximumHitTaken": 100.0,
            "ChaosMaximumHitTaken": 100.0,
            "MovementSpeedMod": 1.0,
            "FireResist": 75.0,
            "ColdResist": 75.0,
            "LightningResist": 75.0,
            "ChaosResist": 0.0,
            "FireResistMax": 75.0,
            "ColdResistMax": 75.0,
            "LightningResistMax": 75.0,
            "ChaosResistMax": 75.0,
        }
    )
    values.update(overrides)
    return values


def _comparison(
    before: dict[str, float | str | None] | None = None,
    after: dict[str, float | str | None] | None = None,
    *,
    slot: str = "Ring 1",
) -> dict:
    return {
        "pob_slot": slot,
        "product_slot": pob_slot_to_product(slot).value,
        "baseline": {"metrics": before or _raw()},
        "candidate": {"metrics": after or _raw(), "item_present": True},
        "restore": {"pass": True},
    }


def _selection(slot: str, verdict: str, *, quality: str = "FULL", rating: float = 50.0) -> dict:
    return {
        "pob_slot": slot,
        "product_slot": pob_slot_to_product(slot).value,
        "evaluation_outcome": {"verdict": verdict, "evaluation_quality": quality},
        "value": {"rating": rating},
        "metric_profile": {"primary_offense": {"absolute_delta": 1.0}, "ehp": {"absolute_delta": 1.0}},
        "restore": {"pass": True},
    }


@pytest.mark.parametrize(
    ("pob_slot", "item_type", "expected"),
    [
        ("Helmet", None, ProductSlot.HELMET),
        ("Body Armour", None, ProductSlot.BODY_ARMOUR),
        ("Gloves", None, ProductSlot.GLOVES),
        ("Boots", None, ProductSlot.BOOTS),
        ("Belt", None, ProductSlot.BELT),
        ("Amulet", None, ProductSlot.AMULET),
        ("Ring 1", None, ProductSlot.RING_1),
        ("Ring 2", None, ProductSlot.RING_2),
        ("Weapon 1", "Bow", ProductSlot.WEAPON_1),
        ("Weapon 2", "Quiver", ProductSlot.OFFHAND_1),
        ("Weapon 2", "Shield", ProductSlot.OFFHAND_1),
        ("Weapon 2", "Focus", ProductSlot.OFFHAND_1),
        ("Weapon 2", "Wand", ProductSlot.WEAPON_2),
    ],
)
def test_supported_slot_mapping_is_semantic_not_position_only(pob_slot: str, item_type: str | None, expected: ProductSlot) -> None:
    assert pob_slot_to_product(pob_slot, item_type=item_type) is expected


def test_ring_slot_selection_prefers_full_evidence_over_partial_and_unsupported() -> None:
    ring_one = _selection("Ring 1", PublicVerdict.UNSUPPORTED.value, quality="UNSUPPORTED", rating=100.0)
    ring_two = _selection("Ring 2", PublicVerdict.MINOR_UPGRADE.value, rating=53.0)
    assert select_best_comparison([ring_one, ring_two]) is ring_two


def test_ring_slot_selection_preserves_valid_full_downgrade_over_unsupported() -> None:
    unsupported = _selection("Ring 1", PublicVerdict.UNSUPPORTED.value, quality="UNSUPPORTED", rating=100.0)
    full = _selection("Ring 2", PublicVerdict.MEANINGFUL_DOWNGRADE.value, rating=1.0)
    assert select_best_comparison([unsupported, full]) is full


def test_ring_slot_equal_outcomes_have_a_stable_slot_tiebreaker() -> None:
    ring_two = _selection("Ring 2", PublicVerdict.SIDEGRADE.value)
    ring_one = _selection("Ring 1", PublicVerdict.SIDEGRADE.value)
    assert select_best_comparison([ring_two, ring_one]) is ring_one


@pytest.mark.parametrize("quality", [EvaluationQuality.PARTIAL, EvaluationQuality.UNSUPPORTED, EvaluationQuality.FAILED])
def test_reducing_evidence_never_emits_a_directional_verdict(quality: EvaluationQuality) -> None:
    decision = decide_verdict(90.0, (), quality, [{"code": "TEST", "detail": "reduced evidence"}])
    assert decision.verdict not in {
        PublicVerdict.MEANINGFUL_UPGRADE,
        PublicVerdict.MINOR_UPGRADE,
        PublicVerdict.MINOR_DOWNGRADE,
        PublicVerdict.MEANINGFUL_DOWNGRADE,
    }


def test_known_zero_is_available_but_missing_is_not() -> None:
    zero_profile = build_metric_profile(_raw(CombinedDPS=0.0, TotalEHP=0.0), _raw(CombinedDPS=0.0, TotalEHP=0.0))
    missing_profile = build_metric_profile(_raw(CombinedDPS=None), _raw(CombinedDPS=None))
    assert zero_profile["primary_offense"]["availability"] == "available"
    assert zero_profile["primary_offense"]["absolute_delta"] == 0.0
    assert missing_profile["primary_offense"]["availability"] == "missing"
    assert score_profile(missing_profile, {"elements": {}}, [], profile=ValueProfile.BALANCED)["contributions"]["primary_offense"] == 0.0


@pytest.mark.parametrize("field", ["CombinedDPS", "ManaPerSecondCost"])
@pytest.mark.parametrize("bad_value", ["not-a-number", float("nan"), float("inf"), True])
def test_malformed_worker_output_fails_closed(field: str, bad_value: float | str | bool) -> None:
    comparison = _comparison(after=_raw(**{field: bad_value}))
    result = enrich_slot_comparison(comparison)
    outcome = result["evaluation_outcome"]
    assert outcome["evaluation_quality"] == EvaluationQuality.FAILED.value
    assert outcome["verdict"] == PublicVerdict.NOT_EVALUATED.value
    assert "INVALID_METRICS" in {reason["code"] for reason in outcome["evaluation_quality_reasons"]}


@pytest.mark.parametrize(
    ("current", "candidate", "current_overcap", "candidate_overcap", "expected"),
    [
        (70.0, 74.0, 0.0, 0.0, CapState.BELOW_CAP_IMPROVED),
        (74.0, 75.0, 0.0, 0.0, CapState.CAP_REACHED),
        (80.0, 90.0, 0.0, 0.0, CapState.CAPPED_STAYS_CAPPED),
        (75.0, 75.0, 15.0, 5.0, CapState.OVER_CAP_REDUCED_BUT_STILL_CAPPED),
        (75.0, 74.0, 0.0, 0.0, CapState.CAP_LOST),
    ],
)
def test_resistance_state_boundaries(
    current: float,
    candidate: float,
    current_overcap: float,
    candidate_overcap: float,
    expected: CapState,
) -> None:
    before = _raw(FireResist=current, FireResistMax=75.0, FireResistOverCap=current_overcap)
    after = _raw(FireResist=candidate, FireResistMax=75.0, FireResistOverCap=candidate_overcap)
    assert analyze_resistance(before, after, "fire")["state"] == expected.value


def test_missing_resistance_is_unknown_not_zero_deficit() -> None:
    resistance = analyze_resistance(_raw(FireResist=None), _raw(FireResist=None), "fire")
    assert resistance["state"] == CapState.UNKNOWN.value
    assert resistance["baseline_deficit"] is None


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (SCORE_SCALE.useful - 0.0001, PublicVerdict.MINOR_UPGRADE),
        (SCORE_SCALE.useful, PublicVerdict.MEANINGFUL_UPGRADE),
        (SCORE_SCALE.minor_upgrade - 0.0001, PublicVerdict.SIDEGRADE),
        (SCORE_SCALE.minor_upgrade, PublicVerdict.MINOR_UPGRADE),
        (SCORE_SCALE.minor_downgrade, PublicVerdict.MINOR_DOWNGRADE),
        (SCORE_SCALE.meaningful_downgrade, PublicVerdict.MEANINGFUL_DOWNGRADE),
    ],
)
def test_public_verdict_threshold_boundaries(score: float, expected: PublicVerdict) -> None:
    assert classify_score_verdict(score) is expected


def test_meaningful_cross_axis_tradeoff_is_not_flattened_by_aggregate_score() -> None:
    before = _raw(CombinedDPS=100.0, TotalEHP=1_000.0)
    after = _raw(CombinedDPS=140.0, TotalEHP=700.0)
    profile = build_metric_profile(before, after)
    impact = interpret_item_impact(profile, {"elements": {}}, before, after)
    assert impact.pattern == "TRADEOFF"


@pytest.mark.parametrize(
    ("after_overrides", "guardrail"),
    [
        ({"Str": 70.0, "StrReq": 80.0}, "ATTRIBUTE_REQUIREMENT_LOST"),
        ({"ManaPerSecondCost": 20.0, "ManaRegenRecovery": 10.0}, "RESOURCE_FAILURE"),
    ],
)
def test_critical_constraints_remain_separate_from_an_attractive_score(
    after_overrides: dict[str, float], guardrail: str
) -> None:
    before = _raw(CombinedDPS=100.0, Str=100.0, StrReq=80.0, ManaPerSecondCost=10.0, ManaRegenRecovery=20.0)
    after = _raw(CombinedDPS=200.0, Str=100.0, StrReq=80.0, ManaPerSecondCost=10.0, ManaRegenRecovery=20.0)
    after.update(after_overrides)
    outcome = enrich_slot_comparison(_comparison(before, after))["evaluation_outcome"]
    assert outcome["verdict"] == PublicVerdict.NOT_VIABLE.value
    assert guardrail in {row["code"] for row in outcome["guardrails_applied"]}


def test_empty_slot_is_distinct_from_an_unknown_baseline_slot() -> None:
    empty = resolve_baseline_item(
        pob_slot="Ring 1",
        product_slot="RING_1",
        baseline={"equipment": {"Ring 1": {"equipped": False}}},
    )
    unknown = resolve_baseline_item(pob_slot="Ring 1", product_slot="RING_1", baseline={})
    assert empty.empty is True
    assert unknown.empty is False


def test_candidate_fingerprint_normalizes_formatting_but_not_semantics() -> None:
    item = "Item Class: Rings\nRarity: Rare\nTest\nSapphire Ring\n+20% to Cold Resistance"
    formatted = "\r\n  \r\n" + item.replace("\n", "\r\n") + "   \r\n\r\n"
    changed = item.replace("+20%", "+21%")
    assert canonical_candidate_text(formatted) == item
    assert candidate_fingerprint(formatted) == candidate_fingerprint(item)
    assert candidate_fingerprint(changed) != candidate_fingerprint(item)


@pytest.mark.parametrize("field", ["loadout", "item_set", "worker_generation", "source_revision", "calculation_context"])
def test_context_identity_changes_for_material_evaluation_context(field: str) -> None:
    base = EvaluationContextIdentity(source_identity="build", source_revision="a", loadout="A", item_set="1")
    values = copy.deepcopy(base.__dict__)
    values[field] = 2 if field == "worker_generation" else "changed"
    assert EvaluationContextIdentity(**values).token != base.token


def test_assess_quality_marks_explicit_restore_failure_as_failed() -> None:
    comparison = _comparison()
    comparison["restore"] = {"pass": False}
    profile = build_metric_profile(comparison["baseline"]["metrics"], comparison["candidate"]["metrics"])
    quality, reasons = assess_quality(comparison, metric_profile=profile, resist={"elements": {}})
    assert quality is EvaluationQuality.FAILED
    assert {reason["code"] for reason in reasons} == {"RESTORE_FAILED"}
