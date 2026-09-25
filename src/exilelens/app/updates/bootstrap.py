from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

from exilelens._version import is_packaged
from exilelens.app.updates.paths import bundled_updater_executable, updater_executable

logger = logging.getLogger(__name__)


def ensure_updater_bootstrapped() -> Path | None:
    """Copy the standalone updater into app data so it survives in-place upgrades."""
    if not is_packaged():
        return None
    destination = updater_executable()
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    source = bundled_updater_executable()
    if not source.is_file():
        logger.warning("update_updater_bootstrap_missing source=%s", source)
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    logger.info("update_updater_bootstrapped destination=%s", destination)
    return destination


def launch_updater(job_path: Path) -> None:
    if is_packaged():
        updater = ensure_updater_bootstrapped()
        if updater is None or not updater.is_file():
            raise RuntimeError("updater_unavailable")
        subprocess.Popen(
            [str(updater), str(job_path)],
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )
        return
    subprocess.Popen(
        [sys.executable, "-m", "exilelens.updater", str(job_path)],
        close_fds=True,
    )
