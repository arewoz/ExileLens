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
from exilelens.errors import BuildParseFailed, WorkerUnhealthy

pytestmark = pytest.mark.itemcheck


def _write_build(path: Path, name: str) -> BuildSource:
    path.write_text(
        f'<PathOfBuilding><Build title="{name}" /><Items><Item id="1">{name}</Item></Items></PathOfBuilding>',
        encoding="utf-8",
    )
    return read_build_source(path)


class _HeldEngine:
    """Stub PoB engine. ``hold`` (when set) blocks load_build until released, on whichever thread calls it."""

    boot_gate: threading.Event | None = None   # class-level: holds a replacement worker's boot (crash recovery)

    def __init__(self, config=None, *, use_subprocess: bool = False) -> None:
        self.loaded_source: BuildSource | None = None
        self.shut_down = False
        self.unhealthy = False
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
        if self.unhealthy:
            raise WorkerUnhealthy("worker exited", {"method": "load_build"})
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

    def start(self) -> None:
        if _HeldEngine.boot_gate is not None:
            assert _HeldEngine.boot_gate.wait(10), "test never released the held engine boot"

    def shutdown(self) -> None:
        self.shut_down = True


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
    _HeldEngine.boot_gate = None
    controller = EvaluationController(
        AppSettings(context="MAP", pob_path=str(tmp_path / "pob")), build_cache=BuildCache(tmp_path / "cache")
    )
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


# --- Shift+C after saving the build in PoB: the reload is non-blocking and ordered ----------------------------------


def _item(name: str = "Reload Ring") -> str:
    from tests.test_stale_build_reload_controller import _item as item

    return item(name)


def _ready_with_capture(controller, engine, tmp_path: Path):
    """A READY controller for ``selected.xml`` whose held Item Checks are recorded instead of evaluated."""
    from tests.test_stale_build_reload_controller import _write_build

    build = tmp_path / "selected.xml"
    _write_build(build, "old")
    controller.load_build_async(str(build))
    assert _pump(lambda: controller.build_info.state is BuildState.READY)
    submitted: list[EvaluationRequest] = []
    controller._submit_evaluation_request = lambda request: submitted.append(request) or request.request_id  # type: ignore[method-assign]
    errors: list[tuple[int, str]] = []
    controller.evaluation_error.connect(lambda rid, message: errors.append((rid, message)))
    return build, submitted, errors


def _settled(controller) -> bool:
    return not controller._baseline_jobs and controller._scheduler.active is None


def test_shift_c_after_a_save_reloads_on_the_lane_and_resumes_once(controller_and_engine) -> None:
    from tests.test_stale_build_reload_controller import _write_build

    controller, engine, tmp_path = controller_and_engine
    build, submitted, _errors = _ready_with_capture(controller, engine, tmp_path)
    generation = controller.baseline_generation
    changed = _write_build(build, "saved-in-pob-with-more-bytes")
    engine.hold = threading.Event()
    engine.entered.clear()

    started = time.perf_counter()
    request_id = controller.submit_clipboard_text(_item(), copy_anchor_screen_px=(10, 20))
    assert (time.perf_counter() - started) * 1000 < 500            # the held reload did not hold the Shift+C
    assert controller.build_info.state is BuildState.RELOADING
    assert controller.baseline_generation == generation + 1        # caches invalidated at once
    assert controller._deferred_evaluation is not None and controller._deferred_evaluation.request_id == request_id
    assert _pump(engine.entered.is_set)
    assert submitted == []                                         # nothing evaluated against the old baseline

    engine.hold.set()
    assert _pump(lambda: _settled(controller) and submitted)
    assert [r.request_id for r in submitted] == [request_id]
    assert submitted[0].baseline_generation == controller.baseline_generation
    assert submitted[0].context_identity == controller._current_evaluation_identity().token
    assert engine.load_calls[-1] == changed.sha256
    assert engine.load_threads[-1] != threading.main_thread().name
    assert controller.build_info.state is BuildState.READY


def test_rapid_consecutive_item_checks_during_a_reload_resume_only_the_newest(controller_and_engine) -> None:
    from exilelens.app.item_check_lifecycle import ItemCheckPhase
    from tests.test_stale_build_reload_controller import _write_build

    controller, engine, tmp_path = controller_and_engine
    build, submitted, errors = _ready_with_capture(controller, engine, tmp_path)
    loads_before = len(engine.load_calls)
    _write_build(build, "saved-in-pob-with-more-bytes")
    engine.hold = threading.Event()

    first = controller.submit_clipboard_text(_item("First"), copy_anchor_screen_px=(1, 1), clipboard_sequence=1)
    second = controller.submit_clipboard_text(_item("Second"), copy_anchor_screen_px=(1, 1), clipboard_sequence=2)
    third = controller.submit_clipboard_text(_item("Third"), copy_anchor_screen_px=(1, 1), clipboard_sequence=3)
    assert first < second < third          # (the reload job takes an id from the same sequence)
    engine.hold.set()

    assert _pump(lambda: _settled(controller) and submitted)
    assert [r.request_id for r in submitted] == [third]            # only the newest is resumed
    assert len(engine.load_calls) == loads_before + 1              # one reload served all three
    assert errors == []
    for retired in (first, second):
        assert controller._item_check_lifecycle.track(retired).phase is ItemCheckPhase.SUPERSEDED
    assert controller._deferred_evaluation is None


def test_a_second_save_during_the_reload_is_picked_up_by_the_next_check(controller_and_engine) -> None:
    from tests.test_stale_build_reload_controller import _write_build

    controller, engine, tmp_path = controller_and_engine
    build, submitted, _errors = _ready_with_capture(controller, engine, tmp_path)
    first_save = _write_build(build, "first-save")
    engine.hold = threading.Event()
    engine.entered.clear()
    controller.submit_clipboard_text(_item("One"), copy_anchor_screen_px=(1, 1), clipboard_sequence=1)
    assert _pump(engine.entered.is_set)
    second_save = _write_build(build, "second-save-with-different-size")   # saved again mid-reload
    engine.hold.set()
    assert _pump(lambda: _settled(controller) and len(submitted) == 1)
    assert controller.baseline_state.source_revision == first_save.revision

    engine.hold = None
    controller.submit_clipboard_text(_item("Two"), copy_anchor_screen_px=(1, 1), clipboard_sequence=2)
    assert _pump(lambda: _settled(controller) and len(submitted) == 2)
    assert engine.load_calls[-2:] == [first_save.sha256, second_save.sha256]
    assert controller.baseline_state.source_revision == second_save.revision


def test_a_worker_failure_during_the_reload_fails_the_load_and_the_held_check(controller_and_engine) -> None:
    from tests.test_stale_build_reload_controller import _write_build

    controller, engine, tmp_path = controller_and_engine
    build, submitted, errors = _ready_with_capture(controller, engine, tmp_path)
    _write_build(build, "saved-in-pob-with-more-bytes")
    engine.unhealthy = True                                        # the restore of the last good bytes fails too

    request_id = controller.submit_clipboard_text(_item(), copy_anchor_screen_px=(1, 1))
    assert _pump(lambda: _settled(controller) and errors)
    assert submitted == []
    assert errors[0][0] == request_id
    assert controller.build_info.state is BuildState.FAILED
    assert controller._deferred_evaluation is None


def test_an_unreadable_file_while_a_reload_is_in_flight_keeps_that_baseline(controller_and_engine, monkeypatch) -> None:
    import exilelens.app.controller as controller_module
    from tests.test_stale_build_reload_controller import _write_build

    controller, engine, tmp_path = controller_and_engine
    build, _submitted, _errors = _ready_with_capture(controller, engine, tmp_path)
    saved = _write_build(build, "saved-in-pob-with-more-bytes")
    engine.hold = threading.Event()
    engine.entered.clear()
    controller.finished_log.clear()  # type: ignore[attr-defined]
    controller.reload_evaluation_build()
    assert _pump(engine.entered.is_set)
    generation = controller.baseline_generation

    def unreadable(_path: str):
        raise BuildParseFailed("The build file kept changing while it was read")

    monkeypatch.setattr(controller_module, "read_build_source", unreadable)
    controller.reload_evaluation_build()                           # second request while the first is in flight
    assert controller.baseline_generation == generation            # no new transaction: the baseline is kept
    assert controller.build_info.state is BuildState.RELOADING
    assert controller._auto_reload_status == "FAILED_KEPT_PREVIOUS"

    engine.hold.set()
    assert _pump(lambda: _settled(controller))
    assert controller.build_info.state is BuildState.READY
    assert controller.baseline_state.source_revision == saved.revision
    results = [entry[0] for entry in controller.finished_log]      # type: ignore[attr-defined]
    assert results == [False, True]                                # the refused request, then the in-flight load


# --- worker recovery ---------------------------------------------------------------------------------------------------


def _fake_boot(monkeypatch) -> list[_HeldEngine]:
    import exilelens.app.controller as controller_module

    engines: list[_HeldEngine] = []

    def make(config, *, use_subprocess: bool = False) -> _HeldEngine:
        engine = _HeldEngine(config, use_subprocess=use_subprocess)
        engines.append(engine)
        return engine

    monkeypatch.setattr(controller_module, "Engine", make)
    monkeypatch.setattr(controller_module, "validate_pob_path", lambda config: None)
    return engines


def test_worker_recovery_boots_off_the_ui_thread_holds_checks_and_reloads(controller_and_engine, monkeypatch) -> None:
    controller, engine, tmp_path = controller_and_engine
    build, submitted, errors = _ready_with_capture(controller, engine, tmp_path)
    boots = _fake_boot(monkeypatch)
    _HeldEngine.boot_gate = threading.Event()
    generation = controller.baseline_generation
    crash = WorkerUnhealthy("worker exited", {"method": "evaluate_item_slots"})

    started = time.perf_counter()
    controller._attempt_recovery(crash)
    assert (time.perf_counter() - started) * 1000 < 500            # no 4 s boot on the calling (UI) thread
    assert engine.shut_down                                        # the dead worker was released
    assert controller.engine is None and controller.engine_status() == "starting"
    assert controller.build_info.state is BuildState.RELOADING
    assert controller.baseline_generation > generation

    held = controller.submit_clipboard_text(_item("During recovery"), copy_anchor_screen_px=(1, 1))
    assert controller._deferred_evaluation is not None and controller._deferred_evaluation.request_id == held
    assert submitted == []                                         # never reaches the dead worker

    _HeldEngine.boot_gate.set()
    assert _pump(lambda: _settled(controller) and submitted)
    assert len(boots) == 1 and controller.engine is boots[0]
    assert controller.build_info.state is BuildState.READY
    assert [r.request_id for r in submitted] == [held]
    assert submitted[0].baseline_generation == controller.baseline_generation
    assert controller._recovery_attempted is False                 # a later crash may recover again
    assert errors == []


def test_worker_recovery_that_cannot_boot_reports_an_error_state(controller_and_engine, monkeypatch) -> None:
    from exilelens.errors import PobBootFailed

    controller, engine, tmp_path = controller_and_engine
    _build, _submitted, _errors = _ready_with_capture(controller, engine, tmp_path)
    _fake_boot(monkeypatch)
    failures: list[str] = []
    controller.engine_failed.connect(failures.append)
    monkeypatch.setattr(_HeldEngine, "start", lambda self: (_ for _ in ()).throw(PobBootFailed("lua would not boot")))

    controller._attempt_recovery(WorkerUnhealthy("worker exited", {}))
    assert _pump(lambda: bool(failures))
    assert controller.build_info.state is BuildState.FAILED
    assert "lua would not boot" in controller.build_info.error_message
    assert controller._recovery_reload is None


# --- review findings: recovery/restart edges, apply failures, bookkeeping ------------------------------------------------


def test_a_superseded_queued_load_leaves_no_bookkeeping_and_no_result(controller_and_engine) -> None:
    from tests.test_stale_build_reload_controller import _write_build

    controller, engine, tmp_path = controller_and_engine
    paths = []
    for name in ("a", "b", "c"):
        path = tmp_path / f"{name}.xml"
        _write_build(path, f"build-{name}-" + "x" * len(paths))
        paths.append(path)
    engine.hold = threading.Event()
    engine.entered.clear()
    controller.load_build_async(str(paths[0]))
    assert _pump(engine.entered.is_set)                 # A is inside PoB
    controller.load_build_async(str(paths[1]))          # B queued behind it
    controller.load_build_async(str(paths[2]))          # C replaces B in the queue
    assert len(controller._baseline_jobs) == 2          # A (running) and C (queued); B left nothing behind
    engine.hold.set()
    assert _pump(lambda: _settled(controller))
    assert controller.build_info.path == str(paths[2].resolve())
    assert controller.finished_log == [(True, str(paths[2].resolve()), "")]  # type: ignore[attr-defined]
    assert controller._baseline_jobs == {}


def test_an_exception_while_applying_a_capture_fails_the_load_and_the_held_check(controller_and_engine, monkeypatch) -> None:
    from tests.test_stale_build_reload_controller import _write_build

    controller, engine, tmp_path = controller_and_engine
    build, submitted, errors = _ready_with_capture(controller, engine, tmp_path)
    _write_build(build, "saved-in-pob-with-more-bytes")

    def explode(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(controller, "_persist_ready_build_cache", explode)
    controller.finished_log.clear()  # type: ignore[attr-defined]
    request_id = controller.submit_clipboard_text(_item(), copy_anchor_screen_px=(1, 1))
    assert _pump(lambda: _settled(controller) and errors)
    assert errors[0][0] == request_id and submitted == []
    assert controller.build_info.state is BuildState.FAILED
    assert controller.finished_log[-1][0] is False                     # type: ignore[attr-defined]
    assert controller._deferred_evaluation is None


def test_a_boot_failure_during_recovery_is_terminal_for_the_baseline_and_the_held_check(controller_and_engine, monkeypatch) -> None:
    from exilelens.errors import PobBootFailed

    controller, engine, tmp_path = controller_and_engine
    _build, submitted, errors = _ready_with_capture(controller, engine, tmp_path)
    _fake_boot(monkeypatch)
    gate = threading.Event()

    def failing_start(self) -> None:
        assert gate.wait(10)
        raise PobBootFailed("lua would not boot")

    monkeypatch.setattr(_HeldEngine, "start", failing_start)
    controller._attempt_recovery(WorkerUnhealthy("worker exited", {}))
    held = controller.submit_clipboard_text(_item("Held"), copy_anchor_screen_px=(1, 1))
    gate.set()

    assert _pump(lambda: errors)
    assert errors[0][0] == held and submitted == []
    assert controller.build_info.state is BuildState.FAILED
    assert controller.baseline_state.state is BuildState.FAILED     # every status surface agrees
    assert controller._deferred_evaluation is None


def test_an_unreadable_file_after_a_crash_fails_instead_of_waiting_forever(controller_and_engine, monkeypatch) -> None:
    import exilelens.app.controller as controller_module

    controller, engine, tmp_path = controller_and_engine
    _build, submitted, errors = _ready_with_capture(controller, engine, tmp_path)
    _fake_boot(monkeypatch)

    def unreadable(_path: str):
        raise BuildParseFailed("The build file is incomplete")

    monkeypatch.setattr(controller_module, "read_build_source", unreadable)
    controller._attempt_recovery(WorkerUnhealthy("worker exited", {}))
    assert _pump(lambda: controller.build_info.state is BuildState.FAILED)
    assert "incomplete" in controller.build_info.error_message
    assert submitted == []


def test_a_build_change_during_the_recovery_boot_retargets_the_pending_reload(controller_and_engine, monkeypatch) -> None:
    from tests.test_stale_build_reload_controller import _write_build

    controller, engine, tmp_path = controller_and_engine
    _build, _submitted, _errors = _ready_with_capture(controller, engine, tmp_path)
    boots = _fake_boot(monkeypatch)
    _HeldEngine.boot_gate = threading.Event()
    other = tmp_path / "other.xml"
    _write_build(other, "other-build")
    controller.finished_log.clear()  # type: ignore[attr-defined]
    controller._attempt_recovery(WorkerUnhealthy("worker exited", {}))

    controller.change_build(str(other))                              # while the replacement worker boots
    assert controller.build_info.state is BuildState.RELOADING        # not FAILED("engine is not started")
    _HeldEngine.boot_gate.set()
    assert _pump(lambda: _settled(controller) and controller.build_info.state is BuildState.READY)
    assert controller.build_info.path == str(other.resolve())
    assert controller.finished_log == [(True, str(other.resolve()), "")]  # type: ignore[attr-defined]
    assert len(boots) == 1


def test_a_loadout_switch_asked_for_during_a_load_is_applied_when_it_settles(controller_and_engine) -> None:
    controller, engine, tmp_path = controller_and_engine
    build = tmp_path / "ring.xml"
    from tests.test_stale_build_reload_controller import _write_build

    _write_build(build, "ring")
    engine.hold = threading.Event()
    engine.entered.clear()
    controller.load_build_async(str(build))
    assert _pump(engine.entered.is_set)
    controller.set_active_loadout("Boss")             # the tray click arrives while the build is still loading
    assert controller._pending_identity_switch == ("loadout", "Boss")
    engine.hold.set()
    assert _pump(lambda: _settled(controller) and controller.active_loadout == "Boss")
    assert any(call.startswith("set_active_loadout:Boss") for call in engine.calls)
    assert controller.build_info.state is BuildState.READY


def test_a_value_profile_change_during_a_load_is_not_reverted_by_the_applied_capture(controller_and_engine) -> None:
    from tests.test_stale_build_reload_controller import _write_build

    controller, engine, tmp_path = controller_and_engine
    build = tmp_path / "ring.xml"
    _write_build(build, "ring")
    engine.hold = threading.Event()
    engine.entered.clear()
    controller.load_build_async(str(build))
    assert _pump(engine.entered.is_set)
    controller.settings.value_profile = "OFFENSE_FOCUS"
    engine.hold.set()
    assert _pump(lambda: _settled(controller))
    assert controller.tree_view_model.profile == "OFFENSE_FOCUS"


def test_shutdown_with_a_load_in_flight_stops_the_worker_thread(controller_and_engine) -> None:
    controller, engine, tmp_path = controller_and_engine
    build = tmp_path / "ring.xml"
    from tests.test_stale_build_reload_controller import _write_build

    _write_build(build, "ring")
    engine.hold = threading.Event()
    engine.entered.clear()
    controller.load_build_async(str(build))
    assert _pump(engine.entered.is_set)
    threading.Timer(0.4, engine.hold.set).start()      # the in-flight PoB call ends shortly after shutdown begins
    controller.shutdown()
    assert not controller._thread.isRunning()


def test_the_pending_flag_distinguishes_a_reconnect_from_a_queued_load(controller_and_engine) -> None:
    from tests.test_stale_build_reload_controller import _write_build

    controller, engine, tmp_path = controller_and_engine
    build = tmp_path / "ring.xml"
    _write_build(build, "ring")
    assert controller.build_load_pending is False
    engine.hold = threading.Event()
    engine.entered.clear()
    controller.load_build_async(str(build))
    assert controller.build_load_pending is True
    assert _pump(engine.entered.is_set)
    engine.hold.set()
    assert _pump(lambda: _settled(controller))
    assert controller.build_load_pending is False


def test_startup_handler_loads_after_a_reconnect_but_not_while_recovery_already_queued_it(tmp_path, monkeypatch) -> None:
    """restart_engine marks the build LOADING without queueing a load; the engine_ready handler must queue it."""
    import sys

    from PySide6.QtWidgets import QApplication

    from exilelens.app.main import ExileLensApp
    from exilelens.app.single_instance import InstanceLock
    from exilelens.app.update_check import UpdateService
    import exilelens.app.main as main_module

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    if sys.platform != "win32":
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_module, "acquire_single_instance_lock", lambda: InstanceLock(acquired=True, reason="t"))
    monkeypatch.setattr(ExileLensApp, "_start_instance_server", lambda self: None)
    monkeypatch.setattr(UpdateService, "start_automatic", lambda self: False)
    build = tmp_path / "ring.xml"
    from tests.test_stale_build_reload_controller import _write_build

    _write_build(build, "ring")
    shell = ExileLensApp()
    shell._compose_primary_ui(quit_callback=lambda: None)
    controller = shell.controller
    loads: list[str] = []
    try:
        controller.load_build_async = lambda path, context=None, **kw: loads.append(path)  # type: ignore[method-assign]
        monkeypatch.setattr(shell, "_resolve_startup_build_path", lambda: str(build))
        controller.build_info = BuildInfo(path=str(build.resolve()), name="ring", context="MAP", state=BuildState.LOADING)

        shell._on_engine_ready()                     # Reconnect: LOADING, nothing queued -> the load must be queued
        assert loads == [str(build)]

        loads.clear()
        controller._recovery_reload = (str(build.resolve()), "MAP")   # crash recovery already owns the load
        shell._on_engine_ready()
        assert loads == []
    finally:
        controller._recovery_reload = None
        controller.shutdown()
