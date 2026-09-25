"""Mandatory Qt application startup composition regressions.

These tests exercise the production UI construction path that runs before the
event loop handles real PoB, network updates, or global keyboard hooks.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytestmark = pytest.mark.smoke


@dataclass
class _FakeLock:
    acquired: bool = True
    reason: str = "test"


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _cleanup_runtime(runtime, request: pytest.FixtureRequest) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent

    def _finalizer() -> None:
        if getattr(runtime, "controller", None) is not None:
            runtime.controller.shutdown()
        tray = getattr(runtime, "tray", None)
        if tray is not None:
            menu = tray.contextMenu()
            tray.setContextMenu(None)
            if menu is not None:
                menu.deleteLater()
            tray.deleteLater()
        if getattr(runtime, "dashboard", None) is not None:
            runtime.dashboard.deleteLater()
        if getattr(runtime, "overlay", None) is not None:
            runtime.overlay.deleteLater()
        if getattr(runtime, "controller", None) is not None:
            runtime.controller.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        _app().processEvents()

    request.addfinalizer(_finalizer)


def test_application_startup_composition_and_tray_rebuild(monkeypatch: pytest.MonkeyPatch, tmp_path, request) -> None:
    """Compose dashboard + tray like production startup; rebuild tray menu twice."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from PySide6.QtCore import QTimer

    from exilelens.app.main import ExileLensApp
    from exilelens.app.single_instance import InstanceLock
    from exilelens.app.update_check import UpdateService
    from exilelens.ui.update_actions import tray_update_action_label

    app = _app()
    app.setQuitOnLastWindowClosed(False)

    monkeypatch.setattr(
        "exilelens.app.main.acquire_single_instance_lock",
        lambda: InstanceLock(acquired=True, reason="test"),
    )
    monkeypatch.setattr(ExileLensApp, "_start_instance_server", lambda self: None)
    monkeypatch.setattr(UpdateService, "start_automatic", lambda self: False)

    runtime = ExileLensApp()
    _cleanup_runtime(runtime, request)

    runtime._compose_primary_ui(quit_callback=lambda: None)
    assert runtime.controller is not None
    assert runtime.dashboard is not None
    assert runtime.overlay is not None
    assert runtime.tray is not None
    assert isinstance(runtime.dashboard.update_service, UpdateService)

    monkeypatch.setattr(runtime.controller.price_check_hotkey, "start", lambda: True)
    runtime._wire_signals()
    app.processEvents()

    # Regression for tray.py rebuild_menu using bare `settings`.
    runtime.tray.rebuild_menu()
    runtime.tray.rebuild_menu()
    menu = runtime.tray.contextMenu()
    assert menu is not None
    labels = [action.text() for action in menu.actions() if not action.isSeparator()]
    assert any(text == "Check for Updates" for text in labels)
    assert runtime.tray._update_action is not None
    assert runtime.tray._check_updates_action is not None

    runtime.dashboard.update_service.state_changed.emit("available", "9.9.9b9")
    app.processEvents()
    label, visible, enabled = tray_update_action_label(
        runtime.tray._update_check_state,
        runtime.tray._update_download_state,
        runtime.tray._update_remote_version,
    )
    assert visible and enabled and "9.9.9b9" in label

    runtime.dashboard.update_service.download_state_changed.emit("downloading")
    app.processEvents()
    _, visible_dl, enabled_dl = tray_update_action_label(
        runtime.tray._update_check_state,
        runtime.tray._update_download_state,
        runtime.tray._update_remote_version,
    )
    assert visible_dl and not enabled_dl

    # Deferred update check must not crash when packaged mode is off.
    QTimer.singleShot(0, runtime.dashboard.update_service.start_automatic)
    app.processEvents()


def test_tray_menu_icon_path_executes_rebuild_menu_settings_scope(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Fails if rebuild_menu references undefined `settings` when applying icons."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from exilelens.app.controller import EvaluationController
    from exilelens.app.settings import AppSettings
    from exilelens.ui.dashboard_window import DashboardWindow
    from exilelens.ui.tray import TrayManager

    _app()
    settings = AppSettings()
    controller = EvaluationController(settings)
    dashboard = DashboardWindow(settings, controller)

    class _OverlayStub:
        def show_last_result(self, _payload) -> None:
            return None

        def remember_position(self) -> None:
            return None

    tray = TrayManager(settings, controller, _OverlayStub(), dashboard)
    try:
        tray.rebuild_menu()
        assert float(getattr(tray.settings, "ui_scale", 1.0) or 1.0) >= 0.5
    finally:
        controller.shutdown()
        tray.deleteLater()
        dashboard.deleteLater()
