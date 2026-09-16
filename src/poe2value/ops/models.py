"""Shared result types for ExileLens operational checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class GateVerdict(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCKED = "BLOCKED"


class CompatibilityStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNVERIFIED = "UNVERIFIED"
    BROKEN = "BROKEN"


class MarketCompatStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class StageStatus(str, Enum):
    PASS = "PASS"
    DEGRADED = "DEGRADED"
    FAIL = "FAIL"
    NOT_CHECKED = "NOT_CHECKED"


class Severity(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class ImpactLevel(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class BuildSourceStatus(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    MISMATCH = "MISMATCH"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class CheckResult:
    name: str
    status: GateVerdict
    severity: Severity | None = None
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["severity"] = self.severity.value if self.severity else None
        return payload


def worst_verdict(statuses: list[GateVerdict]) -> GateVerdict:
    if GateVerdict.BLOCKED in statuses:
        return GateVerdict.BLOCKED
    if GateVerdict.WARN in statuses:
        return GateVerdict.WARN
    return GateVerdict.PASS
