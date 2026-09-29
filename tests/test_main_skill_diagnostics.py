"""MAIN-SKILL-01 — main-skill diagnostics (no PoB engine).

Real-PoB counterparts: tests/integration/test_main_skill_01_real_pob.py.
"""

from __future__ import annotations

import pytest

from exilelens.items.evaluation_outcome import EvaluationQuality, assess_quality
from exilelens.items.main_skill_diagnostics import (
    ALT_AVAILABLE,
    ALT_NONE,
    ALT_NOT_ASSESSED,
    MAX_ALTERNATIVES_SHOWN,
    REASON_CODE,
    build_main_skill_diagnostic,
    calculated_alternatives,
    selected_skill_has_no_offense,
)
from exilelens.items.more_info import build_more_info
from exilelens.items.primary_metric import resolve_primary_metric

pytestmark = pytest.mark.itemcheck

ZERO = {"CombinedDPS": 0.0, "TotalDPS": 0.0, "TotalDot": 0.0, "TotalEHP": 9582.5}


def _identity(name="Virtuous Barrier", skill_id="VirtuousBarrierPlayer", group=3):
    return {"main_skill_identity": {
        "skill_name": name, "skill_id": skill_id, "index": group, "stat_set": name,
        "damage_owner": "PLAYER", "output_table": "mainOutput",
    }}


def _row(index, name, combined, *, owner="PLAYER", enabled=True):
    skill_id = name.replace(" ", "") + "Player"
    row = {
        "index": index, "skill_name": name, "skill_id": skill_id, "enabled": enabled, "slot_enabled": True,
        "damage_owner": owner, "stat_set": name, "stat_set_key": f"{skill_id}:sole-set", "stat_set_count": 1,
        "stat_set_resolved": True, "part_key": f"{skill_id}:whole", "part_count": 0, "part_resolved": True,
        "source": "", "slot": "", "actor_id": "" if owner == "PLAYER" else "minion", "actor_skill": "",
        "gems": [name], "output_table": "mainOutput" if owner == "PLAYER" else "mainOutput.Minion",
        "calculation_mode": "DIRECT", "show_average": False,
    }
    if owner == "MINION":
        row["output"] = {"CombinedDPS": 0, "Minion": {"CombinedDPS": combined, "TotalDPS": combined}}
    else:
        row["output"] = {"CombinedDPS": combined, "TotalDPS": combined, "TotalDot": 0}
    return row


def _primary(metrics=ZERO, **identity):
    return resolve_primary_metric(_identity(**identity), metrics)


# ------------------------------------------------------------------ trigger


def test_zero_offense_selected_skill_is_detected() -> None:
    assert selected_skill_has_no_offense(_primary(), ZERO) is True


def test_a_skill_with_calculated_offense_is_not_diagnosed() -> None:
    metrics = {"CombinedDPS": 2191.0, "TotalDPS": 2191.0, "TotalDot": 0.0}
    primary = _primary(metrics, name="Voltaic Barrier", skill_id="VoltaicBarrierPlayer", group=9)
    assert selected_skill_has_no_offense(primary, metrics) is False
    assert build_main_skill_diagnostic(primary, metrics, {"groups": [_row(1, "Other", 5000.0)]}) is None


def test_mixed_ambiguous_output_is_not_a_no_offense_skill() -> None:
    metrics = {"CombinedDPS": 1000.0, "TotalDPS": 100.0, "TotalDot": 300.0, "IgniteDPS": 600.0}
    primary = _primary(metrics)
    assert selected_skill_has_no_offense(primary, metrics) is False


# ------------------------------------------------------------------ alternatives


def test_alternatives_are_only_calculated_skills_in_pob_group_order() -> None:
    rows = [
        _row(1, "Crossbow Shot", 3043.6),
        _row(2, "Mace Strike", 0.0),                     # PoB calculated nothing (weapon not equipped)
        _row(3, "Virtuous Barrier", 0.0),                # the selected skill itself
        _row(9, "Voltaic Barrier", 2191.0),
        _row(10, "Disabled Skill", 900.0, enabled=False),  # not enabled: never listed
    ]
    alternatives = calculated_alternatives(rows, main_index=3)
    assert [alt["name"] for alt in alternatives] == ["Crossbow Shot", "Voltaic Barrier"]
    assert [alt["group_index"] for alt in alternatives] == [1, 9]
    # Never ranked by damage: the larger number does not move first.
    assert alternatives[0]["value"] > alternatives[1]["value"] or alternatives[0]["group_index"] < alternatives[1]["group_index"]


def test_duplicate_names_are_labelled_with_their_pob_group() -> None:
    rows = [_row(1, "Kelari", 100.0), _row(16, "Kelari", 50.0), _row(4, "Skeletal Warrior", 90.0)]
    labels = {alt["group_index"]: alt["label"] for alt in calculated_alternatives(rows, main_index=2)}
    assert labels == {1: "Kelari (PoB group 1)", 4: "Skeletal Warrior", 16: "Kelari (PoB group 16)"}


def test_minion_owned_alternatives_carry_their_owner() -> None:
    rows = [_row(1, "Ruzhan", 61472.4, owner="MINION")]
    (alt,) = calculated_alternatives(rows, main_index=2)
    assert alt["owner"] == "MINION"
    assert alt["field"] == "Minion.CombinedDPS"


# ------------------------------------------------------------------ diagnostic payload


def test_diagnostic_identifies_the_selected_skill_and_never_switches_it() -> None:
    report = {"groups": [_row(3, "Virtuous Barrier", 0.0), _row(9, "Voltaic Barrier", 2191.0)]}
    diagnostic = build_main_skill_diagnostic(_primary(), ZERO, report, context="MAP", skill_group_count=13)
    assert diagnostic["code"] == REASON_CODE
    assert diagnostic["selected"]["name"] == "Virtuous Barrier"
    assert diagnostic["selected"]["group_index"] == 3
    assert diagnostic["selected"]["context"] == "MAP"
    assert diagnostic["auto_switched"] is False
    assert diagnostic["alternatives_status"] == ALT_AVAILABLE
    assert [alt["name"] for alt in diagnostic["alternatives"]] == ["Voltaic Barrier"]
    assert len(diagnostic["recovery_steps"]) == 3
    # Neutral wording: a zero-damage buff is not called a wrong selection.
    text = (diagnostic["summary"] + diagnostic["explanation"]).lower()
    assert "wrong" not in text and "incorrect" not in text and "mistake" not in text


def test_diagnostic_states_when_no_other_skill_is_calculated_or_report_missing() -> None:
    none = build_main_skill_diagnostic(_primary(), ZERO, {"groups": [_row(3, "Virtuous Barrier", 0.0)]})
    assert none["alternatives_status"] == ALT_NONE and none["alternatives"] == []
    unread = build_main_skill_diagnostic(_primary(), ZERO, None, skill_group_count=40)
    assert unread["alternatives_status"] == ALT_NOT_ASSESSED
    assert "40" in unread["alternatives_note"]


def test_alternatives_display_is_bounded_but_total_is_honest() -> None:
    rows = [_row(index, f"Skill {index}", 100.0 + index) for index in range(4, 15)]  # group 3 is the selected skill
    diagnostic = build_main_skill_diagnostic(_primary(), ZERO, {"groups": rows}, skill_group_count=12)
    assert len(diagnostic["alternatives"]) == MAX_ALTERNATIVES_SHOWN
    assert diagnostic["alternatives_total"] == 11


# ------------------------------------------------------------------ quality + presentation


def _comparison(diagnostic):
    metrics = {"CombinedDPS": 0.0, "TotalDPS": 0.0, "TotalEHP": 9000.0}
    return {
        "pob_slot": "Ring 1",
        "baseline": {"metrics": dict(metrics)},
        "candidate": {"metrics": {**metrics, "TotalEHP": 9500.0}, "item_present": True},
        "restore": {"pass": True},
        "main_skill_diagnostic": diagnostic,
    }


def test_main_skill_reason_leads_the_quality_reasons_and_stays_partial() -> None:
    diagnostic = build_main_skill_diagnostic(_primary(), ZERO, {"groups": [_row(9, "Voltaic Barrier", 2191.0)]})
    profile = {
        "primary_offense": {"current": 0.0, "candidate": 0.0, "delta_kind": "MISSING", "pob_field": "CombinedDPS",
                            "availability": "available"},
        "ehp": {"current": 9000.0, "candidate": 9500.0},
        "worst_max_hit": {"current": 1.0, "candidate": 1.0},
    }
    quality, reasons = assess_quality(_comparison(diagnostic), metric_profile=profile,
                                      resist={"elements": {}}, primary_confidence="low")
    assert quality == EvaluationQuality.PARTIAL
    assert reasons[0]["code"] == REASON_CODE
    assert "Virtuous Barrier" in reasons[0]["detail"]
    assert {"OFFENSE_MISSING", "PRIMARY_METRIC_LOW_CONFIDENCE"} <= {reason["code"] for reason in reasons}


def test_no_diagnostic_means_no_new_reason() -> None:
    profile = {
        "primary_offense": {"current": 100.0, "candidate": 110.0, "delta_kind": "MEASURED", "pob_field": "CombinedDPS",
                            "availability": "available", "percent_delta": 10.0, "absolute_delta": 10.0},
        "ehp": {"current": 9000.0, "candidate": 9500.0},
        "worst_max_hit": {"current": 1.0, "candidate": 1.0},
    }
    comparison = _comparison(None)
    comparison.pop("main_skill_diagnostic")
    _quality, reasons = assess_quality(comparison, metric_profile=profile, resist={"elements": {}})
    assert REASON_CODE not in {reason["code"] for reason in reasons}


def test_more_info_shows_the_main_skill_section_with_alternatives_and_recovery() -> None:
    diagnostic = build_main_skill_diagnostic(
        _primary(), ZERO, {"groups": [_row(1, "Crossbow Shot", 3043.6), _row(9, "Voltaic Barrier", 2191.0)]},
        context="MAP", skill_group_count=13,
    )
    outcome = {
        "verdict": "UNCERTAIN", "verdict_label": "UNCERTAIN", "evaluation_quality": "PARTIAL",
        "quality_label": "Partial evaluation", "evaluation_quality_reasons": [{"code": REASON_CODE, "detail": diagnostic["summary"]}],
        "main_skill_diagnostic": diagnostic,
        "item_impact": {"axes": {"DEFENSE": {"support": "MEASURED", "direction": "POSITIVE"}}},
        "guardrails_applied": [], "critical_tradeoffs": [], "resistances": [], "all_deltas": [], "score_contributors": [],
    }
    info = build_more_info({}, outcome=outcome)
    assert "main_skill" in info["section_ids"]
    assert info["section_ids"].index("main_skill") == info["section_ids"].index("verdict_header") + 1
    section = next(item for item in info["sections"] if item["id"] == "main_skill")
    text = "\n".join(section["lines"])
    assert "Selected in Path of Building: Virtuous Barrier (PoB group 3, MAP context)" in text
    lines = section["lines"]
    crossbow = next(line for line in lines if "Crossbow Shot" in line)
    assert crossbow.startswith("• Crossbow Shot") and "PoB TotalDPS 3044" in crossbow
    assert any(line.startswith("• Voltaic Barrier") and "2191" in line for line in lines)
    assert "1. In Path of Building, select the skill you want evaluated" in text
    assert "ExileLens does not change your selected skill." in text
    assert "Defensive changes below are still measured." in text


def test_more_info_is_unchanged_for_a_normal_outcome() -> None:
    outcome = {
        "verdict": "SIDEGRADE", "verdict_label": "SIDEGRADE", "evaluation_quality": "FULL", "quality_label": "",
        "guardrails_applied": [], "critical_tradeoffs": [], "resistances": [], "all_deltas": [], "score_contributors": [],
    }
    assert "main_skill" not in build_more_info({}, outcome=outcome)["section_ids"]
