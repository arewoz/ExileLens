"""Update job contract between ExileLens and the external updater.

Schema 2 (current) is strict: required fields, no unknown fields, every path re-derived from the fixed
layout and compared. Schema 1 (legacy, written by ExileLens <= 0.6.0) is still accepted so a refreshed
updater keeps working after a manual downgrade; it always restarts and carries no package provenance.
A schema-2 job also carries the legacy ``pid``/``version`` keys so an old schema-1 updater can still run
a restart job if the app-data updater could not be refreshed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from exilelens.updater import layout

JOB_SCHEMA = 2
MAX_JOB_BYTES = 64 * 1024
_VERSION_RE = re.compile(r"\d+\.\d+\.\d+(?:b\d+)?")
_JOB_ID_RE = re.compile(r"[0-9a-f]{32}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ZIP_NAME_RE = re.compile(r"ExileLens-v\d+\.\d+\.\d+(?:b\d+)?-win64\.zip")

_V2_KEYS = frozenset(
    {
        "schema",
        "job_id",
        "from_version",
        "to_version",
        "restart_after_update",
        "install_root",
        "staged_root",
        "backup_root",
        "exe_path",
        "zip_path",
        "zip_sha256",
        "zip_size",
        "pid",
        "version",
    }
)
_V1_KEYS = frozenset({"schema", "version", "pid", "install_root", "staged_root", "backup_root", "exe_path"})


class JobError(ValueError):
    pass


@dataclass(frozen=True)
class UpdateJob:
    schema: int
    job_id: str
    from_version: str
    to_version: str
    restart_after_update: bool
    parent_pid: int
    install_root: Path
    staged_root: Path
    backup_root: Path
    exe_path: Path
    updates_dir: Path
    zip_path: Path | None = None
    zip_sha256: str | None = None
    zip_size: int | None = None

    @property
    def mode(self) -> str:
        from exilelens.updater.result import MODE_NO_RESTART, MODE_RESTART

        return MODE_RESTART if self.restart_after_update else MODE_NO_RESTART


def updates_dir_for_job(job_path: Path) -> Path:
    job_path = Path(job_path).absolute()
    if job_path.name != layout.PENDING_JOB_NAME or job_path.parent.name != layout.JOBS_DIR_NAME:
        raise JobError("unexpected_job_location")
    updates_dir = job_path.parent.parent
    if updates_dir.name != layout.UPDATES_DIR_NAME:
        raise JobError("unexpected_job_location")
    return updates_dir


def _path(value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise JobError(f"invalid_{field}")
    path = Path(value)
    if not path.is_absolute():
        raise JobError(f"invalid_{field}")
    return path


def _version(value: object, field: str, *, required: bool) -> str:
    text = value if isinstance(value, str) else ""
    if not text and not required:
        return ""
    if not _VERSION_RE.fullmatch(text):
        raise JobError(f"invalid_{field}")
    return text


def _pid(value: object) -> int:
    if value is None:
        return 0
    if type(value) is not int or value < 0:
        raise JobError("invalid_pid")
    return value


def _validate_layout(job: UpdateJob) -> None:
    updates_dir = job.updates_dir
    install_root = job.install_root
    if install_root.parent == install_root:
        raise JobError("invalid_install_root")
    if not layout.looks_like_install_root(install_root):
        raise JobError("invalid_install_root")
    if layout.is_within(install_root, updates_dir) or layout.is_within(updates_dir, install_root):
        raise JobError("invalid_install_root")
    if not layout.same_path(job.exe_path, install_root / layout.APP_EXECUTABLE_NAME):
        raise JobError("invalid_exe_path")
    if not layout.same_path(job.staged_root, layout.staged_root(updates_dir)):
        raise JobError("invalid_staged_root")
    if not layout.same_path(job.backup_root, layout.backup_root(updates_dir)):
        raise JobError("invalid_backup_root")
    if job.zip_path is not None:
        if not layout.same_path(job.zip_path.parent, layout.downloads_dir(updates_dir)):
            raise JobError("invalid_zip_path")
        if not _ZIP_NAME_RE.fullmatch(job.zip_path.name):
            raise JobError("invalid_zip_path")


def parse_job(payload: object, *, updates_dir: Path) -> UpdateJob:
    if not isinstance(payload, dict):
        raise JobError("invalid_job")
    schema = payload.get("schema", 1)
    if schema == JOB_SCHEMA:
        if set(payload) - _V2_KEYS or (_V2_KEYS - {"version", "pid"}) - set(payload):
            raise JobError("invalid_job_fields")
        job_id = payload["job_id"]
        if not isinstance(job_id, str) or not _JOB_ID_RE.fullmatch(job_id):
            raise JobError("invalid_job_id")
        restart = payload["restart_after_update"]
        if type(restart) is not bool:
            raise JobError("invalid_restart_after_update")
        zip_sha256 = payload["zip_sha256"]
        if not isinstance(zip_sha256, str) or not _SHA256_RE.fullmatch(zip_sha256):
            raise JobError("invalid_zip_sha256")
        zip_size = payload["zip_size"]
        if type(zip_size) is not int or zip_size <= 0:
            raise JobError("invalid_zip_size")
        job = UpdateJob(
            schema=JOB_SCHEMA,
            job_id=job_id,
            from_version=_version(payload["from_version"], "from_version", required=True),
            to_version=_version(payload["to_version"], "to_version", required=True),
            restart_after_update=restart,
            parent_pid=_pid(payload.get("pid")),
            install_root=_path(payload["install_root"], "install_root"),
            staged_root=_path(payload["staged_root"], "staged_root"),
            backup_root=_path(payload["backup_root"], "backup_root"),
            exe_path=_path(payload["exe_path"], "exe_path"),
            updates_dir=updates_dir,
            zip_path=_path(payload["zip_path"], "zip_path"),
            zip_sha256=zip_sha256,
            zip_size=zip_size,
        )
    elif schema == 1:
        if set(payload) - _V1_KEYS:
            raise JobError("invalid_job_fields")
        install_root = _path(payload.get("install_root"), "install_root")
        job = UpdateJob(
            schema=1,
            job_id="",
            from_version="",
            to_version=_version(payload.get("version"), "to_version", required=False),
            restart_after_update=True,
            parent_pid=_pid(payload.get("pid")),
            install_root=install_root,
            staged_root=_path(payload.get("staged_root"), "staged_root"),
            backup_root=_path(payload.get("backup_root"), "backup_root"),
            exe_path=_path(payload.get("exe_path") or str(install_root / layout.APP_EXECUTABLE_NAME), "exe_path"),
            updates_dir=updates_dir,
        )
    else:
        raise JobError("unsupported_job_schema")
    _validate_layout(job)
    return job


def load_job(job_path: Path) -> UpdateJob:
    updates_dir = updates_dir_for_job(job_path)
    try:
        size = Path(job_path).stat().st_size
    except OSError as exc:
        raise JobError("unreadable_job") from exc
    if size > MAX_JOB_BYTES:
        raise JobError("job_too_large")
    try:
        payload = json.loads(Path(job_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise JobError("unreadable_job") from exc
    return parse_job(payload, updates_dir=updates_dir)
