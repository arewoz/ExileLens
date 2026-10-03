"""Per-user Windows DPAPI protection for small secrets (ctypes only, no dependency).

``protect`` / ``unprotect`` wrap ``CryptProtectData`` / ``CryptUnprotectData`` with the *current user* scope
(never ``CRYPTPROTECT_LOCAL_MACHINE``) and an application-specific entropy value, so another Windows
account on the same PC — or another application using DPAPI without our entropy — cannot read the blob.
No size limit applies (unlike the Credential Manager's 2560-byte blob).

On non-Windows platforms the functions raise ``DpapiUnavailable``; callers treat that as "no credential".
"""

from __future__ import annotations

import sys

ENTROPY = b"ExileLens/device-credential/v1"
_UI_FORBIDDEN = 0x1  # CRYPTPROTECT_UI_FORBIDDEN


class DpapiUnavailable(RuntimeError):
    """DPAPI is not usable here (non-Windows) or the blob cannot be decrypted by this user."""


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob), wintypes.LPVOID,
        wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(_Blob),
    ]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_Blob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_Blob), wintypes.LPVOID,
        wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(_Blob),
    ]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    _kernel32.LocalFree.restype = wintypes.HLOCAL

    def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
        buffer = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    def _take(blob: _Blob) -> bytes:
        try:
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(blob.pbData, wintypes.HLOCAL))

    def protect(data: bytes, entropy: bytes = ENTROPY) -> bytes:
        source, _keep1 = _blob(data)
        extra, _keep2 = _blob(entropy)
        out = _Blob()
        if not _crypt32.CryptProtectData(ctypes.byref(source), "ExileLens", ctypes.byref(extra), None, None, _UI_FORBIDDEN, ctypes.byref(out)):
            raise DpapiUnavailable(f"CryptProtectData failed ({ctypes.get_last_error()})")
        return _take(out)

    def unprotect(blob: bytes, entropy: bytes = ENTROPY) -> bytes:
        source, _keep1 = _blob(blob)
        extra, _keep2 = _blob(entropy)
        out = _Blob()
        if not _crypt32.CryptUnprotectData(ctypes.byref(source), None, ctypes.byref(extra), None, None, _UI_FORBIDDEN, ctypes.byref(out)):
            raise DpapiUnavailable(f"CryptUnprotectData failed ({ctypes.get_last_error()})")
        return _take(out)

else:  # pragma: no cover - exercised only on non-Windows hosts

    def protect(data: bytes, entropy: bytes = ENTROPY) -> bytes:
        raise DpapiUnavailable("DPAPI is only available on Windows")

    def unprotect(blob: bytes, entropy: bytes = ENTROPY) -> bytes:
        raise DpapiUnavailable("DPAPI is only available on Windows")
