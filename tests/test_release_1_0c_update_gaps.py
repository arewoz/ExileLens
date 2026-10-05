"""1.0-C: the two update-test gaps found by the 1.0 audit: user cancellation of a download, and the current-version no-op.

Deterministic: injected fake transport / release client, no sleeps (events + thread joins), no network.
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
from types import SimpleNamespace

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from exilelens.app.settings import AppSettings
from exilelens.app.updates import service as svc
from exilelens.app.updates.download import DownloadError, DownloadManager
from exilelens.app.updates.version import ExileLensVersion, Release

pytestmark = pytest.mark.itemcheck

PAYLOAD = bytes(range(64)) * 4  # 256 bytes
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
STEP = 16


class _Response:
    def __init__(self, data: bytes, *, status: int = 200, content_range: str = "", gate: threading.Event | None = None, gate_after: int | None = None):
        self._data, self._pos, self._reads = data, 0, 0
        self.status = status
        self.headers = {"Content-Range": content_range} if content_range else {}
        self._gate, self._gate_after = gate, gate_after
        self.entered = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, _size: int = -1) -> bytes:
        if self._gate is not None and self._reads == self._gate_after:
            self.entered.set()
            assert self._gate.wait(10), "test gate never released"
        self._reads += 1
        chunk = self._data[self._pos : self._pos + STEP]
        self._pos += len(chunk)
        return chunk


class _Opener:
    """A fake transport: honours Range, records every request, optionally blocks mid-download until released."""

    def __init__(self, payload: bytes = PAYLOAD, *, gate: threading.Event | None = None, gate_after: int | None = None):
        self.payload, self.gate, self.gate_after = payload, gate, gate_after
        self.requests: list[dict] = []
        self.last: _Response | None = None

    def __call__(self, request, timeout=None):
        headers = {k.lower(): v for k, v in request.header_items()}
        self.requests.append(headers)
        start = 0
        if "range" in headers:
            start = int(headers["range"].split("=")[1].rstrip("-"))
            body = self.payload[start:]
            self.last = _Response(body, status=206, content_range=f"bytes {start}-{len(self.payload) - 1}/{len(self.payload)}")
        else:
            self.last = _Response(self.payload, gate=self.gate, gate_after=self.gate_after)
        return self.last


def _download(manager: DownloadManager, destination, **overrides):
    args = dict(url="https://example.invalid/pkg.zip", destination=destination, expected_size=len(PAYLOAD), expected_sha256=DIGEST)
    args.update(overrides)
    return manager.download(**args)


# --- cancellation -------------------------------------------------------------------------------------------------------


def test_cancel_stops_the_download_and_leaves_only_a_partial_file(tmp_path):
    manager = DownloadManager(opener=_Opener())
    destination = tmp_path / "pkg.zip"
    seen = []

    def on_progress(done, total):
        seen.append(done)
        if done >= 2 * STEP:
            manager.cancel()  # the user pressed Cancel while bytes were arriving

    with pytest.raises(DownloadError, match="cancelled"):
        _download(manager, destination, on_progress=on_progress)
    part = destination.with_suffix(destination.suffix + ".part")
    assert max(seen) < len(PAYLOAD)  # it really stopped early
    assert part.is_file() and part.stat().st_size == max(seen)  # only the bytes received so far
    assert not destination.exists()  # nothing ready-to-install exists


def test_a_cancelled_partial_is_resumed_and_verified_not_trusted(tmp_path):
    opener = _Opener()
    manager = DownloadManager(opener=opener)
    destination = tmp_path / "pkg.zip"
    with pytest.raises(DownloadError, match="cancelled"):
        _download(manager, destination, on_progress=lambda done, total: manager.cancel() if done >= STEP else None)
    partial = destination.with_suffix(destination.suffix + ".part").stat().st_size
    assert 0 < partial < len(PAYLOAD) and not destination.exists()
    result = _download(manager, destination)  # retry: the existing design resumes the .part with a Range request
    assert opener.requests[-1]["range"] == f"bytes={partial}-"
    assert result.sha256 == DIGEST and destination.read_bytes() == PAYLOAD
    assert not destination.with_suffix(destination.suffix + ".part").exists()


def test_a_tampered_partial_never_becomes_an_accepted_package(tmp_path):
    destination = tmp_path / "pkg.zip"
    part = destination.with_suffix(destination.suffix + ".part")
    part.write_bytes(b"\xff" * len(PAYLOAD))  # a full-size .part whose content is wrong (interrupted / corrupted)
    result = _download(DownloadManager(opener=_Opener()), destination)
    assert result.sha256 == DIGEST and destination.read_bytes() == PAYLOAD  # it was discarded and re-downloaded, never promoted

    broken = _Opener(payload=b"\x00" * len(PAYLOAD))  # the server now sends wrong bytes: hash mismatch, nothing accepted
    other = tmp_path / "other.zip"
    with pytest.raises(DownloadError, match="hash_mismatch"):
        _download(DownloadManager(opener=broken), other)
    assert not other.exists() and not other.with_suffix(".zip.part").exists()


def test_cancel_before_a_download_does_not_poison_the_next_one(tmp_path):
    manager = DownloadManager(opener=_Opener())
    manager.cancel()  # a stale cancel from an earlier attempt
    result = _download(manager, tmp_path / "pkg.zip")
    assert result.sha256 == DIGEST


def test_background_cancel_reports_cancelled_and_emits_no_result(tmp_path):
    gate = threading.Event()
    opener = _Opener(gate=gate, gate_after=2)
    manager = DownloadManager(opener=opener)
    finished: list[object] = []
    destination = tmp_path / "pkg.zip"
    assert manager.start_background(
        url="https://example.invalid/pkg.zip", destination=destination, expected_size=len(PAYLOAD), expected_sha256=DIGEST,
        on_progress=lambda *_: None, on_finished=finished.append,
    )
    assert manager.is_active()
    for _ in range(1000):  # wait (bounded, event-driven) for the worker to reach the blocked read
        if opener.last is not None and opener.last.entered.wait(0.01):
            break
    manager.cancel()
    gate.set()
    manager._thread.join(timeout=10)
    assert not manager.is_active()
    assert len(finished) == 1 and isinstance(finished[0], DownloadError) and str(finished[0]) == "cancelled"
    assert not destination.exists()


# --- service level ------------------------------------------------------------------------------------------------------

INSTALLED = ExileLensVersion.parse("1.0.0")


@pytest.fixture
def service_factory(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(svc, "save_settings", lambda _s: None)
    monkeypatch.setattr(svc, "ensure_updater_bootstrapped", lambda: None)
    monkeypatch.setattr(svc, "is_packaged", lambda: True)
    monkeypatch.setattr(svc, "installed_version", lambda: INSTALLED)
    monkeypatch.setattr(svc, "download_cache_dir", lambda: tmp_path)
    created = []

    def make(client, downloader=None, **settings):
        service = svc.UpdateService(AppSettings(**settings), client=client, downloader=downloader or DownloadManager(opener=_Opener()))
        created.append(service)
        return service

    yield make
    for service in created:
        service.stop_scheduler()
    assert app is not None


def _wait_check(service) -> None:
    for _ in range(2000):
        if not service._check_in_flight:
            break
        QCoreApplication.processEvents()
        threading.Event().wait(0.005)
    QCoreApplication.processEvents()


class _Client:
    """A release client double that records everything it is asked to do."""

    def __init__(self, version: str):
        self.version = version
        self.listed = 0
        self.manifest_fetches: list[str] = []

    def best_newest_release(self):
        self.listed += 1
        return Release(ExileLensVersion.parse(self.version), "https://github.com/x/y/releases/tag/v", f"v{self.version}", False,
                       manifest_asset_url="https://example.invalid/manifest.json", zip_asset_name="ExileLens.zip")

    def fetch_json(self, url):
        self.manifest_fetches.append(url)
        raise AssertionError("an already-current install must not fetch a manifest")


class _RecordingDownloader:
    def __init__(self):
        self.started = 0

    def start_background(self, **_kwargs):
        self.started += 1
        return True

    def cancel(self):
        pass

    def is_active(self):
        return False


@pytest.mark.parametrize("listed", ["1.0.0", "0.9.0"])
def test_current_or_newer_install_gets_no_offer_no_manifest_and_no_download(service_factory, listed):
    client, downloader = _Client(listed), _RecordingDownloader()
    # Even a supporter whose automation is fully enabled must not download when nothing newer exists.
    service = service_factory(client, downloader, updates_auto_download=True, updates_install_on_exit=True)
    service.set_automation_gate(lambda: True)
    states, offers, downloads, errors = [], [], [], []
    service.state_changed.connect(lambda state, _v: states.append(state))
    service.update_available.connect(lambda *a: offers.append(a))
    service.download_state_changed.connect(downloads.append)
    service.action_error.connect(errors.append)

    assert service.check_now() is True
    _wait_check(service)

    assert client.listed == 1 and client.manifest_fetches == []  # the release list was read, no manifest/package was fetched
    assert states[-1] in ("current", "ahead") and "available" not in states
    assert offers == []  # no update offered
    assert downloader.started == 0  # no package download
    assert "ready" not in downloads and "downloading" not in downloads
    assert service._ready is None and service._verified_manifest is None
    assert service.start_download() is False  # nothing to download either on request
    assert downloader.started == 0 and errors  # the user is told there is nothing to download


def test_service_cancel_reaches_the_active_download_and_never_marks_it_ready(service_factory, monkeypatch, tmp_path):
    gate = threading.Event()
    opener = _Opener(gate=gate, gate_after=2)
    client = _Client("1.0.0")
    service = service_factory(client, DownloadManager(opener=opener))
    manifest = SimpleNamespace(
        artifact=SimpleNamespace(url="https://example.invalid/pkg.zip", size=len(PAYLOAD), sha256=DIGEST, filename="pkg.zip"),
        version="2.0.0", seamless_eligible=True,
    )
    service._availability = SimpleNamespace(remote=SimpleNamespace(version=ExileLensVersion.parse("2.0.0")), installed=INSTALLED, manifest=manifest)
    service._verified_manifest, service._verified_envelope = manifest, {"envelope": True}
    ready_writes = []
    monkeypatch.setattr(svc, "write_ready_record", lambda *a, **k: ready_writes.append(a))
    downloads, errors = [], []
    service.download_state_changed.connect(downloads.append)
    service.action_error.connect(errors.append)

    assert service.start_download() is True
    for _ in range(1000):
        if opener.last is not None and opener.last.entered.wait(0.01):
            break
    service.cancel_download()
    gate.set()
    service.downloader._thread.join(timeout=10)
    for _ in range(50):
        QCoreApplication.processEvents()

    assert downloads[0] == "downloading" and downloads[-1] == "error" and "ready" not in downloads
    assert errors == ["Download cancelled."]
    assert ready_writes == []  # no ready-to-install record
    assert service._ready is None
    assert not (tmp_path / "pkg.zip").exists()  # no completed package; only a resumable .part may remain
