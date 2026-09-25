"""Focused public coverage for the manual failure-to-support flow."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from exilelens.app.settings import AppSettings
from exilelens.app.update_check import UpdateCheckService
from exilelens.ui import recovery_actions
from exilelens.ui.dashboard_pages import DiagnosticsPage
from exilelens.ui.health import derive_health


ROOT = Path(__file__).resolve().parents[1]


class _Clipboard:
    value = ""

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API shape
        self.value = text


class _Controller:
    settings = AppSettings()
    build_info = SimpleNamespace(state=None, path="", name="")
    price_check_hotkey = None

    def engine_status(self) -> str:
        return "stopped"

    def active_build_status(self):
        return None

    def reload_evaluation_build(self) -> None:
        pass


def test_copy_diagnostics_uses_extended_summary_when_settings_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    clipboard = _Clipboard()
    monkeypatch.setattr(recovery_actions.QApplication, "clipboard", lambda: clipboard)
    monkeypatch.setattr(
        recovery_actions,
        "copy_extended_diagnostic_summary",
        lambda _controller, _settings, **kwargs: "EXTENDED REPORT",
    )

    controller = _Controller()
    assert recovery_actions.copy_diagnostics(controller) == "EXTENDED REPORT"


def test_copy_diagnostics_falls_back_without_settings(monkeypatch) -> None:
    clipboard = _Clipboard()
    monkeypatch.setattr(recovery_actions.QApplication, "clipboard", lambda: clipboard)
    monkeypatch.setattr(
        "exilelens.app.diagnostics.render_global_diagnostics", lambda _controller: "SAFE REPORT"
    )

    assert recovery_actions.copy_diagnostics(object()) == "SAFE REPORT"
    assert clipboard.value == "SAFE REPORT"


def test_diagnostics_copy_gives_non_blocking_feedback(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    assert app is not None
    settings = AppSettings()
    page = DiagnosticsPage(_Controller(), settings, UpdateCheckService(settings))
    monkeypatch.setattr(
        recovery_actions,
        "copy_diagnostics",
        lambda _controller, _settings=None, **kwargs: "SAFE REPORT",
    )

    page._copy()

    assert page._copy_btn.text() == "Diagnostics copied"


def test_degraded_pob_keeps_recovery_action() -> None:
    settings = AppSettings(pob_path="")
    health = derive_health(_Controller(), settings)

    assert health.pob.status == "error"
    assert health.pob.action == "Locate Path of Building"


def test_public_and_packaged_docs_describe_manual_support_sharing() -> None:
    for relative in ("README.md", "packaging/README.txt"):
        text = (ROOT / relative).read_text(encoding="utf-8").lower()
        assert "copy diagnostic" in text
        assert "nothing is submitted automatically" in text
        assert "logs stay local" in text
        assert "github releases" in text
        assert "itch.io" not in text
