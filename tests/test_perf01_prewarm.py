"""PERF-01: the idle native-report prewarm fills exactly the cache Item Check reads, and only when it has a use.

Measured (interleaved, real PoB, heavy multi-skill build): a first check 3 s after the load drops from about 1.6 s to
1.0 s (the in-check ``get_skill_report`` is gone); a first check made at once is not slower beyond noise because it
waits only for the remainder of a pass it would otherwise have run inline.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from exilelens.items.evaluation import cached_native_component_report
from exilelens.items.prewarm import prewarm_native_report

pytestmark = pytest.mark.itemcheck


class _Engine:
    def __init__(self, *, multi_skill: bool = True) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.multi_skill = multi_skill

    def get_build_info(self) -> dict[str, Any]:
        build = {
            "main_socket_group": 1,
            "weapon_set": 1,
            "active_skill_set_id": 1,
            "skill_group_count": 3,
            "native_damage_group_indices": [1, 2] if self.multi_skill else [1],
            "main_skill_identity": {"skill_id": "Fireball", "damage_target": True},
        }
        return {"build": build, "fingerprint_hash": "fp", "metrics": {"CombinedDPS": 100.0, "TotalDPS": 100.0}}

    def _call(self, method: str, params: dict | None = None) -> dict[str, Any]:
        self.calls.append((method, dict(params or {})))
        return {"groups": [], "metrics": {"CombinedDPS": 100.0}}


def test_a_multi_skill_build_is_prewarmed_once_and_item_check_reuses_the_report() -> None:
    engine = _Engine()
    assert prewarm_native_report(engine, context="MAP") is True
    assert [name for name, _ in engine.calls] == ["get_skill_report"]

    # Item Check asks through the same function with the same baseline identity: no second PoB pass.
    loaded = engine.get_build_info()
    from exilelens.items.primary_metric import resolve_primary_metric

    primary = resolve_primary_metric(loaded["build"], loaded["metrics"])
    report = cached_native_component_report(
        engine, build_info=loaded["build"], primary_metric=primary, baseline_fingerprint="fp", context="MAP"
    )
    assert report == {"groups": [], "metrics": {"CombinedDPS": 100.0}}
    assert len(engine.calls) == 1


def test_a_single_skill_build_or_a_bare_engine_is_left_alone() -> None:
    single = _Engine(multi_skill=False)
    assert prewarm_native_report(single, context="MAP") is False
    assert single.calls == []
    assert prewarm_native_report(object(), context="MAP") is False


def test_the_report_is_keyed_by_baseline_and_context_so_a_changed_baseline_asks_again() -> None:
    engine = _Engine()
    assert prewarm_native_report(engine, context="MAP")
    assert prewarm_native_report(engine, context="MAP")          # same baseline: cached
    assert len(engine.calls) == 1
    assert prewarm_native_report(engine, context="BOSS")         # different calculation context: a new pass
    assert len(engine.calls) == 2


def test_a_loaded_build_queues_the_prewarm_behind_user_visible_work(tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    import exilelens.tree.mutations as tree_mutations
    from exilelens.app.build_cache import BuildCache
    from exilelens.app.controller import EvaluationController, PrewarmRequest
    from exilelens.app.scheduler import KIND_PRIORITY
    from exilelens.app.settings import AppSettings
    from tests.test_perf01_async_build_load import _HeldEngine, _minimal_snapshot, _pump, _write_build

    assert KIND_PRIORITY["gameplay"] > KIND_PRIORITY["baseline"] > KIND_PRIORITY["analysis"] > KIND_PRIORITY["prewarm"]
    assert KIND_PRIORITY["prewarm"] > KIND_PRIORITY["upgrade_path"]

    QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    monkeypatch.setattr(tree_mutations, "load_tree_snapshot", _minimal_snapshot)
    controller = EvaluationController(AppSettings(context="MAP"), build_cache=BuildCache(tmp_path / "cache"))
    engine = _HeldEngine()
    engine._call = lambda method, params=None: engine.calls.append(f"call:{method}") or {}  # type: ignore[attr-defined]
    controller._engine = engine  # type: ignore[assignment]
    submitted: list[object] = []
    original_submit = controller._scheduler.submit
    controller._scheduler.submit = lambda request: submitted.append(request) or original_submit(request)  # type: ignore[method-assign]
    try:
        build = tmp_path / "ring.xml"
        _write_build(build, "ring")
        controller.load_build_async(str(build))
        assert _pump(lambda: controller.build_info.state.value == "READY")
        assert _pump(lambda: any(isinstance(r, PrewarmRequest) for r in submitted))
        prewarm = next(r for r in submitted if isinstance(r, PrewarmRequest))
        assert prewarm.baseline_generation == controller.baseline_generation
        assert _pump(lambda: controller._scheduler.active is None)   # it completed and released the lane
    finally:
        controller._engine = None
        controller.shutdown()
        time.sleep(0)
