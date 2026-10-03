from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from exilelens._paths import repo_root
from exilelens.app.settings import app_data_dir
from exilelens.updater import layout


def updates_data_dir() -> Path:
    return app_data_dir() / layout.UPDATES_DIR_NAME


def download_cache_dir() -> Path:
    return updates_data_dir() / layout.DOWNLOADS_DIR_NAME


def staging_dir() -> Path:
    return updates_data_dir() / layout.STAGING_DIR_NAME


def backup_dir() -> Path:
    return updates_data_dir() / layout.BACKUP_DIR_NAME


def job_dir() -> Path:
    return updates_data_dir() / layout.JOBS_DIR_NAME


def pending_job_path() -> Path:
    return job_dir() / layout.PENDING_JOB_NAME


def ready_record_path() -> Path:
    return updates_data_dir() / "ready.json"


def install_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return repo_root()


def updater_executable() -> Path:
    return app_data_dir() / "ExileLensUpdater.exe"


def bundled_updater_executable() -> Path:
    return install_root() / "_internal" / "ExileLensUpdater.exe"


def write_update_job(payload: dict) -> Path:
    job_dir().mkdir(parents=True, exist_ok=True)
    path = pending_job_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def clear_staging() -> None:
    target = staging_dir()
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
