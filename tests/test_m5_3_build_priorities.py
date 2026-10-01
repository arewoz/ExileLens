"""M5.3 Build Priorities: measured, profile independent, never one universal score."""

from __future__ import annotations

import json
import os
import sys

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from exilelens.analysis.identity import AnalysisBaseline
from exilelens.analysis.pipeline import rescore_analysis
from exilelens.analysis.priorities import MAX_ROWS_PER_LANE, build_priorities, format_priorities, is_priorities_stale
from exilelens.analysis.sensitivity import build_sensitivity

pytestmark = pytest.mark.itemcheck

BASELINE = {
    "build_path": "b.xml", "build_name": "T", "loadout": "L", "item_set": "1", "context": "MAP",
    "profile": "BALANCED", "generation": 2, "fingerprint": "hash1",
}


def _entry(abs_, pct=None):
    return {"availability": "available", "absolute_delta": abs_, "percent_delta": pct}


def _probe(probe_id, label, line, magnitude, *, family="offense", status="ok", score=5.0, **axes):
    probe = {
        "probe_id": probe_id, "status": status, "family": family, "display_name": label, "magnitude": magnitude,
        "unit": "percent", "line": line, "confidence": "HIGH",
    }
    if status == "ok":
        mapping = {"offense": "primary_offense", "ehp": "ehp", "max_hit": "worst_max_hit", "es": "energy_shield", "life": "life", "mana": "mana", "movement": "movement_speed"}
        probe["metric_profile"] = {mapping[k]: _entry(v, v) for k, v in axes.items()}
        probe.update(score_delta=score, marginal_value_per_unit=score / magnitude, breakpoints=[], warnings=[])
    return probe


def _result(probes, *, profile="BALANCED", confidence="HIGH", needs=(), fingerprint_extra=None):
    result = {
        "baseline": {**BASELINE, "profile": profile},
        "audit": {"primary_field": "CombinedDPS", "primary_confidence": confidence.lower()},
        "build_fingerprint": {"offense": {"owner": "PLAYER", "metric": "CombinedDPS", "scope": "PRIMARY_SKILL", "provenance": "POB_PRIMARY_SKILL", "confidence": confidence}, **(fingerprint_extra or {})},
        "global_probes": list(probes),
        "needs": list(needs),
    }
    result["build_sensitivity"] = build_sensitivity(result)
    return result


PROBES = [
    _probe("CAST_SPEED", "Cast Speed", "10% increased Cast Speed", 10.0, offense=6.1),
    _probe("SPELL_DAMAGE", "Spell Damage", "20% increased Spell Damage", 20.0, offense=3.5),
    _probe("SPELL_SKILL_LEVELS", "Spell Skill Levels", "+1 to Level of all Spell Skills", 1.0, offense=8.7),
    _probe("ENERGY_SHIELD", "Energy Shield", "+50 to maximum Energy Shield", 50.0, family="defense", ehp=3.1, max_hit=2.0, es=1.0),
    _probe("LIFE", "Life", "+50 to maximum Life", 50.0, family="defense", ehp=2.4, life=2.4),
    _probe("INTELLIGENCE", "Intelligence", "+20 to Intelligence", 20.0, family="utility", offense=2.1, es=4.3, mana=3.0),
    _probe("MOVEMENT_SPEED", "Movement Speed", "10% increased Movement Speed", 10.0, family="utility", movement=10.0),
    _probe("CRIT_CHANCE", "Crit Chance", "5% increased Critical Hit Chance", 5.0, status="NO_SIGNAL"),
    _probe("ARMOUR", "Armour", "+200 to Armour", 200.0, status="UNSUPPORTED_PROBE"),
]


def test_offense_lane_orders_by_measured_offense_at_the_shown_tested_increment() -> None:
    pri = build_priorities(_result(PROBES))
    assert pri["schema_version"] == 1
    assert [(r["tested_change"], r["response_percent"]) for r in pri["offense"]] == [
        ("+1 to Level of all Spell Skills", 8.7), ("10% increased Cast Speed", 6.1), ("20% increased Spell Damage", 3.5)]
    assert all(r["evidence"] == "MEASURED" and r["tested_change"] for r in pri["offense"])


def test_ehp_and_max_hit_are_separate_rankings_with_secondary_detail() -> None:
    pri = build_priorities(_result(PROBES))
    assert [r["label"] for r in pri["ehp"]][:2] == ["Energy Shield", "Life"]
    assert [r["label"] for r in pri["max_hit"]] == ["Energy Shield"]  # a probe may appear in one lane and not the other
    assert pri["ehp"][0]["response_percent"] == 3.1 and pri["max_hit"][0]["response_percent"] == 2.0
    assert pri["ehp"][0]["also"]["ES"] == 1.0


def test_multi_axis_row_keeps_every_measured_axis_and_defence_probes_are_not_multi_axis() -> None:
    pri = build_priorities(_result(PROBES))
    assert [r["label"] for r in pri["multi_axis"]] == ["Intelligence"]
    assert pri["multi_axis"][0]["responses"] == {"Damage": 2.1, "ES": 4.3, "Mana": 3.0}
    assert "Energy Shield" not in [r["label"] for r in pri["multi_axis"]]
    assert [r["label"] for r in pri["mobility"]] == ["Movement Speed"]


def test_no_universal_scalar_and_no_score_inputs() -> None:
    pri = build_priorities(_result(PROBES))
    text = json.dumps(pri)
    for forbidden in ("score", "build_value", "marginal", "priority_score", "rank", "profile_dependent", "probe_id"):
        assert forbidden not in text
    # Reordering the profile-dependent scores must not change anything.
    flipped = [{**p, "score_delta": 100.0 - i, "marginal_value_per_unit": float(i)} if p["status"] == "ok" else p for i, p in enumerate(PROBES)]
    assert build_priorities(_result(flipped)) == pri


def test_balanced_and_mapping_produce_identical_priorities() -> None:
    a = build_priorities(_result(PROBES, profile="BALANCED"))
    b = build_priorities(_result([{**p, "score_delta": 99.0} if p["status"] == "ok" else p for p in PROBES], profile="MAPPING"))
    assert a == b and "profile" not in a


def test_resistance_breakpoint_goes_to_fix_first_not_to_a_lane() -> None:
    res = _probe("FIRE_RES", "Fire Resistance", "+20% to Fire Resistance", 20.0, family="defense", ehp=4.0)
    res["breakpoints"] = [{"code": "CAP_REACHED", "element": "fire"}]
    exact = {**_probe("FIRE_RES", "Fire Resistance", "+17% to Fire Resistance", 17.0, family="defense", ehp=3.0), "breakpoint_exact": True, "CAP_REACHED_AT": 17}
    need = {"code": "RES_CAP_MISSING", "severity": "critical", "metric": "fire_res", "deficit": 17.0}
    pri = build_priorities(_result([res, exact, *PROBES], needs=[need, {"code": "OFFENSE_OPPORTUNITY", "severity": "medium", "metric": "CAST_SPEED"}]))
    assert pri["fix_first"] == [{"kind": "RESISTANCE_CAP", "title": "Fire Resistance", "detail": "+17% reaches cap", "severity": "critical", "source": "sensitivity"}]
    assert "Fire Resistance" not in [r["label"] for r in pri["ehp"]]  # no per-point resistance ranking, no score-based opportunity needs


def test_resource_pressure_and_attribute_deficit_are_fix_first_from_existing_evidence() -> None:
    needs = [{"code": "RESOURCE_PRESSURE", "severity": "medium", "metric": "mana", "deficit": 5.0},
             {"code": "LOW_CHAOS_RES", "severity": "high", "metric": "chaos_res", "deficit": 40.0}]
    extra = {"requirements": {"dexterity": {"state": {"value": "DEFICIT"}, "margin": {"value": -12.0}}, "strength": {"state": {"value": "MET"}, "margin": {"value": 5.0}}}}
    rows = build_priorities(_result(PROBES, needs=needs, fingerprint_extra=extra))["fix_first"]
    assert [r["kind"] for r in rows] == ["ATTRIBUTE_REQUIREMENT", "RESISTANCE_CAP", "RESOURCE"]  # severity, then source order
    assert rows[0]["detail"] == "12 short of the highest requirement"


def test_no_signal_and_failures_are_coverage_not_low_priority() -> None:
    pri = build_priorities(_result(PROBES))
    assert pri["coverage"]["no_signal"] == ["Crit Chance"] and pri["coverage"]["not_established"] == ["Armour"]
    assert "Crit Chance" not in json.dumps({k: v for k, v in pri.items() if k != "coverage"})
    assert pri["coverage"]["counts"]["UNSUPPORTED"] == 1 and pri["coverage"]["signals_considered"] == 7
    assert pri["coverage"]["basis"] == "Based on stats ExileLens tested against this PoB build."


def test_low_confidence_offense_is_marked_and_other_lanes_still_show() -> None:
    pri = build_priorities(_result(PROBES, confidence="LOW"))
    assert pri["offense_limited_confidence"] is True and pri["offense"] and pri["ehp"]
    assert all(r["confidence"] == "LOW" for r in pri["offense"])
    assert "DAMAGE — limited confidence" in format_priorities(pri)


def test_unavailable_axes_are_not_zero_and_lanes_are_capped() -> None:
    many = [_probe(f"P{i}", f"Stat {i}", f"+{i} stat", 10.0, offense=1.0 + i) for i in range(6)]
    pri = build_priorities(_result(many + [_probe("Q", "Odd", "+1 odd", 1.0, ehp=0.0)]))
    assert len(pri["offense"]) == MAX_ROWS_PER_LANE and pri["ehp"] == [] and pri["max_hit"] == []
    assert "ehp" in pri["coverage"]["lanes_without_response"]
    assert "No measured response" not in format_priorities(pri)
    assert "No measured response" in format_priorities(build_priorities(_result([])))


def test_player_text_has_tested_change_and_no_internal_names() -> None:
    text = format_priorities(build_priorities(_result(PROBES)))
    assert "BUILD PRIORITIES" in text and "+1 to Level of all Spell Skills" in text and "+8.7%" in text
    assert "MULTI-IMPACT" in text and "Based on stats ExileLens tested" in text
    for internal in ("SPELL_SKILL_LEVELS", "hash1", "Build Value", "score_delta", "marginal"):
        assert internal not in text


def test_baseline_identity_invalidation_but_not_profile() -> None:
    pri = build_priorities(_result(PROBES))
    assert not is_priorities_stale(pri, AnalysisBaseline(**BASELINE))
    assert not is_priorities_stale(pri, AnalysisBaseline(**{**BASELINE, "profile": "MAPPING"}))
    for change in ({"fingerprint": "x"}, {"generation": 9}, {"loadout": "M"}, {"item_set": "2"}, {"context": "BOSS"}, {"build_path": "o"}):
        assert is_priorities_stale(pri, AnalysisBaseline(**{**BASELINE, **change}))


def test_rescore_rebuilds_priorities_without_any_engine() -> None:
    result = _result(PROBES)
    result["build_priorities"] = build_priorities(result)
    result["slots"] = []
    rescored = rescore_analysis(result, "MAPPING")  # no engine exists in this call: it can only be pure
    assert rescored["build_priorities"] == result["build_priorities"]
    assert rescored["baseline"]["profile"] == "MAPPING"


def test_analysis_window_shows_priorities_first_and_keeps_slot_view() -> None:
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication

    from exilelens.ui.analysis_window import AnalysisWindow

    class Controller(QObject):
        analysis_started = Signal(int)
        analysis_progress = Signal(object)
        analysis_finished = Signal(object)
        analysis_error = Signal(str)
        analysis_stale = Signal()

    QApplication.instance() or QApplication([])
    window = AnalysisWindow(Controller())
    result = _result(PROBES)
    result["build_priorities"] = build_priorities(result)
    result["performance"] = {"elapsed_ms": 1000, "pob_recalcs": 0, "cache": {}}
    result["slots"] = [{
        "product_slot": "RING", "pob_slot": "Ring 1", "current_item": {"name": "R", "base_name": "B"}, "probes": [],
        "opportunity": {"band": "LOW", "score": 12.0, "drivers": []}, "search_intent": {"slot": "RING"},
    }]
    window.show_result(result)
    assert window._list.count() == 2 and window._list.item(0).text() == "BUILD PRIORITIES"
    assert window._list.currentRow() == 0 and "FIX FIRST" not in window._detail.toPlainText()
    assert "+1 to Level of all Spell Skills" in window._detail.toPlainText()
    window._list.setCurrentRow(1)
    assert "CURRENT ITEM" in window._detail.toPlainText() and window._current_intent() == {"slot": "RING"}
