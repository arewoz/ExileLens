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


def test_rail_and_tray_expose_same_patreon_action_and_overview_has_no_promo(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _app(monkeypatch)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    from exilelens.app.controller import EvaluationController
    from exilelens.app.settings import AppSettings
    from exilelens.ui.dashboard_window import DashboardWindow
    from exilelens.ui.tray import TrayManager
    from PySide6.QtWidgets import QLabel, QMenu, QPushButton

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
        # The old "Enjoying ExileLens?" promo card is gone: Support ExileLens lives in the rail only.
        assert overview.findChild(QPushButton, "patreonSupportCard") is None
        assert "Enjoying ExileLens?" not in [label.text() for label in overview.findChildren(QLabel)]
        assert not [b for b in overview.findChildren(QPushButton) if "Patreon" in b.text()]

        rail_button = dashboard._rail.link_buttons()["support"]
        rail_button.click()

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
        links = dashboard._rail.link_buttons()
        sidebar_button = links["support"]
        assert sidebar_button.text() == "Support ExileLens"
        # Stronger than the utility links, and still the exact shipped Patreon mark.
        assert sidebar_button.objectName() == "railSupport"
        assert links["discord"].objectName() == "railLink" and links["issues"].objectName() == "railLink"
        assert not sidebar_button.icon().isNull()

        labels = [button.text() for button in dashboard.findChildren(QPushButton)]
        assert labels.index("Support ExileLens") < labels.index("Discord") < labels.index("Report an Issue")
    finally:
        controller.shutdown()
        dashboard.deleteLater()
