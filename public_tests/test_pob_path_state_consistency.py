"""Focused regression coverage for PoB folder selection state handling."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from exilelens.app.settings import AppSettings
from exilelens.items.item_check_settings import ItemCheckProSettings
from exilelens.ui.dashboard_pages import SettingsPage


def _make_valid_pob(root: Path) -> Path:
    for relative in (
        "Launch.lua",
        "Modules/Main.lua",
        "Modules/Build.lua",
        "Data/ModItem.lua",
        "lua51.dll",
        "lua/xml.lua",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    return root


class _HotkeyStub(QObject):
    hotkey_tested = Signal()


class _DummyController(QObject):
    value_profile_changed = Signal(str)
    build_changed = Signal(object)
    baseline_state_changed = Signal(object)
    engine_ready = Signal()
    engine_failed = Signal(str)

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.settings = settings
        self.build_info = SimpleNamespace(state=None, path="", name="")
        self.price_check_hotkey = _HotkeyStub()
        self.restart_calls = 0

    def engine_status(self) -> str:
        return "ready"

    def active_build_status(self):
        return None

    def restart_engine(self) -> None:
        self.restart_calls += 1

    def item_check_settings(self) -> ItemCheckProSettings:
        return ItemCheckProSettings.from_dict(self.settings.item_check_pro)


def _page(settings: AppSettings, controller: _DummyController | None = None) -> SettingsPage:
    app = QApplication.instance() or QApplication([])
    assert app is not None
    controller = controller or _DummyController(settings)
    return SettingsPage(settings, controller)


def test_invalid_candidate_keeps_valid_connection(monkeypatch, tmp_path: Path) -> None:
    valid_path = _make_valid_pob(tmp_path / "previous-good")
    settings = AppSettings(pob_path=str(valid_path))
    controller = _DummyController(settings)
    page = _page(settings, controller)
    page._pob_edit.setText(str(tmp_path / "not-a-pob"))

    saved: list[str] = []
    monkeypatch.setattr("exilelens.ui.dashboard_pages.save_settings", lambda _settings: saved.append(_settings.pob_path))
    monkeypatch.setattr("exilelens.ui.dashboard_pages.QMessageBox.warning", lambda *args, **kwargs: None)

    page._apply_pob_path()

    assert settings.pob_path == str(valid_path)
    assert page._pob_edit.text() == str(valid_path)
    assert saved == []
    assert controller.restart_calls == 0


def test_invalid_candidate_keeps_unconfigured_state(monkeypatch, tmp_path: Path) -> None:
    settings = AppSettings(pob_path="")
    controller = _DummyController(settings)
    page = _page(settings, controller)
    page._pob_edit.setText(str(tmp_path / "not-a-pob"))

    saved: list[str] = []
    monkeypatch.setattr("exilelens.ui.dashboard_pages.save_settings", lambda _settings: saved.append(_settings.pob_path))
    monkeypatch.setattr("exilelens.ui.dashboard_pages.QMessageBox.warning", lambda *args, **kwargs: None)

    page._apply_pob_path()

    assert settings.pob_path == ""
    assert page._pob_edit.text() == ""
    assert saved == []
    assert controller.restart_calls == 0


def test_valid_candidate_persists_and_restarts(monkeypatch, tmp_path: Path) -> None:
    settings = AppSettings(pob_path="")
    controller = _DummyController(settings)
    page = _page(settings, controller)
    candidate = _make_valid_pob(tmp_path / "next-good")
    page._pob_edit.setText(str(candidate))

    saved: list[str] = []
    monkeypatch.setattr("exilelens.ui.dashboard_pages.save_settings", lambda _settings: saved.append(_settings.pob_path))
    monkeypatch.setattr("exilelens.ui.dashboard_pages.QMessageBox.warning", lambda *args, **kwargs: None)

    page._apply_pob_path()

    assert settings.pob_path == str(candidate)
    assert saved == [str(candidate)]
    assert controller.restart_calls == 1
