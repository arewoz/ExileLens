from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Qt, Signal

from exilelens.platform.windows.mouse_hook import (
    MouseClickDismissHook,
    apply_observed_click,
    is_mouse_down_message,
)
from exilelens.ui.window_policy import click_blocks_item_dismiss


class ItemDismissController(QObject):
    """Item Check scoped global click dismiss — one WH_MOUSE_LL for module lifetime."""

    dismissed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hook = MouseClickDismissHook(self)
        self._overlay: Any | None = None
        self._controller: Any | None = None
        self._active = False
        self._hook.clicked.connect(self._on_hook_click, Qt.ConnectionType.QueuedConnection)

    @property
    def hook(self) -> MouseClickDismissHook:
        return self._hook

    @property
    def active(self) -> bool:
        return self._active

    @property
    def hook_installed(self) -> bool:
        return self._hook.installed

    def bind(self, *, overlay: Any | None, controller: Any | None) -> None:
        self._overlay = overlay
        self._controller = controller

    def start(self) -> bool:
        from exilelens.security_audit import overlay_disabled

        self._active = True
        if overlay_disabled():
            return True
        return self._hook.start()

    def stop(self) -> None:
        self._active = False
        self._hook.stop()

    def _on_hook_click(self, w_param: int, x: int, y: int) -> None:
        if not self._active:
            return
        if not is_mouse_down_message(int(w_param)):
            return
        if (x or y) and click_blocks_item_dismiss(int(x), int(y)):
            return
        overlay_visible = bool(self._overlay and self._overlay.isVisible())
        pending = bool(self._controller and self._controller.has_inflight_gameplay_request)
        if not overlay_visible and not pending:
            return
        apply_observed_click(overlay=self._overlay, controller=self._controller)
        self.dismissed.emit()
