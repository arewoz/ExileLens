"""PERF-01: the PoB worker boots while the UI is built, and the controller adopts it through the normal signals.

Boot used to start from the first event-loop task, after the dashboard/overlay/tray were built (about 4 s of
subprocess start + Lua data load that did not depend on any of it). A preboot is the same boot, started earlier;
adoption must be indistinguishable from a normal ``start_engine_async`` for success, failure and a PoB folder
that changed in between.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import exilelens.app.controller as controller_module
import exilelens.app.engine_preboot as preboot_module
from exilelens.app.build_cache import BuildCache
from exilelens.app.controller import EvaluationController
from exilelens.app.settings import AppSettings
from exilelens.errors import PobBootFailed

pytestmark = pytest.mark.itemcheck


class _FakeEngine:
    instances: list["_FakeEngine"] = []

    def __init__(self, config, *, use_subprocess: bool = False) -> None:
        self.config = config
        self.started_on: str | None = None
        self.shut_down = False
        self.fail_start = False
        _FakeEngine.instances.append(self)

    def start(self) -> None:
        self.started_on = threading.current_thread().name
        if self.fail_start:
            raise PobBootFailed("lua would not boot")

    def shutdown(self) -> None:
        self.shut_down = True


def _pump(predicate, timeout: float = 10.0) -> bool:
    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    _FakeEngine.instances = []
    monkeypatch.setattr(preboot_module, "Engine", _FakeEngine)
    monkeypatch.setattr(preboot_module, "validate_pob_path", lambda config: None)
    monkeypatch.setattr(controller_module, "Engine", _FakeEngine)
    monkeypatch.setattr(controller_module, "validate_pob_path", lambda config: None)
    settings = AppSettings(pob_path=str(tmp_path / "pob"))
    controller = EvaluationController(settings, build_cache=BuildCache(tmp_path / "cache"))
    events: list[tuple[str, str]] = []
    controller.engine_ready.connect(lambda: events.append(("ready", "")))
    controller.engine_failed.connect(lambda message: events.append(("failed", message)))
    try:
        yield controller, settings, events
    finally:
        controller.shutdown()


def test_an_adopted_preboot_delivers_engine_ready_without_a_second_boot(fakes) -> None:
    controller, settings, events = fakes
    preboot = preboot_module.preboot_for(settings.pob_path)
    assert preboot is not None

    assert controller.start_engine_async(preboot) is True
    assert _pump(lambda: events)
    assert events == [("ready", "")]
    assert len(_FakeEngine.instances) == 1                      # the preboot's engine; no second boot
    assert controller.engine is _FakeEngine.instances[0]
    assert _FakeEngine.instances[0].started_on == "exilelens-engine-preboot"
    assert controller.engine_status() == "ready"


def test_a_failed_preboot_is_reported_exactly_like_a_failed_boot(fakes, monkeypatch) -> None:
    controller, settings, events = fakes
    monkeypatch.setattr(_FakeEngine, "start", lambda self: (_ for _ in ()).throw(PobBootFailed("lua would not boot")))
    preboot = preboot_module.preboot_for(settings.pob_path)

    controller.start_engine_async(preboot)
    assert _pump(lambda: events)
    kind, message = events[0]
    assert kind == "failed"
    assert "lua would not boot" in message and message.startswith("Path of Building could not start")
    assert controller.engine is None
    assert controller.engine_error == message


def test_a_preboot_for_a_different_folder_is_discarded_and_a_normal_boot_runs(fakes, tmp_path) -> None:
    controller, settings, events = fakes
    preboot = preboot_module.preboot_for(str(tmp_path / "old-pob-folder"))
    assert preboot is not None
    assert not preboot.matches(settings.pob_path)

    controller.start_engine_async(preboot)
    assert _pump(lambda: events)
    assert events == [("ready", "")]
    assert len(_FakeEngine.instances) == 2                      # the stale preboot engine and the real boot
    stale, real = _FakeEngine.instances
    assert controller.engine is real and real.started_on == "exilelens-engine-boot"
    assert _pump(lambda: stale.shut_down)                       # the unwanted worker is shut down, not leaked


def test_a_preboot_that_is_never_adopted_shuts_its_engine_down(fakes) -> None:
    _controller, settings, _events = fakes
    preboot = preboot_module.preboot_for(settings.pob_path)
    assert preboot is not None
    preboot.discard()
    assert _pump(lambda: _FakeEngine.instances and _FakeEngine.instances[0].shut_down)


def test_no_folder_configured_means_no_preboot() -> None:
    assert preboot_module.preboot_for("") is None
    assert preboot_module.preboot_for(None) is None
