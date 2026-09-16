from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from poe2value.platform.windows.foreground_info import is_poe_foreground
from poe2value.platform.windows.hotkey_binding import HotkeyBinding, HotkeyValidationError
from poe2value.platform.windows.low_level_keyboard import LowLevelKeyboardHook

user32 = ctypes.windll.user32 if sys.platform == "win32" else None
kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None

logger = logging.getLogger(__name__)

MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_C = 0x43
WM_HOTKEY = 0x0312
PRICE_CHECK_HOTKEY_ID = 0xD2E0
REFINE_PRICE_HOTKEY_ID = 0xD2E1

DEFAULT_PRICE_CHECK_HOTKEY = "shift+c"
DEFAULT_REFINE_PRICE_HOTKEY = "ctrl+shift+r"
DEFAULT_PRICE_CHECK_MODIFIERS = MOD_SHIFT | MOD_NOREPEAT
DEFAULT_PRICE_CHECK_VK = VK_C


def parse_price_check_hotkey(hotkey: str) -> tuple[int, int]:
    """Parse a hotkey string like 'shift+c' into RegisterHotKey modifiers + VK."""
    normalized = str(hotkey or DEFAULT_PRICE_CHECK_HOTKEY).strip().lower()
    if normalized in ("ctrl+d", "control+d"):
        normalized = DEFAULT_PRICE_CHECK_HOTKEY
    parts = [part.strip() for part in normalized.split("+") if part.strip()]
    modifiers = MOD_NOREPEAT
    vk = DEFAULT_PRICE_CHECK_VK
    key_token = parts[-1] if parts else "c"
    for token in parts[:-1]:
        if token in ("shift", "mod_shift"):
            modifiers |= MOD_SHIFT
        elif token in ("ctrl", "control", "mod_control"):
            modifiers |= 0x0002
        elif token in ("alt", "mod_alt"):
            modifiers |= 0x0001
    if len(key_token) == 1:
        vk = ord(key_token.upper())
    return modifiers, vk


class _HotkeyNativeFilter(QAbstractNativeEventFilter):
    def __init__(self, hook: PriceCheckHotkeyHook) -> None:
        super().__init__()
        self._hook = hook

    def nativeEventFilter(self, event_type, message):  # noqa: ANN001
        if user32 is None or event_type != b"windows_generic_MSG":
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError, OverflowError):
            return False, 0
        if int(msg.message) == WM_HOTKEY and int(msg.wParam) == self._hook.hotkey_id:
            self._hook._emit_triggered()
            return True, 0
        return False, 0


class PriceCheckHotkeyHook(QObject):
    """Item Check uses WH_KEYBOARD_LL; Refine retains RegisterHotKey."""

    triggered = Signal()
    binding_released = Signal()
    tested = Signal()
    seen_not_poe = Signal()
    install_changed = Signal(bool, str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        hotkey: str = DEFAULT_PRICE_CHECK_HOTKEY,
        hotkey_id: int = PRICE_CHECK_HOTKEY_ID,
    ) -> None:
        super().__init__(parent)
        self._registered = False
        self._filter: _HotkeyNativeFilter | None = None
        self._hotkey = hotkey
        self._hotkey_id = int(hotkey_id)
        self._modifiers, self._vk = parse_price_check_hotkey(hotkey)
        self._low_level: LowLevelKeyboardHook | None = None
        self._install_error = ""

    @property
    def hotkey_id(self) -> int:
        return self._hotkey_id

    @property
    def registered(self) -> bool:
        return self._low_level.installed if self._low_level is not None else self._registered

    @property
    def install_error(self) -> str:
        return self._install_error or (self._low_level.install_error if self._low_level is not None else "")

    @property
    def hotkey(self) -> str:
        return self._hotkey

    @property
    def register_modifiers(self) -> int:
        return self._modifiers

    def _emit_triggered(self) -> None:
        self.triggered.emit()

    def start(self) -> bool:
        from poe2value.security_audit import keyboard_hooks_disabled

        if keyboard_hooks_disabled():
            self._install_error = "disabled by security audit variant"
            self.install_changed.emit(False, self._install_error)
            return False
        if self._hotkey_id == PRICE_CHECK_HOTKEY_ID:
            if self._low_level is None:
                try:
                    binding = HotkeyBinding.parse(self._hotkey)
                except HotkeyValidationError as exc:
                    self._install_error = str(exc)
                    self.install_changed.emit(False, self._install_error)
                    return False
                self._low_level = LowLevelKeyboardHook(binding, self)
                self._low_level.triggered.connect(self.triggered)
                self._low_level.binding_released.connect(self.binding_released)
                self._low_level.tested.connect(self.tested)
                self._low_level.seen_not_poe.connect(self.seen_not_poe)
                self._low_level.install_changed.connect(self.install_changed)
            return self._low_level.start()
        if self._registered:
            return True
        if user32 is None:
            return False
        ok = bool(user32.RegisterHotKey(None, self._hotkey_id, self._modifiers, self._vk))
        if not ok:
            last_error = int(kernel32.GetLastError() or 0) if kernel32 is not None else 0
            logger.error(
                "RegisterHotKey failed hotkey=%s id=%#x modifiers=%#x vk=%#x win32_error=%s",
                self._hotkey,
                self._hotkey_id,
                self._modifiers,
                self._vk,
                last_error,
            )
            return False
        app = QApplication.instance()
        if app is None:
            user32.UnregisterHotKey(None, self._hotkey_id)
            return False
        self._filter = _HotkeyNativeFilter(self)
        app.installNativeEventFilter(self._filter)
        self._registered = True
        return True

    def stop(self) -> None:
        if self._low_level is not None:
            self._low_level.stop()
            return
        if not self._registered:
            return
        if user32 is not None:
            user32.UnregisterHotKey(None, self._hotkey_id)
        app = QApplication.instance()
        if app is not None and self._filter is not None:
            app.removeNativeEventFilter(self._filter)
        self._filter = None
        self._registered = False

    def set_test_mode(self, enabled: bool) -> None:
        if self._low_level is not None:
            self._low_level.set_test_mode(enabled)
