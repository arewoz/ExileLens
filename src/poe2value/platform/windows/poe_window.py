"""Win32 geometry for the Path of Exile 2 top-level window.

Uses EnumWindows / GetWindowRect / GetClientRect / ClientToScreen only.
This is not game-memory reading.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from typing import Any, Callable, Iterable

user32 = ctypes.windll.user32 if sys.platform == "win32" else None

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

POE_TITLE_HINTS = ("Path of Exile 2", "Path of Exile II")
EXCLUDE_TITLE_HINTS = (
    "ExileLens",
    "PoE2 Value",  # legacy title, kept so stale windows stay excluded
    "Tree Coach",
    "TREE OVERLAY",
    "Calibrate",
    "Diagnostics",
    "Analyze Build",
)


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


@dataclass(frozen=True)
class PoeClientGeometry:
    hwnd: int
    title: str
    class_name: str
    window_rect: tuple[int, int, int, int]
    client_rect_screen: tuple[int, int, int, int]
    client_logical: tuple[int, int, int, int]
    dpi: float
    topmost: bool

    @property
    def client_width(self) -> int:
        x0, _y0, x1, _y1 = self.client_logical
        return max(0, x1 - x0)

    @property
    def client_height(self) -> int:
        _x0, y0, _x1, y1 = self.client_logical
        return max(0, y1 - y0)


def _enum_windows_win32() -> list[dict[str, Any]]:
    if user32 is None:
        return []
    windows: list[dict[str, Any]] = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _cb(hwnd, _lparam):  # noqa: ANN001
        if not user32.IsWindowVisible(hwnd):
            return True
        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)
        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        windows.append({"hwnd": int(hwnd), "title": title_buf.value, "class_name": cls_buf.value})
        return True

    cb = WNDENUMPROC(_cb)
    user32.EnumWindows(cb, 0)
    return windows


def enumerate_top_level_windows(enumerator: Callable[[], list[dict[str, Any]]] | None = None) -> list[dict[str, Any]]:
    fn = enumerator or _enum_windows_win32
    return list(fn())


def _looks_like_poe(title: str) -> bool:
    lowered = title.lower()
    if any(skip.lower() in lowered for skip in EXCLUDE_TITLE_HINTS):
        return False
    return any(hint.lower() in lowered for hint in POE_TITLE_HINTS)


def select_poe_window(windows: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    matches = [row for row in windows if _looks_like_poe(str(row.get("title") or ""))]
    if not matches:
        return None
    exact = [row for row in matches if str(row.get("title") or "").strip() in POE_TITLE_HINTS]
    return exact[0] if exact else matches[0]


def _physical_client_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if user32 is None:
        return None
    client = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(client)):
        return None
    origin = POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    width = int(client.right - client.left)
    height = int(client.bottom - client.top)
    return (int(origin.x), int(origin.y), int(origin.x) + width, int(origin.y) + height)


def _physical_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if user32 is None:
        return None
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))


def physical_to_logical(px: float, py: float, *, screens: list[Any] | None = None) -> tuple[float, float]:
    """Convert Win32 physical pixels to Qt logical pixels."""
    try:
        from PySide6.QtGui import QGuiApplication
    except Exception:
        return (float(px), float(py))
    items = screens if screens is not None else list(QGuiApplication.screens() or [])
    for screen in items:
        geo = screen.geometry()
        dpr = float(screen.devicePixelRatio() or 1.0)
        if dpr <= 0:
            dpr = 1.0
        ox = float(geo.x()) * dpr
        oy = float(geo.y()) * dpr
        w = float(geo.width()) * dpr
        h = float(geo.height()) * dpr
        if ox <= px < ox + w and oy <= py < oy + h:
            return (float(geo.x()) + (px - ox) / dpr, float(geo.y()) + (py - oy) / dpr)
    primary = QGuiApplication.primaryScreen()
    dpr = float(primary.devicePixelRatio() or 1.0) if primary is not None else 1.0
    if dpr <= 0:
        dpr = 1.0
    return (px / dpr, py / dpr)


def _screen_dpi_at(lx: float, ly: float) -> float:
    try:
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication
    except Exception:
        return 1.0
    screen = QGuiApplication.screenAt(QPoint(int(lx), int(ly))) or QGuiApplication.primaryScreen()
    if screen is None:
        return 1.0
    return float(screen.devicePixelRatio() or 1.0)


def _exstyle(hwnd: int) -> int:
    if user32 is None:
        return 0
    getter = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
    getter.restype = ctypes.c_ssize_t
    getter.argtypes = [ctypes.c_void_p, ctypes.c_int]
    return int(getter(hwnd, GWL_EXSTYLE) or 0)


def poe_client_geometry(
    *,
    enumerator: Callable[[], list[dict[str, Any]]] | None = None,
    client_rect_fn: Callable[[int], tuple[int, int, int, int] | None] | None = None,
    window_rect_fn: Callable[[int], tuple[int, int, int, int] | None] | None = None,
    screens: list[Any] | None = None,
) -> PoeClientGeometry | None:
    row = select_poe_window(enumerate_top_level_windows(enumerator))
    if row is None:
        return None
    hwnd = int(row["hwnd"])
    physical_client = (client_rect_fn or _physical_client_rect)(hwnd)
    physical_window = (window_rect_fn or _physical_window_rect)(hwnd)
    if physical_client is None or physical_window is None:
        return None
    lx0, ly0 = physical_to_logical(physical_client[0], physical_client[1], screens=screens)
    lx1, ly1 = physical_to_logical(physical_client[2], physical_client[3], screens=screens)
    wx0, wy0 = physical_to_logical(physical_window[0], physical_window[1], screens=screens)
    wx1, wy1 = physical_to_logical(physical_window[2], physical_window[3], screens=screens)
    return PoeClientGeometry(
        hwnd=hwnd,
        title=str(row.get("title") or ""),
        class_name=str(row.get("class_name") or ""),
        window_rect=(int(round(wx0)), int(round(wy0)), int(round(wx1)), int(round(wy1))),
        client_rect_screen=physical_client,
        client_logical=(int(round(lx0)), int(round(ly0)), int(round(lx1)), int(round(ly1))),
        dpi=_screen_dpi_at(lx0, ly0),
        topmost=bool(_exstyle(hwnd) & WS_EX_TOPMOST),
    )


def set_hwnd_topmost(hwnd: int, *, topmost: bool = True) -> None:
    """Z-order only.

    SWP_SHOWWINDOW used to be part of these flags, which made every topmost
    refresh a show command: a window that had been dismissed came back the next
    time anything restacked it. Z-order maintenance and visibility are separate
    concerns — callers that want the window on screen must show it explicitly.
    """
    if user32 is None or not hwnd:
        return
    insert = HWND_TOPMOST if topmost else HWND_NOTOPMOST
    user32.SetWindowPos(int(hwnd), insert, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def describe_widget_hwnd(widget: Any) -> dict[str, Any]:
    hwnd = 0
    try:
        hwnd = int(widget.winId())
    except Exception:
        hwnd = 0
    geo = widget.geometry() if widget is not None else None
    native = _exstyle(hwnd) if hwnd else 0
    return {
        "hwnd": hwnd,
        "title": str(widget.windowTitle()) if widget is not None else "",
        "geometry": (geo.x(), geo.y(), geo.width(), geo.height()) if geo is not None else None,
        "visible": bool(widget.isVisible()) if widget is not None else False,
        "topmost": bool(native & WS_EX_TOPMOST),
        "ws_ex": native,
        "window_opacity": float(widget.windowOpacity()) if widget is not None else 1.0,
    }
