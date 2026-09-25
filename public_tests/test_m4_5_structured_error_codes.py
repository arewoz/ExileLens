"""Focused coverage for M4.5 structured error codes."""

from __future__ import annotations

import json
import os

import pytest

from exilelens.error_catalog import (
    ERROR_REGISTRY,
    EVALUATION_LIMITATION_CATALOG,
    all_error_codes,
    describe_evaluation_limitation,
    get_error_definition,
    resolve_exception,
    resolve_from_engine_code,
)
from exilelens.error_catalog.integration import record_engine_error, record_evaluation_outcome
from exilelens.error_catalog.session import ErrorContextStore
from exilelens.errors import BuildNotFound, WorkerUnhealthy

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytestmark = pytest.mark.smoke


def test_registry_codes_are_unique_and_stable() -> None:
    codes = all_error_codes()
    assert len(codes) == len(set(codes))
    assert all(code.startswith("EL-") for code in codes)
    assert len(codes) >= 30


def test_engine_error_maps_to_structured_code() -> None:
    report = resolve_from_engine_code("BUILD_NOT_FOUND", "missing file", subsystem="build")
    assert report.code == "EL-BLD-001"
    definition = get_error_definition(report.code)
    assert definition is not None
    assert definition.severity.value == "error"
    assert definition.retryability.value == "user_action"


def test_worker_unhealthy_maps_to_wrk_code() -> None:
    store = ErrorContextStore()
    exc = WorkerUnhealthy("worker down")
    recorded = record_engine_error(store, exc, subsystem="item_check")
    assert recorded.code == "EL-WRK-001"
    assert store.last_error is recorded


def test_unrecognized_exception_does_not_crash_reporting() -> None:
    report = resolve_exception(RuntimeError("secret internal"), subsystem="item_check")
    assert report.code == "EL-APP-099"
    assert "secret" not in report.message.lower()


def test_evaluation_limitation_catalog_is_separate_from_errors() -> None:
    lim = describe_evaluation_limitation("OFFENSE_UNSUPPORTED")
    assert lim is not None
    assert lim.code not in ERROR_REGISTRY
    assert lim.code in EVALUATION_LIMITATION_CATALOG


def test_record_evaluation_outcome_preserves_limitation_not_error() -> None:
    store = ErrorContextStore()
    result = {
        "recommendation": {
            "evaluation_outcome": {
                "verdict": "UNSUPPORTED",
                "coverage_class": "UNSUPPORTED",
                "reason_codes": [{"code": "OFFENSE_UNSUPPORTED", "detail": "x"}],
            }
        }
    }
    record_evaluation_outcome(store, result)
    assert store.last_limitation is not None
    assert store.last_limitation.code == "OFFENSE_UNSUPPORTED"
    assert store.last_error is None


def test_extended_summary_includes_structured_errors(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from exilelens.app.controller import EvaluationController
    from exilelens.app.settings import AppSettings
    from exilelens.diagnostics.summary import build_extended_summary

    settings = AppSettings()
    controller = EvaluationController(settings)
    record_engine_error(controller.error_context, BuildNotFound("nope"), subsystem="build")
    try:
        payload = build_extended_summary(controller, settings)
        structured = payload["error_codes"]["structured"]
        assert structured["last_structured_error"]["code"] == "EL-BLD-001"
        text = json.dumps(payload)
        assert "nope" not in text or "EL-BLD" in text
    finally:
        controller.shutdown()


def test_event_history_records_error_code(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from exilelens.diagnostics.events import clear_event_history, event_buffer

    clear_event_history()
    store = ErrorContextStore()
    record_engine_error(store, BuildNotFound("x"), subsystem="build")
    events = event_buffer().snapshot(include_verbose=True)
    assert any(event.name == "EL-BLD-001" for event in events)


def test_recovery_action_present_on_definitions() -> None:
    for code in all_error_codes():
        definition = get_error_definition(code)
        assert definition is not None
        assert definition.recovery_action.strip()
