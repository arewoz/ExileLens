from __future__ import annotations

import time
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from exilelens.items.recognition import recognize_input
from exilelens.items.raw_input import RawItemInput
from exilelens.platform.windows.clipboard_identity import (
    read_clipboard_sequence_number,
    read_clipboard_text,
)
from exilelens.platform.windows.foreground_info import evaluate_poe_foreground_match, is_poe_foreground
from exilelens.platform.windows.send_input import SendInputResult, send_ctrl_c_to_foreground
from exilelens.price_check.capture_diagnostics import (
    CaptureFailureReason,
    CapturePhase,
    log_capture_failure_terminal,
    log_capture_phase,
)
from exilelens.price_check.capture_session import CaptureStatus, PriceCheckCaptureSession, SessionLifecycle

SendCopyFn = Callable[[], bool | SendInputResult]
ReadSequenceFn = Callable[[], int | None]
ReadTextFn = Callable[[], str]
IsPoeForegroundFn = Callable[[], bool]
ForegroundMatchFn = Callable[[], dict[str, Any]]

CLIPBOARD_POLL_MS = 20
# PERF-01: PoE2 usually answers the synthetic Ctrl+C within a few ms, but the poll
# timer's first tick only landed at CLIPBOARD_POLL_MS, costing ~10 ms on average.
# Poll finely across the window where the answer normally arrives, then fall back to
# the original interval so a slow game does not get polled hard for 600 ms.
CLIPBOARD_FAST_POLL_MS = 4
CLIPBOARD_FAST_POLL_TICKS = 4
_POE_FOREGROUND_REQUIRED_MESSAGE = "Path of Exile 2 must be active."


class PriceCheckCaptureCoordinator(QObject):
    """Owns Shift+C Item Check capture and its synthetic clipboard event."""

    capture_started = Signal(int)
    capture_ready = Signal(int, str, object, object)  # request_id, text, anchor, sequence
    capture_failed = Signal(int, str)  # request_id, message

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        timeout_ms: int = 600,
        send_copy: SendCopyFn | None = None,
        read_sequence: ReadSequenceFn | None = None,
        read_text: ReadTextFn | None = None,
        is_poe_foreground_fn: IsPoeForegroundFn | None = None,
        foreground_match_fn: ForegroundMatchFn | None = None,
    ) -> None:
        super().__init__(parent)
        self._timeout_ms = max(100, int(timeout_ms))
        self._send_copy = send_copy or send_ctrl_c_to_foreground
        self._read_sequence = read_sequence or read_clipboard_sequence_number
        self._read_text = read_text or read_clipboard_text
        self._is_poe_foreground = is_poe_foreground_fn or is_poe_foreground
        self._foreground_match_fn = foreground_match_fn
        self._session: PriceCheckCaptureSession | None = None
        self._request_id = 0
        self._completed_sequences: dict[int, tuple[int, int | None]] = {}
        self._hotkey_consumed_sequences: list[int] = []
        self._max_hotkey_consumed_sequences = 64
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(CLIPBOARD_POLL_MS)
        self._poll_timer.timeout.connect(self._poll_clipboard_sequence)
        self._fast_polls_left = 0

    @property
    def active_session(self) -> PriceCheckCaptureSession | None:
        return self._session

    @property
    def has_pending_session(self) -> bool:
        return self._session is not None and self._session.is_pending()

    @property
    def is_idle(self) -> bool:
        return self._session is None

    @property
    def completed_sequences(self) -> dict[int, tuple[int, int | None]]:
        return self._completed_sequences

    def mark_hotkey_consumed_sequence(self, sequence: int | None) -> None:
        """Remember sequences consumed by owned Shift+C capture."""
        if sequence is None:
            return
        seq = int(sequence)
        if seq in self._hotkey_consumed_sequences:
            return
        self._hotkey_consumed_sequences.append(seq)
        overflow = len(self._hotkey_consumed_sequences) - self._max_hotkey_consumed_sequences
        if overflow > 0:
            self._hotkey_consumed_sequences = self._hotkey_consumed_sequences[overflow:]

    def is_hotkey_owned_sequence(self, sequence: int | None) -> bool:
        """True when a pending or recently completed Shift+C capture owns this sequence."""
        if sequence is None:
            return False
        if self._session is not None and self._session.is_pending() and not self._session.is_expired():
            return int(sequence) > int(self._session.start_sequence)
        return int(sequence) in self._hotkey_consumed_sequences

    def begin_capture(self, anchor_screen_px: tuple[int, int], *, request_id: int | None = None) -> int | None:
        poe_match = self._foreground_match()
        log_capture_phase(
            CapturePhase.FOREGROUND_CHECK,
            capture_id=request_id,
            current_hwnd=poe_match.get("current_hwnd"),
            current_pid=poe_match.get("current_pid"),
            current_process_name=poe_match.get("current_process_name"),
            current_window_title=poe_match.get("current_window_title"),
            poe_match_result=poe_match.get("poe_match_result"),
        )
        identity = self._authorized_identity(poe_match)
        if identity is None:
            log_capture_phase(
                CapturePhase.FOREGROUND_REJECTED,
                capture_id=request_id,
                failure_reason=CaptureFailureReason.POE_NOT_FOREGROUND.value,
                current_hwnd=poe_match.get("current_hwnd"),
                current_pid=poe_match.get("current_pid"),
                current_process_name=poe_match.get("current_process_name"),
                current_window_title=poe_match.get("current_window_title"),
                poe_match_result=poe_match.get("poe_match_result"),
            )
            self._fail_owned_hotkey_capture(request_id, _POE_FOREGROUND_REQUIRED_MESSAGE)
            return None

        if self._session is not None and self._session.is_pending():
            log_capture_phase(
                CapturePhase.SESSION_ALREADY_ACTIVE,
                capture_id=self._session.session_id,
            )
            self._cancel_session(mark=CaptureStatus.CANCELLED)

        start_sequence = self._read_sequence()
        if start_sequence is None:
            start_sequence = 0

        if request_id is None:
            self._request_id += 1
            request_id = self._request_id
        elif request_id > self._request_id:
            self._request_id = request_id
        self._session = PriceCheckCaptureSession(
            session_id=request_id,
            start_sequence=int(start_sequence),
            deadline_monotonic=time.monotonic() + (self._timeout_ms / 1000.0),
            anchor_screen_px=anchor_screen_px,
            authorized_hwnd=identity[0],
            authorized_pid=identity[1],
            expected_trigger="shift_c",
            lifecycle=SessionLifecycle.WAITING_CLIPBOARD,
        )
        log_capture_phase(
            CapturePhase.CAPTURE_SESSION_CREATED,
            capture_id=request_id,
            start_sequence=int(start_sequence),
            current_hwnd=poe_match.get("current_hwnd"),
            current_pid=poe_match.get("current_pid"),
            current_process_name=poe_match.get("current_process_name"),
            current_window_title=poe_match.get("current_window_title"),
            poe_match_result=poe_match.get("poe_match_result"),
        )
        log_capture_phase(
            CapturePhase.SEQUENCE_BEFORE,
            capture_id=request_id,
            sequence=int(start_sequence),
        )
        recheck = self._foreground_match()
        log_capture_phase(
            CapturePhase.FOREGROUND_RECHECK,
            capture_id=request_id,
            current_hwnd=recheck.get("current_hwnd"),
            current_pid=recheck.get("current_pid"),
            current_process_name=recheck.get("current_process_name"),
            current_window_title=recheck.get("current_window_title"),
            poe_match_result=recheck.get("poe_match_result"),
        )
        if self._authorized_identity(recheck) != identity:
            log_capture_phase(
                CapturePhase.FOREGROUND_REJECTED,
                capture_id=request_id,
                failure_reason=CaptureFailureReason.FOREGROUND_LOST_BEFORE_SENDINPUT.value,
                stage="before_sendinput",
            )
            self._cancel_session(mark=CaptureStatus.CANCELLED)
            self._fail_owned_hotkey_capture(request_id, _POE_FOREGROUND_REQUIRED_MESSAGE)
            return request_id

        log_capture_phase(CapturePhase.SENDINPUT_REQUESTED, capture_id=request_id)
        send_result = self._send_copy()
        if not self._send_copy_succeeded(send_result, capture_id=request_id):
            if isinstance(send_result, SendInputResult) and send_result.failure_stage == "foreground_guard":
                self._cancel_session(mark=CaptureStatus.CANCELLED)
                self._fail_owned_hotkey_capture(request_id, _POE_FOREGROUND_REQUIRED_MESSAGE)
                return request_id
            self._fail_active("Could not request game-side item copy.", send_result=send_result)
            return request_id

        after_sequence = self._read_sequence()
        log_capture_phase(
            CapturePhase.SEQUENCE_AFTER,
            capture_id=request_id,
            sequence=after_sequence,
            start_sequence=int(start_sequence),
        )
        log_capture_phase(CapturePhase.SENDINPUT_ACCEPTED, capture_id=request_id)
        self.capture_started.emit(request_id)

        # PERF-01: the game may already have answered by the time SendInput returns.
        # This sequence was read for the log anyway; when it belongs to us, consume it
        # now instead of idling until the first poll tick. _consume_clipboard re-checks
        # foreground authorization exactly as the poll path does.
        session = self._session
        if session is not None and session.is_pending() and session.owns_clipboard_sequence(after_sequence):
            log_capture_phase(
                CapturePhase.CLIPBOARD_POLL,
                capture_id=request_id,
                sequence=after_sequence,
                start_sequence=int(start_sequence),
                source="post_sendinput",
            )
            if self._consume_clipboard(
                session=session,
                text=self._read_text(),
                sequence=after_sequence,
                anchor_screen_px=anchor_screen_px,
                source="post_sendinput",
            ):
                return request_id

        self._start_timeout(request_id)
        self._start_clipboard_poll(request_id)
        return request_id

    def route_clipboard_event(
        self,
        *,
        text: str,
        sequence: int | None,
        anchor_screen_px: tuple[int, int],
    ) -> bool:
        """Return True when the event belongs to the owned Shift+C capture."""
        session = self._session
        if session is None or not session.is_pending():
            return False

        if not self._session_still_authorized(session):
            self._cancel_for_foreground_loss(session, source="qt_event")
            return True

        log_capture_phase(
            CapturePhase.CLIPBOARD_EVENT,
            capture_id=session.session_id,
            sequence=sequence,
        )

        if not session.owns_clipboard_sequence(sequence):
            log_capture_phase(
                CapturePhase.CLIPBOARD_EVENT_NOT_OWNED,
                capture_id=session.session_id,
                sequence=sequence,
                start_sequence=session.start_sequence,
            )
            # A different clipboard update may be PoE2 Market's Copy Item action.
            return False

        return self._consume_clipboard(
            session=session,
            text=text,
            sequence=sequence,
            anchor_screen_px=anchor_screen_px,
            source="qt_event",
        )

    def should_suppress_gameplay(self, sequence: int | None) -> bool:
        session = self._session
        if session is None:
            return False
        return session.is_pending()

    def cancel(self) -> None:
        self._cancel_session(mark=CaptureStatus.CANCELLED)

    def shutdown(self) -> None:
        self._stop_timers()
        self._cancel_session(mark=CaptureStatus.CANCELLED)

    def _start_timeout(self, capture_id: int) -> None:
        self._timeout_timer.stop()
        self._timeout_timer.setProperty("capture_id", capture_id)
        self._timeout_timer.start(self._timeout_ms)

    def _start_clipboard_poll(self, capture_id: int) -> None:
        self._poll_timer.setProperty("capture_id", capture_id)
        if not self._poll_timer.isActive():
            self._fast_polls_left = CLIPBOARD_FAST_POLL_TICKS
            self._poll_timer.setInterval(CLIPBOARD_FAST_POLL_MS)
            self._poll_timer.start()

    def _stop_timers(self) -> None:
        self._timeout_timer.stop()
        self._poll_timer.stop()
        self._fast_polls_left = 0
        self._poll_timer.setInterval(CLIPBOARD_POLL_MS)

    def _poll_clipboard_sequence(self) -> None:
        session = self._session
        poll_id = self._poll_timer.property("capture_id")
        if session is None or not session.is_pending():
            self._poll_timer.stop()
            return
        if poll_id is not None and int(poll_id) != int(session.session_id):
            log_capture_phase(
                CapturePhase.SESSION_STALE,
                capture_id=int(poll_id),
                active_capture_id=session.session_id,
                stage="clipboard_poll",
            )
            return

        if self._fast_polls_left > 0:
            self._fast_polls_left -= 1
            if self._fast_polls_left == 0:
                self._poll_timer.setInterval(CLIPBOARD_POLL_MS)

        if not self._session_still_authorized(session):
            self._cancel_for_foreground_loss(session, source="sequence_poll")
            return

        sequence = self._read_sequence()
        if not session.owns_clipboard_sequence(sequence):
            if session.is_expired():
                return
            log_capture_phase(
                CapturePhase.CLIPBOARD_POLL,
                capture_id=session.session_id,
                sequence=sequence,
                start_sequence=session.start_sequence,
            )
            return

        text = self._read_text()
        self._consume_clipboard(
            session=session,
            text=text,
            sequence=sequence,
            anchor_screen_px=session.anchor_screen_px,
            source="sequence_poll",
        )

    def _consume_clipboard(
        self,
        *,
        session: PriceCheckCaptureSession,
        text: str,
        sequence: int | None,
        anchor_screen_px: tuple[int, int],
        source: str,
    ) -> bool:
        if not session.is_pending() or self._session is not session:
            return False

        if not self._session_still_authorized(session):
            self._cancel_for_foreground_loss(session, source=source)
            return True

        log_capture_phase(
            CapturePhase.CLIPBOARD_EVENT_OWNED,
            capture_id=session.session_id,
            sequence=sequence,
            source=source,
        )
        self._stop_timers()

        raw = RawItemInput.from_text(text or "")
        recognition = recognize_input(raw)
        if not recognition.recognized:
            session.mark_failed()
            self._session = None
            log_capture_phase(CapturePhase.NON_ITEM_CLIPBOARD, capture_id=session.session_id, failure_reason=CaptureFailureReason.NON_ITEM_CLIPBOARD.value)
            log_capture_failure_terminal(
                capture_id=session.session_id,
                failure_reason=CaptureFailureReason.NON_ITEM_CLIPBOARD.value,
                sequence_before=session.start_sequence,
                sequence_after=sequence,
                clipboard_text_len=len(text or ""),
                clipboard_read=True,
                item_recognized=False,
            )
            self._reset_idle(session.session_id, reason="non_item")
            self.capture_failed.emit(session.session_id, "Could not read hovered item.")
            return True

        log_capture_phase(CapturePhase.ITEM_RECOGNIZED, capture_id=session.session_id, sequence=sequence)
        session.mark_captured(sequence)
        self.mark_hotkey_consumed_sequence(sequence)
        self._completed_sequences[session.session_id] = (session.start_sequence, sequence)
        self._session = None
        log_capture_phase(CapturePhase.CAPTURE_SUCCESS, capture_id=session.session_id, sequence=sequence)
        self._reset_idle(session.session_id, reason="success")
        self.capture_ready.emit(session.session_id, text, anchor_screen_px, sequence)
        return True

    def _on_timeout(self) -> None:
        timeout_id = self._timeout_timer.property("capture_id")
        session = self._session
        if session is None or not session.is_pending():
            return
        if timeout_id is not None and int(timeout_id) != int(session.session_id):
            log_capture_phase(
                CapturePhase.SESSION_STALE,
                capture_id=int(timeout_id),
                active_capture_id=session.session_id,
                stage="timeout",
            )
            return
        if not self._session_still_authorized(session):
            self._cancel_for_foreground_loss(session, source="timeout")
            return
        session.mark_timeout()
        failed_id = session.session_id
        self._session = None
        self._stop_timers()
        failure_reason = CaptureFailureReason.CLIPBOARD_TIMEOUT
        if session.captured_sequence is None:
            failure_reason = CaptureFailureReason.CLIPBOARD_SEQUENCE_DID_NOT_ADVANCE
        log_capture_phase(
            CapturePhase.CLIPBOARD_TIMEOUT,
            capture_id=failed_id,
            failure_reason=failure_reason.value,
            start_sequence=session.start_sequence,
        )
        after_sequence = self._read_sequence()
        log_capture_failure_terminal(
            capture_id=failed_id,
            failure_reason=failure_reason.value,
            sequence_before=session.start_sequence,
            sequence_after=after_sequence,
            clipboard_read=False,
            item_recognized=False,
        )
        self._reset_idle(failed_id, reason="timeout")
        self.capture_failed.emit(failed_id, "Could not read hovered item.")

    def _send_copy_succeeded(self, result: bool | SendInputResult, *, capture_id: int) -> bool:
        if isinstance(result, SendInputResult):
            if result.ok:
                return True
            phase = CapturePhase.SENDINPUT_PARTIAL if result.inserted > 0 else CapturePhase.SENDINPUT_REJECTED
            if result.failure_stage == "modifier_still_down":
                phase = CapturePhase.MODIFIER_STILL_DOWN
            log_capture_phase(phase, capture_id=capture_id, **result.to_dict())
            return False
        if not bool(result):
            log_capture_phase(CapturePhase.SENDINPUT_REJECTED, capture_id=capture_id, legacy_bool=False)
            return False
        return True

    def _foreground_match(self) -> dict[str, Any]:
        """Return one fresh authorization snapshot; lookup errors fail closed."""
        if self._foreground_match_fn is not None:
            try:
                return dict(self._foreground_match_fn() or {})
            except Exception:
                return {"accepted": False, "poe_match_result": False}
        if self._is_poe_foreground is not is_poe_foreground:
            # Compatibility seam for deterministic callers predating identity
            # injection. Production never uses these synthetic identifiers.
            try:
                accepted = bool(self._is_poe_foreground())
            except Exception:
                accepted = False
            return {
                "accepted": accepted,
                "poe_match_result": accepted,
                "current_hwnd": 1 if accepted else 0,
                "current_pid": 1 if accepted else 0,
                "current_process_name": "pathofexile.exe" if accepted else "",
                "current_window_title": "",
            }
        try:
            return dict(evaluate_poe_foreground_match() or {})
        except Exception:
            return {"accepted": False, "poe_match_result": False}

    @staticmethod
    def _authorized_identity(match: dict[str, Any]) -> tuple[int, int] | None:
        if not bool(match.get("accepted")):
            return None
        hwnd = int(match.get("current_hwnd") or 0)
        pid = int(match.get("current_pid") or 0)
        if hwnd <= 0 or pid <= 0:
            return None
        return hwnd, pid

    def _session_still_authorized(self, session: PriceCheckCaptureSession) -> bool:
        return self._authorized_identity(self._foreground_match()) == (
            session.authorized_hwnd,
            session.authorized_pid,
        )

    def _cancel_for_foreground_loss(self, session: PriceCheckCaptureSession, *, source: str) -> None:
        if self._session is not session or not session.is_pending():
            return
        log_capture_phase(
            CapturePhase.FOREGROUND_REJECTED,
            capture_id=session.session_id,
            failure_reason="foreground_lost_before_clipboard",
            stage=source,
            authorized_hwnd=session.authorized_hwnd,
            authorized_pid=session.authorized_pid,
        )
        self._cancel_session(mark=CaptureStatus.CANCELLED)

    def _fail_active(
        self,
        message: str,
        *,
        send_result: bool | SendInputResult | None = None,
        failure_reason: CaptureFailureReason | None = None,
    ) -> None:
        session = self._session
        if session is None:
            return
        failed_id = session.session_id
        start_sequence = session.start_sequence
        self._stop_timers()
        session.mark_failed()
        self._session = None
        terminal_reason = (failure_reason or CaptureFailureReason.SENDINPUT_REJECTED).value
        sendinput_inserted: int | None = None
        if send_result is not None and not isinstance(send_result, SendInputResult):
            log_capture_phase(
                CapturePhase.SENDINPUT_REJECTED,
                capture_id=failed_id,
                legacy_bool=bool(send_result),
                failure_reason=terminal_reason,
            )
        elif isinstance(send_result, SendInputResult):
            sendinput_inserted = send_result.inserted
        elif failure_reason is not None:
            log_capture_phase(
                CapturePhase.FOREGROUND_REJECTED,
                capture_id=failed_id,
                failure_reason=terminal_reason,
            )
        after_sequence = self._read_sequence()
        log_capture_failure_terminal(
            capture_id=failed_id,
            failure_reason=terminal_reason,
            sequence_before=start_sequence,
            sequence_after=after_sequence,
            clipboard_read=False,
            item_recognized=False,
            sendinput_inserted=sendinput_inserted,
        )
        self._reset_idle(failed_id, reason="send_failure")
        self.capture_failed.emit(failed_id, message)

    def _cancel_session(self, *, mark: CaptureStatus) -> None:
        self._stop_timers()
        if self._session is None:
            return
        cancelled_id = self._session.session_id
        if mark is CaptureStatus.CANCELLED:
            self._session.mark_cancelled()
            log_capture_phase(CapturePhase.SESSION_CANCELLED, capture_id=cancelled_id)
        elif mark is CaptureStatus.TIMEOUT:
            self._session.mark_timeout()
        else:
            self._session.mark_failed()
        self._session = None
        self._reset_idle(cancelled_id, reason=mark.value)

    def _reset_idle(self, capture_id: int, *, reason: str) -> None:
        assert self._session is None
        log_capture_phase(CapturePhase.CAPTURE_RESET_IDLE, capture_id=capture_id, reason=reason)
        log_capture_phase(CapturePhase.SESSION_RESET, capture_id=capture_id, reason=reason)

    def _fail_owned_hotkey_capture(self, request_id: int | None, message: str) -> None:
        """Surface Shift+C ownership failures instead of failing silently."""
        if request_id is None:
            return
        self.capture_failed.emit(int(request_id), message)
