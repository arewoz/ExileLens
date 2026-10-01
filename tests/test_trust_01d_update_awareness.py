"""TRUST-01D: update awareness -- bounded automatic checks and one non-modal in-app notice."""

from __future__ import annotations

import os
import sys
import time
from types import MethodType, SimpleNamespace

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from exilelens.app.settings import AppSettings
from exilelens.app.updates import service as svc
from exilelens.app.updates.constants import CHECK_COOLDOWN_SECONDS
from exilelens.app.updates.version import ExileLensVersion, Release
from exilelens.ui.update_actions import update_notice_view

pytestmark = [pytest.mark.smoke, pytest.mark.itemcheck]

INSTALLED = "0.4.0"
NEWER = "9.9.9"


class _Clock:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Client:
    def __init__(self, version: str = INSTALLED, fail: bool = False) -> None:
        self.calls = 0
        self.version = version
        self.fail = fail

    def best_newest_release(self):
        self.calls += 1
        if self.fail:
            raise OSError("offline")
        return Release(ExileLensVersion.parse(self.version), "https://github.com/x/y/releases/tag/v", "v", False)


@pytest.fixture
def make_service(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(svc, "save_settings", lambda _s: None)
    monkeypatch.setattr(svc, "ensure_updater_bootstrapped", lambda: None)
    monkeypatch.setattr(svc, "is_packaged", lambda: True)
    monkeypatch.setattr(svc, "installed_version", lambda: ExileLensVersion.parse(INSTALLED))
    created = []

    def make(client=None, clock=None, **settings):
        service = svc.UpdateService(AppSettings(**settings), client=client or _Client(), clock=clock or _Clock())
        created.append(service)
        return service

    yield make
    for service in created:
        service.stop_scheduler()
    assert app is not None


def _wait(service) -> None:
    deadline = time.time() + 5
    while service._check_in_flight and time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    QCoreApplication.processEvents()


def test_startup_check_runs_and_cooldown_bounds_dashboard_opens(make_service) -> None:
    client, clock = _Client(), _Clock()
    service = make_service(client, clock)
    assert service.start_automatic() is True  # startup
    _wait(service)
    for _ in range(5):  # repeated dashboard openings inside the cooldown
        assert service.start_automatic() is False
    assert client.calls == 1
    clock.now += CHECK_COOLDOWN_SECONDS + 5  # dashboard opened after the cooldown
    assert service.start_automatic() is True
    _wait(service)
    assert client.calls == 2


def test_manual_check_ignores_the_automatic_cooldown(make_service) -> None:
    client = _Client()
    service = make_service(client)
    service.start_automatic()
    _wait(service)
    assert service.check_now() is True
    _wait(service)
    assert client.calls == 2


def test_in_flight_request_does_not_reset_the_cooldown_timestamp(make_service) -> None:
    clock = _Clock()
    service = make_service(_Client(), clock)
    service.start_automatic()
    stamp = service.settings.update_last_check_at
    clock.now += 100
    assert service.start_automatic() is False  # check still in flight
    assert service.settings.update_last_check_at == stamp


def test_long_running_session_schedules_the_next_eligible_check(make_service) -> None:
    clock = _Clock()
    service = make_service(_Client(), clock)
    service.start_automatic()
    _wait(service)
    assert service._timer.isActive()
    delay = service.next_automatic_delay_ms()
    assert CHECK_COOLDOWN_SECONDS * 1000 <= delay <= (CHECK_COOLDOWN_SECONDS + 5) * 1000
    clock.now += CHECK_COOLDOWN_SECONDS - 3600
    assert 3600 * 1000 <= service.next_automatic_delay_ms() <= 3605 * 1000
    clock.now += 10 * CHECK_COOLDOWN_SECONDS  # overdue: wakes soon, never below the 60 s floor
    assert service.next_automatic_delay_ms() == 60_000


def test_unpackaged_builds_stay_offline_and_unscheduled(make_service, monkeypatch) -> None:
    client = _Client()
    service = make_service(client)
    monkeypatch.setattr(svc, "is_packaged", lambda: False)
    states = []
    service.state_changed.connect(lambda s, v: states.append(s))
    assert service.start_automatic() is False
    assert client.calls == 0 and not service._timer.isActive() and states == ["unavailable"]
    assert update_notice_view("unavailable", "", "", INSTALLED, None) is None


def test_automatic_network_failure_is_quiet(make_service) -> None:
    service = make_service(_Client(fail=True))
    announced, states = [], []
    service.update_available.connect(lambda *a: announced.append(a))
    service.state_changed.connect(lambda s, v: states.append(s))
    service.start_automatic()
    _wait(service)
    assert states[-1] == "failed" and announced == []
    assert update_notice_view("failed", "", NEWER, INSTALLED, None) is None


def test_pending_update_from_an_earlier_session_verifies_then_downloads(make_service, monkeypatch) -> None:
    service = make_service(update_latest_version=NEWER)
    started = []
    monkeypatch.setattr(service, "_start_check", lambda manual: started.append(manual) or True)
    states = []
    service.download_state_changed.connect(states.append)
    assert service.start_download() is True
    assert started == [True] and states == ["downloading"] and service._download_when_verified


# --------------------------------------------------------------- notice policy


def test_notice_follows_the_update_state_machine() -> None:
    view = update_notice_view("available", "", NEWER, INSTALLED, None)
    assert view["title"] == f"ExileLens {NEWER} is available" and view["detail"] == f"You're using {INSTALLED}"
    assert view["action"] == "Download update" and view["action_kind"] == "download" and view["action_enabled"]
    busy = update_notice_view("available", "downloading", NEWER, INSTALLED, 40)
    assert busy["action"] == "Downloading… 40%" and not busy["action_enabled"]
    ready = update_notice_view("available", "ready", NEWER, INSTALLED, None)
    assert ready["action"] == "Restart & Update" and ready["action_kind"] == "restart"
    installing = update_notice_view("available", "installing", NEWER, INSTALLED, None)
    assert not installing["action_enabled"] and not installing["later_visible"]


def test_notice_hidden_for_current_unverified_stale_and_dismissed() -> None:
    assert update_notice_view("current", "", INSTALLED, INSTALLED, None) is None
    assert update_notice_view("available", "", "0.3.0", INSTALLED, None) is None  # old persisted remote
    assert update_notice_view("verification_failed", "", NEWER, INSTALLED, None) is None
    assert update_notice_view("available", "", NEWER, INSTALLED, None, {NEWER}) is None
    assert update_notice_view("available", "", "10.0.0", INSTALLED, None, {NEWER}) is not None


def _fake_dashboard(service):
    from exilelens.ui import dashboard_window as dw

    fake = SimpleNamespace(
        update_service=service,
        _update_check_state="unchecked",
        _update_download_state="",
        _update_remote_version="",
        _update_progress_percent=None,
    )
    for name in ("_build_update_notice", "_refresh_update_notice", "_dismiss_update_notice", "_open_release_page", "_footer_update_action"):
        setattr(fake, name, MethodType(getattr(dw.DashboardWindow, name), fake))
    fake._build_update_notice()
    return fake


def test_dashboard_notice_shows_once_dismisses_for_the_session_and_footer_state_stays(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    import exilelens._version as version_module

    monkeypatch.setattr(version_module, "__version__", INSTALLED)
    calls = []
    service = SimpleNamespace(start_download=lambda: calls.append("download"), release_url=lambda: "https://github.com/x/y/releases/tag/v")
    fake = _fake_dashboard(service)
    # discovered while the dashboard was hidden: the widget state is already correct when it is later shown
    fake._update_check_state, fake._update_remote_version = "available", NEWER
    fake._refresh_update_notice()
    assert not fake._update_notice.isHidden()
    assert fake._update_notice_title.text() == f"ExileLens {NEWER} is available"
    assert not fake._update_notice_whats_new.isHidden()
    fake._update_notice_action.click()
    assert calls == ["download"]  # reuses the existing UpdateService path
    fake._update_notice_later.click()
    assert fake._update_notice.isHidden()
    fake._refresh_update_notice()  # same version, same session: never re-pops
    assert fake._update_notice.isHidden()
    assert fake._update_check_state == "available"  # footer / tray state is untouched by Later
    # a new application session starts with an empty dismissed set and shows the pending update again
    again = _fake_dashboard(service)
    again._update_check_state, again._update_remote_version = "available", NEWER
    again._refresh_update_notice()
    assert not again._update_notice.isHidden()
