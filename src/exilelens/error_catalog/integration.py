from __future__ import annotations

import logging
from typing import Any

from exilelens.diagnostics.events import record_event
from exilelens.diagnostics.sanitize import sanitize_text, sanitize_value
from exilelens.error_catalog.evaluation_limitations import describe_evaluation_limitation
from exilelens.error_catalog.registry import get_error_definition
from exilelens.error_catalog.resolve import resolve_exception, resolve_from_engine_code
from exilelens.error_catalog.session import ErrorContextStore, EvaluationLimitationReport, StructuredErrorReport
from exilelens.errors import EngineError

logger = logging.getLogger(__name__)


def _emit_diagnostic_event(report: StructuredErrorReport) -> None:
    record_event(
        "error",
        report.code,
        detail=sanitize_value(
            {
                "subsystem": report.subsystem,
                "severity": report.severity,
                "engine_code": report.engine_code or None,
                "stage": report.context.get("stage"),
            }
        ),
    )


def record_structured_error(store: ErrorContextStore, report: StructuredErrorReport) -> StructuredErrorReport:
    store.record_error(report)
    _emit_diagnostic_event(report)
    return report


def record_engine_error(
    store: ErrorContextStore,
    exc: EngineError,
    *,
    subsystem: str,
    stage: str = "",
) -> StructuredErrorReport:
    details = dict(exc.details or {})
    if stage:
        details["stage"] = stage
    report = resolve_from_engine_code(exc.code, exc.message, subsystem=subsystem, details=details)
    return record_structured_error(store, report)


def record_generic_failure(
    store: ErrorContextStore,
    message: str,
    *,
    el_code: str,
    subsystem: str,
    stage: str = "",
    context: dict[str, Any] | None = None,
) -> StructuredErrorReport:
    definition = get_error_definition(el_code) or get_error_definition("EL-APP-099")
    assert definition is not None
    payload = dict(context or {})
    if stage:
        payload["stage"] = stage
    report = StructuredErrorReport.from_definition(
        definition,
        message=message,
        subsystem=subsystem,
        context=payload,
    )
    return record_structured_error(store, report)


def record_exception(
    store: ErrorContextStore,
    exc: BaseException,
    *,
    subsystem: str,
    stage: str = "",
) -> StructuredErrorReport:
    report = resolve_exception(exc, subsystem=subsystem, stage=stage)
    return record_structured_error(store, report)


def record_update_state(store: ErrorContextStore, state: str, version: str = "") -> None:
    if state == "verification_failed":
        definition = get_error_definition("EL-UPD-001")
        assert definition is not None
        report = StructuredErrorReport.from_definition(
            definition,
            message=definition.explanation,
            subsystem="update",
            context={"remote_version": sanitize_text(version)},
        )
        record_structured_error(store, report)
    elif state == "failed":
        definition = get_error_definition("EL-UPD-003")
        assert definition is not None
        report = StructuredErrorReport.from_definition(
            definition,
            message=definition.explanation,
            subsystem="update",
            context={},
        )
        record_structured_error(store, report)


def record_evaluation_outcome(store: ErrorContextStore, result: dict[str, Any]) -> None:
    recommendation = result.get("recommendation") if isinstance(result, dict) else {}
    if not isinstance(recommendation, dict):
        return
    outcome = recommendation.get("evaluation_outcome") or {}
    if not isinstance(outcome, dict):
        return
    verdict = str(outcome.get("verdict") or "")
    coverage = str(outcome.get("coverage_class") or "")
    if verdict not in ("UNCERTAIN", "UNSUPPORTED"):
        return
    reasons = outcome.get("reason_codes") or outcome.get("reasons") or []
    primary_code = ""
    if isinstance(reasons, list) and reasons:
        first = reasons[0]
        if isinstance(first, dict):
            primary_code = str(first.get("code") or "")
        else:
            primary_code = str(first)
    if not primary_code:
        primary_code = str(outcome.get("reason_code") or outcome.get("reason") or "")
    definition = describe_evaluation_limitation(primary_code)
    if definition is None:
        definition = describe_evaluation_limitation("OFFENSE_MECHANICS_PARTIAL")
    if definition is None:
        return
    report = EvaluationLimitationReport.from_definition(
        definition,
        verdict=verdict,
        coverage_class=coverage,
    )
    store.record_limitation(report)
    record_event(
        "item_check",
        "evaluation_limitation",
        detail=sanitize_value(
            {
                "code": report.code,
                "verdict": verdict,
                "coverage_class": coverage,
            }
        ),
    )
