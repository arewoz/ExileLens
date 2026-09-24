"""Regression coverage for the P1.2 always-on-top fix.

The Dashboard/Settings window used to share ``WindowInteractionPolicy.
INTERACTIVE_TOOL`` with the over-the-game tools (Tree Coach, calibration,
pinned comparisons), which forces ``WindowStaysOnTopHint``/``WS_EX_TOPMOST``.
That made a normal desktop window stay pinned above every other unrelated
application. It now uses the dedicated ``INTERACTIVE_APP_WINDOW`` policy,
which drops the topmost bits while leaving every over-the-game tool policy
unchanged.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from exilelens.ui.window_policy import WindowInteractionPolicy, apply_window_interaction_policy


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_dashboard_policy_does_not_request_always_on_top() -> None:
    _app()
    widget = QWidget()
    apply_window_interaction_policy(widget, WindowInteractionPolicy.INTERACTIVE_APP_WINDOW)

    flags = widget.windowFlags()
    assert not (flags & Qt.WindowType.WindowStaysOnTopHint)
    assert widget.property("windowInteractionPolicy") == WindowInteractionPolicy.INTERACTIVE_APP_WINDOW.value


def test_over_the_game_tool_policy_is_unchanged_and_stays_on_top() -> None:
    _app()
    widget = QWidget()
    apply_window_interaction_policy(widget, WindowInteractionPolicy.INTERACTIVE_TOOL)

    flags = widget.windowFlags()
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint)


def test_dashboard_window_uses_the_app_window_policy() -> None:
    from exilelens.app.settings import AppSettings
    from exilelens.app.controller import EvaluationController
    from exilelens.ui.dashboard_window import DashboardWindow

    app = _app()
    settings = AppSettings()
    controller = EvaluationController(settings)
    try:
        dashboard = DashboardWindow(settings, controller)
        try:
            assert dashboard.property("windowInteractionPolicy") == WindowInteractionPolicy.INTERACTIVE_APP_WINDOW.value
            assert not (dashboard.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        finally:
            dashboard.hide()
    finally:
        controller.shutdown()
