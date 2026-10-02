"""R1 build-aware Item Check context: cached Build Intelligence explains, the direct PoB result decides."""

from __future__ import annotations

import copy
import json

import pytest

from exilelens.analysis.identity import AnalysisBaseline
from exilelens.analysis.priorities import build_priorities
from exilelens.items import build_context as bc
from exilelens.items.build_context import (
    AVAILABLE,
    NO_SIGNAL,
    NOT_ANALYZED,
    STALE,
    build_item_context,
    compact_lines,
    detail_lines,
    intelligence_status,
    item_stat_totals,
    snapshot_intelligence,
)
from exilelens.items.compact_tooltip import MAX_REASONS, apply_compact_tooltip
from exilelens.items.more_info import build_more_info
from exilelens.items.why_explanation import build_why_explanation
from tests.test_m2_3_deterministic_why import _delta, _outcome
from tests.test_m5_3_build_priorities import BASELINE, PROBES, _probe, _result

pytestmark = pytest.mark.itemcheck

SLOT = "Ring 1"
CURRENT = AnalysisBaseline(**BASELINE)
FIRE_NEED = {"code": "RES_CAP_MISSING", "severity": "critical", "metric": "fire_res", "deficit": 17.0}

PLAIN_RING = "Rarity: RARE\nOld Loop\nRuby Ring\n--------\n+30 to maximum Life\n"
CASTER_RING = (
    "Item Class: Rings\nRarity: Rare\nGale Band\nSapphire Ring\n--------\nItem Level: 80\n--------\n"
    "+2 to Level of all Spell Skills\n24% increased Cast Speed\n+30 to maximum Life\n"
)


def _snapshot(probes=PROBES, **kwargs):
    analysis = _result(probes, **kwargs)
    analysis["build_priorities"] = build_priorities(analysis)
    return snapshot_intelligence(analysis)


def _item_result(outcome, *, candidate=CASTER_RING, replaced=PLAIN_RING, slot=SLOT):
    outcome = {**outcome, "replacement_slot": slot}
    comparison = {"pob_slot": slot, "evaluation_outcome": outcome, "baseline_item": {"raw": replaced, "empty": not replaced}}
    return {
        "raw_input": {"raw_text": candidate},
        "recommendation": {"pob_slot": slot, "baseline": {"fingerprint_hash": "hash1"}, "evaluation_outcome": outcome},
        "slot_comparisons": [comparison],
    }


def _context(result, snapshot=None, current=CURRENT):
    before = copy.deepcopy(result)
    context = build_item_context(result, snapshot, status=intelligence_status(snapshot, current))
    assert result == before  # the direct evaluation (verdict, score, deltas) is read, never changed
    return context


def _codes(context, slot=SLOT):
    return bc.note_codes(context["slots"][slot])


def _texts(context, slot=SLOT):
    return [note["text"] for note in context["slots"][slot]]


def _res_row(element, state, current, candidate, cap=75.0):
    return {"element": element, "state": state, "current": current, "candidate": candidate, "cap_current": cap, "cap_candidate": cap,
            "deficit_current": max(0.0, cap - current), "deficit_candidate": max(0.0, cap - candidate)}


UPGRADE = _outcome("MEANINGFUL_UPGRADE", [_delta("primary_offense", 7.2)])


# ------------------------------------------------------------------ item stat reading


def test_item_stats_are_read_from_game_text_and_pob_text_alike() -> None:
    assert item_stat_totals(CASTER_RING) == {"Spell Skill Levels": 2.0, "Cast Speed": 24.0, "Life": 30.0}
    pob = "{tags:life}{range:0.5}+(70-80) to maximum Life\n{crafted}12% increased Cast Speed\n+85(80-91) to maximum Energy Shield (implicit)\n"
    assert item_stat_totals(pob) == {"Life": 75.0, "Cast Speed": 12.0, "Energy Shield": 85.0}
    assert item_stat_totals("+12 to Strength and Intelligence\n+5 to all Attributes\nMinions have 10% increased Cast Speed\n") == {
        "Strength": 17.0, "Intelligence": 17.0, "Dexterity": 5.0, "Minion Cast Speed": 10.0}
    assert item_stat_totals("Energy Shield: 120\n30% increased Energy Shield\nAdds 3 to 5 Fire Damage\n") == {}  # related, not the tested stat


# ------------------------------------------------------------------- required fixtures


def test_01_strong_relevant_stat_gain_is_explained_after_the_measured_result() -> None:
    context = _context(_item_result(UPGRADE), _snapshot())
    assert context["status"] == AVAILABLE and context["uses_build_intelligence"] is True
    assert _codes(context) == ["HIGH_RESPONSE_GAIN", "HIGH_RESPONSE_GAIN"]
    assert _texts(context)[0] == "Adds Spell Skill Levels (+2) — your build's strongest measured damage response."
    assert _texts(context)[1] == "Adds Cast Speed (24%) — one of your build's strongest measured damage responses."
    assert context["slots"][SLOT][0]["detail"] == "Tested +1 to Level of all Spell Skills → Damage +8.7%."
    for text in _texts(context):  # sensitivity describes the stat; it never claims the item's value
        assert "best" not in text.lower() and "upgrade" not in text.lower()


def test_02_strong_relevant_stat_loss() -> None:
    downgrade = _outcome("MINOR_DOWNGRADE", [_delta("primary_offense", -6.0)])
    context = _context(_item_result(downgrade, candidate=PLAIN_RING, replaced=CASTER_RING), _snapshot())
    assert _codes(context) == ["HIGH_RESPONSE_LOSS", "HIGH_RESPONSE_LOSS"]
    assert _texts(context)[0] == "Loses Spell Skill Levels (+2) — your build's strongest measured damage response."
    less = _context(_item_result(downgrade, candidate=CASTER_RING.replace("24%", "8%"), replaced=CASTER_RING), _snapshot())
    assert _texts(less) == ["Less Cast Speed than your current item (8% vs 24%) — one of your build's strongest measured damage responses."]


def test_03_resistance_cap_break_states_the_actual_values() -> None:
    outcome = _outcome("SIDEGRADE", [_delta("primary_offense", 9.0)], resistances=[_res_row("fire", "CAP_LOST", 75.0, 58.0)])
    context = _context(_item_result(outcome, candidate=PLAIN_RING, replaced=PLAIN_RING), None)
    assert context["status"] == NOT_ANALYZED and _codes(context) == ["RESISTANCE_CAP_BROKEN"]
    assert _texts(context) == ["Fire Resistance falls from 75% to 58%, below the 75% cap."]
    assert context["slots"][SLOT][0]["source"] == "direct"


def test_04_resistance_cap_restoration_resolves_a_fix_first_issue_when_analysis_listed_it() -> None:
    outcome = _outcome("MEANINGFUL_UPGRADE", [_delta("ehp", 4.0)], resistances=[_res_row("fire", "CAP_REACHED", 58.0, 75.0)])
    result = _item_result(outcome, candidate=PLAIN_RING, replaced=PLAIN_RING)
    with_analysis = _context(result, _snapshot(needs=[FIRE_NEED]))
    assert _codes(with_analysis) == ["FIX_FIRST_RESOLVED"]
    assert _texts(with_analysis) == ["Fixes a Fix First issue: Fire Resistance reaches the cap (58% → 75%)."]
    without = _context(result, None)
    assert _codes(without) == ["RESISTANCE_CAP_RESTORED"] and _texts(without) == ["Fire Resistance reaches the cap (58% → 75%)."]
    closer = _outcome("MINOR_UPGRADE", [_delta("ehp", 2.0)], resistances=[_res_row("fire", "BELOW_CAP_IMPROVED", 58.0, 70.0)])
    assert _codes(_context(_item_result(closer, candidate=PLAIN_RING, replaced=PLAIN_RING), _snapshot(needs=[FIRE_NEED]))) == ["FIX_FIRST_PROGRESS"]


def test_05_attribute_requirement_break_uses_pob_facts_only() -> None:
    outcome = _outcome("NOT_VIABLE", [_delta("primary_offense", 12.0)])
    outcome["baseline_metrics"] = {"Str": 130.0, "ReqStr": 120.0, "Dex": 80.0, "ReqDex": 60.0}
    outcome["candidate_metrics"] = {"Str": 104.0, "ReqStr": 120.0, "Dex": 80.0, "ReqDex": 60.0}
    context = _context(_item_result(outcome, candidate=PLAIN_RING, replaced=PLAIN_RING), _snapshot())
    assert _codes(context) == ["ATTRIBUTE_REQUIREMENT_BROKEN"]
    assert _texts(context) == ["Strength no longer meets what your gear and gems need (requires 120 Strength, current 104)."]
    outcome["candidate_metrics"] = {"Str": 125.0, "ReqStr": 120.0}  # still met: nothing is guessed about future requirements
    assert _codes(_context(_item_result(outcome, candidate=PLAIN_RING, replaced=PLAIN_RING), _snapshot())) == []


def test_06_meaningful_ehp_max_hit_trade_off_is_one_line_and_small_splits_are_silent() -> None:
    split = _outcome("SIDEGRADE", [_delta("ehp", 6.0), _delta("worst_max_hit", -5.0)])
    context = _context(_item_result(split, candidate=PLAIN_RING, replaced=PLAIN_RING), None)
    assert _codes(context) == ["MAX_HIT_TRADEOFF"]
    assert _texts(context) == ["EHP rises 6.0% but Max Hit falls 5.0%: tougher against sustained damage, weaker against one big hit."]
    damage = _outcome("MINOR_UPGRADE", [_delta("primary_offense", 9.0), _delta("worst_max_hit", -4.0)])
    assert "Damage rises 9.0% but Max Hit falls 4.0%" in _texts(_context(_item_result(damage, candidate=PLAIN_RING, replaced=PLAIN_RING), None))[0]
    small = _outcome("SIDEGRADE", [_delta("ehp", 2.0), _delta("worst_max_hit", -1.5), _delta("mana", -0.4)])
    assert _codes(_context(_item_result(small, candidate=PLAIN_RING, replaced=PLAIN_RING), None)) == []


def test_07_multi_axis_gain_keeps_every_measured_axis() -> None:
    ring = "Rarity: RARE\nMind Loop\nRuby Ring\n--------\n+25 to Intelligence\n"
    context = _context(_item_result(UPGRADE, candidate=ring, replaced=PLAIN_RING), _snapshot())
    assert "MULTI_AXIS_GAIN" in _codes(context)
    note = next(n for n in context["slots"][SLOT] if n["code"] == "MULTI_AXIS_GAIN")
    assert note["text"] == "Adds Intelligence (+25) — a multi-impact stat for your build."
    assert note["detail"] == "Tested +20 to Intelligence → Damage +2.1% · ES +4.3% · Mana +3.0%."


def test_08_no_build_intelligence_keeps_the_direct_explanation_and_adds_no_sensitivity_claim() -> None:
    result = _item_result(UPGRADE)
    context = _context(result, None)
    assert context["status"] == NOT_ANALYZED and context["uses_build_intelligence"] is False
    assert _codes(context) == [] and context["hint"] and not context["basis"]
    assert compact_lines(context, SLOT) == []
    assert detail_lines(context, SLOT) == [bc.HINT_NOT_ANALYZED]  # More Info only says how to get build context


def test_09_stale_build_intelligence_is_never_used() -> None:
    snapshot = _snapshot()
    for change in ({"fingerprint": "other"}, {"generation": 9}, {"loadout": "M"}, {"item_set": "2"}, {"context": "BOSS"}, {"build_path": "other.xml"}):
        current = AnalysisBaseline(**{**BASELINE, **change})
        assert intelligence_status(snapshot, current) == STALE
        context = _context(_item_result(UPGRADE), snapshot, current)
        assert context["status"] == STALE and _codes(context) == [] and not context["uses_build_intelligence"]
        assert "strongest measured" not in json.dumps(context["slots"]) and not context["basis"]


def test_10_compatible_cached_build_intelligence_is_used_and_path_spelling_does_not_matter() -> None:
    snapshot = _snapshot()
    assert intelligence_status(snapshot, CURRENT) == AVAILABLE
    assert intelligence_status(snapshot, AnalysisBaseline(**{**BASELINE, "build_path": ".\\B.xml"})) == AVAILABLE
    context = _context(_item_result(UPGRADE), snapshot)
    assert context["basis"] == bc.BASIS and not context["hint"]


def test_11_no_signal_or_unsupported_build_intelligence_adds_nothing() -> None:
    flat = _snapshot([_probe("CAST_SPEED", "Cast Speed", "10% increased Cast Speed", 10.0, status="NO_SIGNAL"),
                      _probe("SPELL_SKILL_LEVELS", "Spell Skill Levels", "+1 to Level of all Spell Skills", 1.0, status="REJECTED")])
    assert intelligence_status(flat, CURRENT) == NO_SIGNAL
    context = _context(_item_result(UPGRADE), flat)
    assert context["status"] == NO_SIGNAL and _codes(context) == [] and not context["hint"]
    limited = _context(_item_result(UPGRADE), _snapshot(confidence="LOW"))  # low-confidence damage never characterises an item
    assert "HIGH_RESPONSE_GAIN" not in _codes(limited)


def test_12_profile_only_change_keeps_the_context_valid() -> None:
    snapshot = _snapshot(profile="BALANCED")
    mapping = AnalysisBaseline(**{**BASELINE, "profile": "MAPPING"})
    assert intelligence_status(snapshot, mapping) == AVAILABLE
    assert _context(_item_result(UPGRADE), snapshot, mapping) == _context(_item_result(UPGRADE), snapshot, CURRENT)
    assert _context(_item_result(UPGRADE), snapshot) == _context(_item_result(UPGRADE), _snapshot(profile="MAPPING"))


# -------------------------------------------------------- resource semantics (M5.5)


def test_one_use_affordability_is_surfaced_and_continuous_sustain_is_not() -> None:
    blocked = _outcome("MINOR_UPGRADE", [_delta("primary_offense", 6.0)])
    blocked["baseline_metrics"] = {"ManaUnreserved": 120.0, "ManaCost": 90.0, "ManaPerSecondCost": 300.0, "ManaRegenRecovery": 20.0}
    blocked["candidate_metrics"] = {"ManaUnreserved": 70.0, "ManaCost": 90.0, "ManaPerSecondCost": 300.0, "ManaRegenRecovery": 20.0}
    context = _context(_item_result(blocked, candidate=PLAIN_RING, replaced=PLAIN_RING), None)
    assert _texts(context) == ["Unreserved Mana (70) no longer covers one use of your main skill (90)."]
    sustain_only = _outcome("MINOR_UPGRADE", [_delta("primary_offense", 6.0)])
    sustain_only["baseline_metrics"] = {"ManaUnreserved": 500.0, "ManaCost": 90.0, "ManaPerSecondCost": 10.0, "ManaRegenRecovery": 20.0}
    sustain_only["candidate_metrics"] = {"ManaUnreserved": 500.0, "ManaCost": 90.0, "ManaPerSecondCost": 300.0, "ManaRegenRecovery": 20.0}
    assert _codes(_context(_item_result(sustain_only, candidate=PLAIN_RING, replaced=PLAIN_RING), _snapshot())) == []


# ------------------------------------------------------------------- surface wiring


def _model(outcome, context):
    return {"evaluation_outcome": {**outcome, "replacement_slot": SLOT}, "rows": [], "warning_groups": [], "build_context": context}


def test_compact_tooltip_puts_build_context_below_the_measured_why_and_caps_it() -> None:
    outcome = _outcome("MEANINGFUL_UPGRADE", [_delta("primary_offense", 7.2)], resistances=[_res_row("fire", "CAP_REACHED", 58.0, 75.0)])
    context = _context(_item_result(outcome), _snapshot(needs=[FIRE_NEED]))
    model = _model(outcome, context)
    apply_compact_tooltip(model)
    # The direct measured result leads and is unchanged; context never takes one of its slots.
    assert {line["metric"] for line in model["primary_reasons"]} == {"fire_res", "primary_offense"}
    assert len(model["primary_reasons"]) <= MAX_REASONS
    assert [line["code"] for line in model["build_context_lines"]] == ["HIGH_RESPONSE_GAIN", "HIGH_RESPONSE_GAIN"]
    assert len(model["build_context_lines"]) == bc.MAX_COMPACT_LINES < len(context["slots"][SLOT])
    # The cap the measured Why already names is not repeated as a context line.
    assert bc.note_codes(context["slots"][SLOT])[-1] == "FIX_FIRST_RESOLVED"
    assert all("Fire Resistance" not in line["text"] for line in model["build_context_lines"])
    only_fix = _context(_item_result(outcome, candidate=PLAIN_RING, replaced=PLAIN_RING), _snapshot(needs=[FIRE_NEED]))
    assert [line["code"] for line in compact_lines(only_fix, SLOT)] == ["FIX_FIRST_RESOLVED"]
    assert compact_lines(only_fix, SLOT, claimed=["fire_res"]) == []
    bare = _model(outcome, {})
    apply_compact_tooltip(bare)
    assert bare["build_context_lines"] == [] and bare["primary_reasons"] == model["primary_reasons"]


def test_tooltip_panel_paints_build_context_after_the_measured_reasons() -> None:
    from PySide6.QtWidgets import QApplication

    from exilelens.ui.overlay_presentation import ItemOverlayPanel

    QApplication.instance() or QApplication([])
    model = _model(UPGRADE, _context(_item_result(UPGRADE), _snapshot()))
    apply_compact_tooltip(model)
    panel = ItemOverlayPanel()
    panel.render_presentation(model)
    painted = [widget.text() for widget in panel._why_widgets]
    assert painted[0].startswith("• Damage improves by 7.2%")  # the measured result is read first
    assert painted[1:] == [
        "• Adds Spell Skill Levels (+2) — your build's strongest measured damage response.",
        "• Adds Cast Speed (24%) — one of your build's strongest measured damage responses.",
    ]
    plain = _model(UPGRADE, {})
    apply_compact_tooltip(plain)
    panel.render_presentation(plain)
    assert [widget.text() for widget in panel._why_widgets] == painted[:1]  # no analysis: the tooltip is exactly as before


def test_compact_tooltip_does_not_repeat_cap_breaks_or_blockers_it_already_states() -> None:
    outcome = _outcome("SIDEGRADE", [_delta("primary_offense", 9.0)], resistances=[_res_row("fire", "CAP_LOST", 75.0, 58.0)])
    context = _context(_item_result(outcome, candidate=PLAIN_RING, replaced=PLAIN_RING), _snapshot())
    assert compact_lines(context, SLOT) == []
    assert detail_lines(context, SLOT) == ["Fire Resistance falls from 75% to 58%, below the 75% cap."]


def test_more_info_adds_a_for_your_build_section_after_why_and_states_the_source() -> None:
    context = _context(_item_result(UPGRADE), _snapshot())
    info = build_more_info(_model(UPGRADE, context))
    ids = info["section_ids"]
    assert ids.index("build_context") == ids.index("why_verdict") + 1
    section = next(s for s in info["sections"] if s["id"] == "build_context")
    assert section["title"] == "FOR YOUR BUILD"
    assert section["lines"][0].endswith("Tested +1 to Level of all Spell Skills → Damage +8.7%.")
    assert section["lines"][-1] == bc.BASIS and "testing this exact item" in bc.BASIS
    assert "build_context" not in build_more_info(_model(UPGRADE, {}))["section_ids"]


def test_verdict_score_and_why_are_identical_with_and_without_build_context() -> None:
    outcome = _outcome("MINOR_UPGRADE", [_delta("primary_offense", 8.4), _delta("ehp", -4.1)])
    result = _item_result(outcome)
    before = copy.deepcopy(result)
    why = build_why_explanation(outcome)
    for snapshot in (None, _snapshot(), _snapshot(needs=[FIRE_NEED])):
        build_item_context(result, snapshot, status=intelligence_status(snapshot, CURRENT))
        assert result == before and build_why_explanation(outcome) == why
    with_context, without = _model(outcome, _context(result, _snapshot())), _model(outcome, {})
    apply_compact_tooltip(with_context)
    apply_compact_tooltip(without)
    for key in ("verdict_headline", "score_value", "impact_rows", "primary_reasons", "primary_reasons_title", "critical_notes"):
        assert with_context[key] == without[key]


def test_explanation_enrichment_needs_no_engine_and_player_text_has_no_internal_names() -> None:
    import inspect

    source = inspect.getsource(bc)
    for forbidden in ("evaluate_candidate", "analyze_build", "ProbeEngine", "run_probe", "analysis.pipeline", "analysis.probes", "get_metrics"):
        assert forbidden not in source
    assert "engine" not in inspect.signature(build_item_context).parameters
    context = _context(_item_result(UPGRADE, candidate=CASTER_RING + "+25 to Intelligence\n"), _snapshot(needs=[FIRE_NEED]))
    text = " ".join(detail_lines(context, SLOT) + [line["text"] for line in compact_lines(context, SLOT)])
    for internal in ("SPELL_SKILL_LEVELS", "CAST_SPEED", "probe", "hash1", "Build Value", "NO_SIGNAL", "MEASURED"):
        assert internal not in text
