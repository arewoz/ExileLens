"""One running copy of the app, not two.

MARKET-01B13 §16. Nothing stopped a second instance from starting, and two instances
register the same global Price Check hotkey — one keypress, two overlays, two searches
against a shared per-IP request budget. The second copy now detects the first and exits
cleanly instead.

Windows uses a named kernel mutex, which the OS releases even if the process is killed,
so a crash cannot leave the app permanently unstartable. Other platforms fall back to a
PID file that is treated as stale when the process it names is gone.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Deliberately keeps the pre-ExileLens name: the lock only has to be stable, and a
# rename would let an old PoE2ValueForMyBuild.exe and a new ExileLens.exe both run,
# both grabbing the Price Check hotkey and the same per-IP budget. See docs/BRANDING.md.
LOCK_NAME = "Global\\PoE2ValueForMyBuild.singleton"
_ERROR_ALREADY_EXISTS = 183


@dataclass
class InstanceLock:
    """The outcome of trying to become the one running instance."""

    acquired: bool
    reason: str
    _release: Callable[[], None] | None = None

    def release(self) -> None:
        if self._release is not None:
            try:
                self._release()
            finally:
                self._release = None


def _acquire_windows(name: str) -> InstanceLock:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.CreateMutexW(None, True, name)
    last_error = ctypes.get_last_error()
    if not handle:
        # Without a handle we cannot tell; let the app start rather than block it.
        return InstanceLock(True, f"could not create the instance mutex (error {last_error})")
    if last_error == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return InstanceLock(False, "another instance already holds the lock")
    return InstanceLock(True, "acquired", lambda: kernel32.CloseHandle(handle))


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _acquire_pidfile(path: Path) -> InstanceLock:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = int(path.read_text(encoding="utf-8").strip() or 0)
        except (ValueError, OSError):
            existing = 0
        if existing and existing != os.getpid() and _process_alive(existing):
            return InstanceLock(False, f"another instance is running (pid {existing})")
    try:
        path.write_text(str(os.getpid()), encoding="utf-8")
    except OSError as exc:
        return InstanceLock(True, f"could not write the instance lock file ({exc})")

    def _release() -> None:
        try:
            if path.exists() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                path.unlink()
        except OSError:
            pass

    return InstanceLock(True, "acquired", _release)


def acquire_single_instance_lock(
    *,
    name: str = LOCK_NAME,
    pid_file: Path | None = None,
) -> InstanceLock:
    """Become the one running instance, or report that another already is.

    A failure to evaluate the lock resolves to *acquired* on purpose: the guard exists to
    stop a duplicate, and it must never be the reason the app cannot start at all.
    """
    if sys.platform == "win32" and pid_file is None:
        try:
            return _acquire_windows(name)
        except Exception as exc:  # pragma: no cover - defensive
            return InstanceLock(True, f"instance lock unavailable ({exc})")

    if pid_file is None:
        from poe2value.app.settings import app_data_dir

        pid_file = app_data_dir() / "instance.pid"
    return _acquire_pidfile(Path(pid_file))
