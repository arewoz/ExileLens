from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CaptureStatus(str, Enum):
    PENDING = "pending"
    CAPTURED = "captured"
    TIMEOUT = "timeout"
    FAILED = "failed"
    CANCELLED = "cancelled"
    POE_INACTIVE = "poe_inactive"


class SessionLifecycle(str, Enum):
    """Coordinator lifecycle — must return to IDLE after every terminal path."""

    IDLE = "idle"
    WAITING_CLIPBOARD = "waiting_clipboard"
    CONSUMED = "consumed"


@dataclass
class PriceCheckCaptureSession:
    """Single owner for one Shift+C hover-copy attempt."""

    session_id: int
    start_sequence: int
    deadline_monotonic: float
    anchor_screen_px: tuple[int, int]
    authorized_hwnd: int
    authorized_pid: int
    expected_trigger: str = "shift_c"
    captured_sequence: int | None = None
    consumed: bool = False
    status: CaptureStatus = CaptureStatus.PENDING
    lifecycle: SessionLifecycle = SessionLifecycle.WAITING_CLIPBOARD

    def is_pending(self) -> bool:
        return (
            self.lifecycle == SessionLifecycle.WAITING_CLIPBOARD
            and self.status == CaptureStatus.PENDING
            and not self.consumed
        )

    def is_idle_equivalent(self) -> bool:
        return self.consumed or self.lifecycle in {SessionLifecycle.IDLE, SessionLifecycle.CONSUMED}

    def is_expired(self, now: float | None = None) -> bool:
        if not self.is_pending():
            return False
        current = now if now is not None else time.monotonic()
        return current >= self.deadline_monotonic

    def owns_clipboard_sequence(self, sequence: int | None) -> bool:
        if not self.is_pending() or sequence is None:
            return False
        return int(sequence) > int(self.start_sequence)

    def should_suppress_gameplay(self, sequence: int | None) -> bool:
        """While pending, suppress gameplay until session resolves."""
        return self.is_pending()

    def mark_captured(self, sequence: int | None) -> None:
        self.captured_sequence = sequence
        self.consumed = True
        self.status = CaptureStatus.CAPTURED
        self.lifecycle = SessionLifecycle.CONSUMED

    def mark_timeout(self) -> None:
        self.consumed = True
        self.status = CaptureStatus.TIMEOUT
        self.lifecycle = SessionLifecycle.CONSUMED

    def mark_failed(self) -> None:
        self.consumed = True
        self.status = CaptureStatus.FAILED
        self.lifecycle = SessionLifecycle.CONSUMED

    def mark_cancelled(self) -> None:
        self.consumed = True
        self.status = CaptureStatus.CANCELLED
        self.lifecycle = SessionLifecycle.CONSUMED

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "start_sequence": self.start_sequence,
            "deadline_monotonic": self.deadline_monotonic,
            "anchor_screen_px": self.anchor_screen_px,
            "authorized_hwnd": self.authorized_hwnd,
            "authorized_pid": self.authorized_pid,
            "expected_trigger": self.expected_trigger,
            "captured_sequence": self.captured_sequence,
            "consumed": self.consumed,
            "status": self.status.value,
            "lifecycle": self.lifecycle.value,
        }
