from __future__ import annotations

import logging
from typing import Any

from exilelens.error_catalog.registry import engine_code_to_el, get_error_definition
from exilelens.error_catalog.session import StructuredErrorReport
from exilelens.errors import EngineError

logger = logging.getLogger(__name__)


def resolve_from_engine_code(
    engine_code: str,
    message: str,
    *,
    subsystem: str,
    details: dict[str, Any] | None = None,
) -> StructuredErrorReport:
    el_code = engine_code_to_el(engine_code)
    definition = get_error_definition(el_code)
    if definition is None:
        definition = get_error_definition("EL-APP-099")
    assert definition is not None
    context = {"engine_code": engine_code, "subsystem": subsystem}
    if details:
        for key in definition.diagnostic_fields:
            if key in details:
                context[key] = details[key]
    return StructuredErrorReport.from_definition(
        definition,
        message=message,
        subsystem=subsystem,
        context=context,
        engine_code=engine_code,
    )


def resolve_exception(exc: BaseException, *, subsystem: str, stage: str = "") -> StructuredErrorReport:
    try:
        if isinstance(exc, EngineError):
            details = dict(exc.details or {})
            if stage:
                details.setdefault("stage", stage)
            return resolve_from_engine_code(exc.code, exc.message, subsystem=subsystem, details=details)
        context: dict[str, Any] = {"exception_type": type(exc).__name__}
        if stage:
            context["stage"] = stage
        definition = get_error_definition("EL-APP-099")
        assert definition is not None
        return StructuredErrorReport.from_definition(
            definition,
            message="An unexpected error occurred.",
            subsystem=subsystem,
            context=context,
        )
    except Exception:  # noqa: BLE001 - reporting must never crash the app
        logger.exception("structured_error_resolve_failed")
        definition = get_error_definition("EL-APP-099")
        assert definition is not None
        return StructuredErrorReport.from_definition(
            definition,
            message="An unexpected error occurred.",
            subsystem=subsystem,
            context={"stage": stage},
        )
