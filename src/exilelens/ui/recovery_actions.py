"""Recovery actions shared by the tray, Settings and Diagnostics."""

from __future__ import annotations

import logging

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


def open_github_releases() -> None:
    """Open the fixed, official ExileLens releases destination on user action."""
    from exilelens.app.update_check import GITHUB_RELEASES_URL

    QDesktopServices.openUrl(QUrl(GITHUB_RELEASES_URL))


def open_github_issues() -> None:
    """Open the fixed, official ExileLens issue tracker on user action."""
    from exilelens.app.update_check import GITHUB_ISSUES_URL

    QDesktopServices.openUrl(QUrl(GITHUB_ISSUES_URL))


def open_discord_invite() -> None:
    """Open the fixed, official ExileLens Discord invite on user action."""
    from exilelens.app.update_check import DISCORD_INVITE_URL

    QDesktopServices.openUrl(QUrl(DISCORD_INVITE_URL))


def open_logs_folder() -> None:
    from exilelens.app.logging_setup import log_dir

    folder = log_dir()
    logger.info("open_logs_folder path=%s", folder)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def copy_diagnostics(controller) -> str:  # noqa: ANN001
    """Put the allowlisted global diagnostic report on the clipboard."""
    # Keep every support surface on the explicit SUPPORT-02 representation.  In
    # particular, do not delegate to a controller formatter that could later grow
    # item, path, worker-stderr, or exception details.
    from exilelens.app.diagnostics import render_global_diagnostics

    report = render_global_diagnostics(controller)
    clipboard = QApplication.clipboard()
    if clipboard is not None:
        clipboard.setText(report)
    logger.info("diagnostics_copied chars=%s", len(report))
    return report
