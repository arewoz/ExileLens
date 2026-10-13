"""Render the real integrated Qt pages with isolated, synthetic inputs.

QT_QPA_PLATFORM=offscreen python scripts/filter_product_qa.py --out .run/evidence/after
Use QT_SCALE_FACTOR=1.25 in a separate process to check 125% display scaling.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT), str(ROOT / 'scripts')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / '.run/evidence/after')
    args = parser.parse_args()
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from ui_visual_qa import Harness
    from qa_states import STATE_REGISTRY
    from exilelens.filters.build_needs import BuildNeedsSnapshot
    from exilelens.filters.intel_status import IntelState
    from tests.test_r1_analyze_build_ui import realistic_analysis
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QScrollArea

    with tempfile.TemporaryDirectory(prefix='exilelens-filter-qa-') as directory:
        h = Harness(Path(directory))
        for state in ('analyze-results', 'analyze-running', 'analyze-error', 'analyze-stale'):
            if state not in STATE_REGISTRY:
                continue
            STATE_REGISTRY[state](h)
            # Keep screenshot evidence synthetic, including the loading/error states.
            page = h.window._analysis
            page._view['build']['name'] = 'Spark Stormweaver'
            page._refresh_chrome()
            for size in ((980, 720), (720, 560)):
                h.shot(f'{state}-{size[0]}x{size[1]}', size, args.out, frame=False)
        STATE_REGISTRY['analyze-results'](h)
        h.window._analysis._view['build']['name'] = 'Spark Stormweaver with a deliberately long build name for layout verification'
        h.window._analysis._refresh_chrome()
        h.shot('analyze-long-name-720x560', (720, 560), args.out, frame=False)
        h.set_state('setup', build=False)
        h.window.navigate('filters')
        page = h.window._filters_page
        # Never detect or write in the user's actual game directory during QA.
        page._filter_dir = None
        page._update_directory()
        page._seed = 731
        page._config_changed()
        for size in ((980, 720), (720, 560)):
            h.shot(f'filters-general-{size[0]}x{size[1]}', size, args.out, frame=False)
        h.set_state('ready', build=True)
        needs = BuildNeedsSnapshot.from_json((ROOT / 'tests/fixtures/filter_needs/filter08c/spark_fixture.json').read_text(encoding='utf-8'))
        page._needs = needs
        page._intel_state = IntelState.CURRENT
        page._config_changed()
        h.shot('filters-personalized-980x720', (980, 720), args.out, frame=False)
        page._scene_preset.setCurrentText('Clutter Stress Test')
        page._environment.setCurrentIndex(1)
        page._theme.setCurrentIndex(7)
        page._profile.setCurrentText('Uber Strict')
        h.shot('filters-dense-light-720x560', (720, 560), args.out, frame=False)
        scroll = page.findChild(QScrollArea)
        scroll.verticalScrollBar().setValue(460)
        h.shot('filters-dense-light-scrolled-720x560', (720, 560), args.out, frame=False)
        # Exercise keyboard navigation on the actual rail; each destination remains a tab stop.
        h.window.activateWindow()
        for _ in range(8):
            h.app.processEvents()
        for key, destination in ((Qt.Key.Key_2, 'build_analysis'), (Qt.Key.Key_3, 'filters'),
                                 (Qt.Key.Key_4, 'settings'), (Qt.Key.Key_5, 'diagnostics')):
            QTest.keyClick(h.window, key, Qt.KeyboardModifier.ControlModifier)
            for _ in range(8):
                h.app.processEvents()
            assert h.window.current_page_id() == destination, (key, destination, h.window.current_page_id())
        assert all(button.focusPolicy() == Qt.FocusPolicy.TabFocus for button in h.window._rail.nav_buttons().values())
        h.controller.shutdown()
    print(f'Qt screenshots and keyboard checks saved to {args.out}')


if __name__ == '__main__':
    raise SystemExit(main())
