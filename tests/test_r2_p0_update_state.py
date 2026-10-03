"""R2-P0: persisted ready state, next-launch result surfacing, cleanup, updater self-refresh, startup guard.

Every test isolates %LOCALAPPDATA% so nothing touches the developer's real ExileLens data.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from exilelens.app.updates import trust
from exilelens.app.updates.manifest import canonical_manifest_bytes
from exilelens.app.updates.version import ExileLensVersion
from exilelens.updater import layout
from exilelens.updater.result import Outcome, make_result, write_result

pytestmark = pytest.mark.smoke

ROOT = Path(__file__).resolve().parents[1]
TEST_KEY = ROOT / "fixtures" / "update_signing" / "test_signing_key.pem"
PACKAGE = b"PK-fake-package-bytes" * 64


@pytest.fixture(autouse=True)
def isolated_app_data(tmp_path: Path, monkeypatch) -> Path:
    base = tmp_path / "LocalAppData"
    base.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(base))
    monkeypatch.setenv("APPDATA", str(base))
    with trust.use_test_trust_profile():
        yield base / "ExileLens"


def _envelope(version: str = "0.7.0", *, size: int = len(PACKAGE), sha: str | None = None) -> dict:
    from cryptography.hazmat.primitives import serialization

    tag = f"v{version}"
    filename = f"ExileLens-{tag}-win64.zip"
    manifest = {
        "schema": 1,
        "channel": "stable",
        "version": version,
        "tag": tag,
        "signing_key_id": trust.TEST_SIGNING_KEY_ID,
        "artifact": {
            "filename": filename,
            "size": size,
            "sha256": sha or hashlib.sha256(PACKAGE).hexdigest(),
            "url": f"https://github.com/arewoz/ExileLens/releases/download/{tag}/{filename}",
        },
    }
    key = serialization.load_pem_private_key(TEST_KEY.read_bytes(), password=None)
    return {"manifest": manifest, "signature": base64.b64encode(key.sign(canonical_manifest_bytes(manifest))).decode()}


def _ready_on_disk(version: str = "0.7.0") -> tuple[dict, Path]:
    from exilelens.app.updates.manifest import verify_signed_envelope
    from exilelens.app.updates.paths import download_cache_dir
    from exilelens.app.updates.ready import write_ready_record

    envelope = _envelope(version)
    manifest = verify_signed_envelope(envelope)
    archive = download_cache_dir() / manifest.artifact.filename
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(PACKAGE)
    write_ready_record(envelope, manifest)
    return envelope, archive


INSTALLED = ExileLensVersion.parse("0.6.0")


# ----------------------------------------------------------------------------- persisted ready state


def test_ready_record_restores_after_full_reverification() -> None:
    from exilelens.app.updates.ready import load_ready_update

    _envelope_written, archive = _ready_on_disk()
    ready = load_ready_update(INSTALLED)
    assert ready is not None and str(ready.version) == "0.7.0" and ready.archive_path == archive


@pytest.mark.parametrize(
    "tamper",
    ["package_bytes", "package_truncated", "package_missing", "signature", "record_field", "extra_field", "downgrade"],
)
def test_tampered_or_stale_ready_record_is_discarded(tamper: str) -> None:
    from exilelens.app.updates.paths import ready_record_path
    from exilelens.app.updates.ready import load_ready_update

    _env, archive = _ready_on_disk()
    record_path = ready_record_path()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    installed = INSTALLED
    if tamper == "package_bytes":
        archive.write_bytes(PACKAGE[:-1] + b"X")
    elif tamper == "package_truncated":
        archive.write_bytes(PACKAGE[:10])
    elif tamper == "package_missing":
        archive.unlink()
    elif tamper == "signature":
        record["envelope"]["manifest"]["artifact"]["size"] = 1
    elif tamper == "record_field":
        record["filename"] = "ExileLens-v0.7.0-win64-other.zip"
    elif tamper == "extra_field":
        record["trusted"] = True
    elif tamper == "downgrade":
        installed = ExileLensVersion.parse("0.7.0")
    record_path.write_text(json.dumps(record), encoding="utf-8")
    assert load_ready_update(installed) is None
    assert not record_path.exists()
    assert not archive.exists()


def test_ready_record_is_not_trusted_in_production_profile() -> None:
    from exilelens.app.updates.paths import ready_record_path
    from exilelens.app.updates.ready import load_ready_update

    _ready_on_disk()
    with trust.use_test_trust_profile(False):
        assert load_ready_update(INSTALLED) is None  # test-signed envelope: rejected like any forged record
    assert not ready_record_path().exists()


# ----------------------------------------------------------------------------- next-launch result surfacing


def _write_result(outcome: Outcome, to_version: str = "0.7.0") -> None:
    from exilelens.app.updates.paths import updates_data_dir

    write_result(
        layout.result_path(updates_data_dir()),
        make_result(job_id="b" * 32, from_version="0.6.0", to_version=to_version, mode="restart", outcome=outcome),
    )


@pytest.mark.parametrize(
    ("outcome", "installed", "kind", "code"),
    [
        (Outcome.SUCCESS, "0.7.0", "updated", None),
        (Outcome.RELAUNCH_FAILED, "0.7.0", "updated", None),
        (Outcome.RESTORED, "0.6.0", "restored", "EL-UPD-004"),
        (Outcome.RECOVERED, "0.6.0", "restored", "EL-UPD-004"),
        (Outcome.RESTORE_FAILED, "0.6.0", "failed", "EL-UPD-005"),
        (Outcome.PREPARE_FAILED, "0.6.0", "not_installed", "EL-UPD-004"),
        (Outcome.PROCESS_TIMEOUT, "0.6.0", "not_installed", "EL-UPD-004"),
    ],
)
def test_result_is_consumed_once_with_a_matching_notice(outcome, installed, kind, code) -> None:
    from exilelens.app.updates.outcome import consume_update_result, last_seen_result

    _write_result(outcome)
    result, notice = consume_update_result(ExileLensVersion.parse(installed))
    assert result is not None and result.outcome == outcome
    assert notice is not None and notice.kind == kind and notice.error_code == code
    if kind == "updated":
        assert notice.message == "Updated to 0.7.0."
    if kind == "restored":
        assert "previous version was restored" in notice.message
    if kind == "failed":
        assert "GitHub Releases" in notice.message
    assert consume_update_result(ExileLensVersion.parse(installed)) == (None, None)  # one-time
    assert last_seen_result() == result  # still available to Diagnostics


def test_success_for_a_version_that_did_not_start_shows_no_success_notice() -> None:
    from exilelens.app.updates.outcome import consume_update_result

    _write_result(Outcome.SUCCESS, to_version="0.7.0")
    result, notice = consume_update_result(ExileLensVersion.parse("0.6.0"))
    assert result is not None and notice is None


def test_corrupt_result_file_is_ignored_and_consumed() -> None:
    from exilelens.app.updates.outcome import consume_update_result
    from exilelens.app.updates.paths import updates_data_dir

    path = layout.result_path(updates_data_dir())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"outcome": "success", "traceback": "C:\\\\Users\\\\me"}', encoding="utf-8")
    assert consume_update_result(INSTALLED) == (None, None)
    assert not path.exists()


# ----------------------------------------------------------------------------- cleanup


def _fake_install(root: Path) -> Path:
    (root / "_internal").mkdir(parents=True)
    (root / "ExileLens.exe").write_text("exe", encoding="utf-8")
    return root


def _leftovers(tmp_path: Path, monkeypatch):
    from exilelens.app.updates import outcome as outcome_module
    from exilelens.app.updates.paths import backup_dir, download_cache_dir, pending_job_path, staging_dir

    install = _fake_install(tmp_path / "install")
    monkeypatch.setattr(outcome_module, "install_root", lambda: install)
    for path in (install / layout.INSTALL_OLD_DIR / "_internal", backup_dir() / "_internal", staging_dir() / "ExileLens"):
        path.mkdir(parents=True)
    pending_job_path().parent.mkdir(parents=True, exist_ok=True)
    pending_job_path().write_text("{}", encoding="utf-8")
    downloads = download_cache_dir()
    downloads.mkdir(parents=True, exist_ok=True)
    (downloads / "ExileLens-v0.7.0-win64.zip").write_bytes(b"x")
    (downloads / "ExileLens-v0.8.0-win64.zip").write_bytes(b"x")
    stale = downloads / "ExileLens-v0.9.0-win64.zip.part"
    stale.write_bytes(b"x")
    os.utime(stale, (time.time() - 30 * 86400, time.time() - 30 * 86400))
    return install


def test_cleanup_after_healthy_post_update_launch(tmp_path: Path, monkeypatch) -> None:
    from exilelens.app.updates.outcome import cleanup_after_launch
    from exilelens.app.updates.paths import backup_dir, download_cache_dir, pending_job_path, staging_dir

    install = _leftovers(tmp_path, monkeypatch)
    consumed = make_result(job_id="", from_version="0.6.0", to_version="0.7.0", mode="restart", outcome=Outcome.SUCCESS)
    cleanup_after_launch(installed=ExileLensVersion.parse("0.7.0"), consumed=consumed, keep_archive=None, updater_running=False)
    assert not (install / layout.INSTALL_OLD_DIR).exists()
    assert not backup_dir().exists() and not staging_dir().exists() and not pending_job_path().exists()
    remaining = sorted(p.name for p in download_cache_dir().iterdir())
    assert remaining == ["ExileLens-v0.8.0-win64.zip"]  # installed zip and stale .part removed; newer kept


def test_cleanup_keeps_recovery_material_after_restore_failed(tmp_path: Path, monkeypatch) -> None:
    from exilelens.app.updates.outcome import cleanup_after_launch
    from exilelens.app.updates.paths import backup_dir

    install = _leftovers(tmp_path, monkeypatch)
    consumed = make_result(job_id="", from_version="0.6.0", to_version="0.7.0", mode="restart", outcome=Outcome.RESTORE_FAILED)
    cleanup_after_launch(installed=ExileLensVersion.parse("0.6.0"), consumed=consumed, keep_archive=None, updater_running=False)
    assert (install / layout.INSTALL_OLD_DIR).exists() and backup_dir().exists()


@pytest.mark.parametrize("blocker", ["journal", "updater_running"])
def test_cleanup_never_runs_while_an_install_or_recovery_owns_the_files(tmp_path: Path, monkeypatch, blocker: str) -> None:
    from exilelens.app.updates.outcome import cleanup_after_launch
    from exilelens.app.updates.paths import backup_dir, updates_data_dir

    install = _leftovers(tmp_path, monkeypatch)
    if blocker == "journal":
        layout.journal_path(updates_data_dir()).write_text("{}", encoding="utf-8")
    cleanup_after_launch(
        installed=ExileLensVersion.parse("0.7.0"), consumed=None, keep_archive=None, updater_running=blocker == "updater_running"
    )
    assert (install / layout.INSTALL_OLD_DIR).exists() and backup_dir().exists()


def test_cleanup_keeps_the_ready_package(tmp_path: Path, monkeypatch) -> None:
    from exilelens.app.updates.outcome import cleanup_after_launch
    from exilelens.app.updates.paths import download_cache_dir

    _leftovers(tmp_path, monkeypatch)
    cleanup_after_launch(
        installed=ExileLensVersion.parse("0.8.0"), consumed=None, keep_archive="ExileLens-v0.8.0-win64.zip", updater_running=False
    )
    assert (download_cache_dir() / "ExileLens-v0.8.0-win64.zip").exists()


# ----------------------------------------------------------------------------- updater self-refresh


@pytest.fixture
def updater_files(tmp_path: Path, monkeypatch):
    from exilelens.app.updates import bootstrap

    bundled = tmp_path / "install" / "_internal" / "ExileLensUpdater.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"updater-v2")
    appdata = tmp_path / "LocalAppData" / "ExileLens" / "ExileLensUpdater.exe"
    monkeypatch.setattr(bootstrap, "bundled_updater_executable", lambda: bundled)
    monkeypatch.setattr(bootstrap, "updater_executable", lambda: appdata)
    monkeypatch.setattr(bootstrap, "is_packaged", lambda: True)
    monkeypatch.setattr(bootstrap, "updater_active", lambda: False)
    bootstrap._DIGEST_CACHE.clear()
    return bootstrap, bundled, appdata


def test_missing_app_data_updater_is_installed(updater_files) -> None:
    bootstrap, bundled, appdata = updater_files
    assert bootstrap.ensure_updater_bootstrapped() == appdata
    assert appdata.read_bytes() == b"updater-v2" and bootstrap.updater_matches_bundled()


def test_different_app_data_updater_is_refreshed_by_hash(updater_files) -> None:
    bootstrap, bundled, appdata = updater_files
    appdata.parent.mkdir(parents=True, exist_ok=True)
    appdata.write_bytes(b"updater-v1-legacy")
    assert not bootstrap.updater_matches_bundled()
    bootstrap.ensure_updater_bootstrapped()
    assert appdata.read_bytes() == b"updater-v2" and bootstrap.updater_matches_bundled()


def test_identical_updater_is_left_untouched(updater_files) -> None:
    bootstrap, bundled, appdata = updater_files
    appdata.parent.mkdir(parents=True, exist_ok=True)
    appdata.write_bytes(b"updater-v2")
    before = appdata.stat().st_mtime_ns
    os.utime(appdata, ns=(before - 10**9, before - 10**9))  # an older timestamp alone must not trigger a copy
    stamp = appdata.stat().st_mtime_ns
    bootstrap.ensure_updater_bootstrapped()
    assert appdata.stat().st_mtime_ns == stamp


def test_refresh_is_deferred_while_an_updater_is_active(updater_files, monkeypatch) -> None:
    bootstrap, bundled, appdata = updater_files
    appdata.parent.mkdir(parents=True, exist_ok=True)
    appdata.write_bytes(b"updater-v1-legacy")
    monkeypatch.setattr(bootstrap, "updater_active", lambda: True)
    assert bootstrap.ensure_updater_bootstrapped() == appdata
    assert appdata.read_bytes() == b"updater-v1-legacy"


# ----------------------------------------------------------------------------- startup guard


def test_startup_guard_defers_to_active_updater_and_requests_relaunch(monkeypatch) -> None:
    from exilelens.app.updates import startup_guard
    from exilelens.app.updates.paths import updates_data_dir

    monkeypatch.setattr(startup_guard.winsys, "updater_mutex_active", lambda: True)
    assert startup_guard.defer_to_updater_if_needed() is True
    assert layout.launch_request_path(updates_data_dir()).exists()


def test_startup_guard_launches_recovery_for_an_incomplete_journal(monkeypatch) -> None:
    from exilelens.app.updates import bootstrap, startup_guard
    from exilelens.app.updates.paths import updater_executable, updates_data_dir

    monkeypatch.setattr(startup_guard.winsys, "updater_mutex_active", lambda: False)
    journal = layout.journal_path(updates_data_dir())
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("{}", encoding="utf-8")
    updater_executable().write_bytes(b"updater")
    launched: list[tuple] = []
    monkeypatch.setattr(bootstrap, "launch_updater", lambda job, extra_args=(): launched.append((job, extra_args)))
    assert startup_guard.defer_to_updater_if_needed() is True
    assert launched and launched[0][0] is None and launched[0][1][:2] == ("--recover", "--restart")


def test_startup_guard_does_not_loop_after_failed_recovery(monkeypatch) -> None:
    from exilelens.app.updates import startup_guard
    from exilelens.app.updates.paths import updater_executable, updates_data_dir

    monkeypatch.setattr(startup_guard.winsys, "updater_mutex_active", lambda: False)
    updates = updates_data_dir()
    journal = layout.journal_path(updates)
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("{}", encoding="utf-8")
    old = time.time() - 60
    os.utime(journal, (old, old))
    updater_executable().write_bytes(b"updater")
    write_result(
        layout.result_path(updates),
        make_result(job_id="", from_version="", to_version="", mode="recover", outcome=Outcome.RESTORE_FAILED),
    )
    assert startup_guard.defer_to_updater_if_needed() is False


def test_startup_guard_is_inert_without_updater_state(monkeypatch) -> None:
    from exilelens.app.updates import startup_guard

    monkeypatch.setattr(startup_guard.winsys, "updater_mutex_active", lambda: False)
    assert startup_guard.defer_to_updater_if_needed() is False


# ----------------------------------------------------------------------------- UpdateService integration


@pytest.fixture
def service(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from exilelens.app.settings import AppSettings
    from exilelens.app.updates import service as svc

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(svc, "save_settings", lambda _s: None)
    monkeypatch.setattr(svc, "ensure_updater_bootstrapped", lambda: None)
    monkeypatch.setattr(svc, "is_packaged", lambda: True)
    monkeypatch.setattr(svc, "installed_version", lambda: INSTALLED)
    monkeypatch.setattr(svc, "updater_active", lambda: False)

    def immediate_thread(target=None, **_kwargs):
        class _Runner:
            def start(self_inner):
                target()

        return _Runner()

    monkeypatch.setattr(svc.threading, "Thread", immediate_thread)
    instance = svc.UpdateService(AppSettings())
    yield instance
    instance.stop_scheduler()
    assert app is not None


def _release(version: str, *, zip_name: str | None = None):
    from exilelens.app.updates.constants import GITHUB_RELEASES_URL
    from exilelens.app.updates.version import Release

    tag = f"v{version}"
    return Release(
        ExileLensVersion.parse(version),
        GITHUB_RELEASES_URL,
        tag,
        False,
        manifest_asset_url="https://github.com/arewoz/ExileLens/releases/download/x/m.update.json",
        zip_asset_url="https://github.com/arewoz/ExileLens/releases/download/x/z.zip",
        zip_asset_name=zip_name or f"ExileLens-{tag}-win64.zip",
    )


class _Client:
    def __init__(self, release, envelope) -> None:
        self.release, self.envelope = release, envelope

    def best_newest_release(self):
        return self.release

    def fetch_json(self, _url):
        return self.envelope


def test_service_rejects_old_signed_manifest_on_newer_release(service) -> None:
    states: list[tuple[str, str]] = []
    service.state_changed.connect(lambda s, v: states.append((s, v)))
    service.client = _Client(_release("9.0.0"), _envelope("0.7.0"))
    service.check_now()
    assert states[-1] == ("verification_failed", "9.0.0")
    assert service._verified_manifest is None


def test_service_accepts_bound_manifest(service) -> None:
    states: list[tuple[str, str]] = []
    service.state_changed.connect(lambda s, v: states.append((s, v)))
    service.client = _Client(_release("0.7.0"), _envelope("0.7.0"))
    service.check_now()
    assert states[-1] == ("available", "0.7.0")
    assert service._verified_manifest is not None and service._verified_manifest.version == "0.7.0"


def test_service_restores_persisted_ready_state_without_redownload(service, monkeypatch) -> None:
    from exilelens.app.updates import service as svc

    _ready_on_disk("0.7.0")
    downloads: list[str] = []
    monkeypatch.setattr(service.downloader, "start_background", lambda **kw: downloads.append(kw["url"]) or True)
    states: list[str] = []
    service.download_state_changed.connect(states.append)
    monkeypatch.setattr(svc, "consume_update_result", lambda _installed: (None, None))
    service.begin_session()
    assert states[-1] == "ready"
    assert service._verified_manifest is not None and service._verified_manifest.version == "0.7.0"
    assert downloads == []


def test_service_writes_ready_record_after_verified_download(service) -> None:
    from exilelens.app.updates.download import DownloadResult
    from exilelens.app.updates.paths import ready_record_path

    service.client = _Client(_release("0.7.0"), _envelope("0.7.0"))
    service.check_now()
    service._finish_download(DownloadResult(Path("x"), "0" * 64, 1))
    record = json.loads(ready_record_path().read_text(encoding="utf-8"))
    assert record["version"] == "0.7.0" and record["envelope"]["manifest"]["version"] == "0.7.0"


def test_restart_and_update_writes_v2_job_with_provenance(service, monkeypatch) -> None:
    import zipfile

    from exilelens.app.updates import service as svc
    from exilelens.app.updates.paths import download_cache_dir, pending_job_path

    archive = download_cache_dir() / "ExileLens-v0.7.0-win64.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ExileLens/ExileLens.exe", "new")
        zf.writestr("ExileLens/_internal/x.dll", "new")
    data = archive.read_bytes()
    service.client = _Client(_release("0.7.0"), _envelope("0.7.0", size=len(data), sha=hashlib.sha256(data).hexdigest()))
    service.check_now()
    launched: list[Path] = []
    monkeypatch.setattr(svc, "launch_updater", lambda job: launched.append(job))
    monkeypatch.setattr(svc, "updater_matches_bundled", lambda: True)
    assert service.begin_restart_and_update(parent_pid=4321) is True
    job = json.loads(pending_job_path().read_text(encoding="utf-8"))
    assert job["schema"] == 2 and job["restart_after_update"] is True
    from exilelens._version import __version__

    assert (job["from_version"], job["to_version"]) == (__version__, "0.7.0")
    assert job["zip_sha256"] == hashlib.sha256(data).hexdigest() and job["zip_size"] == len(data)
    assert job["pid"] == 4321 and len(job["job_id"]) == 32
    assert launched == [pending_job_path()]


def test_no_restart_job_requires_refreshed_v2_updater(service, monkeypatch) -> None:
    from exilelens.app.updates import service as svc

    service.client = _Client(_release("0.7.0"), _envelope("0.7.0"))
    service.check_now()
    monkeypatch.setattr(svc, "updater_matches_bundled", lambda: False)
    errors: list[str] = []
    service.action_error.connect(errors.append)
    assert service.begin_restart_and_update(parent_pid=1, restart_after_update=False) is False
    assert errors and "out of date" in errors[-1]


def test_begin_session_surfaces_the_previous_result_once(service, monkeypatch) -> None:
    _write_result(Outcome.RESTORED)
    notices: list[object] = []
    service.install_outcome.connect(notices.append)
    service.begin_session()
    service.begin_session()
    assert len(notices) == 1 and notices[0].kind == "restored"
    assert service.last_install_result is not None and service.last_install_result.outcome == Outcome.RESTORED


def test_begin_session_is_inert_in_source_runs(service, monkeypatch) -> None:
    from exilelens.app.updates import service as svc

    monkeypatch.setattr(svc, "is_packaged", lambda: False)
    _write_result(Outcome.SUCCESS)
    service.begin_session()
    assert service.last_install_result is None
