"""FILTER-08C: the experimental dashboard generates the Build Intelligence-aware filter. Offscreen Qt, no PoB.

Run with:  python -m pytest tests/test_filter08c_dashboard.py -m ""
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from exilelens.filters.install import get_installed_filter_info, install_test_filter
from exilelens.filters.intel_fixtures import synthetic_analysis
from exilelens.filters.profiles import BaseTier, DefenseLayer

BUILD_PATH = "C:/builds/spark.xml"


@pytest.fixture()
def harness(monkeypatch):
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication
    from exilelens.ui.filters_page import FiltersPage

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    QApplication.instance() or QApplication([])

    class Controller(QObject):
        build_changed = Signal()
        engine_ready = Signal()
        engine_failed = Signal(str)
        analysis_started = Signal(int)
        analysis_finished = Signal(object)
        analysis_error = Signal(str)
        analysis_stale = Signal()

        def __init__(self):
            super().__init__()
            self.engine = None
            self.baseline_generation = 3
            self.build_info = SimpleNamespace(is_ready=True, state=SimpleNamespace(value="ready"), error_message="",
                                              path=BUILD_PATH, name="spark", context="MAP")
            self.requests = []
            self._last = None

        def last_analysis(self):
            return self._last

        def submit_analyze_build(self, *, slot=None, defence_probes=False):
            self.requests.append({"slot": slot, "defence_probes": defence_probes})
            return 7

    controller = Controller()
    page = FiltersPage(controller, SimpleNamespace())
    from exilelens.filters.intel_generate import fingerprint_from_needs
    from exilelens.filters.build_needs import BuildNeedsSnapshot
    page._fingerprint = fingerprint_from_needs(
        BuildNeedsSnapshot.unavailable("spark", "fixture", skill_name="Spark", equipped={"WEAPON_1": "Ashen Staff"}),
        class_name="Witch", ascendancy="Blood Mage")
    page._config_changed()
    yield page, controller
    page.close()


def _finish(controller, *, generation=3, build_path=BUILD_PATH):
    controller.analysis_started.emit(7)
    controller.analysis_finished.emit(synthetic_analysis(generation=generation, build_path=build_path))


def test_dashboard_generates_through_the_intelligence_pipeline_only():
    source = (Path(__file__).resolve().parents[1] / "src" / "exilelens" / "ui" / "filters_page.py").read_text(encoding="utf-8")
    assert "generate_filter(" in source and "intel=True" in source
    for legacy in ("SlotPriorityResolver", "RuleGenerator(", "FilterSerializer(", "SKILL_WEAPON_CLASSES"):
        assert legacy not in source, f"legacy generation path still referenced: {legacy}"


def test_unanalyzed_build_falls_back_visibly(harness):
    page, _controller = harness
    text = page._intel_label.text()
    assert "General filter" in text and "build not analyzed" in text and "nothing is personalized" in text
    assert page._generated_with == "fallback"
    assert "# Build Intelligence: " in page._filter_text
    assert "MEASURED PERSONALIZATION" not in page._filter_text
    assert "# Intelligence Notes: " in page._filter_text      # the reason is in the installed file too
    assert page._analyze.isEnabled() and page._analyze.text() == "Analyze Build"


def test_analyze_build_uses_production_submit_and_the_result_drives_the_filter(harness):
    page, controller = harness
    fallback_text = page._filter_text
    page._analyze.click()
    assert controller.requests == [{"slot": None, "defence_probes": True}]
    assert "analyzing" in page._intel_label.text().lower() and not page._analyze.isEnabled()
    _finish(controller)
    assert page._generated_with == "measured" and page._needs is not None
    assert page._filter_text != fallback_text
    status = page._intel_label.text()
    assert "Build Intelligence" in status and ("Partial" in status or "Measured" in status) and "analyzed" in status
    assert "built from this analysis" in status
    assert "# Build Intelligence: " in page._filter_text and "analyzed 20" in page._filter_text
    assert page._analyze.text() == "Re-analyze Build"       # a measured build offers a refresh
    assert "Personalization:" in page._intelligence_note.text()


def test_partial_state_names_the_missing_evidence(harness):
    page, controller = harness
    _finish(controller)
    status = page._intel_label.text()
    # the synthetic production result never tested Armour/Evasion: the dashboard says so instead of claiming Measured
    assert "Partial personalization" in status and "defence direction not measured" in status


def test_build_change_marks_the_analysis_stale_and_regenerates_conservatively(harness):
    page, controller = harness
    _finish(controller)
    measured_text = page._filter_text
    controller.baseline_generation = 4
    controller.analysis_stale.emit()
    assert page._needs is None and "re-analysis required" in page._intel_label.text().lower()
    assert page._generated_with == "fallback" and page._filter_text != measured_text


def test_an_analysis_of_another_baseline_is_not_used(harness):
    page, controller = harness
    _finish(controller, generation=2)                         # controller is at generation 3
    assert page._needs is None and page._generated_with == "fallback"
    assert "re-analysis required" in page._intel_label.text().lower()
    controller.analysis_started.emit(7)
    controller.analysis_finished.emit(synthetic_analysis(generation=3, build_path="C:/builds/other.xml"))
    assert page._needs is None                                # right generation, wrong build


def test_failed_analysis_is_reported_not_hidden(harness):
    page, controller = harness
    page._analyze.click()
    controller.analysis_error.emit("PoB crashed")
    assert "Analysis failed" in page._intel_label.text() and "PoB crashed" in page._intel_label.text()
    assert page._generated_with == "fallback" and page._analyze.isEnabled()


def test_a_current_production_analysis_is_reused_without_rerunning(harness):
    page, controller = harness
    controller._last = synthetic_analysis(generation=3, build_path=BUILD_PATH)
    page._adopt_cached_analysis()
    page._config_changed()
    assert page._needs is not None and page._generated_with == "measured"
    assert controller.requests == []


def test_installed_file_records_what_it_was_built_from(harness, tmp_path):
    page, controller = harness
    page._filter_dir = tmp_path
    _finish(controller)
    result = install_test_filter(page._filter_text, tmp_path, "Recommended", "Void Gold")
    assert result.success and result.verified
    info = get_installed_filter_info(tmp_path)
    assert info["intelligence"].startswith("PARTIAL PERSONALIZATION") or info["intelligence"].startswith("MEASURED")
    page._update_installed()
    assert "Build Intelligence: " in page._installed.text() and "legacy file" not in page._installed.text()


def test_preview_tooltips_carry_compact_provenance(harness):
    from PySide6.QtWidgets import QLabel
    page, controller = harness
    _finish(controller)
    page._scene_preset.setCurrentText("Mixed Loot")
    page._render_preview()
    tips = [child.toolTip() for child in page._scene.findChildren(QLabel) if "Rule: Weapon" in child.toolTip()
            or "Rule: Defense" in child.toolTip() or "Rule: Jewellery" in child.toolTip()]
    assert tips, "no build label in the preview scene"
    for heading in ("BUILD", "ITEMIZATION", "CRAFT", "MARKET", "CONFIDENCE"):
        assert heading in tips[0], tips[0]
    assert "HEURISTIC" in tips[0]                              # market provenance is always stated


def test_existing_preview_controls_still_work_on_the_intelligence_path(harness, tmp_path):
    page, controller = harness
    _finish(controller)
    before = len([c for c in page._scene.children()])
    page._theme.setCurrentIndex(page._theme.findText("Emberforge"))
    assert "Theme: Emberforge" in page._filter_text
    page._profile.setCurrentIndex(page._profile.findText("Uber Strict"))
    assert "Profile: Uber Strict" in page._filter_text and page._validation.valid
    assert before >= 0


def test_a_rescore_of_the_same_analysis_does_not_reset_the_analysis_age(harness):
    page, controller = harness
    _finish(controller)
    first = page._needs.measured_at
    page._needs = type(page._needs)(**{**{f: getattr(page._needs, f) for f in page._needs.__dataclass_fields__ if f != "signals_by_probe"},
                                       "measured_at": "2026-01-01T00:00:00+00:00"})
    controller.analysis_finished.emit(synthetic_analysis(generation=3, build_path=BUILD_PATH))   # same baseline, re-emitted
    assert page._needs.measured_at == "2026-01-01T00:00:00+00:00" != first


# -- profile system V2 -------------------------------------------------------------------------------------------------------------------
LEVELS = ["Relaxed", "Recommended", "Strict", "Very Strict", "Uber Strict"]


def test_profile_dropdown_is_the_five_levels_with_recommended_default_and_no_endgame(harness):
    page, _controller = harness
    names = [page._profile.itemText(i) for i in range(page._profile.count())]
    assert names == LEVELS and "Endgame" not in names
    assert page._profile.currentText() == "Recommended"
    for name in LEVELS:                                                   # every level has a short description
        page._profile.setCurrentIndex(page._profile.findText(name))
        assert page._profile_intent.text().strip()


def test_no_build_is_a_first_class_general_filter_at_every_level(harness):
    page, _controller = harness
    for name in LEVELS:
        page._profile.setCurrentIndex(page._profile.findText(name))
        assert page._validation.valid, name
        assert f"Profile: {name}" in page._filter_text
        assert "MEASURED PERSONALIZATION" not in page._filter_text
        rules = page._rules
        assert rules and not any(r.category in {"BUILD_WEAPON", "BUILD_DEFENSE", "BUILD_JEWELLERY"} for r in rules), name
    assert "General filter" in page._intel_label.text()
    assert "scary" not in page._intel_label.text().lower() and "degraded" not in page._intel_label.text().lower()


def test_random_drops_sample_is_stable_while_switching_profiles_and_gets_progressively_cleaner(harness):
    from exilelens.filters.scene_pool import RANDOM_SCENE
    page, _controller = harness
    page._scene_preset.setCurrentIndex(page._scene_preset.findText(RANDOM_SCENE))
    page._reroll()                                                         # one reroll, then only the profile changes
    seed = page._seed
    visible, quiet = [], []
    for name in LEVELS:
        page._profile.setCurrentIndex(page._profile.findText(name))
        assert page._seed == seed, name                                    # the same drops
        visible.append(len(page._preview_decisions))
        quiet.append(sum(1 for d in page._preview_decisions if d.state == "QUIET"))
    assert visible == sorted(visible, reverse=True), visible               # stricter: never more labels on the ground
    assert visible[0] > visible[-1]
    assert max(quiet) > 0


def test_endgame_in_saved_settings_migrates_once_with_an_explanation(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from exilelens.app.settings import AppSettings
    from exilelens.filters.profile_policy import ENDGAME_NOTICE
    from exilelens.ui.filters_page import FiltersPage
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    QApplication.instance() or QApplication([])
    monkeypatch.setattr("exilelens.app.settings.save_settings", lambda settings: None)

    settings = AppSettings.from_dict({"filter_profile": "Endgame"})
    assert settings.filter_profile == "Very Strict" and settings.filter_profile_notice == ENDGAME_NOTICE
    # the notice is data in the saved settings: re-reading the (already migrated) file keeps the level and the notice until it is acknowledged
    reread = AppSettings.from_dict({"filter_profile": settings.filter_profile, "filter_profile_notice": settings.filter_profile_notice})
    assert reread.filter_profile == "Very Strict" and reread.filter_profile_notice == ENDGAME_NOTICE

    controller = SimpleNamespace(build_changed=_Signal(), engine_ready=_Signal(), engine_failed=_Signal(), analysis_started=_Signal(),
                                 analysis_finished=_Signal(), analysis_error=_Signal(), analysis_stale=_Signal(), engine=None,
                                 baseline_generation=0, build_info=SimpleNamespace(is_ready=False, state=SimpleNamespace(value="none"),
                                                                                   error_message="", path="", name="", context="MAP"),
                                 last_analysis=lambda: None)
    page = FiltersPage(controller, settings)
    try:
        assert page._profile.currentText() == "Very Strict"
        assert not page._profile_notice.isHidden() and "Very Strict" in page._profile_notice.text()
        page._profile.setCurrentIndex(page._profile.findText("Strict"))   # the first deliberate choice dismisses it for good
        assert page._profile_notice.isHidden() and settings.filter_profile_notice == "" and settings.filter_profile == "Strict"
    finally:
        page.close()

    assert AppSettings.from_dict({"filter_profile": "no such level"}).filter_profile == "Recommended"
    assert AppSettings.from_dict({}).filter_profile == "Recommended"


class _Signal:
    def connect(self, *_a, **_k):
        pass
