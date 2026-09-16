from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class StallKind(str, Enum):
    NONE = "none"
    GUI = "gui"
    POB = "pob"
    QUEUE = "queue"
    CLIPBOARD = "clipboard"
    OVERLAY = "overlay"


@dataclass
class HeartbeatState:
    last_gui_tick_ms: float = field(default_factory=lambda: time.perf_counter() * 1000)
    last_clipboard_ms: float = 0.0
    last_eval_started_ms: float = 0.0
    last_eval_finished_ms: float = 0.0
    active_request_id: int | None = None
    pending_request_id: int | None = None
    stall_kind: StallKind = StallKind.NONE
    stall_since_ms: float = 0.0

    def touch_gui(self) -> None:
        self.last_gui_tick_ms = time.perf_counter() * 1000
        if self.stall_kind == StallKind.GUI:
            self.stall_kind = StallKind.NONE

    def note_clipboard(self) -> None:
        self.last_clipboard_ms = time.perf_counter() * 1000

    def note_eval_started(self, request_id: int) -> None:
        self.active_request_id = request_id
        self.last_eval_started_ms = time.perf_counter() * 1000
        if self.stall_kind == StallKind.POB:
            self.stall_kind = StallKind.NONE

    def note_eval_finished(self, request_id: int) -> None:
        self.last_eval_finished_ms = time.perf_counter() * 1000
        if self.active_request_id == request_id:
            self.active_request_id = None
        if self.stall_kind == StallKind.POB:
            self.stall_kind = StallKind.NONE

    def note_pending(self, request_id: int | None) -> None:
        self.pending_request_id = request_id

    def detect_stall(
        self,
        *,
        gui_stall_ms: float = 3000,
        pob_stall_ms: float = 120_000,
        now_ms: float | None = None,
    ) -> StallKind:
        now = now_ms if now_ms is not None else time.perf_counter() * 1000
        if self.active_request_id is not None:
            elapsed = now - self.last_eval_started_ms
            if elapsed > pob_stall_ms:
                self.stall_kind = StallKind.POB
                self.stall_since_ms = now
                return StallKind.POB
        if now - self.last_gui_tick_ms > gui_stall_ms:
            self.stall_kind = StallKind.GUI
            self.stall_since_ms = now
            return StallKind.GUI
        self.stall_kind = StallKind.NONE
        return StallKind.NONE
