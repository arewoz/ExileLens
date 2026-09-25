"""Regression tests for unified updates and Diagnostics UX cleanup."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from exilelens.app.settings import AppSettings
from exilelens.app.updates.channels import select_newest_official_release
from exilelens.app.updates.version import ExileLensVersion, Release, parse_release_payload
from exilelens.app.updates import service as update_service_module
from exilelens.app.updates.service import NewestReleaseVerificationFailed, UpdateService
from exilelens.app import update_check


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytestmark = pytest.mark.smoke


def _release(version: str, *, prerelease: bool = False) -> Release:
    parsed = ExileLensVersion.parse(version)
    assert parsed is not None
    return Release(parsed, update_check.GITHUB_RELEASES_URL, f"v{version}", prerelease)


def test_select_newest_prefers_higher_version_not_publish_order() -> None:
    stable_old = _release("0.4.0")
    beta_newer = _release("0.4.1b1", prerelease=True)
    # GitHub list order: stable published after beta but numerically older patch line
    assert select_newest_official_release([stable_old, beta_newer]) == beta_newer
    assert select_newest_official_release([beta_newer, stable_old]) == beta_newer


def test_select_newest_stable_beats_older_beta() -> None:
    beta = _release("0.4.0b9", prerelease=True)
    stable = _release("0.4.0")
    assert select_newest_official_release([beta, stable]) == stable


def test_parse_release_skips_draft_and_bad_tags() -> None:
    assert parse_release_payload({"tag_name": "v1.0.0", "draft": True, "assets": []}) is None
    assert parse_release_payload({"tag_name": "not-a-version", "draft": False, "assets": []}) is None
    ok = parse_release_payload(
        {"tag_name": "v0.5.0b1", "draft": False, "prerelease": True, "assets": []}
    )
    assert ok is not None and str(ok.version) == "0.5.0b1"


def test_github_client_best_newest_release() -> None:
    payloads = [
        {"tag_name": "v0.3.0", "draft": False, "prerelease": False, "assets": []},
        {"tag_name": "v0.4.0b2", "draft": False, "prerelease": True, "assets": []},
        {"tag_name": "v0.4.0", "draft": False, "prerelease": False, "assets": []},
    ]

    class _Response:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self, _max: int) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    client = update_check.GitHubReleaseClient(
        lambda *_a, **_k: _Response(json.dumps(payloads).encode("utf-8"))
    )
    best = client.best_newest_release()
    assert best is not None and str(best.version) == "0.4.0"


def test_legacy_update_channel_setting_is_preserved(monkeypatch) -> None:
    settings = AppSettings(update_channel="stable")
    service = UpdateService(settings)
    monkeypatch.setattr(update_service_module, "save_settings", lambda _s: None)
    service._finish_check(
        NewestReleaseVerificationFailed(_release("9.9.9b9", prerelease=True), "manifest_verification_failed"),
        False,
    )
    assert settings.update_channel == "stable"
    assert settings.update_latest_version == "9.9.9b9"


def test_start_check_uses_best_newest_release(monkeypatch) -> None:
    settings = AppSettings(update_channel="stable")
    calls: list[str] = []

    class _Client:
        def best_newest_release(self):
            calls.append("newest")
            return None

        def best_release_for_channel(self, _channel):
            calls.append("channel")
            return None

    def _immediate_thread(target=None, **_kwargs):
        class _Runner:
            def start(self_inner):
                target()

        return _Runner()

    service = UpdateService(settings, client=_Client())
    monkeypatch.setattr(update_service_module, "is_packaged", lambda: True)
    monkeypatch.setattr(update_service_module, "save_settings", lambda _s: None)
    monkeypatch.setattr(update_service_module.threading, "Thread", _immediate_thread)
    assert service.check_now()
    assert calls == ["newest"]


def test_newest_manifest_failure_does_not_offer_download(monkeypatch) -> None:
    settings = AppSettings()
    service = UpdateService(settings)
    monkeypatch.setattr(update_service_module, "save_settings", lambda _s: None)
    states: list[tuple[str, str]] = []
    service.state_changed.connect(lambda state, value: states.append((state, value)))
    failed = NewestReleaseVerificationFailed(_release("9.9.9b9", prerelease=True), "manifest_verification_failed")
    service._finish_check(failed, manual=False)
    assert states == [("verification_failed", "9.9.9b9")]
    assert service._availability is None
    assert service._verified_manifest is None


def test_dashboard_and_settings_share_update_service_instance(monkeypatch, tmp_path) -> None:
    from PySide6.QtWidgets import QApplication

    from exilelens.app.controller import EvaluationController
    from exilelens.ui.dashboard_window import DashboardWindow

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    QApplication.instance() or QApplication([])
    settings = AppSettings()
    controller = EvaluationController(settings)
    dashboard = DashboardWindow(settings, controller)
    try:
        assert dashboard._settings_page.update_service is dashboard.update_service
        assert dashboard._diagnostics.update_service is dashboard.update_service
        dashboard.update_service.state_changed.emit("available", "8.8.8b8")
        assert "8.8.8b8" in dashboard._settings_page._updates_panel._status.text()
        assert "8.8.8b8" in dashboard._update_indicator.text()
    finally:
        controller.shutdown()
        dashboard.deleteLater()


def test_copy_diagnostics_uses_extended_summary(monkeypatch, tmp_path) -> None:
    from exilelens.ui import recovery_actions

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    clipboard: list[str] = []

    class _Clip:
        def setText(self, text: str) -> None:
            clipboard.append(text)

    monkeypatch.setattr(recovery_actions.QApplication, "clipboard", lambda: _Clip())
    controller = SimpleNamespace(settings=AppSettings())
    recovery_actions.copy_diagnostics(controller)
    assert clipboard
    payload = json.loads(clipboard[0])
    assert payload["application"]["update_selection_policy"] == "newest_verified_official_release"


def test_installed_latest_skips_manifest_verification(monkeypatch) -> None:
    from exilelens._version import __version__

    installed = ExileLensVersion.parse(__version__)
    assert installed is not None
    settings = AppSettings()
    manifest_calls: list[str] = []

    class _Client:
        def best_newest_release(self):
            return _release(str(installed))

        def fetch_json(self, url: str):
            manifest_calls.append(url)
            raise RuntimeError("should not fetch")

    def _immediate_thread(target=None, **_kwargs):
        class _Runner:
            def start(self_inner):
                target()

        return _Runner()

    service = UpdateService(settings, client=_Client())
    monkeypatch.setattr(update_service_module, "is_packaged", lambda: True)
    monkeypatch.setattr(update_service_module, "save_settings", lambda _s: None)
    monkeypatch.setattr(update_service_module.threading, "Thread", _immediate_thread)
    states: list[tuple[str, str]] = []
    service.state_changed.connect(lambda state, value: states.append((state, value)))
    assert service.check_now()
    assert manifest_calls == []
    assert states[-1][0] == "current"


def test_newer_release_without_manifest_is_rejected(monkeypatch) -> None:
    from exilelens._version import __version__

    installed = ExileLensVersion.parse(__version__)
    assert installed is not None
    newer = f"{installed.major}.{installed.minor}.{installed.patch}b{installed.beta + 1}"
    settings = AppSettings()

    class _Client:
        def best_newest_release(self):
            return _release(newer, prerelease=True)

    def _immediate_thread(target=None, **_kwargs):
        class _Runner:
            def start(self_inner):
                target()

        return _Runner()

    service = UpdateService(settings, client=_Client())
    monkeypatch.setattr(update_service_module, "is_packaged", lambda: True)
    monkeypatch.setattr(update_service_module, "save_settings", lambda _s: None)
    monkeypatch.setattr(update_service_module.threading, "Thread", _immediate_thread)
    states: list[tuple[str, str]] = []
    downloads: list[str] = []
    service.state_changed.connect(lambda state, value: states.append((state, value)))
    service.download_state_changed.connect(downloads.append)
    assert service.check_now()
    assert states[-1] == ("verification_failed", newer)
    assert service._availability is None
    assert downloads == [""]
    assert not service.start_download()


def test_diagnostics_advanced_section_is_collapsed_by_default() -> None:
    from PySide6.QtWidgets import QApplication

    from exilelens.ui.dashboard_pages import DiagnosticsPage

    QApplication.instance() or QApplication([])
    settings = AppSettings()
    page = DiagnosticsPage(SimpleNamespace(settings=settings), settings, UpdateService(settings))
    assert hasattr(page, "_advanced")
    assert not page._advanced.is_expanded()
    assert not page._event_history.is_expanded()
    assert not page._technical_report.is_expanded()


def test_diagnostics_nested_sections_expand_independently() -> None:
    from PySide6.QtWidgets import QApplication

    from exilelens.ui.dashboard_pages import DiagnosticsPage

    QApplication.instance() or QApplication([])
    settings = AppSettings()
    page = DiagnosticsPage(SimpleNamespace(settings=settings), settings, UpdateService(settings))
    page._advanced.set_expanded(True)
    page._event_history.set_expanded(True)
    assert page._event_history.is_expanded()
    assert not page._technical_report.is_expanded()
    page._technical_report.set_expanded(True)
    assert page._event_history.is_expanded()
    assert page._technical_report.is_expanded()
