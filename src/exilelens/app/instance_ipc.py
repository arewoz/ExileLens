"""Second-launch activation for the one running ExileLens instance.

The single-instance mutex (``single_instance.py``) stops a duplicate, but on its own it
left a tester with a process that was "already running" and nothing on screen. A second
launch now asks the running copy, over a per-user local socket, to show its window, and
waits for an acknowledgement. No acknowledgement means the running copy is not
processing events; the caller may then offer the user an explicit way to end it.

``instance.json`` records which process owns the lock, so an unresponsive copy can be
identified and verified by executable path before anything is terminated.
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

COMMAND_ACTIVATE = "activate"
COMMAND_QUIT = "quit"
_COMMANDS = frozenset({COMMAND_ACTIVATE, COMMAND_QUIT})
_ACK = b"ok\n"
INSTANCE_RECORD_NAME = "instance.json"
QUIT_ARG = "--quit"
DEFAULT_ACK_TIMEOUT_MS = 3000


def _current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - any failure falls back to the environment
        return os.environ.get("USERNAME") or os.environ.get("USER") or "user"


def server_name(user: str | None = None) -> str:
    """Per-user endpoint name, so two Windows users never activate each other."""
    raw = user if user is not None else _current_user()
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", raw or "user")
    return f"ExileLens.{safe}.activate"


class InstanceServer(QObject):
    """Listens for activate/quit commands from later launches."""

    activate_requested = Signal()
    quit_requested = Signal()

    def __init__(self, name: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = name or server_name()
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)

    @property
    def name(self) -> str:
        return self._name

    @property
    def listening(self) -> bool:
        return self._server.isListening()

    def start(self) -> bool:
        # A crashed owner can leave a stale endpoint on POSIX. On Windows the pipe dies
        # with its process, so this is a no-op there.
        QLocalServer.removeServer(self._name)
        if not self._server.listen(self._name):
            logger.error("instance_ipc listen_failed name=%s error=%s", self._name, self._server.errorString())
            return False
        logger.info("instance_ipc listening name=%s", self._name)
        return True

    def close(self) -> None:
        if self._server.isListening():
            self._server.close()
            logger.info("instance_ipc closed name=%s", self._name)

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                return
            socket.readyRead.connect(lambda s=socket: self._on_ready_read(s))
            socket.disconnected.connect(socket.deleteLater)
            if socket.canReadLine():
                self._on_ready_read(socket)

    def _on_ready_read(self, socket: QLocalSocket) -> None:
        if not socket.canReadLine():
            return
        command = bytes(socket.readLine()).decode("utf-8", "replace").strip().lower()
        if command not in _COMMANDS:
            logger.warning("instance_ipc unknown_command=%r", command[:40])
            socket.disconnectFromServer()
            return
        # Acknowledge first: the waiting launch only needs to know we are alive.
        socket.write(_ACK)
        socket.flush()
        logger.info("ipc_%s_received", command)
        if command == COMMAND_ACTIVATE:
            self.activate_requested.emit()
        else:
            self.quit_requested.emit()
        socket.disconnectFromServer()


def send_command(command: str, *, name: str | None = None, timeout_ms: int = DEFAULT_ACK_TIMEOUT_MS) -> bool:
    """Send one command to the running instance. True only when it acknowledged."""
    if command not in _COMMANDS:
        raise ValueError(f"unknown instance command: {command}")
    target = name or server_name()
    deadline = time.monotonic() + timeout_ms / 1000.0

    def remaining_ms() -> int:
        return max(0, int((deadline - time.monotonic()) * 1000))

    socket = QLocalSocket()
    socket.connectToServer(target)
    if not socket.waitForConnected(remaining_ms()):
        logger.info("instance_ipc connect_failed name=%s error=%s", target, socket.errorString())
        return False
    socket.write(f"{command}\n".encode("utf-8"))
    if not socket.waitForBytesWritten(remaining_ms()):
        logger.info("instance_ipc write_failed name=%s", target)
        socket.abort()
        return False
    received = b""
    while b"\n" not in received:
        wait = remaining_ms()
        if wait <= 0 or not socket.waitForReadyRead(wait):
            received += bytes(socket.readAll())
            break
        received += bytes(socket.readAll())
    socket.abort()
    acknowledged = received.startswith(_ACK.strip())
    logger.info("instance_ipc command=%s acknowledged=%s", command, acknowledged)
    return acknowledged


def allow_foreground_activation() -> None:
    """Let the running instance take the foreground when we hand activation to it.

    Windows only lets a process raise its window if it received the last input; the
    launching process did, so it passes that right on before signalling.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(ctypes.c_uint32(0xFFFFFFFF).value)
    except Exception:  # noqa: BLE001 - activation still works, it may just flash the taskbar
        logger.debug("AllowSetForegroundWindow failed", exc_info=True)


@dataclass(frozen=True)
class InstanceRecord:
    pid: int
    exe: str
    started_at: float


def record_path() -> Path:
    from exilelens.app.settings import app_data_dir

    return app_data_dir() / INSTANCE_RECORD_NAME


def write_instance_record(path: Path | None = None) -> InstanceRecord:
    record = InstanceRecord(pid=os.getpid(), exe=str(sys.executable), started_at=time.time())
    target = path or record_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"pid": record.pid, "exe": record.exe, "started_at": record.started_at}),
            encoding="utf-8",
        )
    except OSError:
        logger.exception("instance_record write_failed path=%s", target)
    return record


def read_instance_record(path: Path | None = None) -> InstanceRecord | None:
    target = path or record_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return InstanceRecord(pid=int(data["pid"]), exe=str(data["exe"]), started_at=float(data.get("started_at", 0)))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def clear_instance_record(path: Path | None = None) -> None:
    target = path or record_path()
    record = read_instance_record(target)
    if record is None or record.pid != os.getpid():
        return
    try:
        target.unlink()
    except OSError:
        logger.debug("instance_record unlink_failed", exc_info=True)


# --- Explicit, user-confirmed termination of an unresponsive copy -----------------------

_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_TH32CS_SNAPPROCESS = 0x00000002


def _same_exe(left: str, right: str) -> bool:
    return bool(left) and bool(right) and os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _process_image(pid: int) -> str:
    from exilelens.platform.windows.foreground_info import _read_process_executable

    return _read_process_executable(int(pid)) or ""


def _snapshot_processes() -> list[tuple[int, int, str]]:
    """(pid, parent_pid, exe_basename) for every process. Empty off Windows."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
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
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return []
    rows: list[tuple[int, int, str]] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            rows.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID), str(entry.szExeFile)))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return rows


def _terminate_pid(pid: int, *, wait_ms: int = 5000) -> bool:
    if sys.platform != "win32":
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except OSError:
            return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(_PROCESS_TERMINATE | _SYNCHRONIZE, False, int(pid))
    if not handle:
        return False
    try:
        if not kernel32.TerminateProcess(handle, 1):
            return False
        kernel32.WaitForSingleObject(handle, int(wait_ms))
        return True
    finally:
        kernel32.CloseHandle(handle)


def find_running_instances() -> list[int]:
    """Other processes running this executable, excluding our own worker children.

    Used when no ``instance.json`` exists, e.g. a pre-0.1.0b3 copy without IPC. Only
    meaningful for the frozen exe; in a source run every python.exe would match.
    """
    if not getattr(sys, "frozen", False):
        return []
    own = os.getpid()
    basename = os.path.basename(sys.executable).lower()
    rows = _snapshot_processes()
    candidates = {pid: parent for pid, parent, exe in rows if exe.lower() == basename and pid != own and parent != own}
    # A PoB worker is the same exe started by another candidate; it is ended with its parent.
    return sorted(pid for pid, parent in candidates.items() if parent not in candidates)


def terminate_instance(pid: int, expected_exe: str) -> tuple[bool, str]:
    """End an unresponsive ExileLens process and its PoB workers after verifying identity."""
    if pid == os.getpid():
        return False, "refusing to end the current process"
    image = _process_image(pid)
    if not image:
        return True, f"process {pid} is no longer running"
    if not _same_exe(image, expected_exe):
        return False, f"process {pid} is {image}, not ExileLens; it was left running"
    children = [child for child, parent, _exe in _snapshot_processes() if parent == pid]
    ended = _terminate_pid(pid)
    for child in children:
        if _same_exe(_process_image(child), expected_exe):
            _terminate_pid(child, wait_ms=2000)
    logger.warning("instance_terminated pid=%s exe=%s children=%s ok=%s", pid, image, children, ended)
    if not ended:
        return False, f"Windows refused to end process {pid}"
    return True, f"ended process {pid}"
