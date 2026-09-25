from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_XBUTTONDOWN = 0x020B

# LRESULT is pointer-sized. Using c_long on 64-bit truncates hook results and
# can cause Windows to silently drop or uninstall WH_MOUSE_LL.
LRESULT = ctypes.c_ssize_t
HHOOK = ctypes.c_void_p
LowLevelMouseProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

CLICK_DOWN_MESSAGES = frozenset(
    {
        WM_LBUTTONDOWN,
        WM_RBUTTONDOWN,
        WM_MBUTTONDOWN,
        WM_XBUTTONDOWN,
    }
)


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]

BUTTON_NAMES = {
    WM_LBUTTONDOWN: "left",
    WM_RBUTTONDOWN: "right",
    WM_MBUTTONDOWN: "middle",
    WM_XBUTTONDOWN: "x",
}

user32 = ctypes.windll.user32


def _configure_user32(api: Any) -> None:
    api.SetWindowsHookExW.restype = HHOOK
    api.SetWindowsHookExW.argtypes = [
        ctypes.c_int,
        LowLevelMouseProc,
        wintypes.HINSTANCE,
        wintypes.DWORD,
    ]
    api.CallNextHookEx.restype = LRESULT
    api.CallNextHookEx.argtypes = [HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    api.UnhookWindowsHookEx.restype = wintypes.BOOL
    api.UnhookWindowsHookEx.argtypes = [HHOOK]


_configure_user32(user32)


def is_mouse_down_message(w_param: int) -> bool:
    return int(w_param) in CLICK_DOWN_MESSAGES


def button_name(w_param: int) -> str:
    return BUTTON_NAMES.get(int(w_param), "unknown")


class MouseClickDismissHook(QObject):
    """Global WH_MOUSE_LL observer. Clicks are never consumed."""

    # int wParam, x, y so queued delivery stays off the hook stack.
    clicked = Signal(int, int, int)

    def __init__(self, parent: QObject | None = None, *, api: Any | None = None) -> None:
        super().__init__(parent)
        self._api = api or user32
        self._hook_id: int | None = None
        self._proc = LowLevelMouseProc(self._handle_event)
        self._installed_once = False

    @property
    def installed(self) -> bool:
        return self._hook_id is not None

    def _call_next(self, n_code: int, w_param: int, l_param: int) -> int:
        hook = self._hook_id or 0
        return int(self._api.CallNextHookEx(hook, n_code, w_param, l_param) or 0)

    def _point(self, l_param: int) -> tuple[int, int]:
        if not l_param:
            return 0, 0
        try:
            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            return int(info.pt.x), int(info.pt.y)
        except Exception:
            return 0, 0

    def _handle_event(self, n_code: int, w_param: int, l_param: int) -> int:
        # Must return immediately. Never hide widgets or emit DirectConnection
        # slots from inside WH_MOUSE_LL — Windows will timeout and unhook us.
        if n_code >= 0 and is_mouse_down_message(int(w_param)):
            try:
                x, y = self._point(int(l_param))
                self.clicked.emit(int(w_param), x, y)
            except Exception:
                pass
        return self._call_next(n_code, w_param, l_param)

    def simulate_click(self, w_param: int = WM_LBUTTONDOWN) -> int:
        """Test helper: run the hook callback without installing a real hook."""
        return int(self._handle_event(0, int(w_param), 0))

    def start(self) -> bool:
        if self._hook_id:
            return True
        # WH_MOUSE_LL in-process callbacks should pass hMod=NULL.
        hook = self._api.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        if not hook:
            return False
        self._hook_id = int(hook)
        self._installed_once = True
        return True

    def stop(self) -> None:
        if not self._hook_id:
            return
        self._api.UnhookWindowsHookEx(self._hook_id)
        self._hook_id = None

    def __del__(self) -> None:
        # A WH_MOUSE_LL registration must never outlive the ctypes trampoline it
        # calls into. self._proc is owned by this object, so once we are collected
        # Windows would be holding a pointer to freed memory and the next mouse
        # message anywhere in the system faults the process with an access
        # violation -- far from whatever code actually dropped the reference.
        # Nothing here touches Qt: at finalisation, and especially at interpreter
        # shutdown, only the raw ctypes handle is safe to use.
        try:
            hook_id = self._hook_id
            if hook_id:
                self._hook_id = None
                self._api.UnhookWindowsHookEx(hook_id)
        except Exception:  # noqa: BLE001 - finalisers must never raise
            pass


def _dismiss_click_through(overlay: Any) -> None:
    """Click-through dismissal is an ExileLens-owned close, not a bare hide."""
    handler = getattr(overlay, "handle_observed_click", None)
    if callable(handler):
        handler()
        return
    overlay.dismiss()


def apply_observed_click(
    *,
    overlay: Any | None,
    controller: Any | None,
    on_idle_hook: Callable[[], None] | None = None,
) -> None:
    """Observe a click: invalidate pending presentation and hide overlay."""
    if controller is not None:
        controller.invalidate_presentation()
        if overlay is not None:
            generation = getattr(controller, "presentation_generation", None)
            if generation is not None:
                overlay.set_presentation_generation(int(generation))
            _dismiss_click_through(overlay)
        return
    if overlay is not None:
        _dismiss_click_through(overlay)
    if on_idle_hook is not None:
        on_idle_hook()
