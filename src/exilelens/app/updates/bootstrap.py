from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
from pathlib import Path

from exilelens._version import is_packaged
from exilelens.app.updates.paths import bundled_updater_executable, updater_executable
from exilelens.updater import winsys

logger = logging.getLogger(__name__)

# (path, size, mtime_ns) -> sha256; avoids re-hashing unchanged executables on every check.
_DIGEST_CACHE: dict[tuple[str, int, int], str] = {}


def _digest(path: Path) -> str | None:
    try:
        info = path.stat()
    except OSError:
        return None
    key = (str(path), int(info.st_size), int(info.st_mtime_ns))
    cached = _DIGEST_CACHE.get(key)
    if cached is not None:
        return cached
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                hasher.update(chunk)
    except OSError:
        return None
    digest = hasher.hexdigest()
    _DIGEST_CACHE[key] = digest
    return digest


def updater_active() -> bool:
    """True while an external updater holds the dedicated updater mutex."""
    return winsys.updater_mutex_active()


def updater_matches_bundled() -> bool:
    """Handshake for job contract v2: the app-data updater is byte-identical to the one shipped with this app."""
    destination, source = updater_executable(), bundled_updater_executable()
    left, right = _digest(destination), _digest(source)
    return left is not None and left == right


def ensure_updater_bootstrapped() -> Path | None:
    """Install or refresh the app-data updater from the bundled copy (SHA-256 comparison, never timestamps).

    The updater runs from app data so it survives the in-place swap of the install directory. It is never
    replaced while an updater instance holds the updater mutex; a failed refresh keeps the existing copy.
    """
    if not is_packaged():
        return None
    destination = updater_executable()
    source = bundled_updater_executable()
    if not source.is_file():
        logger.warning("update_updater_bootstrap_missing source=%s", source)
        return destination if destination.is_file() else None
    source_digest = _digest(source)
    if destination.is_file() and source_digest is not None and _digest(destination) == source_digest:
        return destination
    if updater_active():
        logger.info("update_updater_refresh_deferred reason=updater_active")
        return destination if destination.is_file() else None
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".tmp")
    try:
        with source.open("rb") as reader, tmp.open("wb") as writer:
            while chunk := reader.read(1024 * 1024):
                writer.write(chunk)
        if _digest(tmp) != source_digest:
            raise OSError("updater copy verification failed")
        os.replace(tmp, destination)
    except OSError:
        logger.exception("update_updater_refresh_failed")
        tmp.unlink(missing_ok=True)
        return destination if destination.is_file() else None
    logger.info("update_updater_refreshed destination=%s", destination)
    return destination


def launch_updater(job_path: Path, *, extra_args: tuple[str, ...] = ()) -> None:
    if is_packaged():
        updater = ensure_updater_bootstrapped()
        if updater is None or not updater.is_file():
            raise RuntimeError("updater_unavailable")
        args = [str(updater), *extra_args]
        if job_path is not None:
            args.append(str(job_path))
        subprocess.Popen(
            args,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )
        return
    subprocess.Popen(
        [sys.executable, "-m", "exilelens.updater", *extra_args, *([str(job_path)] if job_path is not None else [])],
        close_fds=True,
    )
