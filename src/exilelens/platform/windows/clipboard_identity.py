from __future__ import annotations

from typing import Any


def read_clipboard_sequence_number() -> int | None:
    """Windows clipboard generation via GetClipboardSequenceNumber."""
    try:
        import ctypes

        return int(ctypes.windll.user32.GetClipboardSequenceNumber() & 0xFFFFFFFF)
    except Exception:
        return None


def read_clipboard_text() -> str:
    """Read current clipboard text via Qt (same source as ClipboardWatcher)."""
    try:
        from PySide6.QtGui import QClipboard
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return ""
        return str(app.clipboard().text(QClipboard.Mode.Clipboard) or "")
    except Exception:
        return ""


def is_duplicate_clipboard_event(previous_sequence: int | None, current_sequence: int | None) -> bool:
    """Same OS clipboard event/sequence must be ignored. Missing sequence is never a duplicate."""
    if current_sequence is None or previous_sequence is None:
        return False
    return int(previous_sequence) == int(current_sequence)


def clipboard_event_decision(
    *,
    previous_sequence: int | None,
    current_sequence: int | None,
    content_hash: str = "",
    previous_content_hash: str = "",
) -> dict[str, Any]:
    """Separate OS-event identity from item text. Identical text is not a reason to ignore."""
    duplicate_event = is_duplicate_clipboard_event(previous_sequence, current_sequence)
    return {
        "duplicate_event": duplicate_event,
        "accept": not duplicate_event,
        "identical_text": bool(content_hash) and content_hash == previous_content_hash,
        "previous_sequence": previous_sequence,
        "current_sequence": current_sequence,
    }
