"""TOOLTIP-PERF — opt-in latency instrumentation for the Item Check hot path.

Diagnostic only. Everything here is inert unless ``EXILELENS_TOOLTIP_PERF=1`` is
set in the environment, so the shipped hot path keeps its current behaviour and
pays at most one module-level boolean test per instrumented stage.

The clock is ``time.perf_counter`` (monotonic, highest available resolution).

One tooltip produces one ``TOOLTIP_PERF`` block in the log, e.g.::

    TOOLTIP_PERF request=41 run=warm
    hotkey_to_capture_start_ms=12.4
    clipboard_wait_ms=31.8
    ...
    total_ms=384.2

Stage names are free-form: a caller marks the end of a stage with
:meth:`TooltipPerfTrace.mark` and the trace records the delta since the previous
mark. ``note`` records a value measured elsewhere (for example the Lua-side
per-slot breakdown) without advancing the clock.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("exilelens.tooltip_perf")

_ENV_FLAG = "EXILELENS_TOOLTIP_PERF"


def perf_enabled() -> bool:
    """True when tooltip latency instrumentation is switched on."""
    return str(os.environ.get(_ENV_FLAG, "")).strip().lower() in {"1", "true", "yes", "on"}


class TooltipPerfTrace:
    """Stage timings for a single tooltip, from hotkey to painted overlay."""

    __slots__ = ("request_id", "run", "_t0", "_last", "_stages", "_notes", "_lock", "_closed")

    def __init__(self, *, request_id: int | None = None, run: str = "warm") -> None:
        now = time.perf_counter()
        self.request_id = request_id
        self.run = run
        self._t0 = now
        self._last = now
        self._stages: list[tuple[str, float]] = []
        self._notes: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._closed = False

    def mark(self, stage: str) -> float:
        """Close ``stage`` at the current instant and return its duration in ms."""
        now = time.perf_counter()
        with self._lock:
            elapsed_ms = (now - self._last) * 1000.0
            self._last = now
            self._stages.append((stage, elapsed_ms))
        return elapsed_ms

    def note(self, key: str, value: Any) -> None:
        """Record a value measured elsewhere without advancing the stage clock."""
        with self._lock:
            self._notes[key] = value

    def add(self, key: str, ms: float) -> None:
        """Accumulate into a named note (used for per-slot sums)."""
        with self._lock:
            self._notes[key] = round(float(self._notes.get(key, 0.0)) + float(ms), 2)

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0

    def set_request_id(self, request_id: int) -> None:
        self.request_id = int(request_id)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            payload: dict[str, Any] = {f"{name}_ms": round(ms, 2) for name, ms in self._stages}
            payload.update(self._notes)
            payload["total_ms"] = round(self.total_ms, 2)
            return payload

    def render(self) -> str:
        payload = self.to_dict()
        head = f"TOOLTIP_PERF request={self.request_id if self.request_id is not None else '-'} run={self.run}"
        lines = [head]
        total = payload.pop("total_ms", 0.0)
        for key in sorted(payload):
            lines.append(f"{key}={payload[key]}")
        lines.append(f"total_ms={total}")
        return "\n".join(lines)

    def emit(self) -> None:
        """Log the block once. Safe to call more than once; later calls are ignored."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        logger.info("%s", self.render())


class _NullTrace(TooltipPerfTrace):
    """Zero-work stand-in used when instrumentation is off."""

    __slots__ = ()

    def mark(self, stage: str) -> float:  # noqa: D102 - inert
        return 0.0

    def note(self, key: str, value: Any) -> None:  # noqa: D102 - inert
        return

    def add(self, key: str, ms: float) -> None:  # noqa: D102 - inert
        return

    def emit(self) -> None:  # noqa: D102 - inert
        return


NULL_TRACE = _NullTrace()


def new_trace(*, request_id: int | None = None, run: str = "warm") -> TooltipPerfTrace:
    """A real trace when instrumentation is enabled, otherwise the inert one."""
    if not perf_enabled():
        return NULL_TRACE
    return TooltipPerfTrace(request_id=request_id, run=run)
