"""PERF-01: the minion / ailment offense-coverage audit runs on the PoB lane, never on the UI thread.

Measured on a poison (ailment-DPS) build: the first Item Check froze the UI thread for 1.75 s *before* the first
placeholder paint, because the controller ran the audit's PoB probes inline (and concurrently with whatever the lane
was doing). The controller now only decides, from the build info captured with the baseline, whether an audit is
needed; the audit itself is the first step of that request's evaluation on the worker.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import exilelens.app.controller as controller_module
from exilelens.app.build_cache import BuildCache
from exilelens.app.build_state import BaselineState, BuildInfo, BuildState
from exilelens.app.controller import EvaluationController, EvaluationRequest, _EvaluationWorker
from exilelens.app.settings import AppSettings
from exilelens.items.offense_coverage import DamageOwner, DamageQuantity

pytestmark = pytest.mark.itemcheck


class _ForbiddenEngine:
    """Any PoB round trip from the UI thread fails the test."""

    def __getattr__(self, name: str):
        if name in {"loaded_revision", "loaded_source", "loaded_source_ref"}:
            return None                      # plain attributes, not PoB round trips
        raise AssertionError(f"UI thread called engine.{name}")

    def shutdown(self) -> None:
        return None


@pytest.fixture
def ready_controller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    controller = EvaluationController(AppSettings(context="MAP"), build_cache=BuildCache(tmp_path / "cache"))
    controller._engine = _ForbiddenEngine()  # type: ignore[assignment]
    controller.build_info = BuildInfo(path="b.xml", name="b", context="MAP", state=BuildState.READY)
    controller.baseline_state = BaselineState(
        state=BuildState.READY, build_path="b.xml", context="MAP", fingerprint="fp", metrics={"CombinedDPS": 10.0}
    )
    controller._baseline_build_info = {"build": {"main_skill_identity": {"skill_id": "Poison"}}, "metrics": {}}
    try:
        yield controller
    finally:
        controller._engine = None
        controller.shutdown()


def _primary(owner: DamageOwner, quantity: DamageQuantity) -> Any:
    return SimpleNamespace(damage_owner=owner, semantic_quantity=quantity, pob_field="PoisonDPS", confidence=None)


def test_an_ailment_build_needs_an_audit_but_the_ui_thread_makes_no_pob_call(ready_controller, monkeypatch) -> None:
    controller = ready_controller
    monkeypatch.setattr(
        controller_module, "resolve_primary_metric",
        lambda build_info, metrics: _primary(DamageOwner.PLAYER, DamageQuantity.AILMENT_DPS),
    )
    inputs = controller._ensure_offense_coverage()
    assert inputs is not None
    assert (inputs["fingerprint"], inputs["context"], inputs["primary_field"]) == ("fp", "MAP", "PoisonDPS")
    assert inputs["build_info"] == controller._baseline_build_info
    assert inputs["generation"] == controller._baseline_generation
    assert controller._offense_coverage is None          # not known yet: the lane computes it


def test_a_plain_build_is_resolved_statically_without_any_pob_call(ready_controller, monkeypatch) -> None:
    controller = ready_controller
    primary_kinds = [member for member in DamageQuantity if member is not DamageQuantity.AILMENT_DPS]
    monkeypatch.setattr(
        controller_module, "resolve_primary_metric",
        lambda build_info, metrics: _primary(DamageOwner.PLAYER, primary_kinds[0]),
    )
    monkeypatch.setattr(
        "exilelens.items.offense_coverage.infer_offense_coverage",
        lambda primary, metrics: SimpleNamespace(to_dict=lambda: {"state": "FULL"}),
    )
    assert controller._ensure_offense_coverage() is None
    assert controller._offense_coverage == {"state": "FULL", "audit_skipped": True}


def test_the_audit_inputs_travel_with_the_request_and_run_in_the_worker(ready_controller, monkeypatch) -> None:
    controller = ready_controller
    monkeypatch.setattr(
        controller_module, "resolve_primary_metric",
        lambda build_info, metrics: _primary(DamageOwner.MINION, DamageQuantity.AILMENT_DPS),
    )
    queued: list[Any] = []
    monkeypatch.setattr(controller._scheduler, "submit", lambda request: queued.append(request) or True)
    monkeypatch.setattr(controller, "_begin_eval_feedback", lambda _rid: None)
    request = EvaluationRequest(
        request_id=3, raw_text="x", content_hash="h", clipboard_received_ms=0.0, copy_timestamp=0.0,
        baseline_generation=controller._baseline_generation,
    )
    controller._submit_evaluation_request(request)
    assert len(queued) == 1 and queued[0].coverage_inputs is not None
    assert queued[0].request_id == 3

    seen: dict[str, Any] = {}

    class _Auditor:
        def __init__(self, engine, cache=None) -> None:
            seen["thread_engine"] = engine
            seen["cache"] = cache

        def get_cached(self, **kwargs):
            seen["cached_args"] = kwargs
            return None

        def ensure(self, **kwargs):
            seen["ensure_args"] = kwargs
            return SimpleNamespace(to_dict=lambda: {"state": "PARTIAL", "reason": "audited"})

    monkeypatch.setattr("exilelens.items.offense_coverage.OffenseCoverageAuditor", _Auditor)
    worker = _EvaluationWorker()
    sentinel = object()
    worker._engine = sentinel  # type: ignore[assignment]
    audited = worker._audit_offense_coverage(queued[0].coverage_inputs)
    assert audited == {"state": "PARTIAL", "reason": "audited"}
    assert seen["thread_engine"] is sentinel
    assert seen["cached_args"] == {"fingerprint": "fp", "context": "MAP", "primary_field": "PoisonDPS"}
    assert seen["ensure_args"]["fingerprint"] == "fp" and seen["ensure_args"]["generation"] == controller._baseline_generation
