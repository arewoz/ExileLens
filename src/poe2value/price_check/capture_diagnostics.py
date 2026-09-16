from __future__ import annotations

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CapturePhase(str, Enum):
    HOTKEY_RECEIVED = "HOTKEY_RECEIVED"
    FOREGROUND_CHECK = "FOREGROUND_CHECK"
    HOTKEY_ACCEPTED = "HOTKEY_ACCEPTED"  # legacy alias
    WAITING_KEY_RELEASE = "WAITING_KEY_RELEASE"
    WAITING_FOR_RELEASE = "WAITING_FOR_RELEASE"  # legacy alias
    KEY_RELEASED = "KEY_RELEASED"
    BINDING_RELEASE_OBSERVED = "BINDING_RELEASE_OBSERVED"
    KEY_RELEASE_TIMEOUT = "KEY_RELEASE_TIMEOUT"
    RELEASE_TIMEOUT = "RELEASE_TIMEOUT"  # legacy alias
    KEY_RELEASE_STILL_HELD = "KEY_RELEASE_STILL_HELD"
    CHORD_STATE_RESET = "CHORD_STATE_RESET"
    FOREGROUND_OK = "FOREGROUND_OK"
    FOREGROUND_REJECTED = "FOREGROUND_REJECTED"
    FOREGROUND_RECHECK = "FOREGROUND_RECHECK"
    FOREGROUND_LOST_DURING_RELEASE = "FOREGROUND_LOST_DURING_RELEASE"
    CAPTURE_SESSION_CREATED = "CAPTURE_SESSION_CREATED"
    CAPTURE_STARTED = "CAPTURE_STARTED"  # legacy alias
    SEQUENCE_BEFORE = "SEQUENCE_BEFORE"
    SEQUENCE_AFTER = "SEQUENCE_AFTER"
    SENDINPUT_REQUESTED = "SENDINPUT_REQUESTED"
    SENDINPUT_ACCEPTED = "SENDINPUT_ACCEPTED"
    SENDINPUT_REJECTED = "SENDINPUT_REJECTED"
    SENDINPUT_PARTIAL = "SENDINPUT_PARTIAL"
    MODIFIER_STILL_DOWN = "MODIFIER_STILL_DOWN"
    CLIPBOARD_EVENT = "CLIPBOARD_EVENT"
    CLIPBOARD_EVENT_OWNED = "CLIPBOARD_EVENT_OWNED"
    CLIPBOARD_EVENT_DEDUPED = "CLIPBOARD_EVENT_DEDUPED"
    CLIPBOARD_EVENT_NOT_OWNED = "CLIPBOARD_EVENT_NOT_OWNED"
    CLIPBOARD_POLL = "CLIPBOARD_POLL"
    CLIPBOARD_TIMEOUT = "CLIPBOARD_TIMEOUT"
    ITEM_RECOGNIZED = "ITEM_RECOGNIZED"
    NON_ITEM_CLIPBOARD = "NON_ITEM_CLIPBOARD"
    PRICE_CHECK_SUBMITTED = "PRICE_CHECK_SUBMITTED"
    CAPTURE_SUCCESS = "CAPTURE_SUCCESS"
    CAPTURE_RESET_IDLE = "CAPTURE_RESET_IDLE"
    SESSION_RESET = "SESSION_RESET"
    SESSION_ALREADY_ACTIVE = "SESSION_ALREADY_ACTIVE"
    SESSION_STALE = "SESSION_STALE"
    SESSION_CANCELLED = "SESSION_CANCELLED"
    CAPTURE_FAILURE_TERMINAL = "CAPTURE_FAILURE_TERMINAL"
    # MARKET-01B9 result -> window trail
    PRICE_CHECK_RESULT_READY = "PRICE_CHECK_RESULT_READY"
    PRESENTATION_BUILT = "PRESENTATION_BUILT"
    OVERLAY_SHOW_CALLED = "OVERLAY_SHOW_CALLED"
    OVERLAY_VISIBLE_AFTER_SHOW = "OVERLAY_VISIBLE_AFTER_SHOW"
    OVERLAY_SUPPRESSED = "OVERLAY_SUPPRESSED"


class CaptureFailureReason(str, Enum):
    NOT_POE_FOREGROUND = "not_poe_foreground"
    POE_NOT_FOREGROUND = "poe_not_foreground"
    FOREGROUND_FAIL = "FOREGROUND_FAIL"
    OVERLAY_APP_FOREGROUND = "overlay_app_foreground"
    FOREGROUND_LOST_BEFORE_SENDINPUT = "foreground_lost_before_sendinput"
    FOREGROUND_LOST_DURING_RELEASE = "foreground_lost_during_release"
    KEY_RELEASE_TIMEOUT = "key_release_timeout"
    KEY_RELEASE_FAIL = "KEY_RELEASE_FAIL"
    SENDINPUT_REJECTED = "sendinput_rejected"
    SENDINPUT_FAIL = "SENDINPUT_FAIL"
    SENDINPUT_PARTIAL = "sendinput_partial"
    MODIFIER_STILL_DOWN = "modifier_still_down"
    CLIPBOARD_TIMEOUT = "clipboard_timeout"
    CLIPBOARD_SEQUENCE_DID_NOT_ADVANCE = "CLIPBOARD_SEQUENCE_DID_NOT_ADVANCE"
    NON_ITEM_CLIPBOARD = "non_item_clipboard"
    SESSION_CANCELLED = "session_cancelled"


def log_capture_phase(phase: CapturePhase, **fields: Any) -> None:
    payload = {"phase": phase.value, **fields}
    logger.info("price_check_capture %s", payload)


def log_capture_failure_terminal(
    *,
    capture_id: int,
    failure_reason: str,
    sequence_before: int | None = None,
    sequence_after: int | None = None,
    clipboard_text_len: int | None = None,
    clipboard_read: bool | None = None,
    item_recognized: bool | None = None,
    sendinput_inserted: int | None = None,
    key_release_status: str | None = None,
    **extra: Any,
) -> None:
    """Single terminal log line for owner failure triage (capture path only)."""
    log_capture_phase(
        CapturePhase.CAPTURE_FAILURE_TERMINAL,
        capture_id=capture_id,
        failure_reason=failure_reason,
        terminal_failure_code=failure_reason,
        sequence_before=sequence_before,
        sequence_after=sequence_after,
        clipboard_text_len=clipboard_text_len,
        clipboard_read=clipboard_read,
        item_recognized=item_recognized,
        sendinput_inserted=sendinput_inserted,
        key_release_status=key_release_status,
        **extra,
    )
