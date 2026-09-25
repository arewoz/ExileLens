"""Focused regressions for the voluntary Patreon support surfaces."""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.itemcheck


def _app(monkeypatch: pytest.MonkeyPatch):
    if sys.platform != "win32":
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_open_patreon_uses_central_url_and_handles_browser_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from exilelens.ui import recovery_actions

    opened = []
    monkeypatch.setattr(
        recovery_actions.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toString()) or False,
    )

    assert recovery_actions.open_patreon() is False
    assert opened == [recovery_actions.PATREON_URL]


def test_open_patreon_handles_browser_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    from exilelens.ui import recovery_actions

    def fail(_url):
        raise RuntimeError("browser unavailable")

    monkeypatch.setattr(recovery_actions.QDesktopServices, "openUrl", fail)

    assert recovery_actions.open_patreon() is False


def test_overview_and_tray_expose_same_patreon_action(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _app(monkeypatch)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    from exilelens.app.controller import EvaluationController
    from exilelens.app.settings import AppSettings
    from exilelens.ui.dashboard_window import DashboardWindow
    from exilelens.ui.tray import TrayManager
    from PySide6.QtWidgets import QMenu, QPushButton

    settings = AppSettings()
    controller = EvaluationController(settings)
    dashboard = DashboardWindow(settings, controller)

    class _OverlayStub:
        def show_last_result(self, _payload) -> None:
            return None

        def remember_position(self) -> None:
            return None

    tray = TrayManager(settings, controller, _OverlayStub(), dashboard)
    calls = []
    monkeypatch.setattr("exilelens.ui.recovery_actions.open_patreon", lambda: calls.append(True))
    try:
        overview = dashboard._overview
        dashboard_button = next(
            button
            for button in overview.findChildren(QPushButton)
            if button.text() == "Support on Patreon ↗"
        )
        dashboard_button.click()

        tray_action = next(
            action
            for menu in tray.contextMenu().findChildren(QMenu)
            for action in menu.actions()
            if action.text() == "Support on Patreon ↗"
        )
        tray_action.trigger()
        assert calls == [True, True]
    finally:
        controller.shutdown()
        tray.deleteLater()
        dashboard.deleteLater()
