"""PERF-01: background Build Intelligence work yields the single PoB lane to a new Item Check.

The post-paint decomposition is several sequential PoB probes (about two seconds on a small build, more than
ten on a heavy one). It holds the only PoB worker, so an Item Check issued while it ran used to wait for the
whole run -- and the run's result was always discarded anyway, because a new Item Check bumps the
presentation generation. These tests pin the cooperative yield: it is checked only between probes (every
probe is a complete, restored PoB transaction), a yielded run produces no payload and caches nothing, and
a run that is never asked to yield is bit-for-bit what it was.
"""

from __future__ import annotations

import pytest

from exilelens.items.build_intel import decomposition as decomp
from exilelens.items.build_intel.item_semantics import parse_item_semantics

pytestmark = pytest.mark.itemcheck

RING = """Item Class: Rings
Rarity: Rare
Doom Loop
Sapphire Ring
--------
Item Level: 80
--------
+45 to maximum Life
+30% to Fire Resistance
+25% to Cold Resistance
12% increased Cast Speed
"""


def _semantic():
    return parse_item_semantics(RING, product_slot="Ring 1")


def _groups(semantic) -> list[str]:
    return [group for group, texts in semantic.groups.items() if texts]


class _Probe:
    """Counts probes; stands in for one complete (restored) PoB candidate transaction."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, engine, **kwargs):
        self.calls += 1
        return {"value": {"score_delta": 1.0}}, 1


def _run(monkeypatch, *, should_yield=None, cache=None):
    probe = _Probe()
    monkeypatch.setattr(decomp, "_evaluate_variant", probe)
    semantic = _semantic()
    kwargs = {} if should_yield is None else {"should_yield": should_yield}
    payload = decomp.run_bounded_decomposition(
        object(),
        slot="Ring 1",
        item_raw=RING,
        semantic=semantic,
        groups=_groups(semantic),
        whole_comparison={"value": {"score_delta": 3.0}, "baseline": {}, "restore": {"pass": True}},
        cache=cache,
        **kwargs,
    )
    return payload, probe


def test_the_fixture_actually_has_several_groups_to_probe() -> None:
    assert len(_groups(_semantic())) >= 3


def test_without_a_yield_probe_the_decomposition_is_unchanged(monkeypatch) -> None:
    cache: dict = {}
    payload, probe = _run(monkeypatch, cache=cache)
    assert payload["status"] == "COMPLETE"
    assert probe.calls >= 3
    assert payload["pob_recalcs"] == probe.calls
    assert cache and payload["cache_key"] in cache


def test_a_yield_requested_up_front_runs_no_probe_and_caches_nothing(monkeypatch) -> None:
    cache: dict = {}
    with pytest.raises(decomp.DecompositionYielded):
        _run(monkeypatch, should_yield=lambda: True, cache=cache)
    assert cache == {}


def test_a_yield_between_probes_stops_after_the_probe_in_flight(monkeypatch) -> None:
    probe_counter = {"asked": 0}

    def yield_after_first_probe() -> bool:
        probe_counter["asked"] += 1
        return probe_counter["asked"] > 1  # allow the first probe, refuse the second

    cache: dict = {}
    probe = _Probe()
    monkeypatch.setattr(decomp, "_evaluate_variant", probe)
    semantic = _semantic()
    with pytest.raises(decomp.DecompositionYielded):
        decomp.run_bounded_decomposition(
            object(),
            slot="Ring 1",
            item_raw=RING,
            semantic=semantic,
            groups=_groups(semantic),
            whole_comparison={"value": {"score_delta": 3.0}, "baseline": {}, "restore": {"pass": True}},
            cache=cache,
            should_yield=yield_after_first_probe,
        )
    assert probe.calls == 1
    assert cache == {}


def test_a_probe_that_never_asks_to_yield_matches_the_default_result(monkeypatch) -> None:
    baseline, _ = _run(monkeypatch)
    guarded, _ = _run(monkeypatch, should_yield=lambda: False)
    assert guarded == baseline


# --- worker wiring ---------------------------------------------------------------------------------------------------


def _decomp_request():
    from exilelens.app.controller import BuildDecompRequest

    return BuildDecompRequest(
        request_id=7,
        parent_request_id=6,
        content_hash="h",
        item_raw=RING,
        slot="Ring 1",
        result_snapshot={"recommendation": {"product_slot": "Ring 1", "build_comparison": {"mods": []}}},
        baseline_generation=3,
        presentation_generation=4,
        profile="BALANCED",
    )


def _worker_with(monkeypatch, *, yielding: bool):
    from exilelens.app import controller as controller_module

    seen: dict[str, object] = {}

    def fake_decomposition(engine, **kwargs):
        seen["should_yield"] = kwargs.get("should_yield")
        probe = kwargs["should_yield"]
        if probe():
            raise decomp.DecompositionYielded
        return {"status": "COMPLETE", "contribution": [], "synergy": [], "pob_recalcs": 0, "groups": [], "cache_key": "k"}

    monkeypatch.setattr(controller_module, "run_bounded_decomposition", fake_decomposition)
    worker = controller_module._EvaluationWorker()
    worker._engine = object()
    worker.yield_probe = lambda: yielding
    emitted: list[tuple] = []
    worker.finished_build_decomp.connect(lambda rid, payload, error: emitted.append((rid, payload, error)))
    return worker, emitted, seen


def test_a_waiting_request_makes_the_worker_abandon_the_decomposition_without_error(monkeypatch) -> None:
    worker, emitted, seen = _worker_with(monkeypatch, yielding=True)
    worker.run_build_decomp(_decomp_request())
    assert emitted == [(7, None, None)]
    assert callable(seen["should_yield"])


def test_without_a_waiting_request_the_decomposition_is_delivered_as_before(monkeypatch) -> None:
    worker, emitted, _ = _worker_with(monkeypatch, yielding=False)
    worker.run_build_decomp(_decomp_request())
    assert len(emitted) == 1
    request_id, payload, error = emitted[0]
    assert (request_id, error) == (7, None)
    assert payload["decomposition"]["status"] == "COMPLETE"
    assert payload["baseline_generation"] == 3 and payload["presentation_generation"] == 4


def test_the_controller_points_the_worker_probe_at_the_scheduler_flag(monkeypatch, tmp_path) -> None:
    import sys

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    from PySide6.QtWidgets import QApplication

    from exilelens.app.controller import EvaluationController
    from exilelens.app.settings import AppSettings

    if sys.platform != "win32":
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QApplication.instance() or QApplication([])
    controller = EvaluationController(AppSettings())
    try:
        probe = controller._worker.yield_probe
        assert probe is not None and probe() is False
        controller._scheduler.yield_requested = True
        assert probe() is True
    finally:
        controller.shutdown()
