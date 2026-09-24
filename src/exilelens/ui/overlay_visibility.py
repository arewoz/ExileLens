"""Explicit visibility lifecycle for ExileLens overlay windows.

An ExileLens overlay may become visible only because of an ExileLens-owned show
command. A live HWND, a topmost refresh, a foreground change, or a late worker
result are *not* show commands: after a dismissal they must repaint nothing.

The state lives here, separate from Qt, so the invariant is unit-testable without
a window server.
"""

from __future__ import annotations

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class OverlayLifecycleState(str, Enum):
    CLOSED = "CLOSED"
    VISIBLE = "VISIBLE"
    HIDING = "HIDING"


class OverlayShowReason(str, Enum):
    """Why something wants the overlay on screen.

    EXPLICIT_* reasons are ExileLens-owned show commands and may open a closed
    overlay. Every other reason is a continuation of an already-open overlay and
    may only repaint one that is still requested-visible.
    """

    EXPLICIT_ITEM_CHECK = "item_check_hotkey"
    EXPLICIT_ITEM_CHECK_WARMING = "item_check_hotkey_warming"
    EXPLICIT_PRICE_CHECK = "price_check_hotkey"
    EXPLICIT_UI_ACTION = "ui_action"

    RESULT_READY = "result_ready"
    RESULT_RESCORED = "result_rescored"
    USER_TIMEOUT = "user_timeout"
    EVALUATION_ERROR = "evaluation_error"
    LAYOUT_REFRESH = "layout_refresh"
    TOPMOST_REFRESH = "topmost_refresh"
    FOREGROUND_CHANGED = "foreground_changed"


EXPLICIT_SHOW_REASONS = frozenset(
    {
        OverlayShowReason.EXPLICIT_ITEM_CHECK,
        OverlayShowReason.EXPLICIT_ITEM_CHECK_WARMING,
        OverlayShowReason.EXPLICIT_PRICE_CHECK,
        OverlayShowReason.EXPLICIT_UI_ACTION,
    }
)


class OverlayHideReason(str, Enum):
    CLOSE_BUTTON = "close_button"
    CLICK_THROUGH = "click_through"
    ESCAPE = "escape"
    AUTO_HIDE = "auto_hide"
    PRESENTATION_INVALIDATED = "presentation_invalidated"
    OVERLAY_DISABLED = "overlay_disabled"
    SHUTDOWN = "shutdown"


class OverlayVisibilityState:
    """`requested_visible` is the single source of truth for "logically open"."""

    def __init__(self) -> None:
        self._requested_visible = False
        self._state = OverlayLifecycleState.CLOSED
        self._show_reason: OverlayShowReason | None = None
        self._hide_reason: OverlayHideReason | None = None
        # True from the moment the user dismisses until the next explicit ExileLens
        # show command. While set, no continuation may put the window back up.
        self._dismissed = False
        # Highest request id covered by a dismissal, for diagnostics.
        self._dismissed_through_request_id = -1

    @property
    def requested_visible(self) -> bool:
        return self._requested_visible

    @property
    def state(self) -> OverlayLifecycleState:
        return self._state

    @property
    def show_reason(self) -> OverlayShowReason | None:
        return self._show_reason

    @property
    def hide_reason(self) -> OverlayHideReason | None:
        return self._hide_reason

    @property
    def dismissed(self) -> bool:
        """Dismissed and not yet reopened by an explicit ExileLens show command."""
        return self._dismissed

    @property
    def dismissed_through_request_id(self) -> int:
        return self._dismissed_through_request_id

    def allows_show(self, reason: OverlayShowReason, request_id: int = -1) -> bool:
        """Decide a show request without mutating state.

        Only an ExileLens-owned show command may open a closed overlay. Every
        other reason — a late worker result, a user timeout, a rescore, a layout
        refresh — is a continuation and needs an overlay that is still open. The
        request id is not an escape hatch: a newer in-flight request whose own
        explicit paint never ran must not resurrect a dismissed window.
        """
        del request_id
        if reason in EXPLICIT_SHOW_REASONS:
            return True
        if self._requested_visible:
            return True
        # Idle-but-never-dismissed is the app's normal starting state: the first
        # paint of a session may open the window. Once the user has dismissed,
        # only an explicit ExileLens show command may open it again.
        return not self._dismissed

    def request_show(self, reason: OverlayShowReason, request_id: int = -1) -> bool:
        """Return True when the caller may actually put the window on screen."""
        logger.info(
            "overlay_show_requested reason=%s request_id=%s requested_visible=%s",
            reason.value,
            request_id,
            self._requested_visible,
        )
        if not self.allows_show(reason, request_id):
            logger.info(
                "overlay_show_suppressed reason=%s request_id=%s state=%s hide_reason=%s",
                reason.value,
                request_id,
                self._state.value,
                self._hide_reason.value if self._hide_reason else None,
            )
            return False
        self._requested_visible = True
        self._state = OverlayLifecycleState.VISIBLE
        self._show_reason = reason
        self._hide_reason = None
        if reason in EXPLICIT_SHOW_REASONS:
            self._dismissed = False
        logger.info("overlay_actual_show reason=%s request_id=%s", reason.value, request_id)
        return True

    def authorize(self, reason: OverlayShowReason, request_id: int = -1) -> None:
        """Arm a new ExileLens-owned session without putting anything on screen.

        Called when a capture ExileLens owns starts. It clears the dismissal latch
        so the paints belonging to *that* session may open the window, even if the
        session's own first paint is skipped. It never shows anything by itself.
        """
        if reason not in EXPLICIT_SHOW_REASONS:
            raise ValueError(f"{reason} is not an ExileLens-owned show command")
        logger.info(
            "overlay_show_authorized reason=%s request_id=%s", reason.value, request_id
        )
        self._dismissed = False

    def request_hide(self, reason: OverlayHideReason, request_id: int = -1) -> None:
        logger.info("overlay_hide_requested reason=%s request_id=%s", reason.value, request_id)
        self._state = OverlayLifecycleState.HIDING
        self._requested_visible = False
        self._hide_reason = reason
        self._show_reason = None
        self._dismissed = True
        if int(request_id) > self._dismissed_through_request_id:
            self._dismissed_through_request_id = int(request_id)
        self._state = OverlayLifecycleState.CLOSED
        logger.info("overlay_actual_hide reason=%s request_id=%s", reason.value, request_id)

    def snapshot(self) -> dict[str, object]:
        return {
            "requested_visible": self._requested_visible,
            "state": self._state.value,
            "show_reason": self._show_reason.value if self._show_reason else None,
            "hide_reason": self._hide_reason.value if self._hide_reason else None,
            "dismissed": self._dismissed,
            "dismissed_through_request_id": self._dismissed_through_request_id,
        }
