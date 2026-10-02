"""R1 Analyze Build page and the controller cache Item Check reads: player wording, states, no hidden analysis."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from exilelens.analysis.priorities import build_priorities
from exilelens.analysis.strongest import strongest_responses
from exilelens.analysis.view import build_analysis_view, progress_text
from exilelens.app.modules.registry import FeatureModule, is_enabled
from exilelens.items.build_context import AVAILABLE, NOT_ANALYZED, STALE
from exilelens.ui.analysis_window import CURRENT, ERROR, IDLE, RUNNING, AnalysisWindow
from exilelens.ui.analysis_window import STALE as PAGE_STALE
from tests.test_m5_3_build_priorities import PROBES, _probe, _result

pytestmark = pytest.mark.itemcheck

FIRE_NEED = {"code": "RES_CAP_MISSING", "severity": "critical", "metric": "fire_res", "deficit": 17.0}
SLOT_ROW = {
    "product_slot": "RING", "pob_slot": "Ring 1", "current_item": {"name": "R", "base_name": "B"}, "probes": [],
    "opportunity": {"band": "LOW", "score": 12.0, "drivers": []}, "search_intent": {"slot": "RING"},
}


class Controller(QObject):
    analysis_started = Signal(int)
    build_analysis_started = Signal(int)
    analysis_progress = Signal(object)
    analysis_finished = Signal(object)
    analysis_error = Signal(str)
    analysis_stale = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.submitted = 0

    def submit_analyze_build(self) -> int:
        self.submitted += 1
        self.build_analysis_started.emit(self.submitted)
        return self.submitted


def _analysis(probes=PROBES, *, slots=(SLOT_ROW,), request_id=1, **kwargs):
    result = _result(probes, **kwargs)
    result["build_priorities"] = build_priorities(result)
    result["strongest_responses"] = strongest_responses(result["build_priorities"])
    result["performance"] = {"elapsed_ms": 4200, "pob_recalcs": 22, "cache": {"hits": 3, "misses": 19, "size": 19}}
    result["slots"] = [dict(row) for row in slots]
    result["request_meta"] = {"request_id": request_id, "kind": "analysis"}
    return result


CHAOS_NEED = {"code": "LOW_CHAOS_RES", "severity": "high", "metric": "chaos_res", "deficit": 41.0, "explanation": "Chaos resistance below cap."}
WINDOWS_PATH = r"C:\Users\Player\Documents\Path of Building (PoE2)\Builds\UrkaBurkass.xml"


def _slot_probe(probe_id, name, line, *, offense=0.0, ehp=0.0, score=0.0, status="ok", breakpoints=()):
    return {"probe_id": probe_id, "display_name": name, "line": line, "status": status, "slot_compatible": True,
            "offense_percent": offense, "ehp_percent": ehp, "score_delta": score, "breakpoints": list(breakpoints), "confidence": "HIGH"}


def realistic_analysis() -> dict:
    """The shape of a real result as the engine produces it: internal driver texts, zero-response tests, a limited weapon."""
    probes = [
        _probe("SPELL_SKILL_LEVELS", "Spell Skill Levels", "+1 to Level of all Spell Skills", 1.0, offense=13.6),
        _probe("PROJECTILE_SKILL_LEVELS", "Projectile Skill Levels", "+1 to Level of all Projectile Skills", 1.0, offense=13.6),
        _probe("CAST_SPEED", "Cast Speed", "10% increased Cast Speed", 10.0, offense=4.7),
        _probe("LIFE", "Life", "+50 to maximum Life", 50.0, family="defense", ehp=2.4, max_hit=2.1, life=2.4),
        _probe("STRENGTH", "Strength", "+20 to Strength", 20.0, family="utility", ehp=1.2, max_hit=1.1),
        _probe("MOVEMENT_SPEED", "Movement Speed", "10% increased Movement Speed", 10.0, family="utility", movement=7.2),
        _probe("MANA", "Mana", "+50 to maximum Mana", 50.0, family="defense", status="NO_SIGNAL"),
    ]
    slot_probes = [
        _slot_probe("CAST_SPEED", "Cast Speed", "10% increased Cast Speed", offense=4.7, score=3.9),
        _slot_probe("LIFE", "Life", "+50 to maximum Life", ehp=2.4, score=6.7),
        _slot_probe("MANA", "Mana", "+50 to maximum Mana", status="NO_SIGNAL"),
        _slot_probe("FIRE_RES", "Fire Resistance", "+20% to Fire Resistance", score=0.1),
        _slot_probe("COLD_RES", "Cold Resistance", "+20% to Cold Resistance"),
        _slot_probe("CHAOS_RES", "Chaos Resistance", "+20% to Chaos Resistance", ehp=0.4, score=2.2),
        _slot_probe("STRENGTH", "Strength", "+20 to Strength", ehp=1.2, score=3.1),
    ]
    intent = {
        "kind": "SearchIntent", "slot": "GLOVES",
        "required": [{"stat": "chaos_res", "probe_id": "CHAOS_RES", "reason": "LOW_CHAOS_RES", "tier": "REQUIRED"}],
        "high_value": [], "useful": [{"stat": "life", "display_name": "Life", "score_delta": 6.7}, {"stat": "cast_speed", "display_name": "Cast Speed", "score_delta": 3.9},
                                      {"stat": "strength", "display_name": "Strength", "score_delta": 3.1}],
        "low_value": [{"stat": "mana", "display_name": "Mana", "score_delta": 0.0}], "avoid": [],
    }
    gloves = {
        "product_slot": "GLOVES", "pob_slot": "Gloves", "current_item": {"name": "Viper Grasp", "base_name": "Sectioned Bracers"},
        "analysis_limited": False, "probes": slot_probes, "search_intent": intent,
        "opportunity": {"band": "MEDIUM", "score": 57, "confidence": "HIGH", "drivers": [
            {"text": "addresses LOW_CHAOS_RES", "kind": "high", "code": "LOW_CHAOS_RES"},
            {"text": "Life has high marginal value", "kind": "marginal", "probe_id": "LIFE", "score_delta": 6.7},
            {"text": "current item contributes little offense", "kind": "contribution"}]},
    }
    belt = {
        "product_slot": "BELT", "pob_slot": "Belt", "current_item": {"name": "Storm Tether", "base_name": "Fine Belt"},
        "analysis_limited": False, "probes": slot_probes[1:], "search_intent": {**intent, "slot": "BELT"},
        "opportunity": {"band": "LOW", "score": 28, "drivers": [{"text": "current slot already performs efficiently", "kind": "note"}]},
    }
    weapon = {
        "product_slot": "WEAPON_1", "pob_slot": "Weapon 1", "current_item": {"name": "Dread Song", "base_name": "Attuned Wand"},
        "analysis_limited": True, "probes": [],
        "search_intent": {"kind": "SearchIntent", "slot": "WEAPON_1", "analysis_limited": True, "note": "WEAPON ANALYSIS LIMITED"},
        "opportunity": {"band": "ANALYSIS LIMITED", "score": None, "analysis_limited": True,
                        "drivers": [{"text": "Weapon / offhand probing is not trustworthy in Phase 5A.", "kind": "limit"}]},
    }
    result = _analysis(probes, slots=(gloves, belt, weapon), needs=[CHAOS_NEED])
    result["baseline"] = {**result["baseline"], "build_name": WINDOWS_PATH, "build_path": WINDOWS_PATH, "loadout": "Default"}
    return result


def _window() -> tuple[AnalysisWindow, Controller]:
    QApplication.instance() or QApplication([])
    controller = Controller()
    return AnalysisWindow(controller, embedded=True), controller


def _page_text(window: AnalysisWindow) -> str:
    return "\n".join([window._header.text(), window._status.text(), window._progress.text(), *window.strongest_text(),
                      *window.fix_first_text(), window._detail.toPlainText()])


# ------------------------------------------------------------------------ view model


def test_view_uses_player_words_and_never_internal_ones() -> None:
    view = build_analysis_view(_analysis(needs=[FIRE_NEED]))
    text = json.dumps(view)
    for internal in ("probe", "NO_SIGNAL", "REJECTED", "UNSUPPORTED", "MEASURED", "hash1", "score", "marginal", "cache", "SPELL_SKILL_LEVELS"):
        assert internal not in text
    assert view["coverage"][0] == "Measured: 7 tested stat changes moved this build."
    assert "No measurable response: Crit Chance." in view["coverage"] and "Could not establish: Armour." in view["coverage"]
    assert any(line.startswith("Not currently supported: ") for line in view["coverage"])
    assert view["fix_first"] == [{"title": "Fire Resistance", "detail": "+17% reaches cap", "urgency": "Critical"}]
    assert "not a per-point comparison" in view["caveat"]


def test_strongest_tiles_keep_the_tested_change_and_merge_a_shared_defensive_winner() -> None:
    tiles = {tile["key"]: tile for tile in build_analysis_view(_analysis())["tiles"]}
    assert list(tiles) == ["damage", "ehp_max_hit", "movement", "multi_impact"]
    assert (tiles["damage"]["value"], tiles["damage"]["change"]) == ("+8.7%", "+1 Spell Skill Level")
    assert tiles["damage"]["tested_change"] == "+1 to Level of all Spell Skills"  # the exact tested line stays available
    assert (tiles["ehp_max_hit"]["value"], tiles["ehp_max_hit"]["change"]) == ("+3.1% · +2.0%", "+50 Energy Shield")
    assert tiles["multi_impact"]["value"] == "Damage +2.1% · ES +4.3% · Mana +3.0%"
    split = [_probe("LIFE", "Life", "+50 to maximum Life", 50.0, family="defense", ehp=3.0, max_hit=1.0),
             _probe("ARMOUR", "Armour", "+200 to Armour", 200.0, family="defense", ehp=1.0, max_hit=4.0)]
    keys = [tile["key"] for tile in build_analysis_view(_analysis(split))["tiles"]]
    assert keys == ["damage", "ehp", "max_hit", "movement", "multi_impact"]


def test_empty_lanes_make_no_section_and_empty_tiles_say_why() -> None:
    only_life = [_probe("LIFE", "Life", "+50 to maximum Life", 50.0, family="defense", ehp=2.4)]
    view = build_analysis_view(_analysis(only_life))
    assert [lane["key"] for lane in view["lanes"]] == ["ehp"]
    tiles = {tile["key"]: tile for tile in view["tiles"]}
    assert (tiles["damage"]["value"], tiles["damage"]["change"], tiles["damage"]["measured"]) == ("—", "No measurable response", False)
    nothing = build_analysis_view(_analysis([_probe("LIFE", "Life", "+50 to maximum Life", 50.0, family="defense", status="REJECTED")]))
    assert all(tile["change"] == "Could not establish" for tile in nothing["tiles"]) and nothing["lanes"] == []
    assert build_analysis_view({"slots": []})["tiles"] == []  # a single-slot analysis has no priorities to show


def test_capped_resistance_is_explained_as_capped_not_as_a_useless_stat() -> None:
    probes = [*PROBES, _probe("FIRE_RES", "Fire Resistance", "+20% to Fire Resistance", 20.0, family="resistance", status="NO_SIGNAL")]
    capped = {"defense": {"resistances": {"fire": {"state": {"value": "CAPPED", "evidence": "DERIVED"}}}}}
    coverage = build_analysis_view(_analysis(probes, fingerprint_extra=capped))["coverage"]
    assert "Already at cap, so more does nothing: Fire Resistance." in coverage
    assert "No measurable response: Crit Chance." in coverage
    uncapped = build_analysis_view(_analysis(probes))["coverage"]
    assert "No measurable response: Crit Chance, Fire Resistance." in uncapped


def test_progress_is_spoken_in_stat_names_not_identifiers() -> None:
    assert progress_text({"stage": "probe", "probe_id": "CAST_SPEED"}, {"CAST_SPEED": "Cast Speed"}) == "Testing Cast Speed"
    assert progress_text({"stage": "slot", "slot": "BODY_ARMOUR"}) == "Checking Body Armour"
    assert progress_text({"stage": "audit"}) == "Reading your build"
    assert "CAST_SPEED" not in progress_text({"stage": "probe", "probe_id": "CAST_SPEED"})


# ---------------------------------------------------------------------------- page


def test_page_renders_strongest_responses_fix_first_and_priorities() -> None:
    window, _controller = _window()
    assert window.state == IDLE and "Not analyzed yet" in window._status.text() and not window.strongest_text()
    window.show_result(_analysis(needs=[FIRE_NEED]))
    assert window.state == CURRENT and window._status.text().startswith("Up to date")
    strongest = window.strongest_text()
    assert strongest[0] == "DAMAGE +8.7% +1 Spell Skill Level"
    assert any(line.startswith("MULTI-IMPACT Damage +2.1%") for line in strongest)
    assert "not a per-point comparison" in window._strongest_note.text()
    assert window.fix_first_text() == ["FIX FIRST", "▲ Fire Resistance — +17% reaches cap  ·  Critical"]
    detail = window._detail.toPlainText()
    for expected in ("DAMAGE", "10% increased Cast Speed", "+6.1%", "MULTI-IMPACT", "WHAT EXILELENS MEASURED",
                     "No measurable response: Crit Chance.", "Based on stats ExileLens tested against this PoB build."):
        assert expected in detail
    assert "FIX FIRST" not in detail  # urgent problems have their own panel, apart from optimisation
    assert "T · L · MAP" in window._header.text()
    for internal in ("hash1", "SPELL_SKILL_LEVELS", "probe", "NO_SIGNAL", "cache", "b.xml"):
        assert internal not in _page_text(window)


def test_fix_first_panel_and_empty_lanes_leave_no_empty_shells() -> None:
    window, _controller = _window()
    window.show_result(_analysis([_probe("LIFE", "Life", "+50 to maximum Life", 50.0, family="defense", ehp=2.4)]))
    assert window._fix_first_panel.isHidden() and window.fix_first_text() == []
    detail = window._detail.toPlainText()
    assert "EHP" in detail and "DAMAGE" not in detail and "MOVEMENT" not in detail and "MAX HIT" not in detail
    window.show_result(_analysis([]))
    assert "No measured response among the tested stats." in window._detail.toPlainText()


def test_measurement_details_are_behind_a_toggle() -> None:
    window, _controller = _window()
    window.show_result(_analysis())
    assert "MEASUREMENT DETAILS" not in window._detail.toPlainText()
    window._details_toggle.setChecked(True)
    detail = window._detail.toPlainText()
    assert "MEASUREMENT DETAILS" in detail and "22 Path of Building calculations" in detail


def test_running_state_is_clear_and_does_not_block_the_page() -> None:
    window, controller = _window()
    window._rerun()
    assert controller.submitted == 1 and window.state == RUNNING
    assert window._analyze_btn.text() == "Analyzing…" and not window._analyze_btn.isEnabled()
    assert "Item Check stays available" in window._status.text()
    controller.analysis_progress.emit({"stage": "probe", "probe_id": "CAST_SPEED"})
    assert window._progress.text() == "Testing Cast Speed"
    controller.analysis_progress.emit({"kind": "tree_visible", "stage": "node"})  # another feature's progress is ignored
    assert window._progress.text() == "Testing Cast Speed"
    controller.analysis_finished.emit(_analysis())
    assert window.state == CURRENT and window._analyze_btn.isEnabled() and window._analyze_btn.text() == "Re-analyze"


def test_stale_state_keeps_the_old_analysis_readable_but_marked() -> None:
    window, controller = _window()
    controller.analysis_stale.emit()
    assert window.state == IDLE  # nothing to be stale about yet
    controller.analysis_finished.emit(_analysis())
    controller.analysis_stale.emit()
    assert window.state == PAGE_STALE and "Out of date" in window._status.text()
    assert "does not use it" in window._progress.text() and window._analyze_btn.text() == "Re-analyze"
    assert window.strongest_text() and "+1 to Level of all Spell Skills" in window._detail.toPlainText()


def test_error_state_explains_and_offers_retry_without_an_empty_window() -> None:
    window, controller = _window()
    controller.analysis_error.emit("unrelated failure")  # not running: not this page's failure
    assert window.state == IDLE
    window._rerun()
    controller.analysis_error.emit("PoB worker stopped responding.")
    assert window.state == ERROR and window._status.text() == "Analysis could not complete"
    assert "PoB worker stopped responding. Item Check still works." in window._progress.text()
    assert window._analyze_btn.text() == "Retry" and window._analyze_btn.isEnabled()
    window._rerun()
    assert controller.submitted == 2 and window.state == RUNNING


def test_slot_entries_search_intent_and_indexing_are_unchanged() -> None:
    window, _controller = _window()
    window.show_result(_analysis())
    assert [window._list.item(i).text() for i in range(window._list.count())] == [
        "Overview", "UPGRADE OPPORTUNITIES", "Ring"]
    assert window._list.currentRow() == 0 and window._current_intent() == {} and not window._copy_btn.isEnabled()
    window._list.setCurrentRow(1)  # the heading is not an entry
    assert window._current_intent() == {}
    window._list.setCurrentRow(2)
    assert "CURRENT ITEM" in window._detail.toPlainText()
    assert window._current_intent() == {"slot": "RING"} and window._copy_btn.isEnabled()
    window._copy_intent()
    assert json.loads(QApplication.clipboard().text()) == {"slot": "RING"}
    # A single-slot analysis has no priorities entry: the heading is row 0 and the slot is selected.
    slot_only = {"baseline": {"build_name": "T"}, "slots": [dict(SLOT_ROW)], "needs": []}
    window.show_result(slot_only)
    assert window._list.count() == 2 and window._current_intent() == {"slot": "RING"}
    assert "CURRENT ITEM" in window._detail.toPlainText() and not window.strongest_text()


def test_tree_results_and_rescores_do_not_disturb_the_page() -> None:
    window, controller = _window()
    controller.analysis_finished.emit(_analysis(request_id=5))
    stamp = window._analyzed_at
    controller.analysis_finished.emit({"kind": "tree", "nodes": [], "slots": []})
    controller.analysis_finished.emit({"kind": "tree_snapshot", "graph": {}})
    assert window._list.count() == 3 and window.state == CURRENT
    controller.analysis_finished.emit(_analysis(request_id=5, profile="MAPPING"))  # profile change: same run, rescored
    assert window._analyzed_at == stamp


# ------------------------------------------------------------- module and controller


def test_build_analysis_is_a_supported_module() -> None:
    assert is_enabled(FeatureModule.BUILD_ANALYSIS) and is_enabled(FeatureModule.ITEM_CHECK)
    assert not is_enabled(FeatureModule.TREE_TOOLS) and not is_enabled(FeatureModule.MARKET)  # nothing else was unparked


def _controller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tests.test_stale_build_reload_controller import _ready_controller

    controller, _engine, _build, _submitted = _ready_controller(tmp_path, monkeypatch)
    scheduled: list[object] = []
    controller._scheduler.submit = lambda request: scheduled.append(request) or True  # type: ignore[method-assign]
    return controller, scheduled


def _matching_analysis(controller) -> dict:
    baseline = {
        "build_path": controller.build_info.path, "build_name": "old", "loadout": controller._active_loadout or "",
        "item_set": str(controller._active_item_set_id or ""), "context": "MAP", "profile": "BALANCED",
        "generation": controller._baseline_generation, "fingerprint": "item-check-fp",
    }
    result = _analysis()
    result["baseline"] = baseline
    from exilelens.analysis.sensitivity import build_sensitivity

    result["build_sensitivity"] = build_sensitivity(result)
    result["build_priorities"] = build_priorities(result)
    result["strongest_responses"] = strongest_responses(result["build_priorities"])
    result["request_meta"] = {"request_id": 41, "baseline_generation": controller._baseline_generation, "kind": "analysis"}
    return result


def _item_check_result() -> dict:
    return {"recommendation": {"pob_slot": "Ring 1", "baseline": {"fingerprint_hash": "item-check-fp"}}, "slot_comparisons": [], "raw_input": {}}


def test_item_check_reads_the_cache_and_never_schedules_an_analysis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller, scheduled = _controller(tmp_path, monkeypatch)
    try:
        # Journey A: no Analyze Build yet.
        context = controller._item_check_build_context(_item_check_result())
        assert context["status"] == NOT_ANALYZED and context["uses_build_intelligence"] is False
        assert scheduled == [] and controller._analysis_resume is None and controller._build_intelligence is None

        # Journey B: an explicit Analyze Build finished for this exact baseline.
        controller._on_analysis_finished(41, _matching_analysis(controller), None)
        assert controller.build_intelligence_status("item-check-fp") == AVAILABLE
        for _ in range(3):
            assert controller._item_check_build_context(_item_check_result())["status"] == AVAILABLE
        assert scheduled == [] and controller._analysis_resume is None  # reading it never queues PoB work

        # Another baseline fingerprint (the item was evaluated against a different PoB state) is stale.
        other = {"recommendation": {"baseline": {"fingerprint_hash": "changed"}}, "slot_comparisons": []}
        assert controller._item_check_build_context(other)["status"] == STALE
    finally:
        controller.shutdown()


def test_build_change_drops_the_cached_intelligence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller, _scheduled = _controller(tmp_path, monkeypatch)
    try:
        controller._on_analysis_finished(41, _matching_analysis(controller), None)
        assert controller._build_intelligence is not None
        # A tree or single-slot analysis replaces `last_analysis` but not the Build Intelligence.
        controller._on_analysis_finished(42, {"kind": "tree_snapshot", "graph": {}, "request_meta": {"baseline_generation": controller._baseline_generation}}, None)
        assert controller.build_intelligence_status("item-check-fp") == AVAILABLE
        stale: list[bool] = []
        controller.analysis_stale.connect(lambda: stale.append(True))
        controller._bump_baseline_generation()
        assert controller._build_intelligence is None and stale
        assert controller._item_check_build_context(_item_check_result())["status"] == NOT_ANALYZED
        # A result produced for the previous generation is rejected, not cached.
        controller._on_analysis_finished(43, _matching_analysis(controller) | {"request_meta": {"baseline_generation": 1}}, None)
        assert controller._build_intelligence is None
    finally:
        controller.shutdown()


def test_explicit_analyze_build_is_the_only_entry_and_survives_a_gameplay_yield(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller, scheduled = _controller(tmp_path, monkeypatch)
    started: list[int] = []
    errors: list[str] = []
    controller.build_analysis_started.connect(started.append)
    controller.analysis_error.connect(errors.append)
    try:
        controller._analysis_cancelled = True  # left set by the build load that preceded this run
        request_id = controller.submit_analyze_build()
        assert request_id is not None and started == [request_id] and len(scheduled) == 1
        assert getattr(scheduled[0], "kind", "") == "analysis"
        # Item Check pre-empts it: the analysis yields and stays queued for resume instead of failing.
        controller._on_analysis_finished(request_id, {"status": "yielded", "request_meta": {"request_id": request_id}}, None)
        assert errors == [] and controller._analysis_resume is not None
    finally:
        controller.shutdown()


# ------------------------------------------------- polish: no internal language by default

INTERNAL = ("LOW_CHAOS_RES", "marginal", "Build Value", "Search Intent", "SearchIntent", "chaos_res", "ANALYSIS LIMITED",
            "Phase 5A", "probing", "Not a market price", "trade URL", "heuristic", "Driver:")


def _all_default_text(window: AnalysisWindow) -> str:
    parts = [window._header.text(), *window.strongest_text(), *window.fix_first_text()]
    for row in range(window._list.count()):
        parts.append(window._list.item(row).text())
        window._list.setCurrentRow(row)
        parts.append(window._detail.toPlainText())
    return "\n".join(parts)


def test_default_view_has_no_internal_language_scores_or_file_path() -> None:
    window, _controller = _window()
    window.show_result(realistic_analysis())
    text = _all_default_text(window)
    for internal in INTERNAL:
        assert internal not in text, internal
    for number in ("57", "28"):  # the internal opportunity numbers
        assert number not in text
    assert "C:\\" not in text and ".xml" not in text and "Users" not in text
    assert window._header.text() == "UrkaBurkass · Default · MAP" and window._header.toolTip() == WINDOWS_PATH


def test_slot_list_is_framed_as_upgrade_opportunities_in_the_same_order() -> None:
    window, _controller = _window()
    window.show_result(realistic_analysis())
    assert [window._list.item(i).text() for i in range(window._list.count())] == [
        "Overview", "UPGRADE OPPORTUNITIES", "Gloves", "Belt", "Weapon 1 — Limited analysis"]
    assert window._list.currentRow() == 0 and "WHAT EXILELENS MEASURED" in window._detail.toPlainText()  # Overview = whole build
    window._list.setCurrentRow(2)
    window._list.setCurrentRow(0)
    assert "DAMAGE" in window._detail.toPlainText() and "CURRENT ITEM" not in window._detail.toPlainText()


def test_selected_slot_reads_as_guidance_built_from_existing_data() -> None:
    window, _controller = _window()
    window.show_result(realistic_analysis())
    window._list.setCurrentRow(2)
    detail = window._detail.toPlainText()
    for expected in ("CURRENT ITEM", "Viper Grasp", "Sectioned Bracers", "WHY THIS SLOT MATTERS", "Can help cap Chaos Resistance",
                     "Life is among this build's strongest measured EHP / Max Hit responses", "Your current item adds little damage",
                     "USEFUL STATS", "Chaos Resistance · Life · Cast Speed · Strength", "MEASURED ON THIS SLOT",
                     "10% Cast Speed → Damage +4.7%", "+50 Life → EHP +2.4%"):
        assert expected in detail, expected
    assert "Mana" not in detail and "+0.0" not in detail and "Fire Resistance" not in detail  # no wall of zero responses
    assert "LIMITATIONS" not in detail
    window._list.setCurrentRow(3)
    assert "This slot already performs well" in window._detail.toPlainText()


def test_limited_weapon_slot_uses_player_language() -> None:
    window, _controller = _window()
    window.show_result(realistic_analysis())
    window._list.setCurrentRow(4)
    detail = window._detail.toPlainText()
    assert "Dread Song" in detail and "LIMITATIONS" in detail and "Weapon analysis is currently limited." in detail
    assert "WHY THIS SLOT MATTERS" not in detail and "Phase" not in detail and "trustworthy" not in detail


def test_technical_values_remain_available_behind_measurement_details() -> None:
    window, _controller = _window()
    window.show_result(realistic_analysis())
    window._list.setCurrentRow(2)
    assert window._copy_btn.isHidden() and window._export_btn.isHidden()  # advanced actions stay out of the way
    window._details_toggle.setChecked(True)
    detail = window._detail.toPlainText()
    for expected in ("MEASUREMENT DETAILS", "Opportunity ordering: MEDIUM 57", "Driver: addresses LOW_CHAOS_RES",
                     "+50 to maximum Mana → Damage +0.0% · EHP +0.0% · Build Value +0.0", "Build Value +6.7",
                     "Search Intent required: chaos_res", "Search Intent low_value: Mana", f"Build file: {WINDOWS_PATH}"):
        assert expected in detail, expected
    assert not window._copy_btn.isHidden() and not window._export_btn.isHidden()
    window._copy_intent()
    assert json.loads(QApplication.clipboard().text())["slot"] == "GLOVES"
    window._list.setCurrentRow(0)
    assert window._copy_btn.isHidden() and not window._export_btn.isHidden()  # Search Intent belongs to a slot
    window._details_toggle.setChecked(False)
    assert window._export_btn.isHidden()


def test_strongest_cards_are_concise_and_an_empty_multi_impact_is_not_an_error() -> None:
    tiles = {tile["key"]: tile for tile in build_analysis_view(realistic_analysis())["tiles"]}
    assert (tiles["damage"]["change"], tiles["damage"]["note"]) == ("+1 Spell Skill Level", "Tied: +1 Projectile Skill Level")
    assert tiles["damage"]["tested_change"] == "+1 to Level of all Spell Skills" and tiles["damage"]["value"] == "+13.6%"
    assert (tiles["multi_impact"]["value"], tiles["multi_impact"]["change"]) == ("", "No multi-impact stat measured")
    assert tiles["movement"]["change"] == "10% Movement Speed"


def test_page_never_needs_a_horizontal_scrollbar() -> None:
    from PySide6.QtCore import Qt

    window, _controller = _window()
    window.resize(760, 520)
    window.show_result(realistic_analysis())
    for widget in (window._list, window._detail):
        assert widget.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    window._details_toggle.setChecked(True)
    window._list.setCurrentRow(2)
    assert window._detail.document().idealWidth() <= max(window._detail.viewport().width(), 1) + 1


# ------------------------------------------------------------ final polish: navigation


def _slot(name, band, drivers=(), limited=False):
    return {"product_slot": name, "pob_slot": name.title(), "current_item": {"name": name, "base_name": ""}, "probes": [],
            "analysis_limited": limited, "search_intent": {"slot": name},
            "opportunity": {"band": band, "score": None if limited else 50, "analysis_limited": limited, "drivers": list(drivers)}}


def test_slot_rows_drop_a_band_everyone_shares_and_keep_only_exceptional_qualifiers() -> None:
    from exilelens.analysis.view import slot_row_texts

    slots = [_slot(name, "MEDIUM") for name in ("GLOVES", "BELT", "BODY_ARMOUR", "BOOTS", "AMULET", "RING_2", "HELMET", "RING_1")]
    slots.append(_slot("WEAPON_1", "ANALYSIS LIMITED", limited=True))
    rows = slot_row_texts(slots)
    assert rows == ["Gloves", "Belt", "Body Armour", "Boots", "Amulet", "Ring 2", "Helmet", "Ring 1", "Weapon 1 — Limited analysis"]
    assert not any(ch.isdigit() for row in rows for ch in row.replace("Ring 2", "").replace("Ring 1", "").replace("Weapon 1", ""))
    # A high band only a minority has is a real difference and stays; one most slots share is noise again.
    standout = slot_row_texts([_slot("AMULET", "HIGH"), _slot("BELT", "MEDIUM"), _slot("BOOTS", "LOW")])
    assert standout == ["Amulet — High opportunity", "Belt", "Boots"]
    assert slot_row_texts([_slot("AMULET", "HIGH"), _slot("BELT", "HIGH"), _slot("BOOTS", "LOW")]) == ["Amulet", "Belt", "Boots"]


def _marginal(name):
    return {"text": f"{name} has high marginal value", "kind": "marginal", "probe_id": name.upper()}


AMULET_DRIVERS = [
    _marginal("Mana"), _marginal("Life"), _marginal("Energy Shield"), _marginal("Strength"), _marginal("Intelligence"),
    _marginal("Cast Speed"), _marginal("Spell Skill Levels"), {"text": "addresses LOW_CHAOS_RES", "kind": "high", "code": "LOW_CHAOS_RES"},
    {"text": "current item contributes little offense", "kind": "contribution"},
]


def test_why_this_slot_matters_shows_at_most_four_distinct_reasons_by_importance() -> None:
    from exilelens.analysis.view import MAX_SLOT_REASONS, build_slot_view

    result = _analysis(needs=[CHAOS_NEED], slots=(_slot("AMULET", "MEDIUM", AMULET_DRIVERS),))
    view = build_slot_view(result, result["slots"][0])
    assert view["why"] == [
        "Can help cap Chaos Resistance",                                                     # build need / Fix First
        "Spell Skill Levels is among this build's strongest measured damage responses",     # strongest offensive response
        "Energy Shield is among this build's strongest measured EHP / Max Hit responses",   # strongest defensive response
        "Your current item adds little damage",                                             # a distinct further reason
    ]
    assert len(view["why"]) == MAX_SLOT_REASONS == 4
    assert not any("is valuable for this build" in text for text in view["why"])  # near-duplicates do not fill the slots
    assert len(view["why_more"]) == 5 and "Cast Speed is among this build's strongest measured damage responses" in view["why_more"]
    assert build_slot_view(result, result["slots"][0]) == view  # deterministic
    few = build_slot_view(result, _slot("BELT", "LOW", [_marginal("Mana"), _marginal("Strength")]))
    assert few["why"] == ["Mana is valuable for this build", "Strength is valuable for this build"] and few["why_more"] == []


def test_remaining_reasons_and_the_full_driver_set_are_in_measurement_details() -> None:
    window, _controller = _window()
    window.show_result(_analysis(needs=[CHAOS_NEED], slots=(_slot("AMULET", "MEDIUM", AMULET_DRIVERS),)))
    window._list.setCurrentRow(2)
    default = window._detail.toPlainText()
    assert default.count("•") == 4 and "MORE REASONS" not in default and "Mana is valuable" not in default
    window._details_toggle.setChecked(True)
    detail = window._detail.toPlainText()
    assert "MORE REASONS" in detail and "Mana is valuable for this build" in detail
    assert "Cast Speed is among this build's strongest measured damage responses" in detail
    assert detail.count("Driver: ") == len(AMULET_DRIVERS)  # the complete underlying set
