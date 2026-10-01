"""Shared update actions for dashboard and tray."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from exilelens.app.updates.service import UpdateService


def restart_and_update(update_service: UpdateService) -> bool:
    """Restart the app to apply a downloaded update, when one is ready."""
    pid = os.getpid()
    app = QApplication.instance()
    if app is not None and hasattr(app, "property") and callable(getattr(app, "property", None)):
        shell = app.property("exilelens_app_shell")
        if shell is not None and hasattr(shell, "request_restart_for_update"):
            shell.request_restart_for_update(parent_pid=pid)
            return True
    if update_service.begin_restart_and_update(parent_pid=pid):
        if app is not None:
            app.quit()
        return True
    return False


def tray_update_action_label(check_state: str, download_state: str, version: str) -> tuple[str, bool, bool]:
    """Return ``(label, visible, enabled)`` for the tray's primary update action."""
    if download_state == "ready":
        return "Restart && Update", True, True
    if download_state == "installing":
        return "Installing update…", True, False
    if download_state == "downloading":
        return "Downloading update…", True, False
    if check_state == "available" and version:
        return f"Download && Install {version}", True, True
    return "Download Update", False, False


def update_notice_view(
    check_state: str,
    download_state: str,
    remote: str,
    installed: str,
    progress_percent: int | None,
    dismissed: set[str] | frozenset[str] = frozenset(),
) -> dict | None:
    """The non-modal dashboard notice for a pending update, or None when nothing should be shown.

    Only a verified, newer release (`check_state == "available"`) is offered; verification failures, failed
    checks, a current version, and a release dismissed with "Later" this session all return None. Neutral wording
    only: no urgency semantics exist in the release metadata.
    """
    from exilelens.app.updates.version import ExileLensVersion

    if check_state != "available" or not remote or remote in dismissed:
        return None
    remote_version, installed_version_ = ExileLensVersion.parse(remote), ExileLensVersion.parse(installed)
    if remote_version is None or installed_version_ is None or remote_version <= installed_version_:
        return None
    if download_state == "ready":
        action, enabled = "Restart & Update", True
    elif download_state == "installing":
        action, enabled = "Installing…", False
    elif download_state == "downloading":
        action = f"Downloading… {progress_percent}%" if progress_percent is not None else "Downloading…"
        enabled = False
    else:
        action, enabled = "Download update", True
    return {
        "title": f"ExileLens {remote} is available",
        "detail": f"You're using {installed}",
        "action": action,
        "action_enabled": enabled,
        "action_kind": "restart" if download_state == "ready" else "download",
        "later_visible": download_state not in {"installing"},
    }


def footer_update_summary(check_state: str, download_state: str, version: str, progress_percent: int | None) -> str:
    if download_state == "installing":
        return "Installing update…"
    if download_state == "ready":
        return f"Update {version} ready — restart to apply" if version else "Update ready — restart to apply"
    if download_state == "downloading":
        if progress_percent is not None:
            return f"Downloading update… {progress_percent}%"
        return "Downloading update…"
    if download_state == "error":
        return "Update download failed"
    if check_state == "available" and version:
        return f"Update available: {version}"
    if check_state == "checking":
        return "Checking for updates…"
    if check_state == "failed":
        return "Update check failed"
    if check_state == "verification_failed":
        return "Latest release could not be verified"
    return ""
