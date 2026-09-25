"""Actionable elevation mismatch diagnostics for keyboard-hook failures."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

from exilelens.platform.windows.poe_window import enumerate_top_level_windows, select_poe_window

kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None
advapi32 = ctypes.windll.advapi32 if sys.platform == "win32" else None
user32 = ctypes.windll.user32 if sys.platform == "win32" else None
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION_CLASS = 20
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

if kernel32 is not None:
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
if advapi32 is not None:
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL


class TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


def _is_elevated(process_handle: int) -> bool | None:
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(wintypes.HANDLE(process_handle), TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        value = TOKEN_ELEVATION()
        size = wintypes.DWORD()
        if not advapi32.GetTokenInformation(token, TOKEN_ELEVATION_CLASS, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(size)):
            return None
        return bool(value.TokenIsElevated)
    finally:
        kernel32.CloseHandle(token)


@dataclass(frozen=True)
class ElevationStatus:
    mismatch: bool
    app_elevated: bool | None
    poe_elevated: bool | None
    detail: str


def evaluate_elevation_status() -> ElevationStatus:
    if kernel32 is None or advapi32 is None or user32 is None:
        return ElevationStatus(False, None, None, "Elevation check is only available on Windows.")
    app_elevated = _is_elevated(kernel32.GetCurrentProcess())
    try:
        row = select_poe_window(enumerate_top_level_windows())
    except Exception:
        row = None
    if not row:
        return ElevationStatus(False, app_elevated, None, "Path of Exile 2 is not running.")
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(int(row.get("hwnd") or 0), ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        detail = "Could not inspect Path of Exile 2 privileges (access denied). If the game runs as administrator, run ExileLens as administrator too."
        return ElevationStatus(not bool(app_elevated), app_elevated, None, detail)
    try:
        poe_elevated = _is_elevated(handle)
    finally:
        kernel32.CloseHandle(handle)
    mismatch = poe_elevated is True and app_elevated is False
    detail = (
        "Path of Exile 2 is running as administrator. Run ExileLens as administrator too so the hotkey can reach the game."
        if mismatch
        else "ExileLens and Path of Exile 2 privilege levels are compatible."
    )
    return ElevationStatus(mismatch, app_elevated, poe_elevated, detail)
