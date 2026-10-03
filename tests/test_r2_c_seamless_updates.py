"""R2 Package C: supporter seamless updates on the single P0 update pipeline.

The service under test is the real UpdateService with a fake GitHub client and a fake byte server; the
updater is the real install code. Everything is isolated under tmp_path (LOCALAPPDATA redirected).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from exilelens.app.settings import AppSettings
from exilelens.app.updates import service as svc
from exilelens.app.updates import trust
from exilelens.app.updates.constants import CHECK_COOLDOWN_SECONDS, SUPPORTER_CHECK_COOLDOWN_SECONDS
from exilelens.app.updates.download import DownloadManager
from exilelens.app.updates.manifest import canonical_manifest_bytes, verify_signed_envelope
from exilelens.app.updates.version import ExileLensVersion, Release
from exilelens.updater import install as updater_install
from exilelens.updater import layout

pytestmark = pytest.mark.smoke

ROOT = Path(__file__).resolve().parents[1]
TEST_KEY = ROOT / "fixtures" / "update_signing" / "test_signing_key.pem"
VERSION = "9.9.9"
TAG = f"v{VERSION}"
FILENAME = f"ExileLens-{TAG}-win64.zip"
URL = f"https://github.com/arewoz/ExileLens/releases/download/{TAG}/{FILENAME}"
INSTALLED = ExileLensVersion.parse("0.6.0")


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch):
    base = tmp_path / "LocalAppData"
    base.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(base))
    monkeypatch.setenv("APPDATA", str(base))
    with trust.use_test_trust_profile():
        yield


def build_package(tmp_path: Path) -> bytes:
    payload = tmp_path / "payload"
    (payload / "_internal").mkdir(parents=True)
    (payload / "ExileLens.exe").write_text("new-exe", encoding="utf-8")
    (payload / "_internal" / "runtime.dll").write_text("new-runtime", encoding="utf-8")
    (payload / "build_stamp.json").write_text("new", encoding="utf-8")
    archive = tmp_path / "pkg.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(payload.rglob("*")):
            if path.is_file():
                zf.write(path, "ExileLens/" + path.relative_to(payload).as_posix())
    return archive.read_bytes()


def signed_envelope(data: bytes, **manifest_overrides) -> dict:
    from cryptography.hazmat.primitives import serialization

    manifest = {
        "schema": 1,
        "channel": "stable",
        "version": VERSION,
        "tag": TAG,
        "signing_key_id": trust.TEST_SIGNING_KEY_ID,
        "artifact": {"filename": FILENAME, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "url": URL},
    }
    manifest.update(manifest_overrides)
    key = serialization.load_pem_private_key(TEST_KEY.read_bytes(), password=None)
    return {"manifest": manifest, "signature": base64.b64encode(key.sign(canonical_manifest_bytes(manifest))).decode()}


class FakeClient:
    def __init__(self, envelope: dict) -> None:
        self.envelope = envelope
        self.manifest_fetches = 0

    def best_newest_release(self):
        return Release(
            ExileLensVersion.parse(VERSION), "https://github.com/arewoz/ExileLens/releases", TAG, False,
            manifest_asset_url="https://github.com/arewoz/ExileLens/releases/download/x/m.update.json",
            zip_asset_url=URL, zip_asset_name=FILENAME,
        )

    def fetch_json(self, _url):
        self.manifest_fetches += 1
        return self.envelope


class Served:
    """Fake byte server that records which URLs were requested."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.requested: list[str] = []

    def opener(self, request, timeout):
        self.requested.append(request.full_url)
        data = self.data

        class _Response:
            status = 200
            headers: dict = {}

            def __init__(self) -> None:
                self._data = data

            def read(self, size):
                chunk, self._data = self._data[:size], self._data[size:]
                return chunk

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return None

        return _Response()


def fake_install(root: Path, label: str = "old") -> Path:
    (root / "_internal").mkdir(parents=True)
    (root / "ExileLens.exe").write_text(f"{label}-exe", encoding="utf-8")
    (root / "_internal" / "runtime.dll").write_text(f"{label}-runtime", encoding="utf-8")
    (root / "build_stamp.json").write_text(label, encoding="utf-8")
    return root


def pump(condition, timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    QCoreApplication.processEvents()
    return condition()


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    data = build_package(tmp_path)
    install = fake_install(tmp_path / "Games" / "ExileLens")
    monkeypatch.setattr(svc, "is_packaged", lambda: True)
    monkeypatch.setattr(svc, "save_settings", lambda _s: None)
    monkeypatch.setattr(svc, "ensure_updater_bootstrapped", lambda: None)
    monkeypatch.setattr(svc, "installed_version", lambda: INSTALLED)
    monkeypatch.setattr(svc, "install_root", lambda: install)
    monkeypatch.setattr(svc, "updater_matches_bundled", lambda: True)
    monkeypatch.setattr(svc, "updater_active", lambda: False)
    launched: list[Path] = []
    monkeypatch.setattr(svc, "launch_updater", lambda job: launched.append(job))
    served = Served(data)
    created: list[svc.UpdateService] = []

    def make(*, gate=None, settings=None, envelope=None, **kw):
        client = FakeClient(envelope or signed_envelope(data, **kw))
        service = svc.UpdateService(settings or AppSettings(), client=client, downloader=DownloadManager(served.opener))
        if gate is not None:
            service.set_automation_gate(gate)
        created.append(service)
        return service

    yield SimpleNamespace(make=make, served=served, install=install, launched=launched, data=data, app=app, tmp=tmp_path)
    for service in created:
        service.stop_scheduler()


def check(service) -> None:
    service.check_now()
    assert pump(lambda: not service._check_in_flight)


# ----------------------------------------------------------------------------- free user unchanged


def test_free_user_gets_no_automation_at_all(env) -> None:
    service = env.make()  # default gate: False
    check(service)
    QCoreApplication.processEvents()
    assert service._availability is not None and service._download_state == ""
    assert env.served.requested == []  # nothing downloaded without a click
    assert not service.automation_permitted() and not service.install_on_exit_ready()
    assert service._cooldown_seconds() == CHECK_COOLDOWN_SECONDS
    # The manual flow is exactly what it was: Download & Install, then Restart & Update (relaunching).
    assert service.start_download()
    assert pump(lambda: service._download_state == "ready")
    assert env.served.requested == [URL]
    assert service.last_download_mode == "manual"
    assert service.begin_restart_and_update(parent_pid=123)
    job = json.loads((Path(env.launched[0])).read_text(encoding="utf-8"))
    assert job["restart_after_update"] is True and job["pid"] == 123


@pytest.mark.parametrize("gate", [lambda: False, lambda: None, lambda: 1, lambda: "yes", lambda: {"url": "https://evil.example/x.zip"}, lambda: [1]])
def test_only_a_real_boolean_true_opens_the_gate(env, gate) -> None:
    service = env.make(gate=gate)
    check(service)
    assert not service._supporter() or gate() is True
    assert service._download_state == "" and env.served.requested == []


def test_a_crashing_gate_means_free_behaviour_not_an_error(env) -> None:
    def boom():
        raise RuntimeError("backend exploded")

    service = env.make(gate=boom)
    check(service)
    assert service._download_state == "" and service._availability is not None
    assert service.start_download() and pump(lambda: service._download_state == "ready")


# ----------------------------------------------------------------------------- supporter flow


def test_supporter_flow_auto_download_prestage_install_on_exit_without_relaunch(env, monkeypatch) -> None:
    service = env.make(gate=lambda: True)
    notified: list[str] = []
    service.auto_update_ready.connect(notified.append)
    assert service._cooldown_seconds() == SUPPORTER_CHECK_COOLDOWN_SECONDS
    check(service)
    assert pump(lambda: service._download_state == "ready" and service._prestaged == FILENAME and not service._prestage_in_flight)
    # ONE pipeline: the URL, size and hash that were downloaded are the signed manifest's, nothing else.
    assert env.served.requested == [URL]
    assert service.last_download_mode == "auto" and notified == [VERSION]
    manifest = verify_signed_envelope(signed_envelope(env.data))
    assert service._verified_manifest == manifest
    assert (Path(os.environ["LOCALAPPDATA"]) / "ExileLens" / "updates" / "ready.json").is_file()
    assert service.install_on_exit_ready()

    assert service.begin_install_on_exit(parent_pid=0) is True
    job_path = env.launched[0]
    job = json.loads(job_path.read_text(encoding="utf-8"))
    assert job["restart_after_update"] is False and job["to_version"] == VERSION
    assert job["zip_sha256"] == hashlib.sha256(env.data).hexdigest()

    # Run the REAL updater transaction against the disposable install: new version in place, no relaunch.
    relaunched: list[Path] = []
    monkeypatch.setattr(updater_install, "restart_application", lambda exe: relaunched.append(exe))
    assert updater_install.run_update_job(job_path, wait_seconds=5) == 0
    assert (env.install / "ExileLens.exe").read_text(encoding="utf-8") == "new-exe"
    assert (env.install / "_internal" / "runtime.dll").read_text(encoding="utf-8") == "new-runtime"
    assert relaunched == []
    result = json.loads((layout.result_path(Path(job_path).parent.parent)).read_text(encoding="utf-8"))
    assert result["outcome"] == "success" and result["mode"] == "no_restart"


def test_supporter_can_restart_now_through_the_same_job_contract(env, monkeypatch) -> None:
    service = env.make(gate=lambda: True)
    check(service)
    assert pump(lambda: service._download_state == "ready" and service._prestaged == FILENAME)
    assert service.begin_restart_and_update(parent_pid=0)
    job = json.loads(env.launched[0].read_text(encoding="utf-8"))
    assert job["restart_after_update"] is True  # an explicit Restart now relaunches; nothing else ever does
    relaunched: list[Path] = []
    monkeypatch.setattr(updater_install, "restart_application", lambda exe: relaunched.append(exe))
    assert updater_install.run_update_job(env.launched[0], wait_seconds=5) == 0
    assert relaunched == [env.install / "ExileLens.exe"]


def test_each_toggle_independently_disables_its_part(env) -> None:
    off_download = env.make(gate=lambda: True, settings=AppSettings(updates_auto_download=False))
    check(off_download)
    assert off_download._download_state == "" and env.served.requested == []
    assert off_download.start_download() and pump(lambda: off_download._download_state == "ready")
    # Let the first service finish reading/extracting the cached package before a second service re-downloads over it
    # (Windows cannot replace a file another thread still has open; this only matters for two services sharing one cache).
    assert pump(lambda: not off_download._prestage_in_flight)
    no_exit = env.make(gate=lambda: True, settings=AppSettings(updates_install_on_exit=False))
    check(no_exit)
    assert pump(lambda: no_exit._download_state == "ready")
    QCoreApplication.processEvents()
    assert no_exit._prestaged is None and not no_exit.install_on_exit_ready()
    assert no_exit.begin_install_on_exit(parent_pid=0) is False


def test_manifest_can_keep_one_release_manual_for_everyone(env) -> None:
    service = env.make(gate=lambda: True, seamless_eligible=False)
    check(service)
    assert service._verified_manifest.seamless_eligible is False
    assert service._download_state == "" and env.served.requested == []
    assert not service.install_on_exit_ready()
    assert service.start_download() and pump(lambda: service._download_state == "ready")  # manual still works


@pytest.mark.parametrize(("value", "expected"), [(True, True), (False, False), ("true", False), (1, False), (None, False)])
def test_seamless_eligible_parsing_is_strict_and_defaults_to_eligible(value, expected) -> None:
    data = b"x"
    envelope = signed_envelope(data, seamless_eligible=value)
    assert verify_signed_envelope(envelope).seamless_eligible is expected
    assert verify_signed_envelope(signed_envelope(data)).seamless_eligible is True  # absent = eligible (older manifests)


def test_not_enough_disk_skips_the_automatic_download(env, monkeypatch) -> None:
    monkeypatch.setattr(svc.shutil, "disk_usage", lambda _p: SimpleNamespace(free=1024))
    service = env.make(gate=lambda: True)
    check(service)
    assert service._download_state == "" and env.served.requested == []


def test_automatic_download_is_attempted_once_per_version_per_session(env) -> None:
    service = env.make(gate=lambda: True)
    check(service)
    assert pump(lambda: service._download_state == "ready")
    before = len(env.served.requested)
    service._ready = None
    service._download_state = ""
    service._maybe_auto_download()
    check(service)
    assert len(env.served.requested) == before


def test_install_on_exit_never_extracts_or_downloads_and_needs_everything_ready(env) -> None:
    service = env.make(gate=lambda: True)
    assert service.begin_install_on_exit(parent_pid=0) is False  # nothing checked yet
    check(service)
    assert pump(lambda: service._download_state == "ready" and service._prestaged == FILENAME)
    service._prestaged = None  # simulate: staging not prepared
    staging_before = list(layout.staged_root(Path(os.environ["LOCALAPPDATA"]) / "ExileLens" / "updates").parent.glob("*"))
    assert service.begin_install_on_exit(parent_pid=0) is False
    assert env.launched == [] and staging_before is not None


def test_lost_or_expired_entitlement_stops_install_on_exit_but_keeps_the_update_available(env) -> None:
    state = {"allowed": True}
    service = env.make(gate=lambda: state["allowed"])
    check(service)
    assert pump(lambda: service._download_state == "ready" and service._prestaged == FILENAME)
    assert service.install_on_exit_ready()
    state["allowed"] = False
    assert not service.install_on_exit_ready() and service.begin_install_on_exit(parent_pid=0) is False
    assert service.begin_restart_and_update(parent_pid=0)  # manual Restart & Update still works


def test_updater_that_is_not_the_v2_one_refuses_no_restart(env, monkeypatch) -> None:
    service = env.make(gate=lambda: True)
    check(service)
    assert pump(lambda: service._download_state == "ready" and service._prestaged == FILENAME)
    monkeypatch.setattr(svc, "updater_matches_bundled", lambda: False)
    assert service.install_on_exit_ready() is False


def test_bad_signature_manifest_never_reaches_the_automation_path(env) -> None:
    envelope = signed_envelope(env.data)
    envelope["signature"] = base64.b64encode(b"\x01" * 64).decode()
    service = env.make(gate=lambda: True, envelope=envelope)
    check(service)
    assert service._verified_manifest is None and env.served.requested == []


def test_downgrade_manifest_is_not_automated_for_supporters(env, monkeypatch) -> None:
    monkeypatch.setattr(svc, "installed_version", lambda: ExileLensVersion.parse("99.0.0"))
    service = env.make(gate=lambda: True)
    check(service)
    assert env.served.requested == [] and service._verified_manifest is None


# ----------------------------------------------------------------------------- trust separation


def test_update_code_cannot_import_cloud_or_entitlement_modules() -> None:
    import ast

    offenders = []
    for folder in ("app/updates", "updater"):
        for path in (ROOT / "src" / "exilelens" / folder).glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                if any(n.startswith("exilelens.cloud") or "entitlement" in n or "patreon" in n for n in names):
                    offenders.append(f"{folder}/{path.name}: {names}")
    assert offenders == []


def test_the_gate_parameter_cannot_carry_update_data() -> None:
    import inspect

    assert str(inspect.signature(svc.UpdateService.set_automation_gate)) == "(self, gate: 'Callable[[], bool]') -> 'None'"
    # No update-decision code reads anything but the boolean the gate returns.
    source = inspect.getsource(svc.UpdateService._supporter)
    assert "is True" in source


def test_entitlement_key_cannot_verify_a_manifest_and_the_update_key_cannot_verify_a_lease() -> None:
    from exilelens.cloud import entitlement

    assert set(entitlement.TEST_ENTITLEMENT_KEYS).isdisjoint(trust.TEST_VERIFY_KEYS)
    manifest_key_id = trust.TEST_SIGNING_KEY_ID
    assert manifest_key_id not in entitlement.entitlement_verify_keys()
    assert entitlement.ENTITLEMENT_TEST_KEY_ID not in trust.trusted_update_keys()


# ----------------------------------------------------------------------------- app lifecycle


def _app_stub(**attrs):
    from exilelens.app.main import ExileLensApp

    stub = SimpleNamespace(_clean_user_exit=False, _session_ending=False, dashboard=None, **attrs)
    return ExileLensApp, stub


def test_install_on_exit_runs_only_for_a_clean_user_exit() -> None:
    calls: list[int] = []
    service = SimpleNamespace(begin_install_on_exit=lambda *, parent_pid: calls.append(parent_pid) or True)
    cls, stub = _app_stub()
    stub.dashboard = SimpleNamespace(update_service=service)
    cls._install_on_exit(stub)  # crash / IPC quit / update restart: not marked as a user exit
    assert calls == []
    stub._clean_user_exit = True
    stub._session_ending = True  # Windows logoff or shutdown
    cls._install_on_exit(stub)
    assert calls == []
    stub._session_ending = False
    cls._install_on_exit(stub)
    assert calls == [os.getpid()]


def test_only_explicit_user_actions_mark_a_user_exit() -> None:
    from exilelens.app.main import ExileLensApp

    stub = SimpleNamespace(_clean_user_exit=False)
    ExileLensApp.mark_user_exit(stub)
    assert stub._clean_user_exit is True
    source = (ROOT / "src" / "exilelens" / "app" / "main.py").read_text(encoding="utf-8")
    assert "def _finish_ipc_quit" in source
    ipc = source.split("def _finish_ipc_quit", 1)[1].split("def ", 1)[0]
    assert "mark_user_exit" not in ipc and "_clean_user_exit" not in ipc
    restart = source.split("def request_restart_for_update", 1)[1].split("def shutdown", 1)[0]
    assert "mark_user_exit" not in restart


def test_session_end_signals_flag_the_exit_and_unknown_signals_do_not_break_startup() -> None:
    from exilelens.app.main import ExileLensApp

    stub = SimpleNamespace(_session_ending=False)
    stub._on_session_ending = lambda *a: ExileLensApp._on_session_ending(stub, *a)
    connected: list[str] = []

    class Sig:
        def __init__(self, name):
            self.name = name

        def connect(self, fn):
            connected.append(self.name)

    app = SimpleNamespace(commitDataRequest=Sig("commitDataRequest"), saveStateRequest=Sig("saveStateRequest"))
    ExileLensApp._connect_session_end_signals(stub, app)
    assert connected == ["commitDataRequest", "saveStateRequest"]
    ExileLensApp._connect_session_end_signals(stub, SimpleNamespace())  # no such signals: harmless
    stub._on_session_ending()
    assert stub._session_ending is True


def test_shutdown_runs_install_on_exit_after_the_worker_and_overlays_are_down() -> None:
    source = (ROOT / "src" / "exilelens" / "app" / "main.py").read_text(encoding="utf-8")
    body = source.split("    def shutdown(self)", 1)[1]
    order = [body.index(token) for token in ('"controller", self.controller.shutdown', '"overlay_hide"', '"install_on_exit"', '"tray", self.tray.hide')]
    assert order == sorted(order)

@pytest.mark.skipif(sys.platform != "win32", reason="Windows session messages")
def test_sentinel_window_reports_a_windows_session_end_even_in_a_tray_only_app() -> None:
    import ctypes
    from ctypes import wintypes

    from exilelens.platform.windows import session_end

    app = QApplication.instance() or QApplication([])
    fired: list[int] = []
    sentinel = session_end.SessionEndSentinel(app, lambda: fired.append(1))
    user32 = ctypes.windll.user32
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    assert not user32.IsWindowVisible(sentinel.handle)  # never shown
    user32.SendMessageW(sentinel.handle, 0x0011, 0, 0x80000000)  # WM_QUERYENDSESSION, logoff
    assert fired, "Qt did not report the session end"
    assert session_end.system_shutting_down() is False


def test_connect_session_end_signals_prefers_the_sentinel_with_a_real_application() -> None:
    from exilelens.app.main import ExileLensApp

    app = QApplication.instance() or QApplication([])
    stub = SimpleNamespace(_session_ending=False)
    stub._on_session_ending = lambda *a: setattr(stub, "_session_ending", True)
    ExileLensApp._connect_session_end_signals(stub, app)
    assert getattr(stub, "_session_sentinel", None) is not None
    stub._session_sentinel._fire()
    assert stub._session_ending is True
