"""Fixed on-disk layout shared by ExileLens and the external updater (stdlib only).

Both processes derive every update path from these names, so a job or journal can be validated against
the expected layout instead of trusting arbitrary paths written into it.
"""

from __future__ import annotations

from pathlib import Path

UPDATES_DIR_NAME = "updates"
DOWNLOADS_DIR_NAME = "downloads"
STAGING_DIR_NAME = "staging"
STAGED_ROOT_NAME = "ExileLens"
BACKUP_DIR_NAME = "backup"
JOBS_DIR_NAME = "jobs"

PENDING_JOB_NAME = "pending.json"
RESULT_NAME = "last_result.json"
SEEN_RESULT_NAME = "last_result.seen.json"
JOURNAL_NAME = "journal.json"
LAUNCH_REQUEST_NAME = "launch_requested"

# Work directories inside the install root: always on the install's own volume, so moves are renames.
INSTALL_NEW_DIR = ".update-new"
INSTALL_OLD_DIR = ".update-old"

APP_EXECUTABLE_NAME = "ExileLens.exe"
APP_INTERNAL_DIR = "_internal"

# Dedicated updater mutex (never the application's single-instance mutex).
UPDATER_MUTEX_NAME = "Local\\ExileLens.Updater"


def jobs_dir(updates_dir: Path) -> Path:
    return updates_dir / JOBS_DIR_NAME


def journal_path(updates_dir: Path) -> Path:
    return jobs_dir(updates_dir) / JOURNAL_NAME


def result_path(updates_dir: Path) -> Path:
    return jobs_dir(updates_dir) / RESULT_NAME


def seen_result_path(updates_dir: Path) -> Path:
    return jobs_dir(updates_dir) / SEEN_RESULT_NAME


def launch_request_path(updates_dir: Path) -> Path:
    return jobs_dir(updates_dir) / LAUNCH_REQUEST_NAME


def staged_root(updates_dir: Path) -> Path:
    return updates_dir / STAGING_DIR_NAME / STAGED_ROOT_NAME


def backup_root(updates_dir: Path) -> Path:
    return updates_dir / BACKUP_DIR_NAME


def downloads_dir(updates_dir: Path) -> Path:
    return updates_dir / DOWNLOADS_DIR_NAME


def looks_like_install_root(path: Path) -> bool:
    return (path / APP_EXECUTABLE_NAME).is_file() and (path / APP_INTERNAL_DIR).is_dir()


def same_path(left: Path, right: Path) -> bool:
    import os

    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def is_within(child: Path, parent: Path) -> bool:
    import os

    child_text = os.path.normcase(os.path.abspath(child))
    parent_text = os.path.normcase(os.path.abspath(parent)).rstrip("\\/")
    return child_text == parent_text or child_text.startswith(parent_text + os.sep)
