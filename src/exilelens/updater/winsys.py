"""Windows-only process and mutex primitives for the updater (ctypes, stdlib only).

Non-Windows platforms get inert fallbacks so the pure-Python install logic stays testable everywhere.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Callable, Iterable

from exilelens.updater.layout import UPDATER_MUTEX_NAME, is_within

_IS_WINDOWS = sys.platform == "win32"
ERROR_ALREADY_EXISTS = 183
SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH_CHARS = 32768

if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.OpenMutexW.restype = wintypes.HANDLE
    _kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    _kernel32.ReleaseMutex.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    _kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _kernel32.Process32FirstW.restype = wintypes.BOOL
    _kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _kernel32.Process32NextW.restype = wintypes.BOOL
    _INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class UpdaterMutex:
    """Owned updater mutex; released explicitly or when the process exits (the OS reclaims it)."""

    def __init__(self, handle) -> None:
        self._handle = handle

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle and _IS_WINDOWS:
            _kernel32.ReleaseMutex(handle)
            _kernel32.CloseHandle(handle)


def acquire_updater_mutex(name: str = UPDATER_MUTEX_NAME) -> UpdaterMutex | None:
    """Return the owned mutex, or ``None`` when another updater instance already holds it."""
    if not _IS_WINDOWS:
        return UpdaterMutex(None)
    handle = _kernel32.CreateMutexW(None, True, name)
    error = ctypes.get_last_error()
    if not handle:
        raise OSError(error, "CreateMutexW failed")
    if error == ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return None
    return UpdaterMutex(handle)


def updater_mutex_active(name: str = UPDATER_MUTEX_NAME) -> bool:
    """True while any updater process holds (or is creating) the updater mutex."""
    if not _IS_WINDOWS:
        return False
    handle = _kernel32.OpenMutexW(SYNCHRONIZE, False, name)
    if not handle:
        return False
    _kernel32.CloseHandle(handle)
    return True


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if not _IS_WINDOWS:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return int(exit_code.value) == STILL_ACTIVE
    finally:
        _kernel32.CloseHandle(handle)


def _image_path(pid: int) -> str | None:
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(MAX_PATH_CHARS)
        buffer = ctypes.create_unicode_buffer(MAX_PATH_CHARS)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value
    finally:
        _kernel32.CloseHandle(handle)


def _all_pids() -> list[int]:
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == _INVALID_HANDLE_VALUE:
        return []
    pids: list[int] = []
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            pids.append(int(entry.th32ProcessID))
            ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    return pids


def processes_running_from(root: Path, *, exclude: Iterable[int] = ()) -> list[int]:
    """PIDs whose executable image lives under ``root`` (e.g. ExileLens.exe UI and PoB worker processes)."""
    if not _IS_WINDOWS:
        return []
    skip = {os.getpid(), *exclude}
    found: list[int] = []
    for pid in _all_pids():
        if pid in skip or pid <= 4:
            continue
        image = _image_path(pid)
        if image and is_within(Path(image), root):
            found.append(pid)
    return found


def wait_for_install_processes(
    install_root: Path,
    *,
    parent_pid: int = 0,
    timeout_seconds: float = 120.0,
    poll_seconds: float = 0.25,
    list_processes: Callable[[Path], list[int]] | None = None,
    is_alive: Callable[[int], bool] = pid_alive,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Wait until the parent and every process running from the install have exited. Never kills anything."""
    lister = list_processes or (lambda root: processes_running_from(root))
    deadline = clock() + timeout_seconds
    while True:
        busy = (parent_pid > 0 and is_alive(parent_pid)) or bool(lister(install_root))
        if not busy:
            return True
        if clock() >= deadline:
            return False
        sleep(poll_seconds)
