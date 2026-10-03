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
