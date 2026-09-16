from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

T = TypeVar("T")

KIND_PRIORITY = {
    "gameplay": 100,
    "price_check": 90,
    "baseline": 95,
    "tree_node": 80,
    "tree_visible": 70,
    "tree_frontier": 60,
    "tree_nearby": 50,
    "market_capture": 45,
    "analysis": 40,
    "market": 38,
    "market_capture_ideal": 37,
    "gear": 36,
    "upgrade_path": 22,
    "build_decomp": 20,
}


@dataclass
class SchedulerMetrics:
    submitted: int = 0
    started: int = 0
    completed: int = 0
    superseded: int = 0
    dropped_non_item: int = 0
    cancelled_queued: int = 0


def _same_request(left: object, right: object) -> bool:
    left_id = getattr(left, "request_id", None)
    right_id = getattr(right, "request_id", None)
    if left_id is not None and right_id is not None:
        return left_id == right_id
    return left is right


def request_kind(request: object) -> str:
    return str(getattr(request, "kind", None) or "gameplay")


def request_priority(request: object) -> int:
    explicit = getattr(request, "priority", None)
    if isinstance(explicit, int) and explicit > 0:
        return explicit
    return KIND_PRIORITY.get(request_kind(request), 40)


def _is_preempting(kind: str) -> bool:
    return kind in {"gameplay", "baseline"}


def _is_analysis_like(request: object) -> bool:
    return request_kind(request) not in {"gameplay", "baseline"}


class BoundedEvaluationScheduler(Generic[T]):
    """Single-owner PoB lane: max one active mutation.

    Gameplay (Ctrl+C) always outranks long-running analysis. An in-flight
    analysis is never torn down mid-PoB mutation; the worker yields between
    transactions, then higher-priority work runs.

    Priority:
    1. gameplay Ctrl+C
    2. baseline reload
    3. explicit node
    4. visible-area tree
    5. remaining frontier
    6. nearby / Analyze Build
    """

    def __init__(self, on_start: Callable[[T], None]) -> None:
        self._on_start = on_start
        self._active: T | None = None
        self._queue: list[T] = []
        self.yield_requested = False
        self.metrics = SchedulerMetrics()

    @property
    def active(self) -> T | None:
        return self._active

    @property
    def pending(self) -> T | None:
        return self._queue[0] if self._queue else None

    @property
    def queued(self) -> tuple[T, ...]:
        return tuple(self._queue)

    @property
    def is_busy(self) -> bool:
        return self._active is not None

    def submit(self, request: T) -> bool:
        kind = request_kind(request)
        self.metrics.submitted += 1
        if self._active is None:
            self._start(request)
            return True
        if _is_preempting(kind) and _is_analysis_like(self._active):
            self.yield_requested = True
        if kind == "gameplay":
            self._queue = [item for item in self._queue if request_kind(item) != "gameplay"]
            self.metrics.superseded += 1
        elif kind == "baseline":
            self._queue = [item for item in self._queue if request_kind(item) != "baseline"]
            self.metrics.superseded += 1
        else:
            self.metrics.superseded += 1
        self._queue.append(request)
        self._queue.sort(key=request_priority, reverse=True)
        return True

    def complete(self, request: T) -> None:
        active = self._active
        if active is not None and (active is request or _same_request(active, request)):
            self._active = None
            self.metrics.completed += 1
            self.yield_requested = False
            nxt = self._pop_next()
            if nxt is not None:
                self._start(nxt)
            return
        self._queue = [item for item in self._queue if not (item is request or _same_request(item, request))]

    def complete_by_id(self, request_id: int) -> None:
        active = self._active
        if active is not None and getattr(active, "request_id", None) == request_id:
            self.complete(active)
            return
        self._queue = [item for item in self._queue if getattr(item, "request_id", None) != request_id]

    def discard_pending(self) -> None:
        self._queue.clear()

    def discard_queued_upgrade_path(self) -> int:
        kept: list[T] = []
        dropped = 0
        for item in self._queue:
            if request_kind(item) in {"upgrade_path", "build_decomp"}:
                dropped += 1
            else:
                kept.append(item)
        self._queue = kept
        self.metrics.cancelled_queued += dropped
        return dropped

    def discard_queued_analysis(self) -> int:
        """Drop queued tree/analyze work. Never interrupt the active restore."""
        kept: list[T] = []
        dropped = 0
        for item in self._queue:
            if request_kind(item) in {"gameplay", "baseline"}:
                kept.append(item)
            else:
                dropped += 1
        self._queue = kept
        self.metrics.cancelled_queued += dropped
        return dropped

    def _pop_next(self) -> T | None:
        if not self._queue:
            return None
        return self._queue.pop(0)

    def _start(self, request: T) -> None:
        self._active = request
        self.metrics.started += 1
        self._on_start(request)
