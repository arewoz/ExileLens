"""Focused ONBOARDING-01 state and persistence coverage (no PoB worker needed)."""
from __future__ import annotations

import pytest

from exilelens.app.build_state import BuildInfo, BuildState
from exilelens.app.readiness import AppReadiness, derive_readiness
from exilelens.app.settings import AppSettings, ONBOARDING_VERSION, complete_onboarding, load_settings, onboarding_required
from exilelens.app.setup_status import SetupCheck


pytestmark = pytest.mark.itemcheck


class Controller:
    def __init__(self, *, engine="ready", booting=False, error="", build=None):
        self._engine = engine
        self.engine_booting = booting
        self.engine_error = error
        self.build_info = build or BuildInfo()

    def engine_status(self):
        return self._engine


@pytest.fixture(autouse=True)
def usable_pob(monkeypatch):
    monkeypatch.setattr(
        "exilelens.app.readiness.check_pob_folder",
        lambda _path: SetupCheck(True, "FOUND", "PoB2 detected"),
    )


def test_clean_profile_requires_onboarding_and_completion_is_versioned(monkeypatch, tmp_path):
    settings = AppSettings()
    assert onboarding_required(settings)
    monkeypatch.setattr("exilelens.app.settings.settings_path", lambda: tmp_path / "settings.json")
    complete_onboarding(settings)
    assert settings.onboarding_version_completed == ONBOARDING_VERSION
    assert not onboarding_required(settings)
    reloaded = load_settings()
    assert reloaded.onboarding_version_completed == ONBOARDING_VERSION
    assert not onboarding_required(reloaded)


def test_existing_configured_profile_migrates_without_replaying_welcome():
    migrated = AppSettings.from_dict({"schema_version": 20, "pob_path": "pob", "build_path": "build.xml"})
    assert migrated.onboarding_version_completed == ONBOARDING_VERSION


def test_skip_persistence_never_changes_runtime_readiness(monkeypatch):
    settings = AppSettings()
    monkeypatch.setattr("exilelens.app.settings.save_settings", lambda _settings: None)
    complete_onboarding(settings)
    assert derive_readiness(settings, Controller()).state is AppReadiness.BUILD_REQUIRED


@pytest.mark.parametrize(
    ("controller", "expected"),
    [
        (Controller(booting=True), AppReadiness.INITIALIZING),
        (Controller(error="worker failed"), AppReadiness.RUNTIME_ERROR),
        (Controller(build=BuildInfo(state=BuildState.LOADING)), AppReadiness.BUILD_LOADING),
        (Controller(build=BuildInfo(path="stale.xml", state=BuildState.FAILED, error_message="bad XML")), AppReadiness.BUILD_ERROR),
        (Controller(build=BuildInfo(path="build.xml", state=BuildState.READY)), AppReadiness.READY),
    ],
)
def test_readiness_uses_worker_and_build_state(controller, expected):
    assert derive_readiness(AppSettings(), controller).state is expected


def test_missing_pob_wins_over_optimistic_build(monkeypatch):
    monkeypatch.setattr(
        "exilelens.app.readiness.check_pob_folder",
        lambda _path: SetupCheck(False, "NOT FOUND", "Choose PoB2"),
    )
    ready_build = BuildInfo(path="build.xml", state=BuildState.READY)
    assert derive_readiness(AppSettings(), Controller(build=ready_build)).state is AppReadiness.POB_NOT_FOUND


def test_recovery_from_failed_build_is_ready_after_new_success():
    controller = Controller(build=BuildInfo(path="bad.xml", state=BuildState.FAILED, error_message="invalid"))
    assert derive_readiness(AppSettings(), controller).state is AppReadiness.BUILD_ERROR
    controller.build_info = BuildInfo(path="good.xml", state=BuildState.READY)
    assert derive_readiness(AppSettings(), controller).state is AppReadiness.READY
