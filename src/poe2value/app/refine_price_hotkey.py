"""Ctrl+Shift+R — open Refine for the last Price Check. Not a capture hotkey."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Qt, Signal

from poe2value.platform.windows.keyboard_hook import (
    DEFAULT_REFINE_PRICE_HOTKEY,
    REFINE_PRICE_HOTKEY_ID,
    PriceCheckHotkeyHook,
    parse_price_check_hotkey,
)


class RefinePriceHotkeyController(QObject):
    """Global refine hotkey. Collision with Shift+C is refused, not stolen."""

    refine_requested = Signal()
    collision = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        hotkey: str = DEFAULT_REFINE_PRICE_HOTKEY,
        price_check_hotkey: str = "shift+c",
    ) -> None:
        super().__init__(parent)
        self._hotkey = str(hotkey or DEFAULT_REFINE_PRICE_HOTKEY).strip().lower()
        self._price_check_hotkey = str(price_check_hotkey or "shift+c").strip().lower()
        self._hook = PriceCheckHotkeyHook(
            self,
            hotkey=self._hotkey,
            hotkey_id=REFINE_PRICE_HOTKEY_ID,
        )
        self._active = False
        self._hook.triggered.connect(self._on_hotkey, Qt.ConnectionType.QueuedConnection)
        self._controller: Any | None = None

    @property
    def hotkey(self) -> str:
        return self._hotkey

    @property
    def registered(self) -> bool:
        return self._hook.registered

    def bind(self, *, controller: Any | None) -> None:
        self._controller = controller

    def _collides(self) -> bool:
        if not self._hotkey or self._hotkey == self._price_check_hotkey:
            return True
        refine = parse_price_check_hotkey(self._hotkey)
        price = parse_price_check_hotkey(self._price_check_hotkey)
        return refine == price

    def start(self) -> bool:
        if self._collides():
            self.collision.emit(
                f"Refine hotkey {self._hotkey} collides with Price Check "
                f"{self._price_check_hotkey}; refine stays tray-only."
            )
            return False
        ok = self._hook.start()
        self._active = ok
        return ok

    def stop(self) -> None:
        self._hook.stop()
        self._active = False

    def _on_hotkey(self) -> None:
        self.refine_requested.emit()
