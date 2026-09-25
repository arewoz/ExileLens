"""Managed tool windows: stable geometry on move, hide-on-close, persisted layout."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QCloseEvent, QMoveEvent, QResizeEvent
from PySide6.QtWidgets import QApplication, QScrollArea, QVBoxLayout, QWidget

from exilelens.ui.window_policy import WindowInteractionPolicy, apply_window_interaction_policy

#: Qt's "no maximum" sentinel. Not exported by PySide6, so it is spelled out here.
QWIDGETSIZE_MAX = (1 << 24) - 1


def clamp_window_to_screen(widget: QWidget) -> None:
    """Clamp position only — never change width/height."""
    if widget.isMinimized() or not widget.isVisible():
        return
    screen = widget.screen() or QApplication.primaryScreen()
    if screen is None:
        return
    available = screen.availableGeometry()
    geo = widget.frameGeometry()
    width = geo.width()
    height = geo.height()
    x = geo.x()
    y = geo.y()
    if width > available.width():
        x = available.x()
    else:
        x = max(available.x(), min(x, available.x() + available.width() - width))
    if height > available.height():
        y = available.y()
    else:
        y = max(available.y(), min(y, available.y() + available.height() - height))
    if x != geo.x() or y != geo.y():
        widget.move(x, y)


def recover_window_geometry(widget: QWidget, *, cap_size: bool = True) -> None:
    """Recover a persisted window that no longer intersects any connected screen."""
    screens = list(QApplication.screens() or [])
    primary = QApplication.primaryScreen()
    if not screens or primary is None:
        return
    geo = widget.frameGeometry()
    intersecting = next((screen for screen in screens if screen.availableGeometry().intersects(geo)), None)
    screen = intersecting or primary
    available = screen.availableGeometry()
    if cap_size and (widget.width() > available.width() or widget.height() > available.height()):
        target = QSize(min(widget.width(), available.width()), min(widget.height(), available.height()))
        widget.setMinimumSize(QSize(min(widget.minimumWidth(), target.width()), min(widget.minimumHeight(), target.height())))
        widget.setMaximumSize(target)
        widget.resize(target)
        if getattr(widget, "resizable", False):
            # Capping is a one-off fit to the screen; re-pinning the maximum would
            # silently make a resizable window fixed for the rest of the session.
            widget.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
        elif hasattr(widget, "_locked_size"):
            widget._locked_size = target  # type: ignore[attr-defined]
        geo = widget.frameGeometry()
    if intersecting is None:
        frame = widget.frameGeometry()
        frame.moveCenter(available.center())
        widget.move(frame.topLeft())
    clamp_window_to_screen(widget)


class ManagedToolWindow(QWidget):
    """Interactive tool window that hides on close and preserves size while moving."""

    #: Opt-in. Subclasses that set this True keep no ``_locked_size``, so the user can
    #: resize freely. Every other managed window keeps the original fixed behaviour.
    resizable = False

    def __init__(
        self,
        *,
        policy: WindowInteractionPolicy = WindowInteractionPolicy.INTERACTIVE_TOOL,
        minimum_size: QSize | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._locked_size = QSize()
        self._geometry_restored = False
        apply_window_interaction_policy(self, policy)
        self.setAttribute(self._size_grip_attr(), False)
        if minimum_size is not None:
            self.setMinimumSize(minimum_size)
        flags = self.windowFlags()
        flags |= (
            self._window_type()
            | self._close_hint()
            | self._minimize_hint()
        )
        self.setWindowFlags(flags)

    @staticmethod
    def _window_type():
        from PySide6.QtCore import Qt

        return Qt.WindowType.Window

    @staticmethod
    def _close_hint():
        from PySide6.QtCore import Qt

        return Qt.WindowType.WindowCloseButtonHint

    @staticmethod
    def _minimize_hint():
        from PySide6.QtCore import Qt

        return Qt.WindowType.WindowMinimizeButtonHint

    @staticmethod
    def _size_grip_attr():
        from PySide6.QtCore import Qt

        return Qt.WidgetAttribute.WA_StaticContents

    def lock_current_size(self) -> None:
        self._locked_size = self.size()

    def restore_geometry(self, *, x: int | None, y: int | None, width: int, height: int) -> None:
        self.resize(max(width, self.minimumWidth()), max(height, self.minimumHeight()))
        if not self.resizable:
            self._locked_size = self.size()
        if x is not None and y is not None:
            self.move(int(x), int(y))
        self._geometry_restored = True
        clamp_window_to_screen(self)

    def remember_geometry(self, settings, *, prefix: str) -> None:
        geo = self.geometry()
        setattr(settings, f"{prefix}_x", geo.x())
        setattr(settings, f"{prefix}_y", geo.y())
        setattr(settings, f"{prefix}_width", geo.width())
        setattr(settings, f"{prefix}_height", geo.height())

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.on_hide()
        event.ignore()
        self.hide()

    def moveEvent(self, event: QMoveEvent) -> None:  # noqa: N802
        super().moveEvent(event)
        if not self.resizable and self._locked_size.isValid() and not self._locked_size.isEmpty():
            current = self.size()
            if current != self._locked_size:
                self.resize(self._locked_size)
        clamp_window_to_screen(self)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.resizable:
            return
        if not self._locked_size.isValid() or self._locked_size.isEmpty():
            self._locked_size = event.size()
        elif event.oldSize().isValid() and event.size() != self._locked_size:
            # User-initiated resize updates lock; layout-driven drift must not grow the window.
            if event.spontaneous() and self.isVisible():
                self._locked_size = event.size()

    def on_hide(self) -> None:
        """Override to persist geometry when hidden via close."""
        return


def wrap_scroll_content(content: QWidget, *, minimum_width: int = 480) -> QScrollArea:
    from PySide6.QtCore import Qt

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    scroll.setMinimumWidth(minimum_width)
    return scroll


def move_preserves_size(widget: QWidget, steps: int = 1) -> tuple[QSize, QSize]:
    """Test helper: return (before, after) sizes across synthetic moves."""
    before = widget.size()
    for idx in range(steps):
        widget.move(widget.x() + 10 + idx, widget.y() + 7 + idx)
        QApplication.processEvents()
    after = widget.size()
    return before, after
