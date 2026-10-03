"""R2-P0: updater job contract v2, journaled swap install, recovery, result file, mutex and process wait."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

import pytest

from exilelens.updater import install, layout, transaction, winsys
from exilelens.updater.job import JobError, load_job, parse_job
from exilelens.updater.result import EXIT_CODES, Outcome, make_result, parse_result, read_result, write_result

pytestmark = pytest.mark.smoke

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows process/mutex primitives")


# ----------------------------------------------------------------------------- fixtures


def _write_tree(root: Path, label: str, *, extra: dict[str, str] | None = None) -> Path:
    files = {
        "ExileLens.exe": f"exe-{label}",
        "_internal/runtime.dll": f"runtime-{label}",
        "_internal/sub/data.txt": f"data-{label}",
        "build_stamp.json": f'{{"v": "{label}"}}',
        **(extra or {}),
    }
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _tree(root: Path) -> dict[str, str]:
    skip = {layout.INSTALL_NEW_DIR, layout.INSTALL_OLD_DIR}
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.relative_to(root).parts[0] not in skip
    }


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.install = _write_tree(tmp_path / "Games" / "ExileLens", "old", extra={"user-notes.txt": "keep"})
        self.updates = tmp_path / "AppData" / "ExileLens" / layout.UPDATES_DIR_NAME
        self.staged = _write_tree(layout.staged_root(self.updates), "new", extra={"NEW_FILE.txt": "added"})
        self.zip_path = layout.downloads_dir(self.updates) / "ExileLens-v0.7.0-win64.zip"
        self.zip_path.parent.mkdir(parents=True)
        with zipfile.ZipFile(self.zip_path, "w") as archive:
            for path in sorted(self.staged.rglob("*")):
                if path.is_file():
                    archive.write(path, "ExileLens/" + path.relative_to(self.staged).as_posix())
        self.job_path = layout.jobs_dir(self.updates) / layout.PENDING_JOB_NAME
        self.old_tree = _tree(self.install)
        self.new_tree = {**{k: v for k, v in _tree(self.staged).items()}, "user-notes.txt": "keep"}

    def job(self, **overrides) -> dict:
        payload = {
            "schema": 2,
            "job_id": uuid.uuid4().hex,
            "from_version": "0.6.0",
            "to_version": "0.7.0",
            "restart_after_update": True,
            "install_root": str(self.install),
            "staged_root": str(self.staged),
            "backup_root": str(layout.backup_root(self.updates)),
            "exe_path": str(self.install / "ExileLens.exe"),
            "zip_path": str(self.zip_path),
            "zip_sha256": hashlib.sha256(self.zip_path.read_bytes()).hexdigest(),
            "zip_size": self.zip_path.stat().st_size,
            "pid": 0,
            "version": "0.7.0",
        }
        payload.update(overrides)
        return payload

    def write_job(self, **overrides) -> Path:
        self.job_path.parent.mkdir(parents=True, exist_ok=True)
        self.job_path.write_text(json.dumps(self.job(**overrides)), encoding="utf-8")
        return self.job_path


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def isolated_updater(monkeypatch):
    """Unique mutex per test, no real relaunch, no real process wait."""
    name = f"Local\\ExileLens.Updater.test.{uuid.uuid4().hex}"
    original = winsys.acquire_updater_mutex
    monkeypatch.setattr(winsys, "acquire_updater_mutex", lambda: original(name))
    launched: list[Path] = []
    monkeypatch.setattr(install, "restart_application", lambda exe: launched.append(exe))
    monkeypatch.setattr(winsys, "wait_for_install_processes", lambda *a, **k: True)
    monkeypatch.setattr(transaction, "_sleep", lambda _s: None)
    return launched


# ----------------------------------------------------------------------------- job contract v2


def test_v2_job_parses_and_binds_to_fixed_layout(env: Env) -> None:
    job = load_job(env.write_job())
    assert job.schema == 2 and job.restart_after_update is True and job.mode == "restart"
    assert job.updates_dir == env.updates
    assert job.zip_size == env.zip_path.stat().st_size


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"restart_after_update": "yes"}, "invalid_restart_after_update"),
        ({"job_id": "not-hex"}, "invalid_job_id"),
        ({"zip_sha256": "x" * 64}, "invalid_zip_sha256"),
        ({"zip_size": 0}, "invalid_zip_size"),
        ({"to_version": "latest"}, "invalid_to_version"),
        ({"extra": 1}, "invalid_job_fields"),
        ({"exe_path": "C:\\Windows\\System32\\cmd.exe"}, "invalid_exe_path"),
        ({"staged_root": "C:\\Temp\\evil"}, "invalid_staged_root"),
        ({"backup_root": "C:\\Temp\\backup"}, "invalid_backup_root"),
        ({"install_root": "relative\\path"}, "invalid_install_root"),
        ({"zip_path": "C:\\Temp\\ExileLens-v0.7.0-win64.zip"}, "invalid_zip_path"),
        ({"schema": 3}, "unsupported_job_schema"),
    ],
)
def test_v2_job_rejects_unsafe_contracts(env: Env, override: dict, reason: str) -> None:
    with pytest.raises(JobError, match=reason):
        parse_job(env.job(**override), updates_dir=env.updates)


def test_v2_job_requires_every_field(env: Env) -> None:
    payload = env.job()
    del payload["zip_sha256"]
    with pytest.raises(JobError, match="invalid_job_fields"):
        parse_job(payload, updates_dir=env.updates)


def test_job_rejects_install_root_that_is_not_an_exilelens_install(env: Env, tmp_path: Path) -> None:
    bogus = tmp_path / "NotAnInstall"
    bogus.mkdir()
    with pytest.raises(JobError, match="invalid_install_root"):
        parse_job(env.job(install_root=str(bogus), exe_path=str(bogus / "ExileLens.exe")), updates_dir=env.updates)


def test_job_must_live_in_the_updates_jobs_directory(env: Env, tmp_path: Path) -> None:
    stray = tmp_path / "pending.json"
    stray.write_text(json.dumps(env.job()), encoding="utf-8")
    with pytest.raises(JobError, match="unexpected_job_location"):
        load_job(stray)


def test_legacy_v1_job_is_accepted_with_restart_semantics(env: Env) -> None:
    legacy = {
        "schema": 1,
        "version": "0.7.0",
        "pid": 123,
        "install_root": str(env.install),
        "staged_root": str(env.staged),
        "backup_root": str(layout.backup_root(env.updates)),
        "exe_path": str(env.install / "ExileLens.exe"),
    }
    job = parse_job(legacy, updates_dir=env.updates)
    assert job.restart_after_update is True and job.zip_path is None and job.parent_pid == 123


# ----------------------------------------------------------------------------- journaled swap


def test_install_job_success_swaps_and_keeps_old_entries_until_healthy_launch(env: Env) -> None:
    job = load_job(env.write_job())
    assert install.install_job(job) == Outcome.SUCCESS
    assert _tree(env.install) == env.new_tree
    assert (env.install / layout.INSTALL_OLD_DIR / "ExileLens.exe").read_text(encoding="utf-8") == "exe-old"
    assert not (env.install / layout.INSTALL_NEW_DIR).exists()
    assert not layout.journal_path(env.updates).exists()


def test_swap_order_places_executable_last(env: Env) -> None:
    entries = transaction.prepare(
        install_root=env.install, staged_root=env.staged, backup_root=layout.backup_root(env.updates),
        zip_path=None, zip_sha256=None, zip_size=None,
    )
    assert entries[-1] == "ExileLens.exe" and "_internal" in entries


def test_tampered_staging_fails_provenance_and_leaves_install_untouched(env: Env) -> None:
    (env.staged / "_internal" / "runtime.dll").write_text("tampered", encoding="utf-8")
    assert install.install_job(load_job(env.write_job())) == Outcome.PREPARE_FAILED
    assert _tree(env.install) == env.old_tree
    assert not (env.install / layout.INSTALL_NEW_DIR).exists()


def test_extra_staged_file_fails_provenance(env: Env) -> None:
    (env.staged / "_internal" / "injected.dll").write_text("x", encoding="utf-8")
    assert install.install_job(load_job(env.write_job())) == Outcome.PREPARE_FAILED
    assert _tree(env.install) == env.old_tree


def test_package_hash_mismatch_fails_before_any_change(env: Env) -> None:
    assert install.install_job(load_job(env.write_job(zip_sha256="0" * 64))) == Outcome.PREPARE_FAILED
    assert _tree(env.install) == env.old_tree


def _failing_rename(fail_on: int, exc: BaseException):
    calls = {"n": 0}
    real = os.replace

    def rename(src, dst):
        calls["n"] += 1
        if calls["n"] == fail_on:
            raise exc
        real(src, dst)

    return rename


@pytest.mark.parametrize("fail_on", [1, 2, 3, 5, 7])  # 7 renames: 4 entries, one without an old version
def test_swap_failure_is_reversed_from_the_journal(env: Env, monkeypatch, fail_on: int) -> None:
    monkeypatch.setattr(transaction, "_rename", _failing_rename(fail_on, OSError(22, "boom")))
    assert install.install_job(load_job(env.write_job())) == Outcome.RESTORED
    assert _tree(env.install) == env.old_tree
    assert not layout.journal_path(env.updates).exists()
    assert not (env.install / layout.INSTALL_NEW_DIR).exists()


def test_rollback_failure_falls_back_to_backup_copy(env: Env, monkeypatch) -> None:
    monkeypatch.setattr(transaction, "_rename", _failing_rename(4, OSError(22, "boom")))

    def broken_rollback(_journal):
        raise OSError(5, "rollback blocked")

    monkeypatch.setattr(transaction, "rollback", broken_rollback)
    assert install.install_job(load_job(env.write_job())) == Outcome.RESTORED
    assert _tree(env.install) == env.old_tree


def test_unrecoverable_failure_reports_restore_failed_and_keeps_evidence(env: Env, monkeypatch) -> None:
    monkeypatch.setattr(transaction, "_rename", _failing_rename(4, OSError(22, "boom")))
    monkeypatch.setattr(transaction, "rollback", lambda _j: (_ for _ in ()).throw(OSError(5, "x")))
    monkeypatch.setattr(transaction, "restore_from_backup", lambda _j, _b: (_ for _ in ()).throw(OSError(5, "y")))
    assert install.install_job(load_job(env.write_job())) == Outcome.RESTORE_FAILED
    assert layout.journal_path(env.updates).exists()


def test_sharing_violations_are_retried_with_bounded_backoff(env: Env, monkeypatch) -> None:
    attempts = {"n": 0}
    real = os.replace

    def flaky(src, dst):
        attempts["n"] += 1
        if attempts["n"] <= 2:
            err = PermissionError(13, "in use")
            err.winerror = 32
            raise err
        real(src, dst)

    monkeypatch.setattr(transaction, "_rename", flaky)
    monkeypatch.setattr(transaction, "_sleep", lambda _s: None)
    assert install.install_job(load_job(env.write_job())) == Outcome.SUCCESS
    assert _tree(env.install) == env.new_tree


def test_persistent_sharing_violation_gives_up_and_restores(env: Env, monkeypatch) -> None:
    clock = {"t": 0.0}

    def sleep(seconds):
        clock["t"] += seconds

    monkeypatch.setattr(transaction, "_sleep", sleep)
    monkeypatch.setattr(transaction, "_clock", lambda: clock["t"])
    real = os.replace

    def rename(src, dst):
        # The old runtime stays locked (e.g. by a scanner) for longer than the retry budget.
        if Path(src).name == "_internal" and Path(dst).parent.name == layout.INSTALL_OLD_DIR:
            err = PermissionError(13, "locked by scanner")
            err.winerror = 32
            raise err
        real(src, dst)

    monkeypatch.setattr(transaction, "_rename", rename)
    assert install.install_job(load_job(env.write_job())) == Outcome.RESTORED
    assert _tree(env.install) == env.old_tree


class _Killed(BaseException):
    """Simulates the updater process dying between filesystem operations."""


@pytest.mark.parametrize("die_on", range(1, 11))
def test_interrupted_updater_is_recovered_deterministically(env: Env, monkeypatch, die_on: int) -> None:
    job = load_job(env.write_job())
    monkeypatch.setattr(transaction, "_rename", _failing_rename(die_on, _Killed()))
    try:
        install.install_job(job)
    except _Killed:
        pass
    monkeypatch.setattr(transaction, "_rename", os.replace)
    outcome = install.recover_interrupted_install(env.updates, expected_install_root=env.install)
    if outcome is None:  # the process died after committing (no journal left): new version in place
        assert _tree(env.install) == env.new_tree
    else:
        assert outcome == Outcome.RECOVERED
        assert _tree(env.install) == env.old_tree
        assert not layout.journal_path(env.updates).exists()
    # Recovery is idempotent.
    assert install.recover_interrupted_install(env.updates, expected_install_root=env.install) is None


def test_recovery_refuses_invalid_or_foreign_journal_and_keeps_it(env: Env, tmp_path: Path) -> None:
    journal = layout.journal_path(env.updates)
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        json.dumps({"schema": 1, "job_id": "", "install_root": str(env.install), "entries": [{"name": "..\\x", "had_old": True}]}),
        encoding="utf-8",
    )
    assert install.recover_interrupted_install(env.updates, expected_install_root=env.install) == Outcome.RESTORE_FAILED
    assert journal.exists()
    journal.write_text(
        json.dumps({"schema": 1, "job_id": "", "install_root": str(tmp_path / "Other"), "entries": [{"name": "a", "had_old": True}]}),
        encoding="utf-8",
    )
    assert install.recover_interrupted_install(env.updates, expected_install_root=env.install) == Outcome.RESTORE_FAILED
    assert journal.exists()
    assert _tree(env.install) == env.old_tree


# ----------------------------------------------------------------------------- run_update_job end to end


def _result(env: Env):
    return read_result(layout.result_path(env.updates))


def test_run_update_job_restart_true_relaunches_new_version(env: Env, isolated_updater) -> None:
    code = install.run_update_job(env.write_job(restart_after_update=True))
    result = _result(env)
    assert code == 0 and result.outcome == Outcome.SUCCESS and result.mode == "restart"
    assert (result.from_version, result.to_version) == ("0.6.0", "0.7.0")
    assert isolated_updater == [env.install / "ExileLens.exe"]
    assert _tree(env.install) == env.new_tree


def test_run_update_job_restart_false_does_not_relaunch(env: Env, isolated_updater) -> None:
    assert install.run_update_job(env.write_job(restart_after_update=False)) == 0
    assert _result(env).mode == "no_restart"
    assert isolated_updater == []


def test_launch_request_marker_relaunches_even_without_restart(env: Env, isolated_updater) -> None:
    marker = layout.launch_request_path(env.updates)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("1", encoding="utf-8")
    install.run_update_job(env.write_job(restart_after_update=False))
    assert isolated_updater == [env.install / "ExileLens.exe"]
    assert not marker.exists()


def test_failed_install_with_restore_relaunches_old_version(env: Env, isolated_updater, monkeypatch) -> None:
    monkeypatch.setattr(transaction, "_rename", _failing_rename(3, OSError(22, "boom")))
    code = install.run_update_job(env.write_job(restart_after_update=True))
    assert code == EXIT_CODES[Outcome.RESTORED] and _result(env).outcome == Outcome.RESTORED
    assert isolated_updater == [env.install / "ExileLens.exe"]
    assert _tree(env.install) == env.old_tree


def test_process_timeout_never_touches_install_or_relaunches(env: Env, isolated_updater, monkeypatch) -> None:
    monkeypatch.setattr(winsys, "wait_for_install_processes", lambda *a, **k: False)
    assert install.run_update_job(env.write_job()) == EXIT_CODES[Outcome.PROCESS_TIMEOUT]
    assert _result(env).outcome == Outcome.PROCESS_TIMEOUT
    assert isolated_updater == [] and _tree(env.install) == env.old_tree


def test_invalid_job_writes_invalid_job_result(env: Env, isolated_updater) -> None:
    assert install.run_update_job(env.write_job(exe_path="C:\\Windows\\System32\\cmd.exe")) == EXIT_CODES[Outcome.INVALID_JOB]
    assert _result(env).outcome == Outcome.INVALID_JOB
    assert isolated_updater == [] and _tree(env.install) == env.old_tree


def test_relaunch_failure_is_reported_without_undoing_install(env: Env, isolated_updater, monkeypatch) -> None:
    monkeypatch.setattr(install, "restart_application", lambda exe: (_ for _ in ()).throw(OSError("no")))
    assert install.run_update_job(env.write_job()) == EXIT_CODES[Outcome.RELAUNCH_FAILED]
    assert _result(env).outcome == Outcome.RELAUNCH_FAILED
    assert _tree(env.install) == env.new_tree


def test_run_recovery_cli_path_rolls_back_and_relaunches(env: Env, isolated_updater, monkeypatch) -> None:
    job = load_job(env.write_job())
    monkeypatch.setattr(transaction, "_rename", _failing_rename(4, _Killed()))
    with pytest.raises(_Killed):
        install.install_job(job)
    monkeypatch.setattr(transaction, "_rename", os.replace)
    assert install.run_recovery(env.updates, restart=True) == EXIT_CODES[Outcome.RECOVERED]
    assert _result(env).outcome == Outcome.RECOVERED and _result(env).mode == "recover"
    assert _tree(env.install) == env.old_tree
    assert isolated_updater == [env.install / "ExileLens.exe"]


def test_second_updater_is_refused_while_mutex_is_held(env: Env, isolated_updater) -> None:
    holder = winsys.acquire_updater_mutex()
    try:
        if sys.platform == "win32":
            assert install.run_update_job(env.write_job()) == EXIT_CODES[Outcome.ALREADY_RUNNING]
            assert _tree(env.install) == env.old_tree
    finally:
        holder.release()


# ----------------------------------------------------------------------------- result file


def test_result_roundtrip_and_strict_parsing(tmp_path: Path) -> None:
    result = make_result(job_id="a" * 32, from_version="0.6.0", to_version="0.7.0", mode="restart", outcome=Outcome.RESTORED)
    path = tmp_path / "last_result.json"
    write_result(path, result)
    loaded = read_result(path)
    assert loaded == result and loaded.exit_code == EXIT_CODES[Outcome.RESTORED]
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == {"schema", "job_id", "from_version", "to_version", "mode", "outcome", "exit_code", "finished_at"}
    for bad in (
        {**payload, "traceback": "boom"},
        {**payload, "outcome": "exploded"},
        {**payload, "exit_code": 0},
        {**payload, "to_version": "C:\\Users\\me"},
        {**payload, "schema": 2},
    ):
        assert parse_result(bad) is None


def test_result_never_carries_free_text() -> None:
    result = make_result(job_id="nothex", from_version="../x", to_version="evil", mode="weird", outcome=Outcome.SUCCESS)
    assert (result.job_id, result.from_version, result.to_version, result.mode) == ("", "", "", "restart")


# ----------------------------------------------------------------------------- mutex and process wait


@windows_only
def test_updater_mutex_is_exclusive_and_observable() -> None:
    name = f"Local\\ExileLens.Updater.test.{uuid.uuid4().hex}"
    assert winsys.updater_mutex_active(name) is False
    first = winsys.acquire_updater_mutex(name)
    assert first is not None
    try:
        assert winsys.updater_mutex_active(name) is True
        assert winsys.acquire_updater_mutex(name) is None
    finally:
        first.release()
    assert winsys.updater_mutex_active(name) is False


def test_wait_for_install_processes_polls_until_clear_or_times_out(tmp_path: Path) -> None:
    clock = {"t": 0.0}
    busy = iter([[101], [101], []])
    assert winsys.wait_for_install_processes(
        tmp_path, list_processes=lambda _r: next(busy), clock=lambda: clock["t"],
        sleep=lambda s: clock.__setitem__("t", clock["t"] + s), timeout_seconds=10,
    )
    clock["t"] = 0.0
    assert not winsys.wait_for_install_processes(
        tmp_path, list_processes=lambda _r: [101], clock=lambda: clock["t"],
        sleep=lambda s: clock.__setitem__("t", clock["t"] + s), timeout_seconds=1,
    )
    assert not winsys.wait_for_install_processes(
        tmp_path, parent_pid=4242, is_alive=lambda _p: True, list_processes=lambda _r: [],
        clock=lambda: clock["t"], sleep=lambda s: clock.__setitem__("t", clock["t"] + s), timeout_seconds=1,
    )


@windows_only
def test_processes_running_from_install_root_are_detected(tmp_path: Path) -> None:
    root = tmp_path / "ExileLens"
    root.mkdir()
    exe = root / "PING.EXE"
    shutil.copy2(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "PING.EXE", exe)
    proc = subprocess.Popen([str(exe), "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 10
        found: list[int] = []
        while time.time() < deadline and proc.pid not in found:
            found = winsys.processes_running_from(root)
            time.sleep(0.1)
        assert proc.pid in found
        assert proc.pid not in winsys.processes_running_from(tmp_path / "Elsewhere")
        assert winsys.wait_for_install_processes(root, timeout_seconds=0.3, poll_seconds=0.1) is False
    finally:
        proc.kill()
        proc.wait(10)
    assert winsys.wait_for_install_processes(root, timeout_seconds=5, poll_seconds=0.1) is True
