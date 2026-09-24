"""UIUX-01 reusable dashboard primitives.

The dashboard used to reuse styling through ~40 loose ``objectName`` conventions and
no shared widgets at all, which is how every label ended up in its own bordered box.
These primitives carry the conventions instead, so grouping is expressed with spacing
and surfaces and a border means "this is interactive".

Every status here renders as dot + text: colour alone is never the carrier.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from exilelens.ui import theme

#: Status name -> the label objectName that paints it.
_STATUS_OBJECT_NAMES = {
    "ok": "statusOk",
    "warn": "statusWarn",
    "error": "statusError",
    "neutral": "statusNeutral",
}

#: Status name -> a text glyph, so the state survives greyscale and colour blindness.
_STATUS_GLYPHS = {
    "ok": "✓",       # check mark
    "warn": "▲",     # up-pointing triangle
    "error": "✕",    # multiplication x
    "neutral": "—",  # em dash
}


def status_color(status: str) -> str:
    return theme.STATUS_COLORS.get(status, theme.NEUTRAL)


def status_glyph(status: str) -> str:
    return _STATUS_GLYPHS.get(status, _STATUS_GLYPHS["neutral"])


class StatusDot(QWidget):
    """A small filled circle. Always paired with text -- never used on its own."""

    def __init__(self, status: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._status = status
        size = theme.STATUS_DOT_SIZE
        self.setFixedSize(size + 4, size + 4)
        self.setObjectName("statusDot")

    def status(self) -> str:
        return self._status

    def set_status(self, status: str) -> None:
        if status == self._status:
            return
        self._status = status
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(status_color(self._status)))
        size = theme.STATUS_DOT_SIZE
        offset = (self.width() - size) // 2
        painter.drawEllipse(offset, (self.height() - size) // 2, size, size)
        painter.end()


class ElidedLabel(QLabel):
    """Middle-elides its text and keeps the full value in the tooltip.

    Filesystem paths used to wrap onto two lines in the primary surface; this keeps
    them on one line and out of the way without hiding them.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_full_text(text)

    def full_text(self) -> str:
        return self._full_text

    def set_full_text(self, text: str) -> None:
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._apply_elision()

    def _apply_elision(self) -> None:
        metrics = QFontMetrics(self.font())
        width = max(self.width() - 2, 40)
        super().setText(metrics.elidedText(self._full_text, Qt.TextElideMode.ElideMiddle, width))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_elision()


class StatusValue(QWidget):
    """Dot + text, for rows like ``Path of Building   Connected``."""

    def __init__(self, text: str = "", status: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dot = StatusDot(status)
        self._wrap = True
        self._full = text
        self._label = QLabel(text)
        self._label.setObjectName(_STATUS_OBJECT_NAMES.get(status, "statusNeutral"))
        self._label.setWordWrap(True)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_SM)
        row.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._label, 1)

    def text(self) -> str:
        return self._label.text()

    def status(self) -> str:
        return self._dot.status()

    def set_word_wrap(self, wrap: bool) -> None:
        self._wrap = bool(wrap)
        self._label.setWordWrap(self._wrap)

    def set_value(self, text: str, status: str = "neutral") -> None:
        self._dot.set_status(status)
        self._full = text
        self._label.setText(text)
        self._label.setObjectName(_STATUS_OBJECT_NAMES.get(status, "statusNeutral"))
        # A changed objectName only repaints after the style is re-resolved.
        self._label.style().unpolish(self._label)
        self._label.style().polish(self._label)


class SectionHeader(QLabel):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title.upper(), parent)
        self.setObjectName("sectionTitle")


class Section(QWidget):
    """A borderless titled group. Grouping is spacing, not an outline."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("section")
        self._title = SectionHeader(title)
        # An empty title means the content is its own heading; adding a label just
        # for structural symmetry ("NEXT") reads as noise.
        self._title.setVisible(bool(title))
        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(theme.ROW_GAP)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.SPACE_MD)
        outer.addWidget(self._title)
        outer.addLayout(self._body)

    def title(self) -> str:
        return self._title.text()

    def add_widget(self, widget: QWidget) -> QWidget:
        self._body.addWidget(widget)
        return widget

    def title_text(self) -> str:
        return self._title.text()

    def add_layout(self, layout) -> None:
        self._body.addLayout(layout)


class SettingRow(QWidget):
    """Label, control, and optional helper text -- none of which get their own box."""

    def __init__(
        self,
        label: str,
        control: QWidget | None = None,
        helper: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingRow")
        self._label = QLabel(label)
        self._label.setObjectName("fieldLabel")
        self.control = control

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.LABEL_GAP)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(theme.SPACE_MD)
        head.addWidget(self._label, 0)
        if control is not None:
            control.setMinimumHeight(theme.CONTROL_HEIGHT)
            head.addWidget(control, 0)
        self._head = head
        head.addStretch(1)
        column.addLayout(head)
        self._column = column

        self._helper = QLabel(helper)
        self._helper.setObjectName("helperText")
        self._helper.setWordWrap(True)
        self._helper.setVisible(bool(helper))
        column.addWidget(self._helper)

        if control is not None:
            self._label.setBuddy(control)

    def set_helper(self, text: str) -> None:
        self._helper.setText(text)
        self._helper.setVisible(bool(text))

    def add_trailing(self, widget: QWidget) -> QWidget:
        """Put an action on the same line as the control it acts on."""
        # Insert before the trailing stretch so the action hugs the control.
        self._head.insertWidget(self._head.count() - 1, widget)
        return widget

    def set_helper_widget(self, widget: QWidget) -> QWidget:
        """Use an externally owned label as this row's helper line."""
        self._helper.setVisible(False)
        self._column.addWidget(widget)
        return widget


class SegmentedControl(QWidget):
    """Exclusive pill selector -- replaces stacks of full-width radio rows.

    The selected value is carried on the button as a Qt property, never parsed back
    out of the visible label.
    """

    changed = Signal(str)

    def __init__(self, options: Sequence[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("segmentGroup")
        # A plain QWidget ignores stylesheet background/border without this.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(3)
        for value, label in options:
            button = QPushButton(label)
            button.setObjectName("segmentButton")
            button.setCheckable(True)
            button.setMinimumHeight(theme.SEGMENT_HEIGHT - 6)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("value", value)
            button.clicked.connect(lambda _checked=False, v=value: self._on_clicked(v))
            self._group.addButton(button)
            self._buttons[value] = button
            row.addWidget(button)
        # Equal-width segments: without this the control reads as one button beside
        # three unrelated text links rather than a single grouped selector.
        #
        # Measured against the *checked* appearance on purpose. The checked segment
        # gains a 1px border and font-weight 700, so sizing from the resting
        # (weight 600) hint made the selected label overflow its own box and clip
        # its first character.
        self._apply_uniform_width(options)

    _SEGMENT_FONT_PX = 12
    #: 14px padding each side + 1px border each side, plus slack for the bold delta.
    _SEGMENT_CHROME = 34

    def _apply_uniform_width(self, options: Sequence[tuple[str, str]]) -> None:
        from PySide6.QtGui import QFont

        bold = QFont(self.font())
        bold.setPixelSize(self._SEGMENT_FONT_PX)
        bold.setWeight(QFont.Weight.Bold)
        metrics = QFontMetrics(bold)
        widest = max(
            (metrics.horizontalAdvance(label) for _value, label in options), default=0
        )
        widest += self._SEGMENT_CHROME
        for button in self._buttons.values():
            button.setMinimumWidth(widest)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def values(self) -> list[str]:
        return list(self._buttons)

    def buttons(self) -> list[QPushButton]:
        return list(self._buttons.values())

    def current_value(self) -> str:
        for value, button in self._buttons.items():
            if button.isChecked():
                return value
        return ""

    def _on_clicked(self, value: str) -> None:
        self.changed.emit(value)

    def set_current_value(self, value: str) -> None:
        """Select without emitting -- used when the model pushes a change back."""
        button = self._buttons.get(value)
        if button is None:
            return
        was_blocked = self._group.signalsBlocked()
        self._group.blockSignals(True)
        for candidate in self._buttons.values():
            candidate.setChecked(candidate is button)
        self._group.blockSignals(was_blocked)


class Disclosure(QWidget):
    """Collapsible 'Technical details' style section, collapsed by default."""

    toggled = Signal(bool)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("disclosure")
        self._title = title
        self.toggle = QToolButton()
        self.toggle.setObjectName("disclosureToggle")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(False)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        # QToolButton treats '&' as a mnemonic marker and swallows it, so
        # "Troubleshooting & diagnostics" rendered as "Troubleshooting  diagnostics".
        self.toggle.setText(title.replace("&", "&&"))
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.toggled.connect(self._on_toggled)

        self.content = QWidget()
        self.content.setObjectName("disclosureContent")
        self._content_layout = QVBoxLayout(self.content)
        self._content_layout.setContentsMargins(0, theme.SPACE_SM, 0, 0)
        self._content_layout.setSpacing(theme.ROW_GAP)
        self.content.setVisible(False)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        column.addWidget(self.content)

    def is_expanded(self) -> bool:
        return self.toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.toggle.setChecked(bool(expanded))

    def add_widget(self, widget: QWidget) -> QWidget:
        self._content_layout.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        self._content_layout.addLayout(layout)

    def _on_toggled(self, checked: bool) -> None:
        self.content.setVisible(checked)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.toggled.emit(checked)


class HealthRow(QWidget):
    """``label   value   status`` -- the user-facing layer of Diagnostics."""

    def __init__(
        self,
        label: str,
        value: str = "",
        status: str = "neutral",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("healthRow")
        self._label = QLabel(label)
        self._label.setObjectName("fieldLabel")
        self._value = StatusValue(value, status)
        # One line: there is ample width beside a 170px label column, and wrapping
        # "UrkaBurkass · loaded just now" onto two lines misreads as two facts.
        # Long explanations go on the detail line instead, never into the value.
        self._value.set_word_wrap(False)
        self._detail = QLabel("")
        self._detail.setObjectName("helperText")
        self._detail.setWordWrap(True)
        self._detail.setVisible(False)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_MD)
        # Fixed label column, then the value. A stretch between them would push the
        # value to the far window edge and break the association at wide sizes.
        self._label.setFixedWidth(170)
        row.addWidget(self._label, 0)
        row.addWidget(self._value, 0)
        row.addStretch(1)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.LABEL_GAP)
        column.addLayout(row)
        column.addWidget(self._detail)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addLayout(column)

    def label(self) -> str:
        return self._label.text()

    def value(self) -> str:
        return self._value.text()

    def status(self) -> str:
        return self._value.status()

    def set_value(self, value: str, status: str = "neutral", detail: str = "") -> None:
        self._value.set_value(value, status)
        self._detail.setText(detail)
        self._detail.setVisible(bool(detail))

    def detail(self) -> str:
        return self._detail.text()


class ThemedCheckBox(QCheckBox):
    """Checkbox that paints its own indicator.

    The native Windows indicator is bright system blue, the one saturated colour in
    an otherwise warm dark UI. Styling it through QSS can recolour the box but not
    draw the tick without an image asset, which would leave "checked" signalled by
    fill colour alone. This paints the tick, so the state survives greyscale.
    """

    _BOX = 15

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtGui import QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        box = self._BOX
        top = (self.height() - box) // 2
        rect_x = 0
        enabled = self.isEnabled()
        checked = self.isChecked()

        if checked and enabled:
            painter.setBrush(QColor(203, 184, 146, 60))
            painter.setPen(QPen(QColor(theme.ACCENT), 1))
        else:
            painter.setBrush(QColor(theme.INPUT_BG))
            painter.setPen(
                QPen(QColor(255, 255, 255, 40 if enabled else 18), 1)
            )
        painter.drawRoundedRect(rect_x, top, box, box, 3, 3)

        if checked:
            tick = QColor(theme.TEXT_EMPHASIS if enabled else theme.TEXT_DISABLED)
            pen = QPen(tick, 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline(
                [
                    QPoint(rect_x + 4, top + 8),
                    QPoint(rect_x + 6, top + 11),
                    QPoint(rect_x + 11, top + 4),
                ]
            )

        painter.setPen(QColor(theme.TEXT if enabled else theme.TEXT_DISABLED))
        text_x = rect_x + box + theme.SPACE_SM
        painter.drawText(
            text_x,
            0,
            max(self.width() - text_x, 0),
            self.height(),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.text(),
        )
        painter.end()

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setHeight(max(hint.height(), theme.CONTROL_HEIGHT - 4))
        return hint


def make_button(text: str, tier: str = "secondary", *, tooltip: str = "") -> QPushButton:
    """Create a button in one of the four explicit tiers."""
    object_names = {
        "primary": "btnPrimary",
        "secondary": "btnSecondary",
        "tertiary": "btnTertiary",
        "destructive": "btnDestructive",
    }
    button = QPushButton(text)
    button.setObjectName(object_names.get(tier, "btnSecondary"))
    button.setMinimumHeight(theme.CONTROL_HEIGHT)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        button.setToolTip(tooltip)
    return button


def button_row(buttons: Iterable[QWidget], *, trailing_stretch: bool = True) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(theme.SPACE_SM)
    for button in buttons:
        row.addWidget(button)
    if trailing_stretch:
        row.addStretch(1)
    return row
