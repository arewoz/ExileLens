"""Compact application header.

Replaces ``BaselineHeader``, which carried the build name, the full XML path, the
last-loaded timestamp, a freshness badge, the value profile and a Refresh button --
all of which are also rendered elsewhere. The header now holds exactly one global
fact: whether ExileLens is connected to Path of Building. Everything else is
contextual and lives on the page it belongs to.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from poe2value.branding import APP_NAME
from poe2value.ui import theme
from poe2value.ui.components import StatusValue
from poe2value.ui.health import derive_health, header_status


class AppHeader(QWidget):
    """``ExileLens                              * PoB connected``"""

    def __init__(
        self,
        controller,
        settings,
        *,
        navigate: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self._navigate = navigate
        self.setObjectName("appHeader")
        self.setFixedHeight(theme.HEADER_HEIGHT)

        self._wordmark = QLabel(APP_NAME)
        self._wordmark.setObjectName("appWordmark")

        self._status = StatusValue("", "neutral")
        self._status.setObjectName("headerStatus")

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_LG, 0, theme.SPACE_LG, 0)
        row.setSpacing(theme.SPACE_MD)
        row.addWidget(self._wordmark, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        row.addWidget(self._status, 0, Qt.AlignmentFlag.AlignVCenter)

        controller.engine_ready.connect(self.refresh)
        controller.engine_failed.connect(lambda _msg: self.refresh())
        controller.build_changed.connect(lambda _info: self.refresh())
        controller.baseline_state_changed.connect(lambda _state: self.refresh())
        self.refresh()

    # --- state ------------------------------------------------------------------

    def status_text(self) -> str:
        return self._status.text()

    def status_level(self) -> str:
        return self._status.status()

    def refresh(self) -> None:
        health = derive_health(self.controller, self.settings)
        text, status = header_status(health)
        self._status.set_value(text, status)
        # Only offer navigation when there is actually something to look at.
        actionable = status in ("warn", "error")
        self._status.setCursor(
            Qt.CursorShape.PointingHandCursor if actionable else Qt.CursorShape.ArrowCursor
        )
        self._status.setToolTip(
            health.pob.detail or ("Open Diagnostics" if actionable else "")
        )
        self._actionable = actionable

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if getattr(self, "_actionable", False) and self._navigate is not None:
            self._navigate("diagnostics")
        super().mouseReleaseEvent(event)
