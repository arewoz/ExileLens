"""Recovery actions shared by the tray, Settings and Diagnostics."""

from __future__ import annotations

import logging

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


def open_logs_folder() -> None:
    from poe2value.app.logging_setup import log_dir

    folder = log_dir()
    logger.info("open_logs_folder path=%s", folder)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def copy_diagnostics(controller) -> str:  # noqa: ANN001
    """Put the diagnostic report on the clipboard. Returns the text for display."""
    report = controller.diagnostic_report()
    clipboard = QApplication.clipboard()
    if clipboard is not None:
        clipboard.setText(report)
    logger.info("diagnostics_copied chars=%s", len(report))
    return report
