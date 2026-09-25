from __future__ import annotations

import ctypes
import logging
import time
from dataclasses import dataclass

from ctypes import wintypes

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QClipboard, QCursor
from PySide6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

WM_CLIPBOARDUPDATE = 0x031D

from exilelens.app.runtime_trace import trace
from exilelens.platform.windows.clipboard_identity import (
    is_duplicate_clipboard_event,
    read_clipboard_sequence_number,
)
from exilelens.platform.windows.cursor import get_cursor_pos_physical

# PoE sometimes updates the Win32 clipboard sequence without a reliable Qt dataChanged
# callback while the game owns focus. The owned Shift+C coordinator polls its own
# sequence; this observer keeps the generic clipboard stream current for other modules.
CLIPBOARD_SEQUENCE_POLL_MS = 50


class _ClipboardUpdateListener(QWidget):
    """Win32 AddClipboardFormatListener bridge for WM_CLIPBOARDUPDATE."""

    def __init__(self, on_update: object, parent: QObject | None = None) -> None:
        super().__init__(None)
        self._on_update = on_update
        self._registered = False
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        # show() is required so Win32 can register HWND for WM_CLIPBOARDUPDATE, but the
        # listener must never appear as a desktop window during tray-first startup.
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.hide()

    def showEvent(self, event) -> None:  # noqa: ANN001 - Qt signature
        super().showEvent(event)
        self._ensure_registered()

    def _ensure_registered(self) -> None:
        if self._registered:
            return
        try:
            hwnd = int(self.winId())
            if hwnd and bool(ctypes.windll.user32.AddClipboardFormatListener(hwnd)):
                self._registered = True
                logger.debug("clipboard_format_listener registered hwnd=%s", hwnd)
        except Exception:
            logger.debug("clipboard_format_listener registration failed", exc_info=True)

    def nativeEvent(self, eventType, message):  # noqa: ANN001 - Qt signature
        if eventType == b"windows_generic_MSG":
            try:
                msg = wintypes.MSG.from_address(int(message))
                if int(msg.message) == WM_CLIPBOARDUPDATE:
                    self._on_update()
            except (TypeError, ValueError, OverflowError):
                logger.debug("clipboard nativeEvent handling failed", exc_info=True)
        return False, 0

    def closeEvent(self, event) -> None:  # noqa: ANN001 - Qt signature
        if self._registered:
            try:
                hwnd = int(self.winId())
                if hwnd:
                    ctypes.windll.user32.RemoveClipboardFormatListener(hwnd)
            except Exception:
                logger.debug("clipboard_format_listener removal failed", exc_info=True)
            self._registered = False
        super().closeEvent(event)


@dataclass(frozen=True)
class ClipboardEvent:
    text: str
    cursor_position: QPoint
    copy_anchor_screen_px: tuple[int, int]
    received_at: float
    content_hash: str
    sequence: int | None = None


class ClipboardWatcher(QObject):
    """Application-lifetime clipboard listener: Qt dataChanged + Win32 sequence identity."""

    clipboard_event = Signal(object)
    text_changed = Signal(str)  # legacy; prefer clipboard_event

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._clipboard = QApplication.clipboard()
        self._last_sequence: int | None = None
        self._fallback_sequence = 0
        self._enabled = True
        self._listening = True
        self._pending_mode: QClipboard.Mode | None = None
        self._defer_timer = QTimer(self)
        self._defer_timer.setSingleShot(True)
        self._defer_timer.timeout.connect(self._process_pending)
        self._sequence_poll_timer = QTimer(self)
        self._sequence_poll_timer.setInterval(CLIPBOARD_SEQUENCE_POLL_MS)
        self._sequence_poll_timer.timeout.connect(self._poll_clipboard_sequence)
        self._clipboard_listener: _ClipboardUpdateListener | None = None
        self._clipboard.dataChanged.connect(self._on_data_changed)
        if self._enabled:
            self._sequence_poll_timer.start()
            self._start_clipboard_listener()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def listening(self) -> bool:
        return self._listening and self._enabled

    @property
    def sequence(self) -> int | None:
        return self._last_sequence

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if enabled:
            self._sequence_poll_timer.start()
            self._start_clipboard_listener()
        else:
            self._sequence_poll_timer.stop()
            self._stop_clipboard_listener()
        trace("clipboard_enabled", enabled=enabled, listening=self.listening)

    def _start_clipboard_listener(self) -> None:
        if self._clipboard_listener is not None:
            return
        listener = _ClipboardUpdateListener(self._on_clipboard_update, parent=self)
        listener.show()
        self._clipboard_listener = listener

    def _stop_clipboard_listener(self) -> None:
        if self._clipboard_listener is None:
            return
        self._clipboard_listener.close()
        self._clipboard_listener = None

    def _on_clipboard_update(self) -> None:
        if not self._enabled:
            return
        self._pending_mode = QClipboard.Clipboard
        self._defer_timer.start(0)

    def _on_data_changed(self, mode: QClipboard.Mode = QClipboard.Clipboard) -> None:
        trace("clipboard_callback", mode=str(mode), enabled=self._enabled, listening=self.listening)
        if not self._enabled or mode != QClipboard.Clipboard:
            return
        self._pending_mode = mode
        self._defer_timer.start(0)

    def _next_sequence(self) -> int | None:
        sequence = read_clipboard_sequence_number()
        if sequence is not None:
            return sequence
        self._fallback_sequence += 1
        return self._fallback_sequence

    def inject_text(self, text: str, *, cursor_position: QPoint | None = None, sequence: int | None = None) -> ClipboardEvent | None:
        """Same emit path as a real clipboard change. Used by tests."""
        if sequence is None:
            sequence = self._next_sequence()
        return self._emit_from_text(text, cursor_position=cursor_position, sequence=sequence)

    def _process_pending(self) -> None:
        if not self._enabled or self._pending_mode != QClipboard.Clipboard:
            return
        self._pending_mode = None
        sequence = self._next_sequence()
        if is_duplicate_clipboard_event(self._last_sequence, sequence):
            return
        text = self._clipboard.text(QClipboard.Mode.Clipboard)
        self._emit_from_text(text, sequence=sequence, source="qt_event")

    def _poll_clipboard_sequence(self) -> None:
        if not self._enabled:
            return
        sequence = read_clipboard_sequence_number()
        if sequence is None or is_duplicate_clipboard_event(self._last_sequence, sequence):
            return
        text = self._clipboard.text(QClipboard.Mode.Clipboard)
        self._emit_from_text(text, sequence=sequence, source="sequence_poll")

    def _emit_from_text(
        self,
        text: str,
        *,
        cursor_position: QPoint | None = None,
        sequence: int | None = None,
        source: str = "qt_event",
    ) -> ClipboardEvent | None:
        if not text:
            trace("clipboard_empty")
            return None
        if len(text) > 64_000:
            trace("clipboard_too_large", length=len(text))
            return None
        if is_duplicate_clipboard_event(self._last_sequence, sequence):
            trace("clipboard_duplicate_sequence", sequence=sequence)
            return None
        content_hash = _fast_hash(text)
        self._last_sequence = sequence
        anchor = get_cursor_pos_physical()
        if anchor is None:
            pos = cursor_position if cursor_position is not None else QCursor.pos()
            anchor = (int(pos.x()), int(pos.y()))
        from exilelens.platform.windows.poe_window import physical_to_logical

        lx, ly = physical_to_logical(float(anchor[0]), float(anchor[1]))
        logical = QPoint(int(round(lx)), int(round(ly)))
        event = ClipboardEvent(
            text=text,
            cursor_position=logical,
            copy_anchor_screen_px=anchor,
            received_at=time.perf_counter(),
            content_hash=content_hash,
            sequence=sequence,
        )
        # Clipboard content is private and may come from any application. Trace
        # only event metadata; never emit a preview, hash, or reversible encoding.
        trace("clipboard_event", sequence=sequence, length=len(text), source=source)
        self.clipboard_event.emit(event)
        self.text_changed.emit(text)
        return event


def _fast_hash(text: str) -> str:
    if len(text) <= 4096:
        import hashlib

        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    import hashlib

    sample = f"{len(text)}:{text[:2048]}:{text[-2048:]}"
    return hashlib.sha256(sample.encode("utf-8")).hexdigest()
