from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from poe2value.platform.windows.cursor import get_cursor_pos_physical
from poe2value.platform.windows.foreground_info import evaluate_poe_foreground_match, is_poe_foreground
from poe2value.platform.windows.keyboard_hook import (
    DEFAULT_PRICE_CHECK_HOTKEY,
    PriceCheckHotkeyHook,
)
from poe2value.platform.windows.keyboard_state import is_hotkey_combo_physically_down
from poe2value.price_check.capture_diagnostics import (
    CaptureFailureReason,
    CapturePhase,
    log_capture_phase,
)

logger = logging.getLogger(__name__)

DEFAULT_RELEASE_WATCHDOG_MS = 10_000
# The release poll only reconciles hook state against the real keyboard. A chord the OS
# still reports as physically down stays latched for as long as the user holds it: elapsed
# time alone is never grounds to reset, because an unlatched matcher would read the next
# auto-repeat KEYDOWN as a fresh activation. This threshold only gates one diagnostic.
LONG_HOLD_DIAGNOSTIC_MS = 60_000


def is_price_check_combo_physically_down() -> bool:
    """Compatibility seam for tests that still stub OS polling."""
    return False


_LEGACY_RELEASE_CHECK = is_price_check_combo_physically_down


class HotkeyLifecycle(str):
    IDLE = "idle"
    WAITING_RELEASE = "waiting_release"


def _foreground_diag_fields(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_hwnd": match.get("current_hwnd"),
        "current_pid": match.get("current_pid"),
        "current_process_name": match.get("current_process_name"),
        "current_window_title": match.get("current_window_title"),
        "poe_match_result": match.get("poe_match_result"),
    }


class PriceCheckHotkeyController(QObject):
    """Item Check hotkey trigger.

    A matching KEYDOWN latches exactly one Item Check. Capture itself must wait for the
    chord to be released, because the synthetic Ctrl+C is refused while Shift/Alt/Win is
    still down. That wait is unbounded: holding the shortcut only delays the capture, it
    never fails it. A periodic poll reconciles hook chord state with the real keyboard so
    a swallowed or missed KEYUP still completes the pending Item Check and unlatches the
    hotkey instead of stranding it.
    """

    capture_requested = Signal(int, object)
    poe_inactive = Signal(int)
    capture_blocked = Signal(int, str)
    hotkey_tested = Signal()
    diagnostics_changed = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        hotkey: str = DEFAULT_PRICE_CHECK_HOTKEY,
        release_wait_ms: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._hook = PriceCheckHotkeyHook(self, hotkey=hotkey)
        self._controller: Any | None = None
        self._active = False
        self._release_poll_ms = max(100, int(release_wait_ms or DEFAULT_RELEASE_WATCHDOG_MS))
        self._long_hold_diagnostic_ms = LONG_HOLD_DIAGNOSTIC_MS
        self._pending_anchor: tuple[int, int] | None = None
        self._capture_id = 0
        self._release_capture_id: int | None = None
        self._lifecycle = HotkeyLifecycle.IDLE
        self._release_watchdog = QTimer(self)
        self._release_watchdog.setSingleShot(False)
        self._release_watchdog.timeout.connect(self._on_release_watchdog)
        self._release_started_monotonic = 0.0
        self._last_release_source = ""
        self._last_long_hold = ""
        self._long_hold_logged = False
        self._hook.triggered.connect(self._on_hotkey, Qt.ConnectionType.QueuedConnection)
        self._hook.binding_released.connect(self._on_binding_released, Qt.ConnectionType.QueuedConnection)
        self._hook.tested.connect(self.hotkey_tested, Qt.ConnectionType.QueuedConnection)
        self._hook.seen_not_poe.connect(self._on_seen_not_poe, Qt.ConnectionType.QueuedConnection)
        self._last_received = ""
        self._last_not_poe = ""

    @property
    def hook(self) -> PriceCheckHotkeyHook:
        return self._hook

    @property
    def active(self) -> bool:
        return self._active

    @property
    def hook_registered(self) -> bool:
        return self._hook.registered

    @property
    def waiting_for_release(self) -> bool:
        return self._lifecycle == HotkeyLifecycle.WAITING_RELEASE

    def bind(self, *, controller: Any | None) -> None:
        self._controller = controller

    def start(self) -> bool:
        self._active = True
        ok = self._hook.start()
        self.diagnostics_changed.emit()
        return ok

    def stop(self) -> None:
        self._active = False
        self._cancel_release_wait()
        self._hook.stop()

    def shutdown(self) -> None:
        self.stop()

    def set_test_mode(self, enabled: bool) -> None:
        self._hook.set_test_mode(enabled)

    def reconfigure(self, hotkey: str) -> bool:
        was_active = self._active
        self._hook.stop()
        self._hook.deleteLater()
        self._hook = PriceCheckHotkeyHook(self, hotkey=hotkey)
        self._hook.triggered.connect(self._on_hotkey, Qt.ConnectionType.QueuedConnection)
        self._hook.binding_released.connect(self._on_binding_released, Qt.ConnectionType.QueuedConnection)
        self._hook.tested.connect(self.hotkey_tested, Qt.ConnectionType.QueuedConnection)
        self._hook.seen_not_poe.connect(self._on_seen_not_poe, Qt.ConnectionType.QueuedConnection)
        return self._hook.start() if was_active else True

    def diagnostic_report(self) -> str:
        tracker = getattr(getattr(self._hook, "_low_level", None), "chord_tracker", None)
        tracker_diag = tracker.diagnostics() if tracker is not None else {}
        return (
            f"Item Check hotkey: {self._hook.hotkey}\n"
            f"Hook installed: {self.hook_registered}\n"
            f"Hook error: {self._hook.install_error or '(none)'}\n"
            f"Last received: {self._last_received or '(none)'}\n"
            f"Last release source: {self._last_release_source or '(none)'}\n"
            f"Last long hold: {self._last_long_hold or '(none)'}\n"
            f"Hook chord state: {tracker_diag}\n"
            f"Last seen outside PoE2: {self._last_not_poe or '(none)'}"
        )

    def _on_seen_not_poe(self) -> None:
        import time

        self._last_not_poe = time.strftime("%Y-%m-%d %H:%M:%S")
        self.diagnostics_changed.emit()

    def notify_app_deactivated(self) -> None:
        """Cancel in-flight release wait when overlay app loses activation."""
        if not self.waiting_for_release:
            return
        capture_id = self._release_capture_id
        self._cancel_release_wait()
        self._reconcile_stuck_chord_state(reason="app_deactivated", capture_id=capture_id)
        if capture_id is not None:
            log_capture_phase(
                CapturePhase.FOREGROUND_LOST_DURING_RELEASE,
                capture_id=capture_id,
                failure_reason=CaptureFailureReason.SESSION_CANCELLED.value,
                stage="app_deactivated",
            )

    def _on_hotkey(self) -> None:
        import time

        if not self._active:
            return
        self._last_received = time.strftime("%Y-%m-%d %H:%M:%S")
        self.diagnostics_changed.emit()
        hotkey_match = evaluate_poe_foreground_match()
        if not is_poe_foreground():
            log_capture_phase(
                CapturePhase.HOTKEY_RECEIVED,
                capture_id=None,
                hotkey=self._hook.hotkey,
                **_foreground_diag_fields(hotkey_match),
            )
            log_capture_phase(
                CapturePhase.FOREGROUND_REJECTED,
                capture_id=None,
                stage="hotkey",
                failure_reason=CaptureFailureReason.POE_NOT_FOREGROUND.value,
                **_foreground_diag_fields(hotkey_match),
            )
            return
        self._capture_id += 1
        capture_id = self._capture_id
        log_capture_phase(
            CapturePhase.HOTKEY_RECEIVED,
            capture_id=capture_id,
            hotkey=self._hook.hotkey,
            **_foreground_diag_fields(hotkey_match),
        )
        log_capture_phase(CapturePhase.HOTKEY_ACCEPTED, capture_id=capture_id, hotkey=self._hook.hotkey)
        anchor = get_cursor_pos_physical()
        if anchor is None:
            anchor = (0, 0)
        self._begin_release_wait(anchor, capture_id=capture_id)

    def _begin_release_wait(self, anchor: tuple[int, int], *, capture_id: int | None = None) -> None:
        import time

        self._cancel_release_wait(reset_capture_id=False)
        if capture_id is None:
            self._capture_id += 1
            capture_id = self._capture_id
        self._pending_anchor = anchor
        self._release_capture_id = capture_id
        self._lifecycle = HotkeyLifecycle.WAITING_RELEASE
        self._release_started_monotonic = time.monotonic()
        self._long_hold_logged = False
        self._release_watchdog.setProperty("capture_id", capture_id)
        tracker = getattr(getattr(self._hook, "_low_level", None), "chord_tracker", None)
        log_capture_phase(
            CapturePhase.WAITING_KEY_RELEASE,
            capture_id=capture_id,
            hook_chord_state=tracker.diagnostics() if tracker is not None else {},
        )
        log_capture_phase(CapturePhase.WAITING_FOR_RELEASE, capture_id=capture_id)
        if tracker is not None and not tracker.armed:
            tracker.arm()
        if tracker is not None and not tracker.binding_keys_down():
            self._complete_release_wait(release_source="hook_already_released")
            return
        self._release_watchdog.start(self._release_poll_ms)

    def _on_binding_released(self) -> None:
        if not self.waiting_for_release:
            return
        self._complete_release_wait(release_source="hook_observed")

    def _on_release_watchdog(self) -> None:
        """Reconcile hook chord state. Never fails the Item Check that is waiting."""
        import time

        watchdog_id = self._release_watchdog.property("capture_id")
        if self._release_capture_id is None or watchdog_id is None:
            return
        if int(watchdog_id) != int(self._release_capture_id):
            log_capture_phase(
                CapturePhase.SESSION_STALE,
                capture_id=int(watchdog_id),
                active_capture_id=self._release_capture_id,
                stage="release_watchdog",
            )
            return
        if not is_poe_foreground():
            cancelled_id = self._release_capture_id
            release_match = evaluate_poe_foreground_match()
            self._cancel_release_wait()
            self._reconcile_stuck_chord_state(reason="foreground_lost", capture_id=cancelled_id)
            log_capture_phase(
                CapturePhase.FOREGROUND_LOST_DURING_RELEASE,
                capture_id=cancelled_id,
                failure_reason=CaptureFailureReason.FOREGROUND_LOST_DURING_RELEASE.value,
                **_foreground_diag_fields(release_match),
            )
            return
        tracker = self._chord_tracker()
        if tracker is not None and not tracker.binding_keys_down():
            self._complete_release_wait(release_source="hook_watchdog_reconcile")
            return
        elapsed_ms = int((time.monotonic() - self._release_started_monotonic) * 1000)
        if not self._combo_physically_down():
            # The hook missed a KEYUP (swallowed chord, suspended queue, focus change).
            # The keys are really up, so the pending Item Check is allowed to proceed.
            self._reset_hook_chord_state()
            self._complete_release_wait(release_source="os_state_reconcile")
            return
        # The OS confirms the chord is still physically down. Stay latched: one physical
        # press cycle yields at most one Item Check no matter how long it is held.
        log_capture_phase(
            CapturePhase.KEY_RELEASE_STILL_HELD,
            capture_id=self._release_capture_id,
            elapsed_release_wait_ms=elapsed_ms,
            hook_chord_state=tracker.diagnostics() if tracker is not None else {},
        )
        if elapsed_ms >= self._long_hold_diagnostic_ms:
            self._note_long_hold(elapsed_ms=elapsed_ms, tracker=tracker)

    def _chord_tracker(self) -> Any | None:
        return getattr(getattr(self._hook, "_low_level", None), "chord_tracker", None)

    def _combo_physically_down(self) -> bool:
        """Real keyboard state, used only to detect a KEYUP the hook never saw."""
        try:
            return bool(is_hotkey_combo_physically_down(self._hook.hotkey))
        except Exception:  # pragma: no cover - defensive; never fail a capture on this
            logger.debug("item_check_physical_key_probe_failed", exc_info=True)
            return True

    def _reset_hook_chord_state(self) -> None:
        """Unlatch hook state so the next KEYDOWN can trigger Item Check again."""
        low_level = getattr(self._hook, "_low_level", None)
        tracker = getattr(low_level, "chord_tracker", None)
        if tracker is not None:
            tracker.reset()
        matcher = getattr(low_level, "matcher", None)
        reset = getattr(matcher, "reset", None)
        if callable(reset):
            reset()

    def _reconcile_stuck_chord_state(self, *, reason: str, capture_id: int | None) -> None:
        """After a cancel, drop hook latches when the keys are not really held."""
        if self._combo_physically_down():
            return
        self._reset_hook_chord_state()
        log_capture_phase(
            CapturePhase.CHORD_STATE_RESET,
            capture_id=capture_id,
            stage=reason,
        )

    def _note_long_hold(self, *, elapsed_ms: int, tracker: Any | None) -> None:
        """Log an unusually long hold once. Diagnostic only; state stays latched."""
        import time

        if self._long_hold_logged:
            return
        self._long_hold_logged = True
        self._last_long_hold = time.strftime("%Y-%m-%d %H:%M:%S")
        logger.warning(
            "item_check_hotkey_long_hold hotkey=%s capture_id=%s held_ms=%s hook_chord_state=%s",
            self._hook.hotkey,
            self._release_capture_id,
            elapsed_ms,
            tracker.diagnostics() if tracker is not None else {},
        )
        self.diagnostics_changed.emit()

    def _complete_release_wait(self, *, release_source: str) -> None:
        import time

        capture_id = self._release_capture_id
        self._release_watchdog.stop()
        anchor = self._pending_anchor
        elapsed_ms = int((time.monotonic() - self._release_started_monotonic) * 1000) if self._release_started_monotonic else 0
        tracker = getattr(getattr(self._hook, "_low_level", None), "chord_tracker", None)
        self._pending_anchor = None
        self._release_capture_id = None
        self._lifecycle = HotkeyLifecycle.IDLE
        self._last_release_source = release_source
        self.diagnostics_changed.emit()
        if anchor is None or capture_id is None:
            return
        log_capture_phase(
            CapturePhase.KEY_RELEASED,
            capture_id=capture_id,
            release_source=release_source,
            elapsed_release_wait_ms=elapsed_ms,
            hook_chord_state=tracker.diagnostics() if tracker is not None else {},
        )
        release_match = evaluate_poe_foreground_match()
        if not is_poe_foreground():
            log_capture_phase(
                CapturePhase.FOREGROUND_REJECTED,
                capture_id=capture_id,
                stage="hotkey_release",
                failure_reason=CaptureFailureReason.POE_NOT_FOREGROUND.value,
                **_foreground_diag_fields(release_match),
            )
            return
        log_capture_phase(
            CapturePhase.FOREGROUND_OK,
            capture_id=capture_id,
            **_foreground_diag_fields(release_match),
        )
        self.capture_requested.emit(capture_id, anchor)

    def _cancel_release_wait(self, *, reset_capture_id: bool = True) -> None:
        self._release_watchdog.stop()
        self._pending_anchor = None
        if reset_capture_id:
            self._release_capture_id = None
        self._lifecycle = HotkeyLifecycle.IDLE
