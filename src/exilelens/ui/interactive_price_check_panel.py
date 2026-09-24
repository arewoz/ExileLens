"""MARKET-03 — the interactive Price Check panel.

One surface. A Price Check session opens it, shows the item immediately, and fills in the market
answer when that arrives, and every filter the search used is editable in place. There is
no second hotkey and no separate Refine dialog on this path.

Three things here are deliberate rather than incidental.

**The panel owns its own generation counter.** It does not borrow the overlay's request
ordering, because the two surfaces have different lifetimes — a pinned panel outlives the
capture that opened it. A stale network completion is dropped, but never silently: it is
logged with both generations and the state being discarded, because "nothing appeared and
nothing said why" is the failure mode this product has already been bitten by.

**Height follows current content, in both directions.** Expanding More Stats grows the
panel and collapsing it shrinks the panel back. Folding the current height into the
measurement is what made the passive overlay one-directional, and it is not repeated here.

**Edits coalesce.** Four fast clicks are one refresh, not four. The panel emits an intent
and never touches the network itself, so nothing here can get around the rate scheduler.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from exilelens.price_check.panel_model import (
    FilterRow,
    PanelState,
    PriceCheckPanelModel,
    RowEmphasis,
)
from exilelens.ui.styles import OVERLAY_STYLESHEET
from exilelens.ui.window_policy import (
    WindowInteractionPolicy,
    apply_native_extended_style,
    apply_window_interaction_policy,
)

logger = logging.getLogger(__name__)

#: Long enough that a burst of clicks becomes one request, short enough to feel live.
EDIT_DEBOUNCE_MS = 350

#: How long an unpinned panel stays after the pointer leaves.
AUTO_HIDE_MS = 2600

PANEL_WIDTH = 460


class FilterRowWidget(QWidget):
    """One editable filter line: checkbox, name, item value, bound, and why.

    Compact by default. The range explanation and tier sit on a second line that is only
    built when there is something to say, so a row with nothing to explain stays one line.
    """

    changed = Signal()

    def __init__(self, row: FilterRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.row = row
        self.setObjectName("priceFilterRow")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 1, 0, 1)
        root.setSpacing(1)

        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)

        self.checkbox = QCheckBox(row.name)
        self.checkbox.setChecked(row.enabled)
        self.checkbox.setEnabled(row.editable)
        self.checkbox.setToolTip(self._tooltip())
        self.checkbox.toggled.connect(lambda _checked: self.changed.emit())
        line.addWidget(self.checkbox, 1)

        self.value_label = QLabel(row.value_text)
        self.value_label.setObjectName("metricLabel")
        line.addWidget(self.value_label)

        self.minimum = QDoubleSpinBox()
        self.minimum.setObjectName("filterBound")
        self.minimum.setDecimals(0)
        self.minimum.setRange(-99999, 99999)
        self.minimum.setPrefix("min ")
        self.minimum.setKeyboardTracking(False)
        self.minimum.setValue(float(row.minimum if row.minimum is not None else 0))
        self.minimum.setVisible(row.minimum is not None)
        self.minimum.setEnabled(row.editable)
        self.minimum.valueChanged.connect(lambda _value: self.changed.emit())
        line.addWidget(self.minimum)

        self.maximum = QDoubleSpinBox()
        self.maximum.setObjectName("filterBound")
        self.maximum.setDecimals(0)
        self.maximum.setRange(-99999, 99999)
        self.maximum.setPrefix("max ")
        self.maximum.setKeyboardTracking(False)
        self.maximum.setValue(float(row.maximum if row.maximum is not None else 0))
        self.maximum.setVisible(row.maximum is not None)
        self.maximum.setEnabled(row.editable)
        self.maximum.valueChanged.connect(lambda _value: self.changed.emit())
        line.addWidget(self.maximum)

        root.addLayout(line)

        note = " · ".join(part for part in (row.range_note, row.coverage_note) if part)
        if note:
            self.note_label = QLabel(note)
            self.note_label.setObjectName("baseLabel")
            self.note_label.setWordWrap(True)
            root.addWidget(self.note_label)
        else:
            self.note_label = None

        if row.emphasis is RowEmphasis.REQUIRED:
            self.checkbox.setObjectName("requiredFilter")
        elif row.emphasis is RowEmphasis.DETAIL:
            self.checkbox.setObjectName("detailFilter")

    def _tooltip(self) -> str:
        parts = [self.row.tier_note, self.row.range_note, self.row.coverage_note]
        return "\n".join(part for part in parts if part)

    def state(self) -> dict[str, Any]:
        """The row's current values.

        Keyed on whether the model gave this row a bound, not on whether the spin box is
        on screen: a widget in a window that has not been shown yet reports itself
        invisible, which would silently drop every edited bound.
        """
        return {
            "key": self.row.key,
            "enabled": self.checkbox.isChecked(),
            "minimum": self.minimum.value() if self.row.minimum is not None else None,
            "maximum": self.maximum.value() if self.row.maximum is not None else None,
        }


class InteractivePriceCheckPanel(QWidget):
    """The MARKET-03 Price Check surface."""

    #: The user changed something. Payload is the full edited filter state.
    refresh_requested = Signal(dict)
    pin_toggled = Signal(bool)
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("overlayRoot")
        self.setStyleSheet(OVERLAY_STYLESHEET)
        apply_window_interaction_policy(
            self, WindowInteractionPolicy.INTERACTIVE_PIN_AFFORDANCE, activate_on_show=False
        )
        self.setFixedWidth(PANEL_WIDTH)

        self._generation = 0
        self._model: PriceCheckPanelModel | None = None
        self._rows: list[FilterRowWidget] = []
        self._more_expanded = False
        self._pinned = False
        self._user_refined = False

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(EDIT_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit_refresh)

        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.setInterval(AUTO_HIDE_MS)
        self._auto_hide.timeout.connect(self._auto_hide_now)

        # Qt serves a layout's size hint from cache until the new content has been laid
        # out, so the measurement taken during a render still describes the previous
        # content. This re-measures once the event loop has caught up.
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(0)
        self._settle.timeout.connect(self._fit_to_content)

        self._build()

    # -- construction ------------------------------------------------------------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(6)

        self._item_name = QLabel("")
        self._item_name.setObjectName("nameLabel")
        self._item_name.setWordWrap(True)
        root.addWidget(self._item_name)

        self._base_line = QLabel("")
        self._base_line.setObjectName("baseLabel")
        self._base_line.setWordWrap(True)
        root.addWidget(self._base_line)

        price_row = QHBoxLayout()
        price_row.setContentsMargins(0, 4, 0, 0)
        self._trust_label = QLabel("")
        self._trust_label.setObjectName("sectionTitle")
        price_row.addWidget(self._trust_label, 1)
        self._price = QLabel("")
        self._price.setObjectName("baselineLabel")
        price_row.addWidget(self._price)
        root.addLayout(price_row)

        self._state_line = QLabel("")
        self._state_line.setObjectName("baseLabel")
        self._state_line.setWordWrap(True)
        root.addWidget(self._state_line)

        self._trust_note = QLabel("")
        self._trust_note.setObjectName("baseLabel")
        self._trust_note.setWordWrap(True)
        root.addWidget(self._trust_note)

        self._compare = QLabel("")
        self._compare.setObjectName("profileChip")
        self._compare.setWordWrap(True)
        root.addWidget(self._compare)

        self._required_title = QLabel("REQUIRED")
        self._required_title.setObjectName("sectionTitle")
        root.addWidget(self._required_title)
        self._required_host, self._required_layout = self._section(root)

        self._group_host, self._group_layout = self._section(root)

        self._limitations = QLabel("")
        self._limitations.setObjectName("warningTitle")
        self._limitations.setWordWrap(True)
        root.addWidget(self._limitations)

        self._more_toggle = QPushButton("▸ MORE STATS")
        self._more_toggle.setObjectName("pinAffordanceButton")
        self._more_toggle.setFlat(True)
        self._more_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_toggle.clicked.connect(self._toggle_more)
        root.addWidget(self._more_toggle)
        self._more_host, self._more_layout = self._section(root)
        self._more_host.setVisible(False)

        self._comparables_title = QLabel("COMPARABLES")
        self._comparables_title.setObjectName("sectionTitle")
        root.addWidget(self._comparables_title)
        self._comparables_host, self._comparables_layout = self._section(root)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self._pin_button = QPushButton("PIN")
        self._pin_button.setObjectName("pinAffordanceButton")
        self._pin_button.setFlat(True)
        self._pin_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pin_button.clicked.connect(self._toggle_pin)
        footer.addWidget(self._pin_button)
        self._close_button = QPushButton("CLOSE")
        self._close_button.setObjectName("pinAffordanceButton")
        self._close_button.setFlat(True)
        self._close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_button.clicked.connect(self.close_panel)
        footer.addWidget(self._close_button)
        root.addLayout(footer)

    def _section(self, root: QVBoxLayout) -> tuple[QWidget, QVBoxLayout]:
        host = QWidget()
        host.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        root.addWidget(host)
        return host, layout

    # -- generations -------------------------------------------------------------

    @property
    def generation(self) -> int:
        return self._generation

    def adopt_generation(self, generation: int) -> None:
        """Accept a generation minted elsewhere.

        The controller session mints generations so every async completion can carry the
        one it belongs to. The panel never moves backwards, so a late adopt cannot
        re-open the door to an update it has already rejected.
        """
        self._generation = max(self._generation, int(generation))

    def begin_generation(self) -> int:
        """Claim the panel for a new capture. Older updates stop applying."""
        self._generation += 1
        self._user_refined = False
        return self._generation

    def _accepts(self, generation: int, state: PanelState) -> bool:
        if generation >= self._generation:
            return True
        logger.info(
            "price_check_panel_stale_update_dropped incoming_generation=%s "
            "current_generation=%s dropped_state=%s",
            generation,
            self._generation,
            state.value,
        )
        return False

    # -- rendering ---------------------------------------------------------------

    def open_for_capture(
        self, generation: int, *, item_name: str, base_line: str = "", state_text: str = ""
    ) -> None:
        """Show the item the instant it is captured, before the market is asked.

        Immediate acknowledgement matters more than completeness here: a Shift+C that
        produces nothing on screen is indistinguishable from a Shift+C that did not fire.
        """
        if not self._accepts(generation, PanelState.CAPTURED):
            return
        self._item_name.setText(item_name)
        self._base_line.setText(base_line)
        self._base_line.setVisible(bool(base_line))
        self._trust_label.setText("")
        self._price.setText("")
        self._trust_note.setText("")
        self._trust_note.setVisible(False)
        self._state_line.setText(state_text or "Checking market…")
        self._state_line.setVisible(True)
        self._compare.setVisible(False)
        self._limitations.setVisible(False)
        for layout in (self._required_layout, self._group_layout, self._more_layout, self._comparables_layout):
            self._clear(layout)
        self._rows.clear()
        self._required_title.setVisible(False)
        self._more_toggle.setVisible(False)
        self._comparables_title.setVisible(False)
        self._fit_to_content()
        self._settle.start()
        self.show_panel()

    def apply_presentation_fallback(self, generation: int, presentation: dict[str, Any]) -> bool:
        """Render league/queue/error states that do not have a full panel model yet."""
        title = str(presentation.get("title") or "PRICE CHECK")
        headline = str(
            presentation.get("headline")
            or presentation.get("disclaimer")
            or presentation.get("blocker")
            or ""
        )
        if generation:
            self.adopt_generation(generation)
        self._item_name.setText(title)
        self._base_line.setText("")
        self._base_line.setVisible(False)
        self._trust_label.setText("")
        self._price.setText("")
        self._trust_note.setText("")
        self._state_line.setText(headline or title)
        self._state_line.setVisible(bool(headline or title))
        self._compare.setVisible(False)
        self._limitations.setVisible(False)
        for layout in (self._required_layout, self._group_layout, self._more_layout, self._comparables_layout):
            self._clear(layout)
        self._rows.clear()
        self._required_title.setVisible(False)
        self._more_toggle.setVisible(False)
        self._comparables_title.setVisible(False)
        self._fit_to_content()
        self.show_panel()
        return True

    def apply_model(self, generation: int, model: PriceCheckPanelModel) -> bool:
        """Render a model. Returns False when the update was stale and dropped."""
        if not self._accepts(generation, model.state):
            return False
        self.adopt_generation(generation)
        self._model = model

        self._item_name.setText(model.item_name)
        self._base_line.setText(model.base_line)
        self._base_line.setVisible(bool(model.base_line))

        trust_styles = {
            "HIGH CONFIDENCE": "trustHigh",
            "ASSISTED ESTIMATE": "trustAssisted",
            "NEEDS REFINEMENT": "trustNeeds",
        }
        self._trust_label.setObjectName(trust_styles.get(model.trust_label, "sectionTitle"))
        self._trust_label.style().unpolish(self._trust_label)
        self._trust_label.style().polish(self._trust_label)
        self._trust_label.setText(model.trust_label)
        self._trust_label.setVisible(bool(model.trust_label))
        self._price.setText(model.price_text)
        self._price.setVisible(bool(model.price_text))

        listing_note = f"{model.listing_count} comparable listings" if model.listing_count else ""
        state_text = model.state_text if model.state is not PanelState.READY else listing_note
        self._state_line.setText(state_text)
        self._state_line.setVisible(bool(state_text))

        self._trust_note.setText(model.trust_note)
        self._trust_note.setVisible(bool(model.trust_note))

        compare = model.compare_text
        if model.compare_detail:
            compare = f"{compare} · {model.compare_detail}"
        self._compare.setText(compare)
        self._compare.setVisible(bool(compare))

        self._rows.clear()
        self._clear(self._required_layout)
        for row in model.required:
            self._required_layout.addWidget(self._make_row(row))
        self._required_title.setVisible(bool(model.required))
        self._required_host.setVisible(bool(model.required))

        self._clear(self._group_layout)
        for group in model.substitutable:
            caption = QLabel(group.caption.upper())
            caption.setObjectName("sectionTitle")
            self._group_layout.addWidget(caption)
            for row in group.rows:
                self._group_layout.addWidget(self._make_row(row))
            if group.limitation:
                warning = QLabel(f"⚠ {group.limitation}")
                warning.setObjectName("warningTitle")
                warning.setWordWrap(True)
                self._group_layout.addWidget(warning)
        self._group_host.setVisible(bool(model.substitutable))

        limitation_text = "\n".join(f"⚠ {line}" for line in model.limitations)
        self._limitations.setText(limitation_text)
        self._limitations.setVisible(bool(limitation_text) and model.serious_limitation)

        self._more_toggle.setVisible(bool(model.more_stats))
        self._rebuild_more_stats()

        self._clear(self._comparables_layout)
        for comparable in model.comparables:
            line = QHBoxLayout()
            price = QLabel(comparable.price_text)
            price.setObjectName("metricLabel")
            line.addWidget(price)
            stats = QLabel(comparable.stats_text)
            stats.setObjectName("baseLabel")
            stats.setWordWrap(True)
            line.addWidget(stats, 1)
            holder = QWidget()
            holder.setLayout(line)
            line.setContentsMargins(0, 0, 0, 0)
            if comparable.is_closest:
                holder.setObjectName("closestComparable")
            self._comparables_layout.addWidget(holder)
        self._comparables_title.setVisible(bool(model.comparables))
        self._comparables_host.setVisible(bool(model.comparables))

        self._fit_to_content()
        self._settle.start()
        return True

    def _make_row(self, row: FilterRow) -> FilterRowWidget:
        widget = FilterRowWidget(row, self)
        widget.changed.connect(self._on_edit)
        self._rows.append(widget)
        return widget

    @staticmethod
    def _clear(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    # -- geometry ----------------------------------------------------------------

    def settle_layout(self) -> None:
        """Re-measure now. Runtime does this on a timer; tests call it directly."""
        self._settle.stop()
        self._fit_to_content()

    def _fit_to_content(self) -> None:
        """Height from the current hint alone, so the panel shrinks as well as grows."""
        layout = self.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.adjustSize()
        hint = self.sizeHint().height()
        if hint <= 0:
            hint = max(self.height(), 1)
        self.setFixedHeight(max(1, hint))
        self._clamp_to_screen()

    def _clamp_to_screen(self) -> None:
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        if self.height() > available.height():
            self.setFixedHeight(available.height())
        x = min(max(self.x(), available.left()), max(available.left(), available.right() - self.width()))
        y = min(max(self.y(), available.top()), max(available.top(), available.bottom() - self.height()))
        if (x, y) != (self.x(), self.y()):
            self.move(QPoint(int(x), int(y)))

    def place_near(self, anchor: tuple[int, int] | None) -> None:
        if anchor is None:
            return
        self.move(QPoint(int(anchor[0]) + 18, int(anchor[1]) + 18))
        self._clamp_to_screen()

    # -- interaction -------------------------------------------------------------

    def _toggle_more(self) -> None:
        self._more_expanded = not self._more_expanded
        self._rebuild_more_stats()
        self._fit_to_content()
        self._settle.start()

    def _rebuild_more_stats(self) -> None:
        """Populate the section only while it is open.

        A hidden section still contributed to the panel's size hint, so collapsing left
        the window taller than the compact layout needs. Clearing it removes the thing
        being measured instead of asking Qt to ignore it.
        """
        rows = self._model.more_stats if self._model else ()
        keep = [row for row in self._rows if not self._in_layout(row, self._more_layout)]
        self._clear(self._more_layout)
        self._rows = keep
        if self._more_expanded:
            for row in rows:
                self._more_layout.addWidget(self._make_row(row))
        self._more_host.setVisible(self._more_expanded and bool(rows))
        self._more_toggle.setText(
            f"{'▾' if self._more_expanded else '▸'} MORE STATS ({len(rows)})"
        )

    @staticmethod
    def _in_layout(widget: QWidget, layout: QVBoxLayout) -> bool:
        return any(layout.itemAt(index).widget() is widget for index in range(layout.count()))

    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        self._pin_button.setText("UNPIN" if self._pinned else "PIN")
        if self._pinned:
            self._auto_hide.stop()
        self.pin_toggled.emit(self._pinned)

    @property
    def pinned(self) -> bool:
        return self._pinned

    @property
    def user_refined(self) -> bool:
        return self._user_refined

    def _on_edit(self) -> None:
        """Any edit makes the plan the user's. Automatic broadening stops there."""
        self._user_refined = True
        self._debounce.start()

    def _emit_refresh(self) -> None:
        self.refresh_requested.emit(self.filter_state())

    def filter_state(self) -> dict[str, Any]:
        return {
            "generation": self._generation,
            "user_refined": self._user_refined,
            "filters": [row.state() for row in self._rows],
        }

    def flush_pending_edits(self) -> bool:
        """Apply a queued refresh now. Used by tests and by an explicit refresh control."""
        if not self._debounce.isActive():
            return False
        self._debounce.stop()
        self._emit_refresh()
        return True

    @property
    def refresh_pending(self) -> bool:
        return self._debounce.isActive()

    # -- lifetime ----------------------------------------------------------------

    def show_panel(self) -> None:
        self.show()
        apply_native_extended_style(self, WindowInteractionPolicy.INTERACTIVE_PIN_AFFORDANCE)
        self.raise_()

    def close_panel(self) -> None:
        self._debounce.stop()
        self._auto_hide.stop()
        self.hide()
        self.closed.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close_panel()
            return
        super().keyPressEvent(event)

    def enterEvent(self, event: QEvent) -> None:  # noqa: N802
        self._auto_hide.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        if not self._pinned:
            self._auto_hide.start()
        super().leaveEvent(event)

    def _auto_hide_now(self) -> None:
        if not self._pinned:
            self.hide()
