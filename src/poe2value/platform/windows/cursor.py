"""Win32 cursor position and monitor work-area helpers."""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass

user32 = ctypes.windll.user32 if sys.platform == "win32" else None

MONITOR_DEFAULTTONEAREST = 2


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


@dataclass(frozen=True)
class MonitorWorkArea:
    monitor_rect: tuple[int, int, int, int]
    work_rect: tuple[int, int, int, int]

    @property
    def work_width(self) -> int:
        return self.work_rect[2] - self.work_rect[0]

    @property
    def work_height(self) -> int:
        return self.work_rect[3] - self.work_rect[1]


def get_cursor_pos_physical() -> tuple[int, int] | None:
    if user32 is None:
        return None
    point = POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return None
    return (int(point.x), int(point.y))


def monitor_work_area_at_physical(px: int, py: int) -> MonitorWorkArea | None:
    if user32 is None:
        return None
    point = POINT(int(px), int(py))
    monitor = user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
    if not monitor:
        return None
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    mon = info.rcMonitor
    work = info.rcWork
    return MonitorWorkArea(
        monitor_rect=(int(mon.left), int(mon.top), int(mon.right), int(mon.bottom)),
        work_rect=(int(work.left), int(work.top), int(work.right), int(work.bottom)),
    )
