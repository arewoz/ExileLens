"""Ask Windows for its native dark title bar on a top-level window.

The dashboard keeps the *native* frame (no custom title bar). This only tells DWM to draw
that frame dark, via ``DWMWA_USE_IMMERSIVE_DARK_MODE``, so the title bar matches the
window regardless of the user's system app theme. On Windows 11 the caption colour is also
set to the window background so frame and rail read as one surface. Every call is
best-effort: failures (older Windows, non-Windows, missing attribute) are ignored.
"""

from __future__ import annotations

import sys

_DWMWA_USE_IMMERSIVE_DARK_MODE_PRE20H1 = 19
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_BORDER_COLOR = 34
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36


def _colorref(hex_color: str) -> int:
    """``#rrggbb`` -> Win32 COLORREF (0x00bbggrr)."""
    value = hex_color.lstrip("#")
    r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return (b << 16) | (g << 8) | r


def apply_dark_title_bar(hwnd: int, *, caption: str = "#101113", text: str = "#c4c0b6") -> bool:
    """Return True when the dark-mode attribute was accepted."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
        set_attribute = dwm.DwmSetWindowAttribute
        set_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        set_attribute.restype = ctypes.c_long

        def _set(attribute: int, value: int) -> bool:
            data = ctypes.c_int(value)
            return set_attribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data)) == 0

        accepted = _set(_DWMWA_USE_IMMERSIVE_DARK_MODE, 1) or _set(_DWMWA_USE_IMMERSIVE_DARK_MODE_PRE20H1, 1)
        # Windows 11 only; silently ignored elsewhere.
        _set(_DWMWA_CAPTION_COLOR, _colorref(caption))
        _set(_DWMWA_TEXT_COLOR, _colorref(text))
        return bool(accepted)
    except Exception:  # noqa: BLE001 - cosmetic only, never raise into the UI
        return False
