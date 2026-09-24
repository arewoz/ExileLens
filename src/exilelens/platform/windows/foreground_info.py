from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

from exilelens.platform.windows.poe_window import (
    POE_TITLE_HINTS,
    enumerate_top_level_windows,
    select_poe_window,
)

user32 = ctypes.windll.user32 if sys.platform == "win32" else None
kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None

GA_ROOT = 2

POE_EXECUTABLE_HINTS = (
    "pathofexile.exe",
    "pathofexilesteam.exe",
    "pathofexile_kg.exe",
    "pathofexileegs.exe",
)


@dataclass(frozen=True)
class ForegroundWindowInfo:
    hwnd: int
    title: str
    pid: int
    executable: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "pid": self.pid,
            "executable": self.executable,
        }


def _read_process_executable(pid: int) -> str:
    if kernel32 is None or pid <= 0:
        return ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    try:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    except Exception:
        return ""
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if hasattr(kernel32, "QueryFullProcessImageNameW"):
            try:
                ok = bool(kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)))
            except Exception:
                ok = False
            if ok:
                return str(buf.value or "")
        return ""
    finally:
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass


def _window_pid(hwnd: int) -> int:
    if user32 is None or not hwnd:
        return 0
    pid = wintypes.DWORD(0)
    try:
        user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
    except Exception:
        return 0
    return int(pid.value or 0)


def _root_hwnd(hwnd: int) -> int:
    if user32 is None or not hwnd:
        return hwnd
    try:
        root = int(user32.GetAncestor(int(hwnd), GA_ROOT) or hwnd)
    except Exception:
        return hwnd
    return root if root else hwnd


def get_foreground_window_info() -> ForegroundWindowInfo | None:
    if user32 is None:
        return None
    try:
        hwnd = int(user32.GetForegroundWindow() or 0)
    except Exception:
        return None
    if not hwnd:
        return None
    try:
        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)
        title = str(title_buf.value or "")
    except Exception:
        title = ""
    pid = _window_pid(hwnd)
    executable = _read_process_executable(pid)
    return ForegroundWindowInfo(
        hwnd=hwnd,
        title=title,
        pid=pid,
        executable=executable,
    )


def _executable_basename(executable: str) -> str:
    lowered = str(executable or "").replace("\\", "/").lower()
    if not lowered:
        return ""
    return lowered.rsplit("/", 1)[-1]


def _executable_matches_poe(executable: str) -> bool:
    name = _executable_basename(executable)
    if not name:
        return False
    return any(name == hint for hint in POE_EXECUTABLE_HINTS)


def _title_looks_like_poe(title: str) -> bool:
    lowered = str(title or "").lower()
    return any(hint.lower() in lowered for hint in POE_TITLE_HINTS)


def evaluate_poe_foreground_match() -> dict[str, Any]:
    """Fresh fail-closed PoE foreground authorization snapshot.

    Capture authorization is based only on the foreground HWND's owning PID and
    executable.  Window enumeration, titles, and the selected PoE window are
    retained solely for diagnostics and overlay geometry.
    """
    try:
        fg = get_foreground_window_info()
    except Exception:
        fg = None
    try:
        windows = enumerate_top_level_windows()
        row = select_poe_window(windows)
    except Exception:
        row = None

    fg_hwnd = int(fg.hwnd) if fg is not None else 0
    fg_root = _root_hwnd(fg_hwnd) if fg_hwnd else 0
    fg_title = fg.title if fg is not None else ""
    fg_exe = fg.executable if fg is not None else ""
    fg_pid = fg.pid if fg is not None else 0
    process_name = _executable_basename(fg_exe)

    expected_hwnd = int(row.get("hwnd") or 0) if row else 0
    expected_title = str(row.get("title") or "") if row else ""
    expected_pid = _window_pid(expected_hwnd) if expected_hwnd else 0

    hwnd_match = bool(
        expected_hwnd and (fg_hwnd == expected_hwnd or fg_root == expected_hwnd)
    )
    pid_match = bool(expected_pid and fg_pid == expected_pid)
    exe_match = _executable_matches_poe(fg_exe)
    title_match = _title_looks_like_poe(fg_title)

    accepted = bool(fg_hwnd and fg_pid and fg_exe and exe_match)

    return {
        "current_hwnd": fg_hwnd,
        "current_root_hwnd": fg_root,
        "current_pid": fg_pid,
        "current_process_name": process_name,
        "current_window_title": fg_title,
        "poe_match_result": accepted,
        "accepted": accepted,
        "hwnd_match": hwnd_match,
        "pid_match": pid_match,
        "executable_match": exe_match,
        "title_match": title_match,
        "foreground": fg.to_dict() if fg is not None else None,
        "expected_poe_window": {
            "hwnd": expected_hwnd,
            "title": expected_title,
            "pid": expected_pid,
        },
    }


def describe_poe_foreground_match() -> dict[str, Any]:
    """Diagnostic snapshot for PoE foreground matching."""
    return evaluate_poe_foreground_match()


def is_own_app_foreground() -> bool:
    """True when this process owns the foreground window."""
    fg = get_foreground_window_info()
    if fg is None:
        return False
    return int(fg.pid or 0) == int(os.getpid())


def is_poe_foreground() -> bool:
    """True when the Path of Exile 2 window owns foreground focus."""
    if user32 is None:
        return False
    try:
        if is_own_app_foreground():
            return False
        return bool(evaluate_poe_foreground_match().get("accepted"))
    except Exception:
        return False
