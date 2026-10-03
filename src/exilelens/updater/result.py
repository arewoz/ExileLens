"""Bounded, structured updater result file (written by the updater, consumed once by the next launch)."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

RESULT_SCHEMA = 1
MAX_RESULT_BYTES = 4096
_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+(?:b\d+)?)?")
_JOB_ID_RE = re.compile(r"([0-9a-f]{32})?")


class Outcome(str, Enum):
    SUCCESS = "success"  # new version installed (and relaunched when requested)
    RELAUNCH_FAILED = "relaunch_failed"  # new version installed; the requested relaunch failed
    INVALID_JOB = "invalid_job"  # job rejected; install untouched
    ALREADY_RUNNING = "already_running"  # another updater holds the updater mutex; install untouched
    PROCESS_TIMEOUT = "process_timeout"  # ExileLens processes from the install never exited; install untouched
    PREPARE_FAILED = "prepare_failed"  # package/provenance/copy/backup failed before any swap; install untouched
    RESTORED = "restored"  # swap failed; previous version restored (journal reversal or backup copy)
    RESTORE_FAILED = "restore_failed"  # swap failed and the previous version could not be fully restored
    RECOVERED = "recovered"  # an interrupted earlier install was rolled back to the previous version


EXIT_CODES: dict[Outcome, int] = {
    Outcome.SUCCESS: 0,
    Outcome.INVALID_JOB: 10,
    Outcome.ALREADY_RUNNING: 11,
    Outcome.PROCESS_TIMEOUT: 12,
    Outcome.PREPARE_FAILED: 13,
    Outcome.RESTORED: 14,
    Outcome.RESTORE_FAILED: 15,
    Outcome.RECOVERED: 16,
    Outcome.RELAUNCH_FAILED: 17,
}

MODE_RESTART = "restart"
MODE_NO_RESTART = "no_restart"
MODE_RECOVER = "recover"
_MODES = {MODE_RESTART, MODE_NO_RESTART, MODE_RECOVER}


@dataclass(frozen=True)
class UpdateResult:
    job_id: str
    from_version: str
    to_version: str
    mode: str
    outcome: Outcome
    exit_code: int
    finished_at: int
    schema: int = RESULT_SCHEMA

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["outcome"] = self.outcome.value
        return payload


def make_result(*, job_id: str, from_version: str, to_version: str, mode: str, outcome: Outcome) -> UpdateResult:
    return UpdateResult(
        job_id=job_id if _JOB_ID_RE.fullmatch(job_id or "") else "",
        from_version=from_version if _VERSION_RE.fullmatch(from_version or "") else "",
        to_version=to_version if _VERSION_RE.fullmatch(to_version or "") else "",
        mode=mode if mode in _MODES else MODE_RESTART,
        outcome=outcome,
        exit_code=EXIT_CODES[outcome],
        finished_at=int(time.time()),
    )


def write_result(path: Path, result: UpdateResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(result.to_dict(), sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def parse_result(payload: object) -> UpdateResult | None:
    """Strict parse: any unexpected shape yields ``None`` (the file is then ignored)."""
    if not isinstance(payload, dict):
        return None
    expected = {"schema", "job_id", "from_version", "to_version", "mode", "outcome", "exit_code", "finished_at"}
    if set(payload) != expected or payload.get("schema") != RESULT_SCHEMA:
        return None
    try:
        outcome = Outcome(payload["outcome"])
    except (ValueError, TypeError):
        return None
    job_id, from_version, to_version, mode = (payload[k] for k in ("job_id", "from_version", "to_version", "mode"))
    if not all(isinstance(v, str) for v in (job_id, from_version, to_version, mode)):
        return None
    if not _JOB_ID_RE.fullmatch(job_id) or not _VERSION_RE.fullmatch(from_version) or not _VERSION_RE.fullmatch(to_version):
        return None
    if mode not in _MODES:
        return None
    exit_code, finished_at = payload["exit_code"], payload["finished_at"]
    if type(exit_code) is not int or type(finished_at) is not int or exit_code != EXIT_CODES[outcome]:
        return None
    return UpdateResult(job_id, from_version, to_version, mode, outcome, exit_code, finished_at)


def read_result(path: Path) -> UpdateResult | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_RESULT_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return parse_result(payload)
