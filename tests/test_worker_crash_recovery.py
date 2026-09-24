"""Focused REL-01 worker fail-stop regressions.

These tests exercise the Qt worker slot synchronously with deterministic engine
stubs.  They verify signal ordering and error propagation; they are not a
substitute for real-Path-of-Building integration coverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from exilelens.app import controller as controller_module
from exilelens.app.controller import (
    EvaluationController,
    EvaluationRequest,
    EvaluationTiming,
    _EvaluationWorker,
)
from exilelens.app.scheduler import BoundedEvaluationScheduler
from exilelens.errors import RestoreFailed, WorkerUnhealthy
from exilelens.items.evaluation_identity import EvaluationContextIdentity

pytestmark = pytest.mark.itemcheck


@dataclass
class _LoadedSource:
    short_sha: str = "abc123"


class _EngineStub:
    loaded_source = _LoadedSource()

    def __init__(self, restore_error: Exception | None = None) -> None:
        self.restore_error = restore_error
        self.finalize_calls = 0

    def finalize_transaction(self) -> None:
        self.finalize_calls += 1
        if self.restore_error is not None:
            raise self.restore_error


def _request(request_id: int = 17) -> EvaluationRequest:
    return EvaluationRequest(
        request_id=request_id,
        raw_text="Rarity: Rare\nTest Item",
        content_hash="candidate",
        clipboard_received_ms=1.0,
        copy_timestamp=2.0,
        baseline_generation=3,
        presentation_generation=4,
        context_identity="context-token",
        candidate_fingerprint="candidate",
    )


def _successful_evaluation(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {
        "raw_input": {"content_hash": "candidate"},
        "source_revision": "revision-1",
        "source_generation": 3,
        "timings": {},
    }


def test_failed_deferred_restore_suppresses_success_result(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _EvaluationWorker()
    engine = _EngineStub(RestoreFailed("baseline restore failed"))
    worker._engine = engine  # type: ignore[assignment]
    monkeypatch.setattr(controller_module, "evaluate_item", _successful_evaluation)
    emissions: list[tuple[int, object, object]] = []
    worker.finished_eval.connect(
        lambda request_id, payload, error: emissions.append((request_id, payload, error))
    )

    worker.run_evaluation(_request())

    assert engine.finalize_calls == 1
    assert len(emissions) == 1
    request_id, payload, error = emissions[0]
    assert request_id == 17
    assert payload is None
    assert isinstance(error, RestoreFailed)


def test_success_is_emitted_after_deferred_restore_completes(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _EvaluationWorker()
    engine = _EngineStub()
    worker._engine = engine  # type: ignore[assignment]
    monkeypatch.setattr(controller_module, "evaluate_item", _successful_evaluation)
    emissions: list[tuple[int, object, object]] = []
    worker.finished_eval.connect(
        lambda request_id, payload, error: emissions.append((request_id, payload, error))
    )

    worker.run_evaluation(_request())

    assert engine.finalize_calls == 1
    assert len(emissions) == 1
    request_id, payload, error = emissions[0]
    assert request_id == 17
    assert payload is not None
    assert error is None


def test_worker_crash_during_evaluation_emits_only_the_unhealthy_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _EvaluationWorker()
    engine = _EngineStub()
    worker._engine = engine  # type: ignore[assignment]

    def _crash(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise WorkerUnhealthy("worker exited", {"method": "evaluate_candidate"})

    monkeypatch.setattr(controller_module, "evaluate_item", _crash)
    emissions: list[tuple[int, object, object]] = []
    worker.finished_eval.connect(
        lambda request_id, payload, error: emissions.append((request_id, payload, error))
    )

    worker.run_evaluation(_request())

    assert engine.finalize_calls == 1
    assert len(emissions) == 1
    request_id, payload, error = emissions[0]
    assert request_id == 17
    assert payload is None
    assert isinstance(error, WorkerUnhealthy)


def test_controller_discards_queued_requests_before_worker_recovery() -> None:
    active = _request(17)
    queued = _request(18)
    scheduler: BoundedEvaluationScheduler[EvaluationRequest] = BoundedEvaluationScheduler(
        lambda request: None
    )
    scheduler.submit(active)
    scheduler.submit(queued)

    class _Lifecycle:
        errors: list[tuple[int, str, dict[str, Any]]] = []
        phases: list[tuple[int, object]] = []

        @classmethod
        def mark_error(cls, request_id: int, message: str, **extra: Any) -> None:
            cls.errors.append((request_id, message, extra))

        @classmethod
        def advance(cls, request_id: int, phase: object, **extra: Any) -> None:
            cls.phases.append((request_id, phase))

    class _Signal:
        emissions: list[tuple[Any, ...]] = []

        @classmethod
        def emit(cls, *args: Any) -> None:
            cls.emissions.append(args)

    class _Heartbeat:
        finished: list[int] = []
        pending: list[int | None] = []

        @classmethod
        def note_eval_finished(cls, request_id: int) -> None:
            cls.finished.append(request_id)

        @classmethod
        def note_pending(cls, request_id: int | None) -> None:
            cls.pending.append(request_id)

    class _Harness:
        _analyzing_timers: dict[int, object] = {}
        _scheduler = scheduler
        _latest_request_id = 18
        _presentation_generation = 4
        _item_check_lifecycle = _Lifecycle()
        _heartbeat_state = _Heartbeat()
        _pending_request_id: int | None = 18
        evaluation_error = _Signal()
        stopped_watchdogs: list[int] = []
        recovery_errors: list[Exception] = []

        @classmethod
        def _stop_item_check_watchdog(cls, request_id: int) -> None:
            cls.stopped_watchdogs.append(request_id)

        @classmethod
        def _attempt_recovery(cls, error: Exception) -> None:
            cls.recovery_errors.append(error)

    crash = WorkerUnhealthy("worker exited", {"method": "evaluate_candidate"})
    EvaluationController._on_worker_finished(_Harness(), 17, None, crash)  # type: ignore[arg-type]

    assert scheduler.active is None
    assert scheduler.pending is None
    assert _Harness.stopped_watchdogs == [18]
    assert _Lifecycle.errors == [
        (18, "PoB worker restarted before this analysis could run.", {"stage": "worker_recovery"})
    ]
    assert _Signal.emissions == [(18, "PoB worker restarted — try Item Check again.")]
    assert _Harness.recovery_errors == [crash]


def test_result_from_previous_worker_generation_is_rejected() -> None:
    previous = EvaluationContextIdentity(
        source_identity="build",
        source_revision="revision-1",
        build_generation=3,
        worker_generation=1,
    )
    current = EvaluationContextIdentity(
        source_identity="build",
        source_revision="revision-1",
        build_generation=3,
        worker_generation=2,
    )

    class _Lifecycle:
        @staticmethod
        def track(request_id: int) -> None:
            return None

    class _Harness:
        _latest_request_id = 17
        _baseline_generation = 3
        _item_check_lifecycle = _Lifecycle()
        _scheduler = SimpleNamespace(active=SimpleNamespace(request_id=17))
        errors: list[tuple[int, str]] = []

        @staticmethod
        def _current_evaluation_identity() -> EvaluationContextIdentity:
            return current

        @classmethod
        def _emit_item_check_error(cls, request_id: int, message: str, **kwargs: Any) -> None:
            cls.errors.append((request_id, message))

    result = {
        "raw_input": {"content_hash": "candidate"},
        "request_meta": {
            "baseline_generation": 3,
            "evaluation_context_identity": previous.token,
            "candidate_fingerprint": "candidate",
        },
    }

    EvaluationController._deliver_evaluation_result(
        _Harness(),  # type: ignore[arg-type]
        17,
        result,
        EvaluationTiming(request_id=17),
        from_cache=False,
    )

    assert _Harness.errors == [(17, "Evaluation context changed — copy the item again.")]
