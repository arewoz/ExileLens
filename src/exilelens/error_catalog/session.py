from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from exilelens.error_catalog.definitions import StructuredErrorDefinition
from exilelens.error_catalog.evaluation_limitations import EvaluationLimitationDefinition


@dataclass
class StructuredErrorReport:
    code: str
    title: str
    message: str
    recovery_action: str
    severity: str
    retryability: str
    subsystem: str
    context: dict[str, Any] = field(default_factory=dict)
    engine_code: str = ""

    def to_diagnostic_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "message": self.message,
            "recovery_action": self.recovery_action,
            "severity": self.severity,
            "retryability": self.retryability,
            "subsystem": self.subsystem,
            "engine_code": self.engine_code or None,
            "context": self.context,
        }

    @classmethod
    def from_definition(
        cls,
        definition: StructuredErrorDefinition,
        *,
        message: str,
        subsystem: str,
        context: dict[str, Any] | None = None,
        engine_code: str = "",
    ) -> StructuredErrorReport:
        return cls(
            code=definition.code,
            title=definition.title,
            message=message or definition.explanation,
            recovery_action=definition.recovery_action,
            severity=definition.severity.value,
            retryability=definition.retryability.value,
            subsystem=subsystem,
            context=dict(context or {}),
            engine_code=engine_code,
        )


@dataclass
class EvaluationLimitationReport:
    code: str
    title: str
    explanation: str
    user_guidance: str
    verdict: str = ""
    coverage_class: str = ""

    def to_diagnostic_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "explanation": self.explanation,
            "user_guidance": self.user_guidance,
            "verdict": self.verdict or None,
            "coverage_class": self.coverage_class or None,
            "kind": "evaluation_limitation",
        }

    @classmethod
    def from_definition(
        cls,
        definition: EvaluationLimitationDefinition,
        *,
        verdict: str = "",
        coverage_class: str = "",
    ) -> EvaluationLimitationReport:
        return cls(
            code=definition.code,
            title=definition.title,
            explanation=definition.explanation,
            user_guidance=definition.user_guidance,
            verdict=verdict,
            coverage_class=coverage_class,
        )


class ErrorContextStore:
    """Session-local last error and last evaluation limitation."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._last_error: StructuredErrorReport | None = None
        self._last_limitation: EvaluationLimitationReport | None = None

    @property
    def last_error(self) -> StructuredErrorReport | None:
        with self._lock:
            return self._last_error

    @property
    def last_limitation(self) -> EvaluationLimitationReport | None:
        with self._lock:
            return self._last_limitation

    def record_error(self, report: StructuredErrorReport) -> None:
        with self._lock:
            self._last_error = report

    def record_limitation(self, report: EvaluationLimitationReport) -> None:
        with self._lock:
            self._last_limitation = report

    def diagnostic_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "last_structured_error": self._last_error.to_diagnostic_dict() if self._last_error else None,
                "last_evaluation_limitation": (
                    self._last_limitation.to_diagnostic_dict() if self._last_limitation else None
                ),
            }
