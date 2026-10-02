"""R1.5 Item Check tie-in: cached, current action plan only; never an analysis on the hot path."""

from __future__ import annotations

from pathlib import Path

import pytest

from exilelens.analysis.actionable import build_actionable
from exilelens.items.build_context import AVAILABLE, NOT_ANALYZED, compact_lines, snapshot_intelligence
from tests.test_m2_3_deterministic_why import _delta, _outcome
from tests.test_r1_5_actionable import CHAOS_NEED, FIRE_NEED
from tests.test_r1_5_actionable import _analysis as actionable_analysis
from tests.test_r1_analyze_build_ui import _controller, _item_check_result, _matching_analysis
from tests.test_r1_item_build_context import CASTER_RING, PLAIN_RING, SLOT, _context, _item_result, _res_row

pytestmark = pytest.mark.itemcheck


def _snapshot(**kwargs):
    return snapshot_intelligence(actionable_analysis(**kwargs))


def test_item_that_fixes_the_current_number_one_priority_says_so() -> None:
    outcome = _outcome("MEANINGFUL_UPGRADE", [_delta("ehp", 4.0)], resistances=[_res_row("chaos", "CAP_REACHED", 42.0, 75.0)])
    snapshot = _snapshot(needs=[CHAOS_NEED], chaos=42.0)
    assert snapshot["actionable"]["action_plan"][0]["title"] == "Cap Chaos Resistance"
    context = _context(_item_result(outcome, candidate=PLAIN_RING, replaced=PLAIN_RING), snapshot)
    assert [line["text"] for line in compact_lines(context, SLOT)] == [
        "Fixes your current #1 priority: Chaos Resistance reaches the cap (42% → 75%)."]
    progress = _outcome("MINOR_UPGRADE", [_delta("ehp", 2.0)], resistances=[_res_row("chaos", "BELOW_CAP_IMPROVED", 42.0, 60.0)])
    closer = _context(_item_result(progress, candidate=PLAIN_RING, replaced=PLAIN_RING), snapshot)
    assert [line["text"] for line in compact_lines(closer, SLOT)] == ["Moves toward your current #1 priority: Chaos Resistance (42% → 60%)."]


def test_a_lower_priority_fix_is_not_called_number_one_and_priority_context_leads_broader_context() -> None:
    outcome = _outcome("MEANINGFUL_UPGRADE", [_delta("primary_offense", 7.0)], resistances=[_res_row("chaos", "CAP_REACHED", 42.0, 75.0)])
    snapshot = _snapshot(needs=[CHAOS_NEED, FIRE_NEED], fire=58.0, chaos=42.0)  # Fire (critical) is #1, Chaos is #2
    lines = [line["text"] for line in compact_lines(_context(_item_result(outcome, candidate=CASTER_RING, replaced=PLAIN_RING), snapshot), SLOT)]
    assert lines[0].startswith("Fixes a current priority: Chaos Resistance reaches the cap")
    assert lines[1] == "More Spell Skill Levels — your strongest measured damage response."  # a current top stat, after the priority


def test_losing_a_top_stat_is_referenced_without_a_second_number() -> None:
    outcome = _outcome("MINOR_DOWNGRADE", [_delta("primary_offense", -6.0)])
    lines = [line["text"] for line in compact_lines(_context(_item_result(outcome, candidate=PLAIN_RING, replaced=CASTER_RING), _snapshot()), SLOT)]
    assert lines == ["Less Spell Skill Levels — your strongest measured damage response.", "Less Cast Speed — among your strongest measured damage responses."]
    assert not any(ch.isdigit() for line in lines for ch in line)


def _with_actionable(result: dict) -> dict:
    result["actionable"] = build_actionable(result)
    return result


def test_journeys_no_analysis_cached_stale_and_reanalysis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller, scheduled = _controller(tmp_path, monkeypatch)
    try:
        # A: no Analyze Build -> normal Item Check, nothing scheduled.
        assert controller._item_check_build_context(_item_check_result())["status"] == NOT_ANALYZED and scheduled == []
        # B: Analyze Build finished for this baseline -> actionable context is available from the cache.
        first = _with_actionable(_matching_analysis(controller))
        controller._on_analysis_finished(41, first, None)
        assert controller._item_check_build_context(_item_check_result())["status"] == AVAILABLE
        assert controller._build_intelligence["actionable"]["action_plan"] == first["actionable"]["action_plan"]
        assert first["actionable"]["changes"] == {"comparable": False, "items": []}  # nothing to compare with yet
        # C: the baseline changes before re-analysis -> the old analysis is not used.
        controller._bump_baseline_generation()
        assert controller._build_intelligence is None
        assert controller._item_check_build_context(_item_check_result())["status"] == NOT_ANALYZED and scheduled == []
        # D: re-analysis of the changed build -> current again, and What Changed compares with the previous run.
        second = _matching_analysis(controller)
        second["needs"] = [{"code": "LOW_CHAOS_RES", "severity": "high", "metric": "chaos_res", "deficit": 30.0}]
        second["baseline"] = {**second["baseline"], "fingerprint": "item-check-fp-2"}
        from exilelens.analysis.priorities import build_priorities
        from exilelens.analysis.sensitivity import build_sensitivity

        second["build_sensitivity"] = build_sensitivity(second)
        second["build_priorities"] = build_priorities(second)
        _with_actionable(second)
        controller._on_analysis_finished(42, second, None)
        fresh = {"recommendation": {"pob_slot": "Ring 1", "baseline": {"fingerprint_hash": "item-check-fp-2"}}, "slot_comparisons": [], "raw_input": {}}
        assert controller._item_check_build_context(fresh)["status"] == AVAILABLE
        changes = second["actionable"]["changes"]
        assert changes["comparable"] is True and changes["items"][0]["kind"] == "ADDED"
        assert "Chaos Resistance is now a priority" in changes["items"][0]["text"]
        assert scheduled == []  # no step of any journey queued PoB work
    finally:
        controller.shutdown()


def test_another_build_starts_a_new_comparison_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller, _scheduled = _controller(tmp_path, monkeypatch)
    try:
        controller._on_analysis_finished(41, _with_actionable(_matching_analysis(controller)), None)
        other = _matching_analysis(controller)
        other["baseline"] = {**other["baseline"], "build_path": str(tmp_path / "another_build.xml"), "fingerprint": "x"}
        from exilelens.analysis.priorities import build_priorities
        from exilelens.analysis.sensitivity import build_sensitivity

        other["build_sensitivity"] = build_sensitivity(other)
        other["build_priorities"] = build_priorities(other)
        _with_actionable(other)
        controller._on_analysis_finished(42, other, None)
        assert other["actionable"]["changes"] == {"comparable": False, "items": []}
    finally:
        controller.shutdown()
