"""Bounded structured diagnostic event history."""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from threading import Lock
from typing import Any

from exilelens.diagnostics.constants import MAX_EVENT_BUFFER_ENTRIES, VERBOSE_DEFAULT_SECONDS
from exilelens.diagnostics.sanitize import sanitize_value

_SESSION_ID = uuid.uuid4().hex[:12]


@dataclass(frozen=True)
class DiagnosticEvent:
    ts: float
    category: str
    name: str
    detail: dict[str, Any] = field(default_factory=dict)
    verbose_only: bool = False

    def to_export_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "category": self.category,
            "name": self.name,
            "detail": sanitize_value(self.detail),
        }


class DiagnosticEventBuffer:
    def __init__(self, capacity: int = MAX_EVENT_BUFFER_ENTRIES) -> None:
        self._events: deque[DiagnosticEvent] = deque(maxlen=capacity)
        self._lock = Lock()

    def record(
        self,
        category: str,
        name: str,
        *,
        detail: dict[str, Any] | None = None,
        verbose_only: bool = False,
    ) -> None:
        event = DiagnosticEvent(
            ts=time.time(),
            category=str(category or "app")[:40],
            name=str(name or "event")[:80],
            detail=dict(detail or {}),
            verbose_only=bool(verbose_only),
        )
        with self._lock:
            self._events.append(event)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def snapshot(self, *, include_verbose: bool) -> list[DiagnosticEvent]:
        with self._lock:
            items = list(self._events)
        if include_verbose:
            return items
        return [event for event in items if not event.verbose_only]

    def export_records(self, *, include_verbose: bool, limit: int) -> list[dict[str, Any]]:
        items = self.snapshot(include_verbose=include_verbose)
        if len(items) > limit:
            items = items[-limit:]
        return [event.to_export_dict() for event in items]


_BUFFER = DiagnosticEventBuffer()


def support_session_id() -> str:
    return _SESSION_ID


def event_buffer() -> DiagnosticEventBuffer:
    return _BUFFER


def record_event(
    category: str,
    name: str,
    *,
    detail: dict[str, Any] | None = None,
    verbose_only: bool = False,
) -> None:
    _BUFFER.record(category, name, detail=detail, verbose_only=verbose_only)


def clear_event_history() -> None:
    _BUFFER.clear()


def verbose_mode_active(settings: Any) -> bool:
    until = float(getattr(settings, "diagnostic_verbose_until", 0.0) or 0.0)
    return until > time.time()


def enable_verbose_mode(settings: Any, *, seconds: int = VERBOSE_DEFAULT_SECONDS) -> float:
    until = time.time() + max(60, int(seconds))
    settings.diagnostic_verbose_until = until
    record_event("diagnostics", "verbose_enabled", detail={"seconds": seconds})
    return until


def disable_verbose_mode(settings: Any) -> None:
    settings.diagnostic_verbose_until = 0.0
    record_event("diagnostics", "verbose_disabled")


def expire_verbose_mode(settings: Any) -> bool:
    if not verbose_mode_active(settings):
        return False
    return True
