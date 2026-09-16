"""Item Check tooltip lifecycle diagnostics and watchdog."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# Measured PoB worker cold eval is ~15–25s; allow headroom for multi-slot items.
# User-visible timeout is much shorter and starts after the worker is ready.
ITEM_CHECK_WATCHDOG_MS = 90_000
ITEM_CHECK_USER_TIMEOUT_MS = 4_000


class OverlayUiState(str, Enum):
    IDLE = "IDLE"
    CAPTURING = "CAPTURING"
    WARMING = "WARMING"
    ANALYZING = "ANALYZING"
    READY = "READY"
    PARTIAL = "PARTIAL"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


class ItemCheckPhase(str, Enum):
    RECEIVED = "ITEM_CHECK_RECEIVED"
    RECOGNIZED = "ITEM_CHECK_RECOGNIZED"
    FIRST_PAINT = "ITEM_CHECK_FIRST_PAINT"
    EVAL_STARTED = "ITEM_CHECK_EVAL_STARTED"
    EVAL_FINISHED = "ITEM_CHECK_EVAL_FINISHED"
    PRESENTATION_BUILT = "ITEM_CHECK_PRESENTATION_BUILT"
    TERMINAL_PAINT = "ITEM_CHECK_TERMINAL_PAINT"
    ERROR = "ITEM_CHECK_ERROR"
    SUPERSEDED = "ITEM_CHECK_SUPERSEDED"
    CANCELLED = "ITEM_CHECK_CANCELLED"
    WATCHDOG = "ITEM_CHECK_WATCHDOG"
    SLOW = "ITEM_CHECK_SLOW"
    TIMEOUT = "ITEM_CHECK_TIMEOUT"


TERMINAL_PHASES = frozenset(
    {
        ItemCheckPhase.TERMINAL_PAINT,
        ItemCheckPhase.ERROR,
        ItemCheckPhase.SUPERSEDED,
        ItemCheckPhase.CANCELLED,
        ItemCheckPhase.WATCHDOG,
        ItemCheckPhase.TIMEOUT,
    }
)


@dataclass
class ItemCheckTrack:
    request_id: int
    received_ms: float = field(default_factory=lambda: time.perf_counter() * 1000)
    phase: ItemCheckPhase = ItemCheckPhase.RECEIVED
    item_class: str = ""
    slot: str = ""
    content_hash: str = ""
    terminal: bool = False
    error_message: str = ""

    def elapsed_ms(self) -> float:
        return max(0.0, time.perf_counter() * 1000 - self.received_ms)


def log_item_check(
    phase: ItemCheckPhase,
    *,
    request_id: int,
    item_class: str = "",
    slot: str = "",
    elapsed_ms: float | None = None,
    **extra: Any,
) -> None:
    payload: dict[str, Any] = {
        "phase": phase.value,
        "request_id": request_id,
        "item_class": item_class or None,
        "slot": slot or None,
    }
    if elapsed_ms is not None:
        payload["elapsed_ms"] = round(elapsed_ms, 1)
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    logger.info("item_check_lifecycle %s", payload)


class ItemCheckLifecycleRegistry:
    def __init__(self) -> None:
        self._tracks: dict[int, ItemCheckTrack] = {}

    def begin(self, request_id: int, *, content_hash: str = "", item_class: str = "") -> ItemCheckTrack:
        track = ItemCheckTrack(request_id=request_id, content_hash=content_hash, item_class=item_class)
        self._tracks[request_id] = track
        log_item_check(ItemCheckPhase.RECEIVED, request_id=request_id, item_class=item_class, content_hash=content_hash)
        return track

    def advance(
        self,
        request_id: int,
        phase: ItemCheckPhase,
        *,
        item_class: str = "",
        slot: str = "",
        **extra: Any,
    ) -> None:
        track = self._tracks.get(request_id)
        if track is None:
            track = ItemCheckTrack(request_id=request_id)
            self._tracks[request_id] = track
        track.phase = phase
        if item_class:
            track.item_class = item_class
        if slot:
            track.slot = slot
        if phase in TERMINAL_PHASES:
            track.terminal = True
        log_item_check(
            phase,
            request_id=request_id,
            item_class=track.item_class,
            slot=track.slot,
            elapsed_ms=track.elapsed_ms(),
            **extra,
        )

    def mark_error(self, request_id: int, message: str, **extra: Any) -> None:
        track = self._tracks.get(request_id)
        if track is not None:
            track.error_message = message
            track.terminal = True
            track.phase = ItemCheckPhase.ERROR
        log_item_check(
            ItemCheckPhase.ERROR,
            request_id=request_id,
            item_class=(track.item_class if track else ""),
            slot=(track.slot if track else ""),
            elapsed_ms=(track.elapsed_ms() if track else None),
            message=message,
            **extra,
        )

    def track(self, request_id: int) -> ItemCheckTrack | None:
        return self._tracks.get(request_id)

    def is_terminal(self, request_id: int) -> bool:
        track = self._tracks.get(request_id)
        return bool(track and track.terminal)

    def clear(self, request_id: int) -> None:
        self._tracks.pop(request_id, None)

    def unfinished_ids(self) -> list[int]:
        return sorted(request_id for request_id, track in self._tracks.items() if not track.terminal)
