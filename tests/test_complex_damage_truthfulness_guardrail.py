from __future__ import annotations

import pytest

from exilelens.items.build_intel.engine import compare_slot
from exilelens.items.compare import CompareEntry, PinCompareState, build_compare_summary
from exilelens.items.comparison_trace import build_comparison_trace
from exilelens.items.decision import build_decision_summary
from exilelens.items.evaluation_outcome import EvaluationQuality, PublicVerdict, SCORED_RAW_FIELDS
from exilelens.items.loot_review import LootCategory, LootReviewSession
from exilelens.items.multi_profile import score_all_profiles
from exilelens.items.presentation import build_presentation
from exilelens.items.ranking import enrich_slot_comparison, rank_slot_comparisons
from exilelens.items.slots import pob_slot_to_product
from exilelens.items.upgrade_path import UpgradePathState, build_upgrade_path_block, classify_upgrade_path_state


pytestmark = pytest.mark.itemcheck


def _raw(damage: float) -> dict[str, float]:
    values = {field: 100.0 for field in SCORED_RAW_FIELDS}
    values.update(
        {
            "CombinedDPS": damage,
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
    return values


def _comparison(
    after: float,
    *,
    slot: str = "Ring 1",
    partial: bool = True,
    semantic_quantity: str = "HIT_DPS",
) -> dict:
    metric = {
        "pob_field": "CombinedDPS",
        "provenance": "POB_COMPONENT" if partial else "POB_PRIMARY_SKILL",
        "semantic_quantity": semantic_quantity,
        "metric_scope": "PRIMARY_SKILL",
        "confidence": "high",
        "skill_name": "Test Skill",
    }
    discovery = {
        "damage_scope": "PARTIAL" if partial else "PRIMARY",
        "provenance": "POB_COMPONENT" if partial else "POB_PRIMARY_SKILL",
        "composition_status": "PARTIAL" if partial else "NOT_ASSESSED",
        "overall_damage_verdict": "UNCERTAIN" if partial else "NOT_DERIVED",
        "components": [
            {
                "name": "Test Skill",
                "status": "MEASURED",
                "before": 100.0,
                "after": after,
                "percent_delta": after - 100.0,
            }
        ] if partial else [],
    }
    return {
        "pob_slot": slot,
        "product_slot": pob_slot_to_product(slot).value,
        "baseline": {"metrics": _raw(100.0)},
        "candidate": {"metrics": _raw(after), "item_present": True},
        "restore": {"pass": True},
        "baseline_primary_metric": metric,
        "candidate_primary_metric": metric,
        "native_damage_discovery": discovery,
        # This is the former bypass: an ordinary comparison deliberately skipped
        # the optional probe audit even though stronger native evidence is PARTIAL.
        "offense_coverage": {
            "state": "PARTIAL",
            "offense_trustworthy": False,
            "audit_skipped": True,
        },
    }


def _enriched(after: float, *, slot: str = "Ring 1", partial: bool = True, semantic_quantity: str = "HIT_DPS") -> dict:
    comparison = _comparison(after, slot=slot, partial=partial, semantic_quantity=semantic_quantity)
    return enrich_slot_comparison(
        comparison,
        primary_field="CombinedDPS",
        primary_confidence="high",
        offense_coverage=comparison["offense_coverage"],
    )


@pytest.mark.parametrize(
    ("after", "forbidden"),
    [
        (118.3, {PublicVerdict.MEANINGFUL_UPGRADE.value, PublicVerdict.MINOR_UPGRADE.value}),
        (80.0, {PublicVerdict.MINOR_DOWNGRADE.value, PublicVerdict.MEANINGFUL_DOWNGRADE.value}),
        (100.0, {PublicVerdict.SIDEGRADE.value}),
    ],
)
def test_partial_composition_never_becomes_directional(after: float, forbidden: set[str]) -> None:
    result = _enriched(after)
    outcome = result["evaluation_outcome"]
    claim = outcome["damage_claim"]

    assert outcome["evaluation_quality"] == EvaluationQuality.PARTIAL.value
    assert outcome["verdict"] == PublicVerdict.UNCERTAIN.value
    assert outcome["verdict"] not in forbidden
    assert claim == result["damage_claim"]
    assert claim["scope"] == "POB_COMPONENT"
    assert claim["absolute_status"] == "EXACT"
    assert claim["relative_status"] == "EXACT"
    assert claim["whole_build_status"] == "PARTIAL"
    assert claim["before"] == pytest.approx(100.0)
    assert claim["after"] == pytest.approx(after)
    assert "PRACTICAL_COMPOSITION_UNAVAILABLE" in claim["reason_codes"]
    assert "OFFENSE_COMPOSITION_PARTIAL" in {
        reason["code"] for reason in outcome["evaluation_quality_reasons"]
    }


def test_ordinary_and_authoritative_mixed_comparisons_remain_full() -> None:
    ordinary = _enriched(120.0, partial=False)
    mixed = _enriched(120.0, partial=False, semantic_quantity="HIT_PLUS_AILMENT")

    for result in (ordinary, mixed):
        outcome = result["evaluation_outcome"]
        assert outcome["evaluation_quality"] == EvaluationQuality.FULL.value
        assert outcome["verdict"] == PublicVerdict.MEANINGFUL_UPGRADE.value
        assert outcome["damage_claim"]["scope"] == "POB_PRIMARY_SKILL"
        assert outcome["damage_claim"]["whole_build_status"] == "NOT_ASSESSED"


@pytest.mark.parametrize(
    "composition_signal",
    [
        {"composition_status": "PARTIAL", "overall_damage_verdict": "NOT_DERIVED"},
        {"composition_status": "NOT_ASSESSED", "overall_damage_verdict": "UNCERTAIN"},
    ],
)
def test_exact_primary_skill_with_explicit_incomplete_composition_is_uncertain(
    composition_signal: dict[str, str],
) -> None:
    comparison = _comparison(120.0, partial=False)
    comparison["native_damage_discovery"].update(
        {
            "damage_scope": "PARTIAL",
            **composition_signal,
        }
    )
    result = enrich_slot_comparison(
        comparison,
        primary_field="CombinedDPS",
        primary_confidence="high",
        offense_coverage=comparison["offense_coverage"],
    )

    outcome = result["evaluation_outcome"]
    assert outcome["damage_claim"]["scope"] == "POB_PRIMARY_SKILL"
    assert outcome["damage_claim"]["relative_status"] == "EXACT"
    assert outcome["damage_claim"]["whole_build_status"] == "PARTIAL"
    assert outcome["evaluation_quality"] == EvaluationQuality.PARTIAL.value
    assert outcome["verdict"] == PublicVerdict.UNCERTAIN.value


def test_partial_component_report_without_materiality_evidence_does_not_overfire() -> None:
    comparison = _comparison(120.0, partial=False)
    comparison["native_damage_discovery"].update(
        {
            "damage_scope": "PARTIAL",
            "composition_status": "NOT_ASSESSED",
            "overall_damage_verdict": "NOT_DERIVED",
        }
    )
    result = enrich_slot_comparison(
        comparison,
        primary_field="CombinedDPS",
        primary_confidence="high",
        offense_coverage=comparison["offense_coverage"],
    )

    outcome = result["evaluation_outcome"]
    assert outcome["damage_claim"]["whole_build_status"] == "NOT_ASSESSED"
    assert outcome["evaluation_quality"] == EvaluationQuality.FULL.value
    assert outcome["verdict"] == PublicVerdict.MEANINGFUL_UPGRADE.value


def test_outcome_presence_prevents_legacy_verdict_fallback() -> None:
    from exilelens.items.evaluation_outcome import authoritative_public_verdict

    assert authoritative_public_verdict(
        {"evaluation_outcome": {}, "verdict": "STRONG_UPGRADE"}
    ) == "UNRESOLVED"


def test_high_score_partial_cannot_win_confidently_or_dominate() -> None:
    partial = _enriched(500.0, slot="Ring 1")
    full = _enriched(105.0, slot="Ring 2", partial=False)
    ranking = rank_slot_comparisons([partial, full], skip_enrich=True)

    assert partial["evaluation_outcome"]["final_score"] > full["evaluation_outcome"]["final_score"]
    assert ranking["recommendation"]["pob_slot"] == "Ring 2"

    only_partial = rank_slot_comparisons([partial], skip_enrich=True)
    assert only_partial["recommendation"]["evaluation_outcome"]["verdict"] == "UNCERTAIN"
    assert only_partial["pareto"]["status"] == "NEITHER_DOMINATES"
    assert only_partial["pareto"]["verdict"] == "UNCERTAIN"


def test_recommendation_consumers_use_authoritative_uncertain_outcome() -> None:
    comparison = _enriched(200.0)
    decision = build_decision_summary(comparison).to_dict()
    intel = compare_slot(comparison).to_dict()
    result = {
        "recommendation": comparison,
        "slot_comparisons": [comparison],
        "decision": decision,
        "build_comparison": intel,
        "primary_metric": comparison["baseline_primary_metric"],
        "offense_coverage": comparison["offense_coverage"],
        "native_damage_discovery": comparison["native_damage_discovery"],
        "damage_claim": comparison["damage_claim"],
        "pob_parse": {"display_name": "Candidate", "item": {"type": "Ring"}},
        "metadata": {"name": "Candidate", "base_type": "Ring"},
        "value_profile": "BALANCED",
    }

    assert decision["verdict"] == "UNCERTAIN"
    assert decision["recommendation_tag"] == ""
    assert decision["confidence"] == "LOW"
    assert intel["product_verdict"] == "UNCERTAIN"
    assert classify_upgrade_path_state(result) == UpgradePathState.UNCERTAIN.value
    upgrade_path = build_upgrade_path_block(
        result,
        potential={
            "product_state": UpgradePathState.ALREADY_UPGRADE.value,
            "paths": [{"label": "legacy directional repair", "magnitude": 10}],
            "repaired_rating": 90,
            "repaired_verdict": "STRONG_UPGRADE",
        },
    )
    assert upgrade_path["product_state"] == UpgradePathState.UNCERTAIN.value
    assert upgrade_path["paths"] == []
    assert upgrade_path["after_repair"] is None

    trace = build_comparison_trace(result)
    assert trace["delta"]["verdict"] == "UNCERTAIN"
    assert trace["delta"]["explanation"].startswith("Partial comparison:")

    presentation = build_presentation(result)
    assert presentation["verdict"] == "UNCERTAIN"
    assert presentation["ranking_verdict"] == "UNCERTAIN"
    assert presentation["product_verdict"] == "UNCERTAIN"
    assert presentation["recommendation_tag"] == ""
    assert presentation["damage_claim"]["whole_build_status"] == "PARTIAL"

    loot = LootReviewSession()
    loot.start(baseline_identity="build")
    entry = loot.record(result, baseline_identity="build")
    assert entry is not None
    assert entry.verdict == "UNCERTAIN"
    assert entry.category == LootCategory.UNCERTAIN.value

    pin = CompareEntry("p1", "hash", "Candidate", "build", result, pin_label="A")
    assert pin.to_dict()["verdict"] == "UNCERTAIN"
    state = PinCompareState(baseline_identity="build", entries=[pin])
    summary = build_compare_summary(state)
    assert summary["rows"][0]["verdict"] == "UNCERTAIN"
    assert summary["best_current_option"] is None

    profiles = score_all_profiles(
        [comparison],
        primary_field="CombinedDPS",
        primary_confidence="high",
        offense_coverage=comparison["offense_coverage"],
    )
    assert all(row["verdict"] == "UNCERTAIN" for row in profiles["profiles"].values())
    assert all(row["ranking_verdict"] == "UNCERTAIN" for row in profiles["profiles"].values())
