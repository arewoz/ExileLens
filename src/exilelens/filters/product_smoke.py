"""Offline packaged-feature smoke report. Does not load or change a user profile."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace


def report() -> dict:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication
    from exilelens.app.settings import AppSettings
    from exilelens.filters.build_needs import BuildNeedsSnapshot
    from exilelens.filters.intel_generate import generate
    from exilelens.filters.profiles import FilterProfileName, FilterThemeName
    from exilelens.filters.style_coverage import has_required_style
    from exilelens.ui.filters_page import FiltersPage
    from exilelens.ui.dashboard_window import PAGE_IDS
    from exilelens.ui.status_rail import _NavButton

    class Controller(QObject):
        build_changed = Signal()
        engine_ready = Signal()
        engine_failed = Signal(str)
        analysis_started = Signal(int)
        analysis_finished = Signal(object)
        analysis_error = Signal(str)
        analysis_stale = Signal()
        engine = None
        build_info = SimpleNamespace(is_ready=False, path='', name='', context='MAP')

        def last_analysis(self):
            return None

    app = QApplication.instance() or QApplication([])
    controller = Controller()
    settings = AppSettings()
    # Avoid inspecting the real game folder in this report.
    import exilelens.ui.filters_page as module
    detect = module.find_poe2_filter_directory
    module.find_poe2_filter_directory = lambda: None
    try:
        page = FiltersPage(controller, settings)
    finally:
        module.find_poe2_filter_directory = detect
    cases = []
    needs = BuildNeedsSnapshot.unavailable('General', 'no build connected')
    for profile in FilterProfileName:
        for theme in FilterThemeName:
            result = generate(needs, profile, theme)
            assert result.valid, result.errors
            assert all(has_required_style(r) for r in result.rules if 'Show' in [line.strip() for line in r.lines])
            cases.append({'profile': profile.value, 'theme': theme.value, 'valid': True})
    badges = {}
    for key, label in (('build_analysis', 'Analyze Build'), ('filters', 'Loot Filters')):
        button = _NavButton(key, label, 'chart')
        button.set_compact(False)
        badges[key] = button._experimental.text()
        assert key in PAGE_IDS and badges[key] == 'Experimental'
    background = Path(__file__).with_name('data') / 'loot_ground.png'
    assert background.is_file() and page._filter_text and page._needs is None
    page.close()
    app.processEvents()
    return {'ok': True, 'general_generations': cases, 'experimental_navigation': badges,
            'preview_background_present': True, 'filter_page_constructed': True,
            'native_client_acceptance': 'UNVERIFIED'}
