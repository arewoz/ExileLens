"""Allowlisted, privacy-safe global application diagnostics.

This module deliberately receives the live controller but only derives bounded
support facts from it. Paths, worker output, item data, settings dumps, and raw
exception text must never enter this model.
"""

from __future__ import annotations

import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from poe2value import SUPPORTED_POB_HEAD
from poe2value._version import build_identity
from poe2value.app.build_state import BuildState
from poe2value.app.setup_status import check_pob_folder
from poe2value.config import PobConfig

_COMMIT = re.compile(r"[0-9a-f]{40}")
_LAYOUTS = {"source", "installed"}
_ARCHITECTURES = {"amd64", "x86_64", "arm64", "aarch64", "x86", "i386"}


def _commit(value: str) -> str:
    value = str(value or "").strip().lower()
    return value[:12] if _COMMIT.fullmatch(value) else "unknown"


def _windows() -> str:
    release, version, _csd, _ptype = platform.win32_ver()
    value = " ".join(part for part in (release, version) if part).strip()
    return value if value else "unknown"


def _architecture() -> str:
    value = platform.machine().strip().lower()
    return value if value in _ARCHITECTURES else "unknown"


def _engine_state(controller: Any) -> str:
    try:
        value = str(controller.engine_status() or "")
    except Exception:  # noqa: BLE001 - diagnostics must never interrupt the UI
        return "unknown"
    if value == "ready":
        return "ready"
    if value == "starting":
        return "starting"
    if value == "stopped":
        return "stopped"
    if value.startswith("failed:"):
        return "failed"
    return "unknown"


def _build_state(controller: Any) -> str:
    state = getattr(getattr(controller, "build_info", None), "state", None)
    if isinstance(state, BuildState):
        return state.value.lower()
    return "unknown"


def _hotkey_state(controller: Any) -> str:
    hotkey = getattr(controller, "price_check_hotkey", None)
    if hotkey is None:
        return "unknown"
    if bool(getattr(hotkey, "hook_registered", False)):
        return "waiting_for_release" if bool(getattr(hotkey, "waiting_for_release", False)) else "ready"
    return "unavailable"


def _pob_state(settings: Any) -> tuple[str, str]:
    path = str(getattr(settings, "pob_path", "") or "")
    try:
        available = "yes" if check_pob_folder(path).ok else "no"
        layout = PobConfig(Path(path)).layout if path else "unknown"
    except Exception:  # noqa: BLE001 - a bad configured path is only unavailable
        return "no", "unknown"
    return available, layout if layout in _LAYOUTS else "unknown"


def _recent_error(engine: str, build: str) -> tuple[str, str]:
    if engine == "failed":
        return "PoB worker", "failed"
    if build in {"failed", "error"}:
        return "Build", "load_failed"
    return "none", "none"


@dataclass(frozen=True)
class GlobalDiagnostics:
    version: str
    build: str
    mode: str
    python: str
    windows: str
    architecture: str
    pob_available: str
    pob_layout: str
    supported_pob_revision: str
    build_state: str
    worker: str
    hotkey: str
    overlay: str
    recent_error_subsystem: str
    recent_error_status: str

    def render(self) -> str:
        return "\n".join(
            (
                "ExileLens Diagnostics",
                "",
                "App",
                f"Version: {self.version}",
                f"Build: {self.build}",
                f"Mode: {self.mode}",
                "",
                "Runtime",
                f"Windows: {self.windows}",
                f"Python: {self.python}",
                f"Architecture: {self.architecture}",
                "",
                "Path of Building",
                f"Available: {self.pob_available}",
                f"Layout: {self.pob_layout}",
                f"Supported revision: {self.supported_pob_revision}",
                f"Build state: {self.build_state}",
                "",
                "Health",
                f"Worker: {self.worker}",
                f"Item check hotkey: {self.hotkey}",
                f"Overlay: {self.overlay}",
                "",
                "Recent error",
                f"Subsystem: {self.recent_error_subsystem}",
                f"Status: {self.recent_error_status}",
            )
        )


def build_global_diagnostics(controller: Any) -> GlobalDiagnostics:
    """Create a global report solely from explicit, bounded support facts."""
    identity = build_identity()
    settings = getattr(controller, "settings", None)
    engine = _engine_state(controller)
    build = _build_state(controller)
    pob_available, pob_layout = _pob_state(settings)
    error_subsystem, error_status = _recent_error(engine, build)
    return GlobalDiagnostics(
        version=identity.version,
        build=_commit(identity.git_commit),
        mode=identity.execution_mode,
        python=identity.python_version,
        windows=_windows(),
        architecture=_architecture(),
        pob_available=pob_available,
        pob_layout=pob_layout,
        supported_pob_revision=SUPPORTED_POB_HEAD[:12] if SUPPORTED_POB_HEAD else "unknown",
        build_state=build,
        worker=engine,
        hotkey=_hotkey_state(controller),
        overlay="enabled" if bool(getattr(settings, "overlay_enabled", False)) else "disabled",
        recent_error_subsystem=error_subsystem,
        recent_error_status=error_status,
    )


def render_global_diagnostics(controller: Any) -> str:
    return build_global_diagnostics(controller).render()
