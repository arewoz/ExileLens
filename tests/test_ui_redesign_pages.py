"""Behavioural checks for the redesigned dashboard: the rail, Overview states, and re-rendering without leftovers.

The QA harness (scripts/ui_visual_qa.py) builds the real DashboardWindow with a substituted health model, so the same
state ladder is exercised here without needing Path of Building.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the dashboard harness uses Windows-only capture helpers")

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(_ROOT / "scripts"))
    monkeypatch.syspath_prepend(str(_ROOT))
    qa = importlib.import_module("ui_visual_qa")
    states = importlib.import_module("qa_states")
    original = os.environ.get("LOCALAPPDATA")
    instance = qa.Harness(tmp_path)
    instance.states = states.STATE_REGISTRY
    yield instance
    instance.controller.shutdown()
    instance.window.close()
    if original is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = original


def _settle(harness) -> None:
    for _ in range(6):
        harness.app.processEvents()


def _status_word(harness) -> str:
    return harness.window._rail.status().label


def test_destinations_are_the_four_agreed_pages(harness) -> None:
    from exilelens.ui import dashboard_window

    window = harness.window
    assert dashboard_window.PAGE_IDS == ("overview", "build_analysis", "settings", "diagnostics")
    for alias, page in (("build", "overview"), ("items", "overview"), ("analyze", "build_analysis"), ("analysis", "build_analysis")):
        window.navigate(alias)
        assert window.current_page_id() == page


@pytest.mark.parametrize(
    "state, word",
    [
        ("overview-ready", "Ready"),
        ("overview-setup", "Setup needed"),
        ("overview-attention", "Needs attention"),
        ("overview-disconnected", "Not connected"),
    ],
)
def test_rail_and_overview_share_one_status(harness, state, word) -> None:
    harness.states[state](harness)
    _settle(harness)
    assert _status_word(harness) == word
    page_text = " ".join(label.text() for label in harness.window._overview.findChildren(__import__("PySide6.QtWidgets").QtWidgets.QLabel) if label.isVisibleTo(harness.window._overview))
    if word == "Ready":
        # The healthy state is said once, in the rail; the page starts with the build.
        assert "Ready" not in page_text
    else:
        assert word in page_text


def test_attention_rows_are_replaced_not_stacked(harness) -> None:
    harness.states["overview-attention"](harness)
    _settle(harness)
    host = harness.window._overview._attention_layout
    first = host.count()
    assert first >= 1
    harness.refresh()
    harness.refresh()
    assert host.count() == first
    assert harness.window._overview._attention_host.findChildren(__import__("PySide6.QtWidgets").QtWidgets.QWidget, "settingsRow").__len__() == first


def test_rail_links_keep_their_heights_after_a_compact_round_trip(harness) -> None:
    window = harness.window
    window.resize(980, 720)
    _settle(harness)
    before = {key: button.height() for key, button in window._rail.link_buttons().items()}
    window.resize(720, 560)
    _settle(harness)
    assert window._rail.is_compact()
    window.resize(980, 720)
    _settle(harness)
    assert not window._rail.is_compact()
    assert {key: button.height() for key, button in window._rail.link_buttons().items()} == before


def test_compact_rail_keeps_names_and_tooltips(harness) -> None:
    window = harness.window
    window.resize(720, 560)
    _settle(harness)
    for button in window._rail.nav_buttons().values():
        assert button.accessibleName() and button.toolTip() == button.accessibleName()
    assert window._rail.link_buttons()["support"].toolTip() == "Support ExileLens"


def test_analyze_page_rerenders_a_second_result_cleanly(harness) -> None:
    harness.states["analyze-results"](harness)
    page = harness.window._analysis
    assert page.state == "CURRENT" or page.state.lower() == "current"
    from tests.test_r1_analyze_build_ui import realistic_analysis

    harness.controller.analysis_finished.emit(realistic_analysis())  # a rescore re-emits the result
    assert page.state.lower() == "current" and page.coverage_text()


def test_analysis_error_then_success_clears_the_error(harness) -> None:
    harness.states["analyze-error"](harness)
    page = harness.window._analysis
    assert page.state.lower() == "error"
    harness.states["analyze-results"](harness)
    assert page.state.lower() == "current"


def test_window_default_and_minimum_sizes(harness) -> None:
    from exilelens.ui import theme

    assert theme.DEFAULT_WINDOW_SIZE == (980, 720) and theme.MINIMUM_WINDOW_SIZE == (720, 560)
    assert (harness.window.minimumWidth(), harness.window.minimumHeight()) == (720, 560)


def test_keyboard_shortcuts_switch_pages(harness) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window = harness.window
    window.activateWindow()
    for key, page in ((Qt.Key.Key_2, "build_analysis"), (Qt.Key.Key_3, "settings"), (Qt.Key.Key_4, "diagnostics"), (Qt.Key.Key_1, "overview")):
        QTest.keyClick(window, key, Qt.KeyboardModifier.ControlModifier)
        _settle(harness)
        assert window.current_page_id() == page
    QTest.keyClick(window, Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier)
    _settle(harness)
    assert window.current_page_id() == "settings"


@pytest.mark.parametrize("page", ["overview", "build_analysis", "settings", "diagnostics"])
def test_every_interactive_control_has_an_accessible_name(harness, page) -> None:
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit

    harness.states["analyze-results"](harness)
    harness.window.navigate(page)
    _settle(harness)
    root = harness.window._pages[page]
    nameless = []
    controls = [c for kind in (QAbstractButton, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit) for c in root.findChildren(kind)]
    for control in controls:
        if not control.isVisibleTo(root):
            continue
        name = control.accessibleName() or (control.text() if isinstance(control, QAbstractButton) else "")
        if not name.strip():
            nameless.append((type(control).__name__, control.objectName()))
    assert nameless == []


def test_nav_buttons_take_keyboard_focus_but_not_mouse_focus_rings(harness) -> None:
    from PySide6.QtCore import Qt

    for button in harness.window._rail.nav_buttons().values():
        assert button.focusPolicy() == Qt.FocusPolicy.TabFocus


def test_only_the_support_link_uses_the_patreon_colour(harness) -> None:
    # The Patreon mark keeps its own red; nothing else in the rail may borrow it.
    from exilelens.ui import theme

    assert "ff424d" not in harness.window._rail.styleSheet().lower()
    assert theme.ACCENT.lower() != "#ff424d"


def test_every_destination_is_a_tab_stop_and_exactly_one_is_checked(harness) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window = harness.window
    window.activateWindow()
    buttons = window._rail.nav_buttons()
    visited: list[str] = []
    for _ in range(12):
        QTest.keyClick(window, Qt.Key.Key_Tab)
        _settle(harness)
        focus = harness.app.focusWidget()
        for key, button in buttons.items():
            if focus is button:
                visited.append(key)
    assert visited[:4] == ["overview", "build_analysis", "settings", "diagnostics"] or set(visited) == set(buttons)
    for page in ("settings", "diagnostics", "overview"):
        window.navigate(page)
        assert [key for key, b in buttons.items() if b.isChecked()] == [page]


def test_fix_first_teaser_is_hidden_when_the_build_failed_to_load(harness) -> None:
    from tests.test_r1_analyze_build_ui import realistic_analysis

    result = realistic_analysis()
    harness.controller.last_analysis = lambda: result  # type: ignore[method-assign]
    harness.states["overview-ready"](harness)
    _settle(harness)
    overview = harness.window._overview
    assert not overview._fix_block.isHidden()  # a loaded build with a cached analysis shows the teaser
    harness.states["overview-build-failed"](harness)
    harness.controller.last_analysis = lambda: result  # type: ignore[method-assign]
    overview.refresh()
    _settle(harness)
    assert overview._fix_block.isHidden()


# ------------------------------------------------------------------------ Windows Text size
@pytest.fixture
def text_scale():
    from exilelens.ui import theme

    yield theme
    theme.apply_text_scale(1.0)


def test_text_scale_is_identity_at_100_percent(text_scale) -> None:
    theme = text_scale
    css = "QLabel { font-size: 13px; } QPushButton { font-size: 13.5px; min-height: 32px; }"
    theme.apply_text_scale(1.0)
    assert theme.scale_stylesheet(css) == css
    assert (theme.CONTROL_HEIGHT, theme.NAV_ITEM_HEIGHT, theme.RAIL_WIDTH, theme.scaled_px(13)) == (32, 34, 208, 13)


def test_text_scale_grows_text_and_text_bearing_sizes_only(text_scale) -> None:
    theme = text_scale
    theme.apply_text_scale(1.25)
    css = theme.scale_stylesheet("QLabel { font-size: 13px; border-radius: 4px; padding: 0 14px; }")
    assert "font-size: 16px" in css and "border-radius: 4px" in css and "padding: 0 14px" in css
    assert theme.CONTROL_HEIGHT == 40 and theme.RAIL_WIDTH == 260
    assert theme.COMPACT_RAIL_WIDTH == 64  # the icon rail holds no text
    theme.apply_text_scale(1.0)  # scaling is always computed from the 100% values, never compounded
    assert theme.CONTROL_HEIGHT == 32 and theme.RAIL_WIDTH == 208


def test_rail_never_takes_over_the_window_at_huge_text(text_scale) -> None:
    text_scale.apply_text_scale(2.25)
    assert text_scale.RAIL_WIDTH == int(round(208 * 1.5))


@pytest.mark.parametrize("stored, expected", [(None, 1.0), (100, 1.0), (125, 1.25), (225, 2.25), (500, 2.25), (50, 1.0)])
def test_system_text_scale_reads_the_windows_setting(monkeypatch, stored, expected) -> None:
    import types

    from exilelens.ui import theme

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def query(_key, name):
        if stored is None:
            raise FileNotFoundError(name)
        return stored, 4

    fake = types.SimpleNamespace(HKEY_CURRENT_USER=0, OpenKey=lambda *a: _Key(), QueryValueEx=query)
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(sys, "platform", "win32")
    assert theme.system_text_scale() == expected


def test_dashboard_follows_the_windows_text_size(harness, monkeypatch) -> None:
    from PySide6.QtGui import QFontInfo

    from exilelens.ui import theme

    monkeypatch.setattr(theme, "system_text_scale", lambda: 1.25)
    from exilelens.ui.dashboard_window import DashboardWindow

    window = DashboardWindow(harness.settings, harness.controller)
    try:
        assert theme.TEXT_SCALE == 1.25
        label = window._overview._build_name
        label.ensurePolished()
        assert QFontInfo(label.font()).pixelSize() == 35  # 28px build name * 1.25
        assert window._rail.width() == 260
        assert window._overview._primary_btn.minimumHeight() >= 40
    finally:
        window.close()
        theme.apply_text_scale(1.0)


@pytest.mark.parametrize(
    "state", ["overview-ready", "overview-attention", "overview-consent", "settings-privacy", "settings-updates-available",
              "settings-patreon-active", "settings-advanced", "diagnostics-degraded", "analyze-results", "analyze-error"],
)
def test_no_visible_text_is_left_at_the_unscaled_size_when_text_is_larger(harness, monkeypatch, state) -> None:
    """Qt resolves widgets that a style sheet gives only a weight against the 9pt application font, so without the
    base rule in ``theme.scale_stylesheet`` some labels would silently ignore the Windows Text size."""
    from PySide6.QtGui import QFontInfo
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QTextEdit

    from exilelens.ui import theme
    from exilelens.ui.dashboard_window import DashboardWindow

    monkeypatch.setattr(theme, "system_text_scale", lambda: 1.25)
    window = DashboardWindow(harness.settings, harness.controller)
    try:
        harness.window = window
        window.show_dashboard()
        harness.states[state](harness)
        window.resize(980, 720)
        _settle(harness)
        small = []
        for kind in (QLabel, QAbstractButton, QComboBox, QLineEdit, QTextEdit):
            for widget in window.findChildren(kind):
                text = widget.text() if hasattr(widget, "text") else ""
                if not widget.isVisibleTo(window) or not str(text).strip():
                    continue
                widget.ensurePolished()
                if QFontInfo(widget.font()).pixelSize() <= 12:
                    small.append((type(widget).__name__, widget.objectName(), str(text)[:24]))
        assert small == []
    finally:
        window.close()
        theme.apply_text_scale(1.0)
