"""TRUST-01A: candidate-own equipability (level / attributes) from PoB's numbers."""

from __future__ import annotations

import pytest

from exilelens.items.compact_tooltip import apply_compact_tooltip
from exilelens.items.consequences import build_warnings
from exilelens.items.equipability import build_equipability
from exilelens.items.evaluation_outcome import build_evaluation_outcome
from exilelens.items.guardrails import evaluate_guardrails
from exilelens.items.why_explanation import build_why_explanation

pytestmark = pytest.mark.itemcheck

CUR = {"CharacterLevel": 74.0, "Str": 132.0, "Dex": 80.0, "Int": 50.0}


def _eq(item, cand=None):
    return build_equipability(item, CUR, cand if cand is not None else CUR)


def _status(result, kind):
    return next(c["status"] for c in result["checks"] if c["kind"] == kind)


def test_level_pass_exact_and_fail_one_below():
    assert _status(_eq({"level_req": 74}), "level") == "PASS"
    result = _eq({"level_req": 75})
    assert _status(result, "level") == "FAIL"
    assert result["status"] == "NOT_EQUIPPABLE"
    assert result["blocking_reasons"] == ["Requires level 75 · Character is level 74"]


def test_attribute_pass_exact_and_fail_one_below():
    assert _status(_eq({"req_str": 132}), "strength") == "PASS"
    result = _eq({"req_str": 133})
    assert _status(result, "strength") == "FAIL"
    assert result["blocking_reasons"] == ["Requires 133 Strength · Character has 132"]


def test_candidate_own_bonus_counts_toward_its_requirement():
    cand = {**CUR, "Str": 160.0}
    assert _status(_eq({"req_str": 155}, cand), "strength") == "PASS"


def test_unknown_is_neither_pass_nor_fail():
    result = _eq({"level_req": 80})  # attribute requirements not reported by PoB
    assert _status(result, "strength") == "UNKNOWN"
    assert _status(result, "level") == "FAIL"
    no_level = build_equipability({"req_str": 10}, {"Str": 5.0}, {"Str": 5.0})
    assert _status(no_level, "level") == "UNKNOWN"
    assert no_level["status"] == "NOT_EQUIPPABLE"  # the known Str failure still stands
    clean = build_equipability({"req_str": 1}, {}, {"Str": 5.0})
    assert clean["status"] == "PARTIAL" and clean["blocking_reasons"] == []


def test_no_requirement_item_has_no_warning():
    item = {"level_req": 0, "req_str": 0, "req_dex": 0, "req_int": 0}
    result = _eq(item)
    assert result["status"] == "EQUIPPABLE"
    assert build_warnings({}, {}, CUR, CUR, equipability=result) == []


def test_multiple_failures_compact_reason_is_two_at_most():
    result = _eq({"level_req": 80, "req_str": 155, "req_dex": 200})
    assert len(result["blocking_reasons"]) == 3
    warning = build_warnings({}, {}, CUR, CUR, equipability=result)[0]
    assert warning["code"] == "EQUIP_REQUIREMENT_NOT_MET"
    assert warning["detail"].count(";") == 1
    assert warning["detail"].startswith("Requires level 80")


def test_guardrail_is_not_viable_with_player_reason():
    result = _eq({"req_str": 155})
    warnings = build_warnings({}, {}, CUR, CUR, equipability=result)
    (guard,) = evaluate_guardrails([w["code"] for w in warnings], warnings=warnings)
    assert guard.not_viable and guard.reason == "Requires 155 Strength · Character has 132"


def test_candidate_caused_post_swap_failure_remains():
    cand = {**CUR, "Str": 100.0, "ReqStr": 157.0}
    warnings = build_warnings({}, {}, CUR, cand, equipability=_eq({"req_str": 0}, cand))
    assert [w["code"] for w in warnings] == ["ATTRIBUTE_REQUIREMENT_LOST"]


def test_baseline_deficit_not_worsened_is_not_blamed():
    base = {**CUR, "Str": 100.0, "ReqStr": 150.0}
    warnings = build_warnings({}, {}, base, base, equipability=build_equipability({"req_str": 0}, base, base))
    assert warnings == []


def test_candidate_own_failure_masked_by_baseline_deficit_still_reported():
    # Baseline already needs 160 Str; the candidate's own 155 does not worsen ReqStr, but it is unwearable.
    base = {**CUR, "ReqStr": 160.0}
    warnings = build_warnings({}, {}, base, base, equipability=build_equipability({"req_str": 155}, base, base))
    assert [w["code"] for w in warnings] == ["EQUIP_REQUIREMENT_NOT_MET"]


def test_candidate_own_attribute_failure_is_one_canonical_blocker():
    cand = {**CUR, "ReqStr": 155.0}
    result = _eq({"req_str": 155}, cand)
    warnings = build_warnings({}, {}, CUR, cand, equipability=result)
    assert {w["code"] for w in warnings} == {"EQUIP_REQUIREMENT_NOT_MET", "ATTRIBUTE_REQUIREMENT_LOST"}
    guards = evaluate_guardrails([w["code"] for w in warnings], warnings=warnings)
    assert [g.code for g in guards] == ["EQUIP_REQUIREMENT_NOT_MET"]


def _outcome_with_big_gain(equipability):
    comparison = {
        "pob_slot": "Helmet",
        "product_slot": "helmet",
        "baseline": {"metrics": dict(CUR)},
        "candidate": {"metrics": dict(CUR)},
        "equipability": equipability,
    }
    metric_profile = {
        "primary_offense": {
            "label": "Damage", "availability": "ok", "current": 100.0, "candidate": 118.0,
            "absolute_delta": 18.0, "percent_delta": 18.0, "direction": "up",
        },
    }
    warnings = build_warnings(metric_profile, {}, CUR, CUR, equipability=equipability)
    value = {"raw_rating": 90.0, "rating": 90.0, "contributions": {}}
    return build_evaluation_outcome(
        comparison, value=value, metric_profile=metric_profile, resist={}, warnings=warnings
    )


def test_huge_gain_cannot_override_equipability_blocker_and_why_leads_with_it():
    outcome = _outcome_with_big_gain(_eq({"req_str": 155}))
    assert outcome.verdict == "NOT_VIABLE"
    assert outcome.equipability["status"] == "NOT_EQUIPPABLE"
    why = build_why_explanation(outcome.to_dict())
    assert why["reasons"][0]["text"].startswith("Requires 155 Strength · Character has 132")


def test_compact_tooltip_and_more_info_copy():
    outcome = _outcome_with_big_gain(_eq({"level_req": 78, "req_str": 155}))
    model = {"evaluation_outcome": outcome.to_dict(), "rows": []}
    apply_compact_tooltip(model)
    assert "NOT VIABLE" in model["verdict_headline"].upper()
    row = next(r for r in model["impact_rows"] if r["key"] == "cannot_equip")
    assert row["label"] == "Can't equip"
    assert row["delta_text"].startswith("Requires level 78 · Character is level 74")
    section = next(s for s in model["more_info"]["sections"] if s["id"] == "equipability")
    assert section["lines"] == [
        "Requires level 78 · Character is level 74",
        "Requires 155 Strength · Character has 132",
    ]
