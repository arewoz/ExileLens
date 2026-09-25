"""Extended diagnostic summary for Diagnostics 2.0."""

from __future__ import annotations

import json
import platform
import time
from typing import Any

from exilelens._version import build_identity
from exilelens.app.diagnostics import build_global_diagnostics
from exilelens.app.build_state import BuildState
from exilelens.diagnostics.constants import DIAGNOSTIC_SCHEMA_VERSION
from exilelens.diagnostics.events import support_session_id, verbose_mode_active
from exilelens.diagnostics.sanitize import sanitize_text, sanitize_value

from importlib.metadata import version as pkg_version


def _dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in ("PySide6", "cryptography"):
        try:
            versions[name] = pkg_version(name)
        except Exception:  # noqa: BLE001
            versions[name] = "unknown"
    return versions


def _item_check_state(controller: Any) -> dict[str, Any]:
    last = getattr(controller, "_last_result", None) or {}
    meta = last.get("request_meta") if isinstance(last, dict) else {}
    recommendation = last.get("recommendation") if isinstance(last, dict) else {}
    outcome = recommendation.get("evaluation_outcome") if isinstance(recommendation, dict) else {}
    return {
        "presentation_generation": int(getattr(controller, "presentation_generation", 0) or 0),
        "has_last_result": bool(last),
        "coverage_class": sanitize_text(str(outcome.get("coverage_class") or "unknown")),
        "verdict": sanitize_text(str(outcome.get("verdict") or "none")),
        "evaluation_reason": sanitize_text(str(outcome.get("reason_code") or outcome.get("reason") or "none")),
        "request_id": int(meta.get("request_id") or 0) if isinstance(meta, dict) else 0,
    }


def _worker_state(controller: Any) -> dict[str, Any]:
    engine = "unknown"
    try:
        engine = str(controller.engine_status() or "unknown")
    except Exception:  # noqa: BLE001
        engine = "unknown"
    return {
        "engine_status": sanitize_text(engine),
        "worker_restarts": int(getattr(controller, "_worker_restart_count", 0) or 0),
        "worker_failures": int(getattr(controller, "_worker_failure_count", 0) or 0),
    }


def _update_state(settings: Any, update_service: Any | None) -> dict[str, Any]:
    last_check = float(getattr(settings, "update_last_check_at", 0.0) or 0.0)
    return {
        "channel": sanitize_text(str(getattr(settings, "update_channel", "beta") or "beta")),
        "last_check_epoch": last_check if last_check > 0 else None,
        "last_check_age_seconds": int(time.time() - last_check) if last_check > 0 else None,
        "latest_known_version": sanitize_text(str(getattr(settings, "update_latest_version", "") or "")),
        "last_error": sanitize_text(str(getattr(settings, "update_last_error", "") or "")),
        "installed_version": sanitize_text(
            update_service.installed_version_text if update_service is not None else "unknown"
        ),
    }


def _pob_extended(controller: Any, settings: Any) -> dict[str, Any]:
    try:
        build_info = getattr(controller, "build_info", None)
        state = getattr(build_info, "state", None)
    except Exception:  # noqa: BLE001
        build_info = None
        state = None
    build_state = state.value.lower() if isinstance(state, BuildState) else "unknown"
    return {
        "build_state": build_state,
        "active_loadout": sanitize_text(str(getattr(controller, "active_loadout", "") or "")),
        "active_item_set_id": sanitize_text(str(getattr(controller, "active_item_set_id", "") or "")),
        "item_set_follow_loadout": bool(getattr(settings, "item_set_follow_loadout", False)),
    }


def _health_extended(controller: Any, settings: Any) -> dict[str, Any]:
    hotkey = getattr(controller, "price_check_hotkey", None)
    hotkey_state = "unknown"
    if hotkey is not None:
        if bool(getattr(hotkey, "hook_registered", False)):
            hotkey_state = "ready"
        else:
            hotkey_state = "unavailable"
    return {
        "hotkey": hotkey_state,
        "overlay_enabled": bool(getattr(settings, "overlay_enabled", False)),
        "clipboard_watcher": "enabled",
        "price_check_enabled": bool(getattr(settings, "price_check_enabled", True)),
    }


def _error_integration(controller: Any) -> dict[str, Any]:
    return {
        "last_error_code": sanitize_text(str(getattr(controller, "_last_support_error_code", "") or "none")),
        "last_coverage_reason": sanitize_text(str(getattr(controller, "_last_coverage_reason", "") or "none")),
        "support_session_id": support_session_id(),
    }


def build_extended_summary(
    controller: Any,
    settings: Any,
    *,
    update_service: Any | None = None,
) -> dict[str, Any]:
    """Allowlisted extended summary suitable for export."""
    try:
        global_report = build_global_diagnostics(controller)
    except Exception:  # noqa: BLE001 - diagnostics must never interrupt Item Check
        global_report = None
    identity = build_identity()
    base = {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "generated_at_epoch": time.time(),
        "support_session_id": support_session_id(),
        "verbose_mode_active": verbose_mode_active(settings),
        "application": {
            "version": identity.version,
            "release_channel": sanitize_text(str(getattr(settings, "update_channel", "beta") or "beta")),
            "git_commit": identity.git_commit,
            "execution_mode": identity.execution_mode,
            "build_mode": identity.build_mode,
            "trusted_build": identity.execution_mode == "packaged" and identity.git_commit != "unknown",
            "python_version": identity.python_version,
            "pyinstaller_version": identity.pyinstaller_version,
            "windows": sanitize_text(" ".join(platform.win32_ver()[:2]).strip() or "unknown"),
            "architecture": sanitize_text(platform.machine()),
            "dependencies": _dependency_versions(),
        },
        "global_report": sanitize_value(
            {
                "version": global_report.version,
                "build": global_report.build,
                "mode": global_report.mode,
                "pob_available": global_report.pob_available,
                "pob_version": global_report.pob_version,
                "pob_version_status": global_report.pob_version_status,
                "pob_version_reason": global_report.pob_version_reason,
                "build_state": global_report.build_state,
                "worker": global_report.worker,
                "hotkey": global_report.hotkey,
                "overlay": global_report.overlay,
                "recent_error_subsystem": global_report.recent_error_subsystem,
                "recent_error_status": global_report.recent_error_status,
            }
            if global_report is not None
            else {"status": "unavailable"}
        ),
        "path_of_building": _pob_extended(controller, settings),
        "item_check": _item_check_state(controller),
        "worker": _worker_state(controller),
        "health": _health_extended(controller, settings),
        "updates": _update_state(settings, update_service),
        "error_codes": _error_integration(controller),
    }
    return sanitize_value(base)


def render_extended_summary_text(
    controller: Any,
    settings: Any,
    *,
    update_service: Any | None = None,
) -> str:
    payload = build_extended_summary(controller, settings, update_service=update_service)
    return json.dumps(payload, indent=2, sort_keys=True)
