"""Pre-UI launch guard for packaged builds (no Qt imports).

* An updater is running (named updater mutex held): starting now would lock files the updater is about to
  replace. Leave a launch request for the updater (it relaunches ExileLens when it finishes) and exit.
* An install journal exists without a running updater: a previous install was interrupted. Start the
  app-data updater in ``--recover --restart`` mode (it waits for this process to exit, rolls back, and
  relaunches) and exit.
"""

from __future__ import annotations

import logging
from pathlib import Path

from exilelens.updater import layout, winsys

logger = logging.getLogger(__name__)


def _updates_dir() -> Path:
    from exilelens.app.updates.paths import updates_data_dir

    return updates_data_dir()


def _request_launch(updates_dir: Path) -> None:
    marker = layout.launch_request_path(updates_dir)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("1", encoding="utf-8")


def _recovery_already_failed(updates_dir: Path, journal: Path) -> bool:
    from exilelens.updater.result import Outcome, read_result

    try:
        journal_mtime = journal.stat().st_mtime
    except OSError:
        return False
    for path in (layout.result_path(updates_dir), layout.seen_result_path(updates_dir)):
        result = read_result(path)
        if result is not None and result.outcome == Outcome.RESTORE_FAILED and result.finished_at >= int(journal_mtime):
            return True
    return False


def defer_to_updater_if_needed() -> bool:
    """Return True when this launch must exit so the updater can finish or recover the install."""
    updates_dir = _updates_dir()
    if winsys.updater_mutex_active():
        _request_launch(updates_dir)
        logger.info("startup_deferred_to_active_updater")
        return True
    journal = layout.journal_path(updates_dir)
    if journal.exists():
        if _recovery_already_failed(updates_dir, journal):
            # Do not loop: start normally so the user sees the recovery guidance in Settings → Updates.
            logger.error("startup_recovery_previously_failed")
            return False
        from exilelens.app.updates.bootstrap import launch_updater
        from exilelens.app.updates.paths import updater_executable

        if not updater_executable().is_file():
            logger.error("startup_recovery_unavailable reason=updater_missing")
            return False
        launch_updater(None, extra_args=("--recover", "--restart", "--updates-dir", str(updates_dir)))
        logger.info("startup_deferred_to_update_recovery")
        return True
    return False
