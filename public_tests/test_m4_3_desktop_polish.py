"""Focused offline coverage for M4.3 desktop UX polish."""

from __future__ import annotations

import pytest

from exilelens._version import __version__
from exilelens.ui.update_actions import footer_update_summary, tray_update_action_label
from exilelens.ui.ui_icons import icon_path, load_icon


@pytest.mark.smoke
def test_bundled_ui_icons_resolve_from_repo() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    for name in ("discord", "github", "download"):
        path = icon_path(name)
        assert path is not None and path.is_file(), name
        icon = load_icon(name)
        assert icon is not None and not icon.isNull(), name


def test_footer_version_uses_canonical_module() -> None:
    summary = footer_update_summary("available", "", "0.9.0b1", None)
    assert summary == "Update available: 0.9.0b1"
    assert __version__  # imported canonical version is non-empty


def test_tray_and_footer_update_labels_stay_aligned() -> None:
    remote = "0.9.0b1"
    footer = footer_update_summary("available", "", remote, None)
    tray_label, visible, enabled = tray_update_action_label("available", "", remote)
    assert "0.9.0b1" in footer
    assert remote in tray_label
    assert visible and enabled

    footer_dl = footer_update_summary("available", "downloading", remote, 42)
    tray_dl, tray_visible, tray_enabled = tray_update_action_label("available", "downloading", remote)
    assert "42%" in footer_dl
    assert tray_visible
    assert not tray_enabled

    footer_ready = footer_update_summary("available", "ready", remote, None)
    tray_ready, ready_visible, ready_enabled = tray_update_action_label("available", "ready", remote)
    assert "ready" in footer_ready.lower()
    assert tray_ready.startswith("Restart")
    assert ready_visible and ready_enabled


def test_dashboard_footer_version_label(monkeypatch, tmp_path) -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from exilelens.app.controller import EvaluationController
    from exilelens.app.settings import AppSettings
    from exilelens.ui.dashboard_window import DashboardWindow

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    QApplication.instance() or QApplication([])
    settings = AppSettings()
    controller = EvaluationController(settings)
    dashboard = DashboardWindow(settings, controller)
    try:
        assert dashboard._version_label.text() == f"ExileLens {__version__}"
        dashboard.update_service.state_changed.emit("available", "9.9.9b9")
        assert "9.9.9b9" in dashboard._update_indicator.text()
        assert not dashboard._footer_download_btn.isHidden()
    finally:
        controller.shutdown()
        dashboard.deleteLater()
