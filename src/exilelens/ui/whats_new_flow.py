"""Owns the What's New dialog for the dashboard: when it appears on its own, and the manual way back.

Automatic display is evaluated only when the player has opened the dashboard (never during tray-only startup) and
only in the running, installed version. It waits a few seconds for Connecting / Loading to settle without blocking,
and defers to the next dashboard open if the app needs setup first or another modal is up. The release is recorded
as seen only when the player dismisses the dialog.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from exilelens._paths import is_frozen
from exilelens.app.settings import save_settings
from exilelens.app.updates.version import ExileLensVersion
from exilelens.ui.status_model import derive_status
from exilelens.ui.whats_new_dialog import WhatsNewDialog
from exilelens.whats_new import content, trigger

logger = logging.getLogger(__name__)

POLL_MS = 250


class ReleaseNotesFlow(QObject):
    def __init__(
        self,
        window: QWidget,
        settings,
        controller,
        *,
        installed: ExileLensVersion | None = None,
        catalog_provider: Callable[[], content.Catalog | None] = content.packaged_catalog,
        navigate: Callable[[str], None] | None = None,
        blocked: Callable[[], bool] | None = None,
        save: Callable[[object], None] = save_settings,
        auto_enabled: bool | None = None,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._settings = settings
        self._controller = controller
        if installed is None:
            from exilelens._version import __version__

            installed = ExileLensVersion.parse(__version__)
        self.installed = installed
        self._catalog_provider = catalog_provider
        self._navigate = navigate
        self._blocked = blocked
        self._save = save
        # Source runs never pop the dialog on their own; the packaged app does.
        self.auto_enabled = is_frozen() if auto_enabled is None else auto_enabled
        self.dialog: WhatsNewDialog | None = None
        self._deadline = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._attempt)
        self.settle_seconds = trigger.SETTLE_SECONDS

    # --- queries -------------------------------------------------------------------------------

    @property
    def catalog(self) -> content.Catalog | None:
        return self._catalog_provider()

    def has_notes(self) -> bool:
        """Packaged notes exist for the installed version (the only condition for any entry point)."""
        return content.has_notes_for(self.installed, self.catalog)

    def pending(self) -> bool:
        """An automatic summary is due: the dashboard would show it now if the app were ready."""
        return self.auto_enabled and trigger.evaluate(self._settings, self.installed, self.catalog) is not None

    def installed_text(self) -> str:
        return str(self.installed) if self.installed is not None else ""

    # --- automatic -----------------------------------------------------------------------------

    def on_dashboard_shown(self) -> None:
        """Called when the player has opened the dashboard."""
        if not self.auto_enabled or self.dialog is not None or self._timer.isActive():
            return
        if trigger.evaluate(self._settings, self.installed, self.catalog) is None:
            return
        self._deadline = time.monotonic() + self.settle_seconds
        self._attempt()

    def _attempt(self) -> None:
        if not self._window.isVisible() or self._window.isMinimized() or self.dialog is not None:
            return   # closed again before it settled: the next open tries again
        if self._is_blocked():
            logger.info("whats_new_deferred reason=modal")
            return
        try:
            verdict = trigger.gate(derive_status(self._controller, self._settings))
        except Exception:  # noqa: BLE001 - never raise into the UI
            logger.exception("whats_new_status_failed")
            return
        if verdict == trigger.SHOW:
            summary = trigger.evaluate(self._settings, self.installed, self.catalog)
            if summary is not None:
                self._present(summary)
            return
        if verdict == trigger.WAIT and time.monotonic() < self._deadline:
            self._timer.start()
            return
        logger.info("whats_new_deferred reason=%s", verdict)

    def _is_blocked(self) -> bool:
        if QApplication.activeModalWidget() is not None:
            return True
        return bool(self._blocked is not None and self._blocked())

    # --- manual --------------------------------------------------------------------------------

    def show_manual(self) -> bool:
        """Reopen the installed version's own notes. Returns False when there are none."""
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return True
        summary = content.manual_summary(self.catalog, self.installed)
        if summary is None:
            return False
        self._present(summary)
        return True

    def open_full_notes(self) -> None:
        """Release page of the installed version on GitHub; works with or without packaged notes."""
        from exilelens.ui.recovery_actions import open_release_notes_page

        open_release_notes_page(self.installed)

    # --- dialog --------------------------------------------------------------------------------

    def _present(self, summary: content.Summary) -> None:
        self._timer.stop()
        dialog = WhatsNewDialog(summary, on_dismissed=self._dismissed, parent=self._window)
        self.dialog = dialog
        logger.info("whats_new_shown kind=%s version=%s", summary.kind, summary.version)
        dialog.open()

    def _dismissed(self, destination: str | None) -> None:
        dialog, self.dialog = self.dialog, None
        if dialog is not None:
            dialog.deleteLater()
        trigger.mark_seen(self._settings, self.installed, self._save)
        logger.info("whats_new_dismissed destination=%s", destination or "")
        if destination and self._navigate is not None:
            self._navigate(destination)
