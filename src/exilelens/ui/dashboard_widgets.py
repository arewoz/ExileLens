"""Widgets for the Status Rail dashboard pages.

Small, flat primitives: space first, a hairline second, a card only when it is
semantically a card (the one-time consent decision). Status always travels with a word
or a shape, never colour alone.
"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from exilelens.ui import theme
from exilelens.ui.ui_icons import outline_icon


def make_label(text: str = "", name: str = "bodyText", *, wrap: bool = True, selectable: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    if selectable:
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class WrapLabel(QLabel):
    """A word-wrapped label that keeps its own height right.

    Nested layouts that are populated after the first layout pass sometimes keep the one-line height; this
    label pins its minimum height to ``heightForWidth`` whenever its width or text changes.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    def _fit(self) -> None:
        if self.width() > 0 and self.wordWrap():
            self.setMinimumHeight(0)  # heightForWidth() never reports less than the current minimum
            self.setMinimumHeight(self.heightForWidth(self.width()))

    def setText(self, text: str) -> None:  # noqa: N802 - mirrors QLabel
        super().setText(text)
        self._fit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit()


def set_property(widget: QWidget, name: str, value) -> None:
    """Set a dynamic property and re-resolve the stylesheet so ``[name=value]`` rules apply."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class Hairline(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hairline")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFixedHeight(1)


class FlowLayout(QLayout):
    """Left-to-right layout that wraps onto further lines when the row is too narrow (button rows)."""

    def __init__(self, parent: QWidget | None = None, *, spacing: int = 10) -> None:
        super().__init__(parent)
        self._items: list = []
        self._gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _layout(self, rect: QRect, *, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_h = area.x(), area.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and line_h > 0:
                x, y, line_h = area.x(), y + line_h + self._gap, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._gap
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + margins.bottom()


class StackingRow(QWidget):
    """A fixed label column with a control beside it that drops *under* the label when the page is narrow.

    Larger Windows text sizes widen both parts; without this the row would force the whole page wider than its
    viewport. The minimum width is the stacked one, so the page can always shrink to the window.
    """

    def __init__(self, label: QWidget, right: QLayout, *, top: int = 0, spacing: int = 16, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = label
        self._right_layout = right
        self._spacing = spacing
        self._outer = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._outer.setContentsMargins(0, top, 0, 0)
        self._outer.setSpacing(spacing)
        self._outer.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._outer.addWidget(label, 0, Qt.AlignmentFlag.AlignTop)
        self._outer.addLayout(right, 1)
        self._stacked = False

    def _right_min(self) -> int:
        return self._right_layout.minimumSize().width()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        base = self._outer.minimumSize()
        return QSize(max(self._label.sizeHint().width(), self._right_min()), base.height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        needed = self._label.width() + self._spacing + self._right_min()
        stacked = self.width() < needed
        if stacked != self._stacked:
            self._stacked = stacked
            self._outer.setDirection(QBoxLayout.Direction.TopToBottom if stacked else QBoxLayout.Direction.LeftToRight)
            self._outer.setSpacing(6 if stacked else self._spacing)
            self._outer.invalidate()
            self.updateGeometry()


class ThemedSwitch(QCheckBox):
    """38x20 switch followed by the word On or Off, so state never rides on colour alone.

    Subclasses :class:`QCheckBox` so ``toggled`` / ``isChecked`` / ``setChecked`` work
    unchanged. The accessible name is the row label; the painted text is only On / Off.
    """

    TRACK_W = 38
    TRACK_H = 20
    KNOB = 12

    def __init__(self, accessible_name: str = "", parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.setObjectName("themedSwitch")
        self.setAccessibleName(accessible_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(self.TRACK_W + 10 + theme.scaled_px(24), max(self.TRACK_H, theme.CONTROL_HEIGHT_COMPACT))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        enabled = self.isEnabled()
        on = self.isChecked()
        top = (self.height() - self.TRACK_H) / 2
        track = QRectF(1, top + 0.5, self.TRACK_W - 1, self.TRACK_H - 1)
        if on and enabled:
            fill, edge, knob = QColor(theme.ACCENT), QColor(theme.ACCENT), QColor(theme.ON_ACCENT)
        else:
            fill, edge, knob = QColor(theme.SURFACE_3), QColor(255, 255, 255, 56), QColor(theme.TEXT_BODY)
        if not enabled:
            for color in (fill, edge, knob):
                color.setAlphaF(0.55)
        painter.setPen(QPen(edge, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        knob_d = self.KNOB
        knob_x = track.right() - 3 - knob_d if on else track.left() + 3
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob)
        painter.drawEllipse(QRectF(knob_x, top + (self.TRACK_H - knob_d) / 2, knob_d, knob_d))
        if self.hasFocus() and self.focusPolicy() != Qt.FocusPolicy.NoFocus:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(theme.FOCUS), 2))
            painter.drawRoundedRect(track.adjusted(-2, -2, 2, 2), track.height() / 2 + 2, track.height() / 2 + 2)
        painter.setPen(QColor(theme.TEXT_BODY if enabled else theme.TEXT_MUTED))
        font = self.font()
        font.setPixelSize(theme.scaled_px(13))
        font.setWeight(font.Weight.DemiBold)
        painter.setFont(font)
        text_x = int(track.right() + 10)
        painter.drawText(
            text_x, 0, self.width() - text_x, self.height(),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            "On" if on else "Off",
        )
        painter.end()

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)


class ChevronComboBox(QComboBox):
    """Combo box with a painted chevron (QSS cannot draw one without an image asset)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(theme.SETTINGS_SELECT_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(theme.TEXT_BODY if self.isEnabled() else theme.TEXT_DISABLED)
        pen = QPen(color, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        cx = self.width() - 16
        cy = self.height() / 2
        painter.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)])
        painter.end()


class Notice(QWidget):
    """One notice row: icon aligned to the first line, text, optional actions at the right.

    Tinted only when it asks for action (``warn`` / ``error``); ``info`` and ``plain``
    explain without alarming.
    """

    _ICONS = {"warn": "warn", "error": "xc", "info": "", "plain": ""}

    def __init__(self, text: str = "", tone: str = "plain", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("notice")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("tone", tone)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)
        self._icon = QLabel()
        self._icon.setFixedSize(16, 20)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        icon_name = self._ICONS.get(tone, "")
        if icon_name:
            colour = theme.WARN if tone == "warn" else theme.ERROR
            self._icon.setPixmap(outline_icon(icon_name, colour, 16).pixmap(16, 16))
            row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        else:
            self._icon.hide()
        self._text = QLabel(text)
        self._text.setObjectName("bodyText")
        self._text.setWordWrap(True)
        self._text.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self._text, 1)
        self._actions = QHBoxLayout()
        self._actions.setSpacing(6)
        row.addLayout(self._actions)

    def set_text(self, text: str) -> None:
        self._text.setText(text)

    def add_action(self, button: QWidget) -> QWidget:
        self._actions.addWidget(button)
        return button


class SettingsRow(QWidget):
    """Label and helper on the left, one control group on the shared right axis.

    Below ``NARROW`` wide the controls drop under the label (a deliberate reflow, not a
    squeeze). Rows draw their own bottom hairline through the stylesheet.
    """

    NARROW = 520

    def __init__(self, label: str = "", helper: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.label = QLabel(label)
        self.label.setObjectName("fieldLabel")
        self.label.setWordWrap(True)
        self.label.setVisible(bool(label))
        self._left = QVBoxLayout()
        self._left.setContentsMargins(0, 0, 0, 0)
        self._left.setSpacing(1)
        self._left.addWidget(self.label)
        self.helper = QLabel(helper)
        self.helper.setObjectName("helperText")
        self.helper.setWordWrap(True)
        self.helper.setVisible(bool(helper))
        self._left.addWidget(self.helper)
        left_host = QWidget()
        left_host.setLayout(self._left)
        left_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._right = QHBoxLayout()
        self._right.setContentsMargins(0, 0, 0, 0)
        self._right.setSpacing(10)
        self._right_host = QWidget()
        self._right_host.setLayout(self._right)
        self._right_host.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self._outer = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._outer.setContentsMargins(0, theme.ROW_PAD, 0, theme.ROW_PAD)
        self._outer.setSpacing(24)
        self._outer.addWidget(left_host, 1)
        self._outer.addWidget(self._right_host, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumHeight(theme.ROW_MIN_HEIGHT)
        self._stacked = False

    # --- content ---
    def set_helper(self, text: str) -> None:
        self.helper.setText(text)
        self.helper.setVisible(bool(text))

    def add_left(self, widget: QWidget) -> QWidget:
        """Extra content under the helper (e.g. a monospace path)."""
        self._left.addWidget(widget)
        return widget

    def add_control(self, widget: QWidget) -> QWidget:
        self._right.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        if self.label.text() and isinstance(widget, (ThemedSwitch, ChevronComboBox)) and not widget.accessibleName():
            widget.setAccessibleName(self.label.text())
        return widget

    def set_disabled_look(self, disabled: bool) -> None:
        if self.property("disabledRow") == disabled:
            return
        set_property(self, "disabledRow", disabled)
        # Descendant selectors (QWidget#settingsRow[disabledRow] QLabel) do not re-polish children by themselves.
        for label in self.findChildren(QLabel):
            label.style().unpolish(label)
            label.style().polish(label)

    # --- reflow ---
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        stacked = self.width() < self.NARROW
        if stacked != self._stacked:
            self._stacked = stacked
            self._outer.setDirection(QBoxLayout.Direction.TopToBottom if stacked else QBoxLayout.Direction.LeftToRight)
            self._outer.setSpacing(8 if stacked else 24)
            self._outer.setAlignment(self._right_host, Qt.AlignmentFlag.AlignLeft if stacked else Qt.AlignmentFlag.AlignVCenter)
            # The direction change happens inside a layout pass: ask the parent to measure this row again.
            self._outer.invalidate()
            self.updateGeometry()


class SettingsGroup(QWidget):
    """A top hairline followed by rows; each row carries its own bottom hairline."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("rowGroup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def add_row(self, row: QWidget) -> QWidget:
        self._layout.addWidget(row)
        return row


class SettingsSection(QWidget):
    """15px heading, optional one-line helper, then a hairline row group."""

    def __init__(self, title: str, helper: str = "", parent: QWidget | None = None, *, with_group: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("settingsSection")
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(0)
        self.heading = QLabel(title)
        self.heading.setObjectName("sectionHeading")
        self.heading.setAccessibleName(title)
        self._column.addWidget(self.heading)
        self.helper = QLabel(helper)
        self.helper.setObjectName("helperText")
        self.helper.setWordWrap(True)
        self.helper.setVisible(bool(helper))
        self._column.addWidget(self.helper)
        self._column.addSpacing(8)
        self.group = SettingsGroup() if with_group else None
        if self.group is not None:
            self._column.addWidget(self.group)

    def title(self) -> str:
        return self.heading.text()

    def add_row(self, row: QWidget) -> QWidget:
        return self.group.add_row(row)

    def add_panel(self, widget: QWidget) -> QWidget:
        self._column.addWidget(widget)
        return widget

    def add_below(self, widget: QWidget, space: int = 12) -> QWidget:
        self._column.addSpacing(space)
        self._column.addWidget(widget)
        return widget


class PageHeader(QWidget):
    """Sticky page header: title, optional subtitle, optional actions at the right."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.PAGE_GUTTER, theme.PAGE_TOP, theme.PAGE_GUTTER + theme.SCROLLBAR_WIDTH, 14)  # right edge = the column's right axis
        row.setSpacing(16)
        self._row = row
        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("pageTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("pageSubtitle")
        self.subtitle_label.setVisible(bool(subtitle))
        texts.addWidget(self.title_label)
        texts.addWidget(self.subtitle_label)
        row.addLayout(texts, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(10)
        row.addLayout(self.actions, 0)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))

    def set_compact(self, compact: bool) -> None:
        gutter = theme.PAGE_GUTTER_COMPACT if compact else theme.PAGE_GUTTER
        self._row.setContentsMargins(gutter, theme.PAGE_TOP, gutter + theme.SCROLLBAR_WIDTH, 14)


class ColumnPage(QWidget):
    """A page: optional sticky header, then a scrolling, left-aligned column (max 716px).

    ``self.column`` is the layout pages add their sections to. Pages are plain widgets
    so the dashboard can stack them and call :meth:`set_compact` on resize.
    """

    def __init__(self, title: str = "", subtitle: str = "", *, sticky_header: bool = True,
                 object_name: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header: PageHeader | None = None
        if sticky_header:
            self.header = PageHeader(title, subtitle)
            outer.addWidget(self.header)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Always reserve the 10px scrollbar gutter so the right axis does not shift between pages.
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.scroll.viewport().setAutoFillBackground(False)
        body = QWidget()
        body.setObjectName("pageBody")
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._margins = QHBoxLayout(body)
        self._margins.setContentsMargins(theme.PAGE_GUTTER, theme.PAGE_TOP if not sticky_header else 22, theme.PAGE_GUTTER, theme.PAGE_BOTTOM)
        self._margins.setSpacing(0)
        self._column_host = QWidget()
        self._column_host.setObjectName("pageColumn")
        self._column_host.setMaximumWidth(theme.COLUMN_MAX_WIDTH)
        self._column_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.column = QVBoxLayout(self._column_host)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(theme.SECTION_GAP)
        self._margins.addWidget(self._column_host, 1, Qt.AlignmentFlag.AlignTop)
        self._margins.addStretch(0)
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)
        self._compact = False
        self._sticky = sticky_header

    def set_max_width(self, width: int) -> None:
        self._column_host.setMaximumWidth(width)

    def set_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        gutter = theme.PAGE_GUTTER_COMPACT if compact else theme.PAGE_GUTTER
        top = 22 if self._sticky else theme.PAGE_TOP
        self._margins.setContentsMargins(gutter, top, gutter, theme.PAGE_BOTTOM)
        if self.header is not None:
            self.header.set_compact(compact)

    def add_section(self, widget: QWidget) -> QWidget:
        self.column.addWidget(widget)
        return widget

    def finish(self) -> None:
        self.column.addStretch(1)


def keycaps(chord: str) -> QWidget:
    """Render ``Shift + C`` as keycaps. The chord comes from settings, never hardcoded."""
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(5)
    parts = [part.strip() for part in str(chord).split("+") if part.strip()]
    for index, part in enumerate(parts):
        if index:
            plus = QLabel("+")
            plus.setObjectName("secondaryText")
            row.addWidget(plus)
        cap = QLabel(part)
        cap.setObjectName("keycap")
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(cap)
    return host


class KeycapDisplay(QWidget):
    """A chord rendered as keycaps with a ``setText`` / ``text`` API like a QLabel.

    The Settings handlers update the displayed chord with ``setText("Shift + C")``.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._text = ""
        self.setText(text)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:  # noqa: N802 - mirrors QLabel
        self._text = str(text)
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._layout.addWidget(keycaps(self._text))
        self.setAccessibleName(f"Hotkey {self._text}")


class MonoPathLabel(QLabel):
    """One-line monospace path, middle-elided, with the full value in the tooltip."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("monoText")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._full = ""
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text or ""
        self.setToolTip(self._full)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def _elide(self) -> None:
        from PySide6.QtGui import QFontMetrics

        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self._full, Qt.TextElideMode.ElideMiddle, max(self.width() - 2, 60)))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()


class StatusGlyph(QWidget):
    """16x20 status marker: filled dot (healthy), ring (neutral), triangle (warn), circled x (error).

    The shape differs per status so the state survives greyscale and colour blindness.
    """

    def __init__(self, status: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._status = status
        self.setFixedSize(16, 20)

    def status(self) -> str:
        return self._status

    def set_status(self, status: str) -> None:
        if status != self._status:
            self._status = status
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        status = self._status
        if status in ("warn", "error"):
            icon = outline_icon("warn" if status == "warn" else "xc", theme.WARN if status == "warn" else theme.ERROR, 16)
            painter.drawPixmap(0, 2, icon.pixmap(16, 16))
        elif status == "ok":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.OK))
            painter.drawEllipse(QRectF(4.5, 6.5, 7, 7))
        else:
            painter.setPen(QPen(QColor(theme.TEXT_MUTED), 1.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(4.7, 6.7, 6.6, 6.6))
        painter.end()


class HealthGridRow(QWidget):
    """One Diagnostics row on a fixed grid: glyph | label | value + detail | action.

    Healthy rows are quiet (small dot, plain value). A row that needs action gains a faint
    tint, a shape glyph, a bold value and its fix button. Below ``NARROW`` the action drops
    under the value.
    """

    NARROW = 560
    LABEL_WIDTH = 140

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("healthRowGrid")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._glyph = StatusGlyph()
        self._label = QLabel(label)
        self._label.setObjectName("healthLabel")
        self._label.setFixedWidth(theme.scaled_px(self.LABEL_WIDTH))
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._value = QLabel("")
        self._value.setObjectName("healthValue")
        self._value.setWordWrap(True)
        self._detail = QLabel("")
        self._detail.setObjectName("healthDetail")
        self._detail.setWordWrap(True)
        self._detail.setVisible(False)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        text.addWidget(self._value)
        text.addWidget(self._detail)
        self._text_host = QWidget()
        self._text_host.setLayout(text)
        self._action_host = QWidget()
        self._action_layout = QHBoxLayout(self._action_host)
        self._action_layout.setContentsMargins(0, 0, 0, 0)
        self._action: QPushButton | None = None
        self._status = "neutral"
        self._outer = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._outer.setContentsMargins(0, 12, 0, 12)
        self._outer.setSpacing(14)
        self._head = QHBoxLayout()
        self._head.setContentsMargins(0, 0, 0, 0)
        self._head.setSpacing(14)
        self._head.addWidget(self._glyph, 0, Qt.AlignmentFlag.AlignTop)
        self._head.addWidget(self._label, 0, Qt.AlignmentFlag.AlignTop)
        self._head.addWidget(self._text_host, 1)
        self._outer.addLayout(self._head, 1)
        self._outer.addWidget(self._action_host, 0, Qt.AlignmentFlag.AlignVCenter)
        self._stacked = False
        self.setMinimumHeight(theme.ROW_MIN_HEIGHT - 4)

    def label(self) -> str:
        return self._label.text()

    def value(self) -> str:
        return self._value.text()

    def status(self) -> str:
        return self._status

    def detail(self) -> str:
        return self._detail.text()

    def action_button(self) -> QPushButton | None:
        return self._action

    def set_item(self, value: str, status: str, detail: str = "", action: QPushButton | None = None) -> None:
        self._status = status
        self._value.setText(value)
        self._detail.setText(detail)
        self._detail.setVisible(bool(detail))
        self._glyph.set_status(status)
        problem = status in ("warn", "error")
        set_property(self, "problem", problem)
        set_property(self._value, "problem", problem)
        self.setAccessibleName(f"{self._label.text()}: {value}")
        if self._action is not None:
            self._action_layout.removeWidget(self._action)
            self._action.hide()
            self._action.setParent(None)
            self._action.deleteLater()
            self._action = None
        if action is not None:
            self._action = action
            self._action_layout.addWidget(action)
        self._action_host.setVisible(action is not None)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # The action drops under the value below NARROW, or sooner when larger text makes the label column,
        # the fix button and a readable value no longer fit side by side.
        # A fixed estimate of the widest fix button, so every row in the grid flips together.
        needed = theme.scaled_px(self.LABEL_WIDTH) + 16 + 28 + theme.scaled_px(110) + 220
        stacked = self.width() < max(self.NARROW, needed)
        if stacked != self._stacked:
            self._stacked = stacked
            self._outer.setDirection(QBoxLayout.Direction.TopToBottom if stacked else QBoxLayout.Direction.LeftToRight)
            self._outer.setAlignment(self._action_host, Qt.AlignmentFlag.AlignLeft if stacked else Qt.AlignmentFlag.AlignVCenter)


class MeasureRow(QWidget):
    """A table row: lead | title + sub | value, with the value right-aligned on the shared axis.

    Used by Analyze Build (next actions, strongest responses, build health). Columns are
    fixed-width where they carry numbers, so every row scans vertically.
    """

    VALUE_WIDTH = 128

    def __init__(self, lead: str = "", title: str = "", sub: str = "", value: str = "", *,
                 lead_width: int = 132, value_width: int = VALUE_WIDTH, tone: str = "",
                 title_name: str = "bodyText", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.lead = QLabel(lead)
        self.lead.setObjectName("measureLead")
        self.lead.setFixedWidth(theme.scaled_px(lead_width))
        self.lead.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.title = QLabel(title)
        self.title.setObjectName(title_name)
        self.title.setWordWrap(True)
        self.sub = QLabel(sub)
        self.sub.setObjectName("helperText")
        self.sub.setWordWrap(True)
        self.sub.setVisible(bool(sub))
        self.value = QLabel(value)
        self.value.setObjectName("measureValue")
        self.value.setFixedWidth(theme.scaled_px(value_width))
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.value.setProperty("tone", tone)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        text.addWidget(self.title)
        text.addWidget(self.sub)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 10, 0, 10)
        row.setSpacing(16)
        row.addWidget(self.lead, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text, 1)
        row.addWidget(self.value, 0, Qt.AlignmentFlag.AlignTop)
        self.lead.setVisible(lead_width > 0)
        self.value.setVisible(value_width > 0)

    def set_texts(self, lead: str, title: str, sub: str, value: str, tone: str = "") -> None:
        self.lead.setText(lead)
        self.title.setText(title)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))
        self.value.setText(value)
        set_property(self.value, "tone", tone)

    def text(self) -> str:
        return " ".join(part for part in (self.lead.text(), self.title.text(), self.sub.text(), self.value.text()) if part)
