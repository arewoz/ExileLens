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
    from PySide6.QtWidgets import QFrame, QLabel, QMenu, QPushButton

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
        support_card = overview.findChild(QFrame, "patreonSupportCard")
        assert support_card is not None
        assert "SUPPORT EXILELENS" in [label.text() for label in support_card.findChildren(QLabel)]
        dashboard_button = next(
            button
            for button in overview.findChildren(QPushButton)
            if button.text() == "Support on Patreon"
        )
        dashboard_button.click()

        tray_action = next(
            action
            for menu in tray.contextMenu().findChildren(QMenu)
            for action in menu.actions()
            if action.text() == "Support on Patreon ↗"
        )
        assert not tray_action.icon().isNull()
        tray_action.trigger()
        assert calls == [True, True]
    finally:
        controller.shutdown()
        tray.deleteLater()
        dashboard.deleteLater()


def test_patreon_icon_uses_existing_asset_loader_and_sidebar_slot(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _app(monkeypatch)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    from exilelens.app.controller import EvaluationController
    from exilelens.app.settings import AppSettings
    from exilelens.ui.dashboard_window import DashboardWindow
    from exilelens.ui.ui_icons import icon_path, load_icon
    from PySide6.QtWidgets import QPushButton

    assert icon_path("patreon") is not None
    assert icon_path("patreon").name == "patreon.svg"
    assert load_icon("patreon") is not None

    settings = AppSettings()
    controller = EvaluationController(settings)
    dashboard = DashboardWindow(settings, controller)
    try:
        sidebar_button = dashboard.findChild(QPushButton, "navButtonPatreon")
        assert sidebar_button is not None
        assert sidebar_button.text() == "Support ExileLens"
        assert not sidebar_button.icon().isNull()

        labels = [button.text() for button in dashboard.findChildren(QPushButton)]
        assert labels.index("Support ExileLens") < labels.index("Discord") < labels.index("Report an Issue")
    finally:
        controller.shutdown()
        dashboard.deleteLater()
