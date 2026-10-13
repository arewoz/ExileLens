"""PERF-01: build loads run on the PoB lane, never freeze the UI thread, and never apply a stale result.

The PoB round trips of a (re)load used to run on the Qt UI thread: 1.5 s on a small build, 4+ s on a heavy one,
at startup and on every switch. ``load_build_async`` begins the transaction on the UI thread (state turns LOADING /
RELOADING at once) and runs the engine half as a ``baseline`` job; the result is applied only behind the baseline
generation. These tests use a stub engine whose load can be held, so what runs on which thread, and what a
superseded load is allowed to change, are observable.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import exilelens.tree.mutations as tree_mutations
from exilelens.app.build_cache import BuildCache
from exilelens.app.build_state import BaselineState, BuildInfo, BuildState
from exilelens.app.controller import EvaluationController, EvaluationRequest
from exilelens.app.settings import AppSettings
from exilelens.build_source import BuildSource, read_build_source
from exilelens.build_sources import LocalPobBuildSource
from exilelens.errors import BuildParseFailed

pytestmark = pytest.mark.itemcheck


def _write_build(path: Path, name: str) -> BuildSource:
    path.write_text(
        f'<PathOfBuilding><Build title="{name}" /><Items><Item id="1">{name}</Item></Items></PathOfBuilding>',
        encoding="utf-8",
    )
    return read_build_source(path)


class _HeldEngine:
    """Stub PoB engine. ``hold`` (when set) blocks load_build until released, on whichever thread calls it."""

    def __init__(self) -> None:
        self.loaded_source: BuildSource | None = None
        self.loaded_source_ref = None
        self.loaded_revision = None
        self.load_threads: list[str] = []
        self.load_calls: list[str] = []
        self.hold: threading.Event | None = None
        self.entered = threading.Event()
        self.reject: set[str] = set()
        self.active_loadout = "Default"
        self.calls: list[str] = []

    def load_build(self, path: str, *, context: str, source: BuildSource) -> dict:
        self.load_threads.append(threading.current_thread().name)
        self.load_calls.append(source.sha256)
        self.entered.set()
        if self.hold is not None:
            assert self.hold.wait(10), "test never released the held load"
        if source.sha256 in self.reject:
            raise BuildParseFailed("worker rejected build")
        self.loaded_source = source
        self.loaded_source_ref = LocalPobBuildSource(path).ref
        self.loaded_revision = SimpleNamespace(token=source.revision)
        return {"build": {"name": Path(path).stem}}

    def list_loadouts(self) -> dict:
        return {"loadouts": [{"name": "Default"}, {"name": "Boss"}], "active": self.active_loadout}

    def list_item_sets(self) -> dict:
        return {"item_sets": [{"id": "1", "title": "Default"}], "active_id": "1"}

    def set_active_loadout(self, name: str) -> dict:
        self.calls.append(f"set_active_loadout:{name}:{threading.current_thread().name}")
        self.active_loadout = name
        return {}

    def set_active_item_set(self, item_set_id: str) -> dict:
        self.calls.append(f"set_active_item_set:{item_set_id}")
        return {}

    def get_metrics(self, *, context: str = "") -> dict:
        sha = self.loaded_source.short_sha if self.loaded_source else ""
        return {"fingerprint": {"build": sha}, "fingerprint_hash": f"fp-{sha}", "raw": {"Life": 1}}

    def get_equipment(self) -> dict:
        return {"equipment": []}

    def get_build_info(self) -> dict:
        return {"name": Path(self.loaded_source.path).stem} if self.loaded_source else {}

    def shutdown(self) -> None:
        return None


def _minimal_snapshot(*_args, **_kwargs):
    from exilelens.tree.models import PassiveTreeSnapshot, TreeBaseline

    baseline = TreeBaseline(
        build_path="", build_name="stub", loadout="Default", tree_set="Default", item_set="1", context="MAP",
        profile="default", generation=0, fingerprint="stub-fp", tree_fingerprint="tree-stub",
    )
    return PassiveTreeSnapshot(baseline=baseline, nodes={}, edges=[], tree_set={"index": 0, "title": "Default"})


def _pump(predicate, timeout: float = 15.0) -> bool:
    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


@pytest.fixture
def controller_and_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(tree_mutations, "load_tree_snapshot", _minimal_snapshot)
    controller = EvaluationController(AppSettings(context="MAP"), build_cache=BuildCache(tmp_path / "cache"))
    engine = _HeldEngine()
    controller._engine = engine  # type: ignore[assignment]
    finished: list[tuple[bool, str, str]] = []
    controller.build_load_finished.connect(lambda ok, path, reason: finished.append((ok, path, reason)))
    controller.finished_log = finished  # type: ignore[attr-defined]
    try:
        yield controller, engine, tmp_path
    finally:
        controller.shutdown()


def test_load_runs_on_the_pob_lane_and_the_ui_thread_is_not_held(controller_and_engine) -> None:
    controller, engine, tmp_path = controller_and_engine
    build = tmp_path / "ring.xml"
    _write_build(build, "ring")
    engine.hold = threading.Event()

    started = time.perf_counter()
    controller.load_build_async(str(build))
    returned_ms = (time.perf_counter() - started) * 1000

    assert returned_ms < 500                      # the held load did not hold the caller
    assert controller.build_info.state is BuildState.LOADING
    assert controller.baseline_state.state is BuildState.LOADING
    assert _pump(engine.entered.is_set)
    assert controller.build_info.state is BuildState.LOADING      # still loading while PoB works
    engine.hold.set()
    assert _pump(lambda: bool(controller.finished_log))           # type: ignore[attr-defined]
    assert controller.finished_log == [(True, str(build.resolve()), "")]  # type: ignore[attr-defined]
    assert controller.build_info.state is BuildState.READY
    assert controller.baseline_state.fingerprint.startswith("fp-")
    assert engine.load_threads and all(name != threading.main_thread().name for name in engine.load_threads)


def test_a_superseded_load_is_never_applied_and_never_fails_the_newer_one(controller_and_engine) -> None:
    controller, engine, tmp_path = controller_and_engine
    first = tmp_path / "first.xml"
    second = tmp_path / "second.xml"
    first_source = _write_build(first, "first-build")
    second_source = _write_build(second, "second-build-with-more-bytes")
    engine.hold = threading.Event()

    controller.load_build_async(str(first))
    assert _pump(engine.entered.is_set)           # the first load is inside PoB
    generation_after_first = controller.baseline_generation
    controller.load_build_async(str(second))      # the user switches again
    assert controller.baseline_generation == generation_after_first + 1
    assert controller.build_info.path == str(second.resolve())
    engine.hold.set()

    assert _pump(lambda: any(path == str(second.resolve()) for _ok, path, _r in controller.finished_log))  # type: ignore[attr-defined]
    assert _pump(lambda: controller._scheduler.active is None)
    assert engine.load_calls == [first_source.sha256, second_source.sha256]
    assert controller.build_info.state is BuildState.READY
    assert controller.build_info.path == str(second.resolve())
    assert controller.baseline_state.build_path == str(second.resolve())
    assert controller.baseline_state.generation == controller.baseline_generation
    # The first (stale) result produced no completion and no state: only the second load is reported.
    assert controller.finished_log == [(True, str(second.resolve()), "")]  # type: ignore[attr-defined]


def test_a_failed_load_reports_the_reason_and_leaves_the_failed_state(controller_and_engine) -> None:
    controller, engine, tmp_path = controller_and_engine
    build = tmp_path / "bad.xml"
    source = _write_build(build, "bad")
    engine.reject.add(source.sha256)

    controller.load_build_async(str(build))
    assert _pump(lambda: bool(controller.finished_log))  # type: ignore[attr-defined]
    ok, path, reason = controller.finished_log[0]  # type: ignore[attr-defined]
    assert (ok, path) == (False, str(build.resolve()))
    assert "worker rejected build" in reason
    assert controller.build_info.state is BuildState.FAILED
    assert "worker rejected build" in controller.last_build_error


def test_change_build_to_a_broken_file_loads_the_previous_build_again(controller_and_engine) -> None:
    controller, engine, tmp_path = controller_and_engine
    good = tmp_path / "good.xml"
    good_source = _write_build(good, "good")
    controller.load_build_async(str(good))
    assert _pump(lambda: controller.build_info.state is BuildState.READY)

    broken = tmp_path / "broken.xml"
    broken_source = _write_build(broken, "broken")
    engine.reject.add(broken_source.sha256)
    controller.finished_log.clear()  # type: ignore[attr-defined]
    controller.change_build(str(broken))

    assert _pump(lambda: len(controller.finished_log) >= 2)  # type: ignore[attr-defined]
    assert controller.finished_log[0][:2] == (False, str(broken.resolve()))  # type: ignore[attr-defined]
    assert controller.finished_log[1] == (True, str(good.resolve()), "")  # type: ignore[attr-defined]
    assert controller.build_info.state is BuildState.READY
    assert controller.build_info.path == str(good.resolve())
    assert engine.load_calls[-1] == good_source.sha256


def test_same_build_reload_that_pob_rejects_keeps_the_last_good_baseline(controller_and_engine) -> None:
    controller, engine, tmp_path = controller_and_engine
    build = tmp_path / "selected.xml"
    old = _write_build(build, "old")
    controller.load_build_async(str(build))
    assert _pump(lambda: controller.build_info.state is BuildState.READY)
    good_fingerprint = controller.baseline_state.fingerprint

    changed = _write_build(build, "worker-rejects-this-one")
    engine.reject.add(changed.sha256)
    controller.finished_log.clear()  # type: ignore[attr-defined]
    controller.reload_evaluation_build()

    assert _pump(lambda: bool(controller.finished_log))  # type: ignore[attr-defined]
    ok, _path, reason = controller.finished_log[0]  # type: ignore[attr-defined]
    assert ok is False and reason
    assert engine.load_calls[-2:] == [changed.sha256, old.sha256]    # new bytes tried, previous bytes put back
    assert controller.build_info.state is BuildState.READY
    assert controller.baseline_state.fingerprint == good_fingerprint
    assert controller._auto_reload_status == "FAILED_KEPT_PREVIOUS"
    assert controller._last_good_source is not None and controller._last_good_source.sha256 == old.sha256


def test_the_held_item_check_resumes_against_the_new_baseline_generation(controller_and_engine) -> None:
    controller, engine, tmp_path = controller_and_engine
    build = tmp_path / "ring.xml"
    _write_build(build, "ring")
    submitted: list[EvaluationRequest] = []
    controller._submit_evaluation_request = lambda request: submitted.append(request) or request.request_id  # type: ignore[method-assign]

    controller.load_build_async(str(build))
    # An Item Check arrives while the build is still loading: it is held, never evaluated on the old state.
    assert controller.build_info.state is BuildState.LOADING
    held = EvaluationRequest(
        request_id=41, raw_text="x", content_hash="h", clipboard_received_ms=0.0, copy_timestamp=0.0,
        baseline_generation=controller.baseline_generation - 1,
    )
    controller._deferred_evaluation = held
    assert _pump(lambda: controller.build_info.state is BuildState.READY)

    assert len(submitted) == 1
    resumed = submitted[0]
    assert resumed.request_id == 41
    assert resumed.baseline_generation == controller.baseline_generation
    assert resumed.context_identity == controller._current_evaluation_identity().token
    assert controller._deferred_evaluation is None


def test_a_loadout_switch_runs_on_the_lane_and_applies_behind_the_generation(controller_and_engine) -> None:
    controller, engine, tmp_path = controller_and_engine
    build = tmp_path / "ring.xml"
    _write_build(build, "ring")
    controller.load_build_async(str(build))
    assert _pump(lambda: controller.build_info.state is BuildState.READY)
    generation = controller.baseline_generation

    controller.set_active_loadout("Boss")
    assert controller.build_info.state is BuildState.RELOADING
    assert controller.baseline_generation == generation + 1
    assert _pump(lambda: controller.build_info.state is BuildState.READY)
    assert controller.active_loadout == "Boss"
    assert any(call.startswith("set_active_loadout:Boss:") and not call.endswith(threading.main_thread().name)
               for call in engine.calls)
    assert controller.baseline_state.loadout_name == "Boss"


def test_the_synchronous_load_is_unchanged(controller_and_engine) -> None:
    controller, engine, tmp_path = controller_and_engine
    build = tmp_path / "ring.xml"
    _write_build(build, "ring")
    controller.load_build(str(build))
    assert controller.build_info.state is BuildState.READY       # returned with the build loaded
    assert engine.load_threads == [threading.main_thread().name]  # and on the calling thread
