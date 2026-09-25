from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErrorCategory(str, Enum):
    APPLICATION = "EL-APP"
    PATH_OF_BUILDING = "EL-POB"
    BUILD = "EL-BLD"
    ITEM_CHECK = "EL-CHK"
    WORKER = "EL-WRK"
    HOTKEY_CLIPBOARD = "EL-KEY"
    USER_INTERFACE = "EL-UI"
    UPDATE = "EL-UPD"
    DIAGNOSTICS = "EL-DIAG"


class ErrorSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Retryability(str, Enum):
    NONE = "none"
    USER_ACTION = "user_action"
    AUTOMATIC = "automatic"


@dataclass(frozen=True)
class StructuredErrorDefinition:
    code: str
    category: ErrorCategory
    severity: ErrorSeverity
    title: str
    explanation: str
    recovery_action: str
    retryability: Retryability
    diagnostic_fields: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "explanation": self.explanation,
            "recovery_action": self.recovery_action,
            "retryability": self.retryability.value,
            "diagnostic_fields": list(self.diagnostic_fields),
        }
