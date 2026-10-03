"""Next-launch handling of the external updater's result, plus bounded cleanup of update leftovers.

The result file is consumed exactly once (moved to ``last_result.seen.json`` for Diagnostics). Recovery
material (``.update-old``, the backup, the installed package) is only removed once this launch proves the
expected version starts, or once a previous launch already consumed the result.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from exilelens.app.updates.paths import install_root, updates_data_dir
from exilelens.app.updates.version import ExileLensVersion
from exilelens.updater import layout
from exilelens.updater.result import Outcome, UpdateResult, read_result

logger = logging.getLogger(__name__)

STALE_PART_SECONDS = 14 * 24 * 60 * 60


@dataclass(frozen=True)
class UpdateOutcomeNotice:
    kind: str  # "updated" | "restored" | "failed" | "not_installed"
    version: str
    title: str
    message: str
    error_code: str | None = None


def consume_update_result(installed: ExileLensVersion | None) -> tuple[UpdateResult | None, UpdateOutcomeNotice | None]:
    """Read and consume ``last_result.json`` once. Returns the result and a user-facing notice (or ``None``)."""
    updates = updates_data_dir()
    source = layout.result_path(updates)
    result = read_result(source)
    if not source.exists():
        return None, None
    try:
        os.replace(source, layout.seen_result_path(updates))
    except OSError:
        source.unlink(missing_ok=True)
    if result is None:
        logger.warning("update_result_unreadable")
        return None, None
    return result, notice_for_result(result, installed)


def last_seen_result() -> UpdateResult | None:
    return read_result(layout.seen_result_path(updates_data_dir()))


def notice_for_result(result: UpdateResult, installed: ExileLensVersion | None) -> UpdateOutcomeNotice | None:
    target = result.to_version or "the new version"
    outcome = result.outcome
    if outcome in {Outcome.SUCCESS, Outcome.RELAUNCH_FAILED}:
        if installed is not None and str(installed) == result.to_version:
            return UpdateOutcomeNotice("updated", result.to_version, "ExileLens updated", f"Updated to {result.to_version}.")
        return None
    if outcome in {Outcome.RESTORED, Outcome.RECOVERED}:
        return UpdateOutcomeNotice(
            "restored",
            result.to_version,
            "Update not installed",
            f"Update to {target} failed. The previous version was restored.",
            "EL-UPD-004",
        )
    if outcome == Outcome.RESTORE_FAILED:
        return UpdateOutcomeNotice(
            "failed",
            result.to_version,
            "Update could not be completed",
            f"Update to {target} failed and ExileLens could not fully restore the previous version. "
            "If ExileLens misbehaves, download the latest ZIP from GitHub Releases and extract it over this folder.",
            "EL-UPD-005",
        )
    if outcome in {Outcome.PREPARE_FAILED, Outcome.PROCESS_TIMEOUT, Outcome.INVALID_JOB}:
        return UpdateOutcomeNotice(
            "not_installed",
            result.to_version,
            "Update not installed",
            f"Update to {target} was not installed; this version is unchanged. You can try again from Settings → Updates.",
            "EL-UPD-004",
        )
    return None


def _remove(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        logger.info("update_cleanup_skipped name=%s", path.name)


def cleanup_after_launch(
    *,
    installed: ExileLensVersion | None,
    consumed: UpdateResult | None,
    keep_archive: str | None,
    updater_running: bool,
    updates_dir: Path | None = None,
    install_dir: Path | None = None,
    now: float | None = None,
) -> None:
    """Remove update leftovers that are provably no longer needed. Safe to call from a worker thread.

    ``updates_dir``/``install_dir`` are captured by the caller at session start, so a delayed cleanup can
    never act on a different directory than the one this session inspected.
    """
    updates = updates_dir or updates_data_dir()
    if updater_running or layout.journal_path(updates).exists():
        return  # an install or a pending recovery owns these files
    root = install_dir or install_root()
    healthy_after_update = (
        consumed is not None
        and consumed.outcome in {Outcome.SUCCESS, Outcome.RELAUNCH_FAILED}
        and installed is not None
        and str(installed) == consumed.to_version
    )
    previous_version_kept = consumed is not None and consumed.outcome in {
        Outcome.RESTORED,
        Outcome.RECOVERED,
        Outcome.PREPARE_FAILED,
        Outcome.PROCESS_TIMEOUT,
        Outcome.INVALID_JOB,
        Outcome.ALREADY_RUNNING,
    }
    if consumed is None or healthy_after_update or previous_version_kept:
        # This build started: the previous install's moved-aside entries and the backup are obsolete.
        # After restore_failed or an unexpected version, recovery material is deliberately kept.
        if layout.looks_like_install_root(root):
            _remove(root / layout.INSTALL_OLD_DIR)
            _remove(root / layout.INSTALL_NEW_DIR)
        _remove(layout.backup_root(updates))
    _remove(updates / layout.STAGING_DIR_NAME)
    _remove(layout.jobs_dir(updates) / layout.PENDING_JOB_NAME)
    downloads = layout.downloads_dir(updates)
    if not downloads.is_dir():
        return
    current = time.time() if now is None else now
    for entry in downloads.iterdir():
        if entry.name == keep_archive or (keep_archive and entry.name == f"{keep_archive}.part"):
            continue
        if entry.suffix == ".part":
            try:
                if current - entry.stat().st_mtime > STALE_PART_SECONDS:
                    _remove(entry)
            except OSError:
                continue
            continue
        version = _archive_version(entry.name)
        if version is not None and installed is not None and version <= installed:
            _remove(entry)


def _archive_version(name: str) -> ExileLensVersion | None:
    prefix, suffix = "ExileLens-v", "-win64.zip"
    if not (name.startswith(prefix) and name.endswith(suffix)):
        return None
    return ExileLensVersion.parse(name[len(prefix) : -len(suffix)])
