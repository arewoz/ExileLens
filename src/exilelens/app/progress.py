from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from PySide6.QtCore import QObject, Signal


class OperationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INDETERMINATE = "indeterminate"


@dataclass
class OperationProgress:
    operation_id: str
    module: str
    title: str
    phase: str = ""
    completed: int | None = None
    total: int | None = None
    fraction: float | None = None
    status: OperationStatus = OperationStatus.RUNNING
    cancellable: bool = False
    started_at: float = field(default_factory=time.perf_counter)
    detail: str = ""

    @property
    def elapsed_s(self) -> float:
        return max(0.0, time.perf_counter() - self.started_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "module": self.module,
            "title": self.title,
            "phase": self.phase,
            "completed": self.completed,
            "total": self.total,
            "fraction": self.fraction,
            "status": self.status.value,
            "cancellable": self.cancellable,
            "elapsed_s": round(self.elapsed_s, 2),
            "detail": self.detail,
        }


def progress_from_payload(payload: dict[str, Any], *, module: str, title: str) -> OperationProgress:
    """Normalize legacy on_progress dicts from market/tree/gear pipelines."""
    completed = payload.get("completed")
    total = payload.get("total")
    if completed is None and payload.get("index") is not None:
        completed = int(payload.get("index", 0)) + 1
    if total is None and payload.get("count") is not None:
        total = int(payload.get("count"))
    fraction: float | None = None
    status = OperationStatus.RUNNING
    if completed is not None and total is not None and int(total) > 0:
        fraction = min(1.0, max(0.0, int(completed) / int(total)))
    elif payload.get("indeterminate"):
        status = OperationStatus.INDETERMINATE
        fraction = None
    phase = str(payload.get("phase") or payload.get("stage") or "")
    detail = str(payload.get("detail") or payload.get("message") or "")
    return OperationProgress(
        operation_id=str(payload.get("operation_id") or uuid.uuid4().hex[:12]),
        module=module,
        title=title,
        phase=phase,
        completed=int(completed) if completed is not None else None,
        total=int(total) if total is not None else None,
        fraction=fraction,
        status=status,
        cancellable=bool(payload.get("cancellable")),
        detail=detail,
    )


class OperationProgressHub(QObject):
    """Global in-flight operation registry for Dashboard activity indicator."""

    progress_updated = Signal(object)
    progress_cleared = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._active: dict[str, OperationProgress] = {}

    @property
    def active_operations(self) -> list[OperationProgress]:
        return list(self._active.values())

    def has_active(self) -> bool:
        return bool(self._active)

    def begin(
        self,
        *,
        module: str,
        title: str,
        operation_id: str | None = None,
        cancellable: bool = False,
        phase: str = "",
    ) -> OperationProgress:
        op = OperationProgress(
            operation_id=operation_id or uuid.uuid4().hex[:12],
            module=module,
            title=title,
            phase=phase,
            cancellable=cancellable,
        )
        self._active[op.operation_id] = op
        self.progress_updated.emit(op.to_dict())
        return op

    def update(self, progress: OperationProgress) -> None:
        self._active[progress.operation_id] = progress
        self.progress_updated.emit(progress.to_dict())

    def update_from_payload(
        self,
        operation_id: str,
        payload: dict[str, Any],
        *,
        module: str,
        title: str,
    ) -> OperationProgress:
        progress = progress_from_payload(payload, module=module, title=title)
        progress.operation_id = operation_id
        return self._store(progress)

    def _store(self, progress: OperationProgress) -> OperationProgress:
        self._active[progress.operation_id] = progress
        self.progress_updated.emit(progress.to_dict())
        return progress

    def finish(
        self,
        operation_id: str,
        *,
        status: OperationStatus = OperationStatus.COMPLETE,
        detail: str = "",
    ) -> None:
        progress = self._active.pop(operation_id, None)
        if progress is None:
            return
        progress.status = status
        progress.detail = detail or progress.detail
        if progress.total and progress.completed is None:
            progress.completed = progress.total
            progress.fraction = 1.0
        self.progress_updated.emit(progress.to_dict())
        self.progress_cleared.emit(operation_id)

    def fail(self, operation_id: str, detail: str) -> None:
        self.finish(operation_id, status=OperationStatus.FAILED, detail=detail)

    def cancel(self, operation_id: str, detail: str = "Cancelled") -> None:
        self.finish(operation_id, status=OperationStatus.CANCELLED, detail=detail)

    def clear_all(self) -> None:
        ids = list(self._active.keys())
        self._active.clear()
        for op_id in ids:
            self.progress_cleared.emit(op_id)
