"""External updater orchestration: mutex → recovery → process wait → prepare → journaled swap → result.

The updater never kills processes, never executes paths it did not validate against the fixed layout,
and always attempts to leave a bounded result file for the next ExileLens launch.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from exilelens.updater import layout, transaction, winsys
from exilelens.updater.job import JobError, UpdateJob, load_job
from exilelens.updater.result import MODE_RECOVER, Outcome, UpdateResult, make_result, write_result

logger = logging.getLogger(__name__)

PROCESS_WAIT_SECONDS = 120.0
_RELAUNCH_OUTCOMES = {Outcome.SUCCESS, Outcome.RESTORED, Outcome.RECOVERED, Outcome.PREPARE_FAILED}


def restart_application(exe_path: Path) -> None:
    subprocess.Popen([str(exe_path)], close_fds=True, cwd=str(exe_path.parent))


def recover_interrupted_install(updates_dir: Path, *, expected_install_root: Path | None) -> Outcome | None:
    """Roll back an incomplete journal, if any. ``None`` means there was nothing to recover."""
    journal_path = layout.journal_path(updates_dir)
    if not journal_path.exists():
        return None
    try:
        journal = transaction.read_journal(journal_path)
    except transaction.InstallError:
        logger.error("update_recovery_invalid_journal")
        return Outcome.RESTORE_FAILED
    root = journal.install_root
    if expected_install_root is not None and not layout.same_path(root, expected_install_root):
        logger.error("update_recovery_foreign_journal")
        return Outcome.RESTORE_FAILED
    if not (root / layout.INSTALL_OLD_DIR).is_dir():
        # Our swap always creates .update-old before the journal; without it the state is not ours to touch.
        logger.error("update_recovery_unrecognized_state")
        return Outcome.RESTORE_FAILED
    ok = transaction.undo(journal, journal_path=journal_path, backup_root=layout.backup_root(updates_dir))
    logger.info("update_recovery_finished ok=%s", ok)
    return Outcome.RECOVERED if ok else Outcome.RESTORE_FAILED


def install_job(job: UpdateJob) -> Outcome:
    journal_path = layout.journal_path(job.updates_dir)
    try:
        entries = transaction.prepare(
            install_root=job.install_root,
            staged_root=job.staged_root,
            backup_root=job.backup_root,
            zip_path=job.zip_path,
            zip_sha256=job.zip_sha256,
            zip_size=job.zip_size,
        )
    except (transaction.InstallError, OSError) as exc:
        logger.error("update_prepare_failed code=%s", getattr(exc, "code", type(exc).__name__))
        transaction.cleanup_work_dir(job.install_root, layout.INSTALL_NEW_DIR)
        return Outcome.PREPARE_FAILED
    try:
        journal = transaction.swap(
            install_root=job.install_root, entries=entries, journal_path=journal_path, job_id=job.job_id
        )
    except Exception:  # noqa: BLE001 - any swap failure is rolled back from the journal
        logger.exception("update_swap_failed")
        try:
            journal = transaction.read_journal(journal_path)
        except transaction.InstallError:
            # The journal was never written, so nothing was moved yet.
            transaction.cleanup_work_dir(job.install_root, layout.INSTALL_NEW_DIR)
            return Outcome.PREPARE_FAILED
        restored = transaction.undo(journal, journal_path=journal_path, backup_root=job.backup_root)
        return Outcome.RESTORED if restored else Outcome.RESTORE_FAILED
    journal_path.unlink(missing_ok=True)  # commit point
    transaction.cleanup_work_dir(job.install_root, layout.INSTALL_NEW_DIR)
    logger.info("update_swap_committed entries=%s", len(journal.entries))
    return Outcome.SUCCESS


def _write(updates_dir: Path, result: UpdateResult) -> None:
    try:
        write_result(layout.result_path(updates_dir), result)
    except OSError:
        logger.exception("update_result_write_failed")


def _consume_launch_request(updates_dir: Path) -> bool:
    marker = layout.launch_request_path(updates_dir)
    if not marker.exists():
        return False
    marker.unlink(missing_ok=True)
    return True


def _finish(updates_dir: Path, result: UpdateResult, *, relaunch_exe: Path | None, mutex) -> int:
    _write(updates_dir, result)
    # Release before relaunching: the relaunched app must not see an active updater.
    mutex.release()
    if relaunch_exe is None:
        return result.exit_code
    try:
        restart_application(relaunch_exe)
    except Exception:  # noqa: BLE001
        logger.exception("update_relaunch_failed")
        if result.outcome == Outcome.SUCCESS:
            failed = make_result(
                job_id=result.job_id,
                from_version=result.from_version,
                to_version=result.to_version,
                mode=result.mode,
                outcome=Outcome.RELAUNCH_FAILED,
            )
            _write(updates_dir, failed)
            return failed.exit_code
    return result.exit_code


def run_update_job(job_path: Path, *, wait_seconds: float = PROCESS_WAIT_SECONDS) -> int:
    mutex = winsys.acquire_updater_mutex()
    if mutex is None:
        logger.error("update_aborted_updater_already_running")
        from exilelens.updater.result import EXIT_CODES

        return EXIT_CODES[Outcome.ALREADY_RUNNING]
    try:
        job = load_job(job_path)
    except JobError as exc:
        logger.error("update_invalid_job code=%s", exc)
        invalid = make_result(job_id="", from_version="", to_version="", mode="restart", outcome=Outcome.INVALID_JOB)
        updates_dir = Path(job_path).absolute().parent.parent
        if updates_dir.name == layout.UPDATES_DIR_NAME:
            return _finish(updates_dir, invalid, relaunch_exe=None, mutex=mutex)
        mutex.release()
        return invalid.exit_code

    def result_for(outcome: Outcome) -> UpdateResult:
        return make_result(
            job_id=job.job_id,
            from_version=job.from_version,
            to_version=job.to_version,
            mode=job.mode,
            outcome=outcome,
        )

    try:
        if not winsys.wait_for_install_processes(
            job.install_root, parent_pid=job.parent_pid, timeout_seconds=wait_seconds
        ):
            logger.error("update_aborted_processes_still_running")
            return _finish(job.updates_dir, result_for(Outcome.PROCESS_TIMEOUT), relaunch_exe=None, mutex=mutex)
        recovered = recover_interrupted_install(job.updates_dir, expected_install_root=job.install_root)
        if recovered == Outcome.RESTORE_FAILED:
            # Evidence of an earlier interrupted install could not be resolved: never install on top of it.
            return _finish(job.updates_dir, result_for(Outcome.RESTORE_FAILED), relaunch_exe=None, mutex=mutex)
        outcome = install_job(job)
    except Exception:  # noqa: BLE001 - last-resort guard; the result file must still be written
        logger.exception("update_unexpected_failure")
        outcome = Outcome.RESTORE_FAILED if layout.journal_path(job.updates_dir).exists() else Outcome.PREPARE_FAILED
    wants_launch = _consume_launch_request(job.updates_dir) or job.restart_after_update
    relaunch = job.exe_path if wants_launch and outcome in _RELAUNCH_OUTCOMES else None
    return _finish(job.updates_dir, result_for(outcome), relaunch_exe=relaunch, mutex=mutex)


def run_recovery(updates_dir: Path, *, restart: bool, wait_seconds: float = PROCESS_WAIT_SECONDS) -> int:
    """``ExileLensUpdater.exe --recover``: roll back an interrupted install without a new job."""
    mutex = winsys.acquire_updater_mutex()
    if mutex is None:
        from exilelens.updater.result import EXIT_CODES

        return EXIT_CODES[Outcome.ALREADY_RUNNING]
    journal_path = layout.journal_path(updates_dir)
    install_root: Path | None = None
    try:
        install_root = transaction.read_journal(journal_path).install_root if journal_path.exists() else None
    except transaction.InstallError:
        install_root = None
    try:
        if install_root is not None and not winsys.wait_for_install_processes(install_root, timeout_seconds=wait_seconds):
            outcome: Outcome | None = Outcome.PROCESS_TIMEOUT
        else:
            outcome = recover_interrupted_install(updates_dir, expected_install_root=None)
    except Exception:  # noqa: BLE001
        logger.exception("update_recovery_unexpected_failure")
        outcome = Outcome.RESTORE_FAILED
    if outcome is None:
        mutex.release()
        return 0
    result = make_result(job_id="", from_version="", to_version="", mode=MODE_RECOVER, outcome=outcome)
    wants_launch = _consume_launch_request(updates_dir) or restart
    relaunch = None
    if wants_launch and outcome == Outcome.RECOVERED and install_root is not None:
        candidate = install_root / layout.APP_EXECUTABLE_NAME
        relaunch = candidate if layout.looks_like_install_root(install_root) else None
    return _finish(updates_dir, result, relaunch_exe=relaunch, mutex=mutex)


def restore_backup(*, install_root: Path, backup_root: Path) -> None:
    """Legacy helper kept for callers/tests: copy every backed-up entry back over the install."""
    if not backup_root.is_dir():
        raise RuntimeError("backup_missing")
    entries = tuple(transaction.JournalEntry(entry.name, True) for entry in backup_root.iterdir())
    transaction.restore_from_backup(transaction.Journal("", install_root, entries), backup_root)
