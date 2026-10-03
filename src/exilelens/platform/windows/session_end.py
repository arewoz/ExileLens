"""Detect Windows logoff / shutdown / restart so nothing is installed while the session is ending.

Two independent signals, either of which is enough to skip an install on exit:

* ``SessionEndSentinel`` — a tiny top-level window whose native handle exists but which is never shown.
  A tray-only app can otherwise have no native top-level Qt window at all, in which case Qt never sees
  ``WM_QUERYENDSESSION``. With the sentinel, Qt emits ``commitDataRequest`` (verified on Windows by sending
  the message to the sentinel; a real logoff has not been exercised).
* ``system_shutting_down()`` — ``GetSystemMetrics(SM_SHUTTINGDOWN)``: non-zero while the session is being
  shut down, regardless of windows.

If the user cancels a shutdown after ``WM_QUERYENDSESSION`` the flag stays set for this run: the safe
direction (the update simply stays pending until the next clean exit).
"""

from __future__ import annotations

import logging
import sys
from typing import Callable

logger = logging.getLogger(__name__)

SM_SHUTTINGDOWN = 0x2000


def system_shutting_down() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.user32.GetSystemMetrics(SM_SHUTTINGDOWN))
    except Exception:  # noqa: BLE001 - unknown means "not provably ending"; the other signal still applies
        return False


class SessionEndSentinel:
    """Create the hidden native window and report ``commitDataRequest`` / ``saveStateRequest`` to ``on_end``."""

    def __init__(self, app, on_end: Callable[[], None]) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QWidget

        self._on_end = on_end
        self._widget = QWidget(None, Qt.WindowType.Tool)
        self._widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self._widget.setWindowTitle("ExileLens session sentinel")
        self.handle = int(self._widget.winId())  # creates the native window without showing it
        for name in ("commitDataRequest", "saveStateRequest"):
            signal = getattr(app, name, None)
            if signal is not None:
                try:
                    signal.connect(self._fire)
                except Exception:  # noqa: BLE001
                    logger.debug("session_end_signal_unavailable name=%s", name)

    def _fire(self, *_args) -> None:
        self._on_end()
