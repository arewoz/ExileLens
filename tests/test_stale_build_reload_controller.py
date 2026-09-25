"""Controller regressions for Item Check after a selected build changes on disk."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from types import MethodType, SimpleNamespace

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from exilelens.app import controller as controller_module
from exilelens.app.build_cache import BuildCache
from exilelens.app.build_state import BaselineState, BuildInfo, BuildState
from exilelens.app.controller import EvaluationController, EvaluationRequest
from exilelens.app.settings import AppSettings
from exilelens.build_source import BuildSource, read_build_source
from exilelens.build_sources import LocalPobBuildSource
from exilelens.errors import BuildParseFailed


pytestmark = pytest.mark.itemcheck


def _item(name: str = "Reload Test Ring") -> str:
    return f"""Item Class: Rings
Rarity: Rare
{name}
Sapphire Ring
--------
Item Level: 80
--------
+20 to maximum Life
"""


def _write_build(path: Path, name: str) -> BuildSource:
    path.write_text(
        f'<PathOfBuilding><Build title="{name}" /><Items><Item id="1">{name}</Item></Items></PathOfBuilding>',
        encoding="utf-8",
    )
    return read_build_source(path)


class _EngineStub:
    def __init__(self, source: BuildSource) -> None:
        self.loaded_source = source
        self.loaded_source_ref = LocalPobBuildSource(source.path).ref
        self.loaded_revision = SimpleNamespace(token=source.revision)
        self.reject_sha = ""
        self.load_calls: list[BuildSource] = []

    def load_build(self, path: str, *, context: str, source: BuildSource) -> dict:
        self.load_calls.append(source)
        if source.sha256 == self.reject_sha:
            raise RuntimeError("worker rejected changed build")
        self.loaded_source = source
        self.loaded_source_ref = LocalPobBuildSource(path).ref
        self.loaded_revision = SimpleNamespace(token=source.revision)
        return {"build": {"name": Path(path).stem}}

    def list_loadouts(self) -> dict:
        return {"loadouts": [{"name": "Default"}], "active": "Default"}

    def list_item_sets(self) -> dict:
        return {"item_sets": [{"id": "1", "name": "Default"}], "active_id": "1"}

    def get_metrics(self, *, context: str = "") -> dict:
        return {"fingerprint": {}, "fingerprint_hash": "stub-fp", "raw": {}}

    def get_equipment(self) -> dict:
        return {"equipment": []}

    def get_build_info(self) -> dict:
        return {"name": Path(self.loaded_source.path).stem}

    def shutdown(self) -> None:
        return None


def _ready_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stub_capture_ready: bool = True,
) -> tuple[EvaluationController, _EngineStub, Path, list[EvaluationRequest]]:
    app = QApplication.instance() or QApplication([])
    assert app is not None
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    build = tmp_path / "selected.xml"
    source = _write_build(build, "old")
    settings = AppSettings(build_path=str(build), context="MAP")
    controller = EvaluationController(settings, build_cache=BuildCache(tmp_path / "cache"))
    engine = _EngineStub(source)
    controller._engine = engine  # type: ignore[assignment]
    controller._baseline_generation = 7
    controller._worker_generation = 3
    source_ref = LocalPobBuildSource(build).ref
    controller.build_info = BuildInfo(
        path=str(build.resolve()), source_ref=source_ref, name="old", context="MAP", state=BuildState.READY
    )
    controller.baseline_state = BaselineState(
        state=BuildState.READY,
        build_path=str(build.resolve()),
        source_ref=source_ref,
        source_revision=source.revision,
        build_name="old",
        context="MAP",
        generation=controller._baseline_generation,
        fingerprint=source.short_sha,
        equipment_fingerprint=f"equipment-{source.short_sha}",
        tree_fingerprint=f"tree-{source.short_sha}",
    )
    controller._equipment_fingerprint = f"equipment-{source.short_sha}"
    controller._last_good_source = source
    controller._build_loaded_at = time.time()
    controller._record_build_revision(str(build))
    submitted: list[EvaluationRequest] = []

    def submit(request: EvaluationRequest) -> int:
        submitted.append(request)
        return request.request_id

    controller._submit_evaluation_request = submit  # type: ignore[method-assign]
    controller._begin_eval_feedback = lambda _request_id: None  # type: ignore[method-assign]

    def capture_ready(
        self: EvaluationController,
        path: str,
        context: str,
        *,
        started: float,
        resume_deferred: bool = True,
    ) -> None:
        loaded = engine.loaded_source
        ref = LocalPobBuildSource(path).ref
        self.build_info = BuildInfo(path=path, source_ref=ref, name=Path(path).stem, context=context, state=BuildState.READY)
        self.baseline_state = BaselineState(
            state=BuildState.READY,
            build_path=path,
            source_ref=ref,
            source_revision=loaded.revision,
            build_name=Path(path).stem,
            context=context,
            generation=self._baseline_generation,
            fingerprint=loaded.short_sha,
            equipment_fingerprint=f"equipment-{loaded.short_sha}",
            tree_fingerprint=f"tree-{loaded.short_sha}",
        )
        self._equipment_fingerprint = f"equipment-{loaded.short_sha}"
        self._record_build_revision(path)
        if resume_deferred:
            self._resume_deferred_evaluation()

    if stub_capture_ready:
        controller._capture_ready_baseline = MethodType(capture_ready, controller)  # type: ignore[method-assign]
    else:
        import exilelens.tree.mutations as tree_mutations
        from exilelens.tree.models import PassiveTreeSnapshot, TreeBaseline

        def _minimal_tree_snapshot(*_args, **_kwargs):
            baseline = TreeBaseline(
                build_path="",
                build_name="stub",
                loadout="Default",
                tree_set="Default",
                item_set="1",
                context="MAP",
                profile="default",
                generation=0,
                fingerprint="stub-fp",
                tree_fingerprint="tree-stub",
            )
            return PassiveTreeSnapshot(
                baseline=baseline,
                nodes={},
                edges=[],
                tree_set={"index": 0, "title": "Default"},
            )

        monkeypatch.setattr(tree_mutations, "load_tree_snapshot", _minimal_tree_snapshot)
    return controller, engine, build, submitted


def test_changed_build_defers_reload_and_resumes_with_current_generation_and_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, engine, build, submitted = _ready_controller(tmp_path, monkeypatch)
    try:
        previous_generation = controller.baseline_generation
        changed = _write_build(build, "new-build-with-different-size")

        request_id = controller.submit_clipboard_text(_item(), copy_anchor_screen_px=(100, 200))

        assert request_id == 1
        assert [source.sha256 for source in engine.load_calls] == [changed.sha256]
        assert controller.baseline_generation == previous_generation + 1
        assert controller.build_info.state is BuildState.READY
        assert controller._deferred_evaluation is None
        assert len(submitted) == 1
        resumed = submitted[0]
        assert resumed.request_id == request_id
        assert resumed.baseline_generation == controller.baseline_generation
        assert resumed.presentation_generation == controller.presentation_generation
        assert resumed.context_identity == controller._current_evaluation_identity().token
        assert resumed.context_identity != ""
        assert controller.baseline_state.source_revision == changed.revision
        assert controller._last_good_source is not None
        assert controller._last_good_source.sha256 == changed.sha256
    finally:
        controller.shutdown()


def test_failed_reload_restores_last_good_but_rejects_triggering_item_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, engine, build, submitted = _ready_controller(tmp_path, monkeypatch)
    errors: list[tuple[int, str]] = []
    controller.evaluation_error.connect(lambda request_id, message: errors.append((request_id, message)))
    previous = controller._last_good_source
    assert previous is not None
    try:
        changed = _write_build(build, "worker-rejected-new-build")
        engine.reject_sha = changed.sha256

        request_id = controller.submit_clipboard_text(_item(), copy_anchor_screen_px=(100, 200))

        assert request_id == 1
        assert [source.sha256 for source in engine.load_calls] == [changed.sha256, previous.sha256]
        assert submitted == []
        assert controller._deferred_evaluation is None
        assert controller.build_info.state is BuildState.READY
        assert controller.baseline_state.source_revision == previous.revision
        assert controller._last_good_source is not None
        assert controller._last_good_source.sha256 == previous.sha256
        assert controller._auto_reload_status == "FAILED_KEPT_PREVIOUS"
        assert errors and errors[0][0] == request_id
        assert "still using the build loaded" in errors[0][1]
    finally:
        controller.shutdown()


def test_stable_read_failure_keeps_active_baseline_and_cannot_submit_stale_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, engine, build, submitted = _ready_controller(tmp_path, monkeypatch)
    errors: list[tuple[int, str]] = []
    controller.evaluation_error.connect(lambda request_id, message: errors.append((request_id, message)))
    previous_generation = controller.baseline_generation
    previous_revision = controller.baseline_state.source_revision
    _write_build(build, "keeps-changing-during-read")

    def unstable_read(_path: str) -> BuildSource:
        raise BuildParseFailed("The build file kept changing while it was read")

    monkeypatch.setattr(controller_module, "read_build_source", unstable_read)
    try:
        request_id = controller.submit_clipboard_text(_item(), copy_anchor_screen_px=(100, 200))

        assert request_id == 1
        assert engine.load_calls == []
        assert submitted == []
        assert controller._deferred_evaluation is None
        assert controller.build_info.state is BuildState.READY
        assert controller.baseline_generation == previous_generation
        assert controller.baseline_state.source_revision == previous_revision
        assert controller._auto_reload_status == "FAILED_KEPT_PREVIOUS"
        assert errors and "kept changing" in errors[0][1]
    finally:
        controller.shutdown()


def test_partial_xml_is_rejected_then_next_valid_save_recovers_consistently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, engine, build, submitted = _ready_controller(tmp_path, monkeypatch)
    errors: list[tuple[int, str]] = []
    controller.evaluation_error.connect(lambda request_id, message: errors.append((request_id, message)))
    previous = controller._last_good_source
    assert previous is not None
    try:
        build.write_text("<PathOfBuilding><Build", encoding="utf-8")
        failed_id = controller.submit_clipboard_text(_item("Partial Save Ring"), copy_anchor_screen_px=(100, 200))

        assert failed_id == 1
        assert submitted == []
        assert engine.load_calls == []
        assert controller.build_info.state is BuildState.READY
        assert controller.baseline_state.source_revision == previous.revision
        assert errors and "incomplete" in errors[0][1]

        recovered = _write_build(build, "recovered-valid-build")
        recovered_id = controller.submit_clipboard_text(_item("Recovered Ring"), copy_anchor_screen_px=(100, 200))

        assert recovered_id == 2
        assert [source.sha256 for source in engine.load_calls] == [recovered.sha256]
        assert len(submitted) == 1
        assert submitted[0].request_id == recovered_id
        assert submitted[0].baseline_generation == controller.baseline_generation
        assert submitted[0].context_identity == controller._current_evaluation_identity().token
        assert controller.baseline_state.source_revision == recovered.revision
        assert controller._last_good_source is not None
        assert controller._last_good_source.sha256 == recovered.sha256
    finally:
        controller.shutdown()


def test_disk_revision_changed_when_build_file_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller, _engine, build, _submitted = _ready_controller(tmp_path, monkeypatch)
    try:
        build.unlink()
        assert controller._disk_revision_changed(str(build)) is True
    finally:
        controller.shutdown()


def test_missing_build_file_rejects_item_check_without_evaluating_stale_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, engine, build, submitted = _ready_controller(tmp_path, monkeypatch)
    errors: list[tuple[int, str]] = []
    controller.evaluation_error.connect(lambda request_id, message: errors.append((request_id, message)))
    previous = controller._last_good_source
    assert previous is not None
    try:
        build.unlink()
        request_id = controller.submit_clipboard_text(_item("Missing Build Ring"), copy_anchor_screen_px=(100, 200))

        assert request_id == 1
        assert submitted == []
        assert controller._deferred_evaluation is None
        assert controller.build_info.state is BuildState.READY
        assert controller.baseline_state.source_revision == previous.revision
        assert controller._last_good_source.sha256 == previous.sha256
        assert controller._auto_reload_status == "FAILED_KEPT_PREVIOUS"
        assert errors and errors[0][0] == request_id
        assert "no longer exists" in errors[0][1] or "still using the build loaded" in errors[0][1]
        assert engine.load_calls == []
    finally:
        controller.shutdown()


def test_repeated_item_checks_while_build_missing_never_submit_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, _engine, build, submitted = _ready_controller(tmp_path, monkeypatch)
    errors: list[int] = []
    controller.evaluation_error.connect(lambda request_id, _message: errors.append(request_id))
    try:
        build.unlink()
        first = controller.submit_clipboard_text(_item("First Missing"), copy_anchor_screen_px=(100, 200))
        second = controller.submit_clipboard_text(_item("Second Missing"), copy_anchor_screen_px=(100, 200))

        assert first == 1 and second == 2
        assert submitted == []
        assert errors == [1, 2]
    finally:
        controller.shutdown()


def test_missing_build_file_restored_source_recovers_item_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, engine, build, submitted = _ready_controller(tmp_path, monkeypatch)
    errors: list[tuple[int, str]] = []
    controller.evaluation_error.connect(lambda request_id, message: errors.append((request_id, message)))
    previous = controller._last_good_source
    assert previous is not None
    try:
        build.unlink()
        failed_id = controller.submit_clipboard_text(_item("While Missing"), copy_anchor_screen_px=(100, 200))
        assert failed_id == 1
        assert submitted == []
        assert errors

        restored = _write_build(build, "restored-after-missing")
        recovered_id = controller.submit_clipboard_text(_item("After Restore"), copy_anchor_screen_px=(100, 200))

        assert recovered_id == 2
        assert [source.sha256 for source in engine.load_calls] == [restored.sha256]
        assert len(submitted) == 1
        assert submitted[0].request_id == recovered_id
        assert controller.baseline_state.source_revision == restored.revision
    finally:
        controller.shutdown()


def test_failed_reload_real_capture_ready_baseline_rejects_triggering_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, engine, build, submitted = _ready_controller(tmp_path, monkeypatch, stub_capture_ready=False)
    errors: list[tuple[int, str]] = []
    controller.evaluation_error.connect(lambda request_id, message: errors.append((request_id, message)))
    previous = controller._last_good_source
    assert previous is not None
    previous_generation = controller.baseline_generation
    try:
        changed = _write_build(build, "worker-rejected-real-capture")
        engine.reject_sha = changed.sha256

        request_id = controller.submit_clipboard_text(_item("Real Capture Ring"), copy_anchor_screen_px=(100, 200))

        assert request_id == 1
        assert [source.sha256 for source in engine.load_calls] == [changed.sha256, previous.sha256]
        assert submitted == []
        assert controller._deferred_evaluation is None
        assert controller.build_info.state is BuildState.READY
        assert controller.baseline_generation == previous_generation + 1
        assert controller.baseline_state.source_revision == previous.revision
        assert controller._last_good_source.sha256 == previous.sha256
        assert controller._auto_reload_status == "FAILED_KEPT_PREVIOUS"
        assert errors and errors[0][0] == request_id
    finally:
        controller.shutdown()
