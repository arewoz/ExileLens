"""Foreground-aware WH_KEYBOARD_LL hook used by Item Check."""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, Signal

from poe2value.platform.windows.foreground_info import is_poe_foreground
from poe2value.platform.windows.hotkey_binding import HotkeyBinding, MODIFIER_VKS
from poe2value.platform.windows.hotkey_chord_tracker import HotkeyChordTracker
from poe2value.platform.windows.user_clipboard_copy import note_foreign_ctrl_c_copy

_ACTIVE_CHORD_TRACKER: HotkeyChordTracker | None = None


def active_chord_tracker() -> HotkeyChordTracker | None:
    return _ACTIVE_CHORD_TRACKER


def hook_modifier_snapshot() -> dict[str, bool] | None:
    tracker = _ACTIVE_CHORD_TRACKER
    return tracker.modifier_snapshot() if tracker is not None else None

logger = logging.getLogger(__name__)

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x10
EXILELENS_INJECT_TAG = 0x4558494C454C454E & ((1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1)
_DOWN_MASK = 0x8000

user32 = ctypes.windll.user32 if sys.platform == "win32" else None
kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else wintypes.ULONG
LRESULT = wintypes.LPARAM
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM) if sys.platform == "win32" else None

if user32 is not None and HOOKPROC is not None:
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    user32.SetWindowsHookExW.restype = wintypes.HANDLE
    user32.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user32.CallNextHookEx.restype = LRESULT
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


@dataclass(frozen=True)
class HookDecision:
    matched: bool = False
    consume: bool = False
    fire: bool = False
    ignored_own_injection: bool = False


class KeyboardMatcher:
    """Pure state machine, separated from Win32 so behavior is unit-testable."""

    def __init__(self, binding: HotkeyBinding) -> None:
        self.binding = binding
        self._down = False
        self._swallowed = False

    def reset(self) -> None:
        """Drop the held-key latch so a missed KEYUP cannot disable the hotkey."""
        self._down = False
        self._swallowed = False

    @property
    def key_down(self) -> bool:
        return self._down

    def handle(self, *, vk: int, is_down: bool, extra_info: int, modifiers: set[str], poe_foreground: bool, test_mode: bool = False) -> HookDecision:
        if extra_info == EXILELENS_INJECT_TAG:
            return HookDecision(ignored_own_injection=True)
        if vk != self.binding.vk:
            return HookDecision()
        if not is_down:
            swallowed = self._swallowed
            self._down = False
            self._swallowed = False
            return HookDecision(matched=swallowed, consume=swallowed and not test_mode)
        matched = modifiers == set(self.binding.modifiers)
        if not matched:
            return HookDecision()
        if self._down:
            return HookDecision(matched=True, consume=self._swallowed and not test_mode)
        self._down = True
        self._swallowed = bool(poe_foreground and not test_mode)
        return HookDecision(matched=True, consume=self._swallowed, fire=bool(test_mode or poe_foreground))


def current_modifiers(get_state: Callable[[int], int] | None = None) -> set[str]:
    if user32 is None and get_state is None:
        return set()
    getter = get_state or user32.GetAsyncKeyState
    return {name for name, vks in MODIFIER_VKS.items() if any(int(getter(vk)) & _DOWN_MASK for vk in vks)}


def _modifiers_from_tracker(tracker: HotkeyChordTracker) -> set[str]:
    snap = tracker.modifier_snapshot()
    return {name for name in ("shift", "ctrl", "alt", "win") if snap.get(name)}


class LowLevelKeyboardHook(QObject):
    triggered = Signal()
    binding_released = Signal()
    tested = Signal()
    seen_not_poe = Signal()
    install_changed = Signal(bool, str)

    def __init__(self, binding: HotkeyBinding, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.binding = binding
        self.matcher = KeyboardMatcher(binding)
        self.chord_tracker = HotkeyChordTracker(binding)
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._hook = None
        self._running = threading.Event()
        self._started = threading.Event()
        self._test_mode = False
        self.install_error = ""

    @property
    def installed(self) -> bool:
        return self._running.is_set()

    def set_test_mode(self, enabled: bool) -> None:
        self._test_mode = bool(enabled)

    def start(self) -> bool:
        if self.installed:
            return True
        global _ACTIVE_CHORD_TRACKER
        _ACTIVE_CHORD_TRACKER = self.chord_tracker
        if user32 is None or kernel32 is None:
            self.install_error = "Low-level keyboard hooks require Windows."
            self.install_changed.emit(False, self.install_error)
            return False
        self._started.clear()
        self._thread = threading.Thread(target=self._message_loop, name="exilelens-item-hotkey", daemon=True)
        self._thread.start()
        self._started.wait(2.0)
        return self.installed

    def stop(self) -> None:
        if self._thread_id and user32 is not None:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None

    def _message_loop(self) -> None:
        self._thread_id = int(kernel32.GetCurrentThreadId())
        def callback(code: int, wparam: int, lparam: int) -> int:
            if code < 0:
                return int(user32.CallNextHookEx(self._hook, code, wparam, lparam))
            event = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            down = int(wparam) in (WM_KEYDOWN, WM_SYSKEYDOWN)
            if down and int(event.vkCode) == 0x43 and "ctrl" in current_modifiers():
                # Any Ctrl+C ExileLens does not own suppresses passive clipboard
                # capture — including one injected by another overlay. Only our own
                # tagged injection is exempt; it is claimed by sequence ownership.
                if int(event.dwExtraInfo) != EXILELENS_INJECT_TAG:
                    note_foreign_ctrl_c_copy(
                        "injected" if int(event.flags) & LLKHF_INJECTED else "physical"
                    )
            vk = int(event.vkCode)
            released = self.chord_tracker.observe(vk=vk, is_down=down)
            modifiers = _modifiers_from_tracker(self.chord_tracker)
            decision = self.matcher.handle(
                vk=vk, is_down=down, extra_info=int(event.dwExtraInfo),
                modifiers=modifiers, poe_foreground=is_poe_foreground(), test_mode=self._test_mode,
            )
            if decision.fire:
                self.chord_tracker.arm()
                if self._test_mode:
                    self.tested.emit()
                else:
                    self.triggered.emit()
            if released:
                self.binding_released.emit()
            elif decision.matched and down and not is_poe_foreground():
                self.seen_not_poe.emit()
            return 1 if decision.consume else int(user32.CallNextHookEx(self._hook, code, wparam, lparam))

        assert HOOKPROC is not None
        self._callback = HOOKPROC(callback)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._callback, kernel32.GetModuleHandleW(None), 0)
        if not self._hook:
            error = int(kernel32.GetLastError() or 0)
            self.install_error = f"SetWindowsHookEx failed (Win32 error {error})."
            logger.error("hotkey_hook_install_failed binding=%s error=%s", self.binding.canonical, error)
            self._started.set()
            self.install_changed.emit(False, self.install_error)
            return
        self._running.set()
        self._started.set()
        logger.info("hotkey_hook_installed binding=%s", self.binding.canonical)
        self.install_changed.emit(True, "")
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
        self._thread_id = 0
        self._running.clear()
        global _ACTIVE_CHORD_TRACKER
        if _ACTIVE_CHORD_TRACKER is self.chord_tracker:
            _ACTIVE_CHORD_TRACKER = None
        self.chord_tracker.reset()
        logger.info("hotkey_hook_stopped binding=%s", self.binding.canonical)
