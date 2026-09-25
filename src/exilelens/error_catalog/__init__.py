"""Structured ExileLens error codes (EL-*) and evaluation limitation reasons."""

from exilelens.error_catalog.definitions import (
    ErrorCategory,
    ErrorSeverity,
    Retryability,
    StructuredErrorDefinition,
)
from exilelens.error_catalog.evaluation_limitations import (
    EVALUATION_LIMITATION_CATALOG,
    EvaluationLimitationDefinition,
    describe_evaluation_limitation,
)
from exilelens.error_catalog.registry import ERROR_REGISTRY, all_error_codes, get_error_definition
from exilelens.error_catalog.resolve import resolve_exception, resolve_from_engine_code
from exilelens.error_catalog.session import ErrorContextStore, StructuredErrorReport
from exilelens.error_catalog.integration import (
    record_engine_error,
    record_evaluation_outcome,
    record_generic_failure,
    record_update_state,
)

__all__ = [
    "ERROR_REGISTRY",
    "EVALUATION_LIMITATION_CATALOG",
    "ErrorCategory",
    "ErrorContextStore",
    "ErrorSeverity",
    "EvaluationLimitationDefinition",
    "Retryability",
    "StructuredErrorDefinition",
    "StructuredErrorReport",
    "all_error_codes",
    "describe_evaluation_limitation",
    "get_error_definition",
    "record_engine_error",
    "record_evaluation_outcome",
    "record_generic_failure",
    "record_update_state",
    "resolve_exception",
    "resolve_from_engine_code",
]
