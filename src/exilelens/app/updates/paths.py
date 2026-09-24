from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from exilelens._paths import repo_root
from exilelens.app.settings import app_data_dir


def updates_data_dir() -> Path:
    return app_data_dir() / "updates"


def download_cache_dir() -> Path:
    return updates_data_dir() / "downloads"


def staging_dir() -> Path:
    return updates_data_dir() / "staging"


def backup_dir() -> Path:
    return updates_data_dir() / "backup"


def job_dir() -> Path:
    return updates_data_dir() / "jobs"


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
    path = job_dir() / "pending.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def clear_staging() -> None:
    target = staging_dir()
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
