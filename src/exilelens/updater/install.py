from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def wait_for_process_exit(pid: int, *, timeout_seconds: float = 120.0) -> bool:
    if pid <= 0:
        return True
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not _process_alive(pid):
            return True
        time.sleep(0.25)
    return not _process_alive(pid)


def _process_alive(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            import os

            os.kill(pid, 0)
        except OSError:
            return False
        return True
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return int(exit_code.value) == STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def install_verified_update(*, install_root: Path, staged_root: Path, backup_root: Path) -> None:
    install_root = install_root.resolve()
    staged_root = staged_root.resolve()
    backup_root = backup_root.resolve()
    if not staged_root.is_dir():
        raise RuntimeError("staged_root_missing")
    if backup_root.exists():
        shutil.rmtree(backup_root, ignore_errors=True)
    backup_root.mkdir(parents=True, exist_ok=True)
    for entry in install_root.iterdir():
        if entry.name in {".update-backup", "updates"}:
            continue
        destination = backup_root / entry.name
        if entry.is_dir():
            shutil.copytree(entry, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, destination)
    for entry in staged_root.iterdir():
        target = install_root / entry.name
        if entry.is_dir():
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(entry, target)
        else:
            shutil.copy2(entry, target)


def restore_backup(*, install_root: Path, backup_root: Path) -> None:
    if not backup_root.is_dir():
        raise RuntimeError("backup_missing")
    for entry in backup_root.iterdir():
        target = install_root / entry.name
        if entry.is_dir():
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(entry, target)
        else:
            shutil.copy2(entry, target)


def restart_application(exe_path: Path) -> None:
    subprocess.Popen([str(exe_path)], close_fds=True, cwd=str(exe_path.parent))


def load_job(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("invalid_job")
    return payload


def run_update_job(job_path: Path) -> int:
    job = load_job(job_path)
    pid = int(job.get("pid") or 0)
    install_root = Path(str(job.get("install_root") or "")).resolve()
    staged_root = Path(str(job.get("staged_root") or "")).resolve()
    backup_root = Path(str(job.get("backup_root") or "")).resolve()
    exe_path = Path(str(job.get("exe_path") or (install_root / "ExileLens.exe"))).resolve()
    if not wait_for_process_exit(pid):
        logger.error("update_aborted_parent_still_running pid=%s", pid)
        return 2
    try:
        install_verified_update(install_root=install_root, staged_root=staged_root, backup_root=backup_root)
    except Exception:
        logger.exception("update_install_failed")
        try:
            restore_backup(install_root=install_root, backup_root=backup_root)
        except Exception:
            logger.exception("update_restore_failed")
            return 3
        return 4
    try:
        restart_application(exe_path)
    except Exception:
        logger.exception("update_restart_failed")
        return 5
    return 0
