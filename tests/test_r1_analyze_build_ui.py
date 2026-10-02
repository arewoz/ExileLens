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
    assert (tiles["damage"]["value"], tiles["damage"]["change"]) == ("+8.7%", "+1 to Level of all Spell Skills")
    assert (tiles["ehp_max_hit"]["value"], tiles["ehp_max_hit"]["change"]) == ("+3.1% · +2.0%", "+50 to maximum Energy Shield")
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
    assert strongest[0] == "DAMAGE +8.7% +1 to Level of all Spell Skills"
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
    assert window._list.count() == 2 and window._list.item(0).text() == "BUILD PRIORITIES"
    assert window._list.currentRow() == 0 and window._current_intent() == {} and not window._copy_btn.isEnabled()
    window._list.setCurrentRow(1)
    assert "CURRENT ITEM" in window._detail.toPlainText() and "SEARCH INTENT" in window._detail.toPlainText()
    assert window._current_intent() == {"slot": "RING"} and window._copy_btn.isEnabled()
    window._copy_intent()
    assert json.loads(QApplication.clipboard().text()) == {"slot": "RING"}
    # A single-slot analysis has no priorities entry: row 0 is then the slot itself.
    slot_only = {"baseline": {"build_name": "T"}, "slots": [dict(SLOT_ROW)], "needs": []}
    window.show_result(slot_only)
    assert window._list.count() == 1 and window._current_intent() == {"slot": "RING"}
    assert "CURRENT ITEM" in window._detail.toPlainText() and not window.strongest_text()


def test_tree_results_and_rescores_do_not_disturb_the_page() -> None:
    window, controller = _window()
    controller.analysis_finished.emit(_analysis(request_id=5))
    stamp = window._analyzed_at
    controller.analysis_finished.emit({"kind": "tree", "nodes": [], "slots": []})
    controller.analysis_finished.emit({"kind": "tree_snapshot", "graph": {}})
    assert window._list.count() == 2 and window.state == CURRENT
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
