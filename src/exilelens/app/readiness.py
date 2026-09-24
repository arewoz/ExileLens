"""Authoritative application readiness used by setup and recovery UI.

This module deliberately observes the controller; it never starts a worker or loads a
build.  Keeping the derivation here prevents the tray, dashboard and first-run flow
from disagreeing about whether Item Check can actually run.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from exilelens.app.build_state import BuildState
from exilelens.app.setup_status import check_pob_folder


class AppReadiness(str, Enum):
    INITIALIZING = "INITIALIZING"
    POB_NOT_FOUND = "POB_NOT_FOUND"
    BUILD_REQUIRED = "BUILD_REQUIRED"
    BUILD_LOADING = "BUILD_LOADING"
    BUILD_ERROR = "BUILD_ERROR"
    READY = "READY"
    RUNTIME_ERROR = "RUNTIME_ERROR"


@dataclass(frozen=True)
class ReadinessStatus:
    state: AppReadiness
    title: str
    detail: str = ""

    @property
    def ready(self) -> bool:
        return self.state is AppReadiness.READY

    @property
    def support_action_available(self) -> bool:
        return self.state in {AppReadiness.BUILD_ERROR, AppReadiness.RUNTIME_ERROR}


def derive_readiness(settings: Any, controller: Any | None) -> ReadinessStatus:
    """Return readiness from the exact worker/build state Item Check will use."""
    pob = check_pob_folder(getattr(settings, "pob_path", ""))
    if not pob.ok:
        return ReadinessStatus(AppReadiness.POB_NOT_FOUND, pob.label, pob.detail)
    if controller is None:
        return ReadinessStatus(AppReadiness.INITIALIZING, "Starting Path of Building", "Checking the PoB2 runtime…")
    if bool(getattr(controller, "engine_booting", False)):
        return ReadinessStatus(AppReadiness.INITIALIZING, "Starting Path of Building", "Checking the PoB2 runtime…")
    error = str(getattr(controller, "engine_error", "") or "")
    if error:
        return ReadinessStatus(AppReadiness.RUNTIME_ERROR, "Path of Building needs attention", error)
    engine_status = str(controller.engine_status() or "")
    if engine_status != "ready":
        return ReadinessStatus(AppReadiness.INITIALIZING, "Starting Path of Building", "Waiting for the PoB2 runtime…")
    info = getattr(controller, "build_info", None)
    state = getattr(info, "state", BuildState.NO_BUILD)
    if state in {BuildState.LOADING, BuildState.RELOADING}:
        return ReadinessStatus(AppReadiness.BUILD_LOADING, "Loading build", getattr(info, "name", "") or "PoB is preparing your build…")
    if state in {BuildState.FAILED, BuildState.ERROR}:
        return ReadinessStatus(AppReadiness.BUILD_ERROR, "Build could not be loaded", getattr(info, "error_message", "") or "Choose another PoB build.")
    if state is BuildState.READY and bool(getattr(info, "is_ready", False)):
        name = getattr(info, "name", "") or "Current build"
        return ReadinessStatus(AppReadiness.READY, "Ready", f"{name} is loaded and Item Check is ready.")
    return ReadinessStatus(AppReadiness.BUILD_REQUIRED, "Build required", "Choose a PoB build XML to compare items against your build.")
