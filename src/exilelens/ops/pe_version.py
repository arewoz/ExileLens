"""Read the Windows version resource of an executable (release gate / tests). Windows only; ``None`` elsewhere or on failure."""

from __future__ import annotations

import sys
from pathlib import Path

_FIELDS = ("CompanyName", "FileDescription", "FileVersion", "InternalName", "OriginalFilename", "ProductName", "ProductVersion")


def read_version_strings(path: Path) -> dict[str, str] | None:
    """The StringFileInfo block of ``path`` (the file's own translation, else US English / Unicode), or None when unreadable."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    version = ctypes.WinDLL("version", use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    version.GetFileVersionInfoW.restype = wintypes.BOOL
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    version.VerQueryValueW.restype = wintypes.BOOL
    handle = wintypes.DWORD(0)
    size = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(handle))
    if not size:
        return None
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        return None
    blocks = ["040904B0"]
    translation = ctypes.c_void_p()
    tlen = wintypes.UINT(0)
    if version.VerQueryValueW(buffer, "\\VarFileInfo\\Translation", ctypes.byref(translation), ctypes.byref(tlen)) and translation.value and tlen.value >= 4:
        lang, page = ctypes.cast(translation.value, ctypes.POINTER(ctypes.c_ushort * 2)).contents
        blocks.insert(0, f"{lang:04X}{page:04X}")
    strings: dict[str, str] = {}
    for block in blocks:
        for name in _FIELDS:
            value = ctypes.c_void_p()
            length = wintypes.UINT(0)
            if version.VerQueryValueW(buffer, f"\\StringFileInfo\\{block}\\{name}", ctypes.byref(value), ctypes.byref(length)) and value.value:
                strings[name] = ctypes.wstring_at(value.value, max(length.value - 1, 0))
        if strings:
            break
    return strings or None
