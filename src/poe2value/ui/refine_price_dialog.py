"""Explicit Refine Price surface — interactive, only because the user asked.

The Shift+C overlay stays click-through. This dialog may take focus.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from poe2value.price_check.market_drivers import MatchMode, PriceCheckHypothesis
from poe2value.price_check.presentation import format_comparable_price
from poe2value.ui.window_policy import WindowInteractionPolicy, apply_window_interaction_policy


class RefinePriceDialog(QDialog):
    """PRICE CHECK — REFINE. Checkboxes, floors, MATCH, REFRESH PRICE."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_refresh: Callable[[PriceCheckHypothesis], dict[str, Any] | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("PRICE CHECK — REFINE")
        self.setModal(False)
        apply_window_interaction_policy(self, WindowInteractionPolicy.INTERACTIVE_TOOL)
        self._on_refresh = on_refresh
        self._hypothesis: PriceCheckHypothesis | None = None
        self._boxes: dict[str, QCheckBox] = {}
        self._mins: dict[str, QDoubleSpinBox] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self._title = QLabel("PRICE CHECK — REFINE")
        self._title.setObjectName("sectionTitle")
        self._subtitle = QLabel("")
        self._subtitle.setWordWrap(True)
        root.addWidget(self._title)
        root.addWidget(self._subtitle)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._scroll.setWidget(self._rows_host)
        root.addWidget(self._scroll, 1)

        match_row = QHBoxLayout()
        self._match_all = QRadioButton("MATCH ALL")
        self._match_count = QRadioButton("2 of 3")
        self._match_group = QButtonGroup(self)
        self._match_group.addButton(self._match_all)
        self._match_group.addButton(self._match_count)
        self._match_all.setChecked(True)
        match_row.addWidget(self._match_all)
        match_row.addWidget(self._match_count)
        match_row.addStretch(1)
        root.addLayout(match_row)

        self._refresh = QPushButton("REFRESH PRICE")
        self._refresh.clicked.connect(self._refresh_clicked)
        root.addWidget(self._refresh)

        self._listings = QLabel("")
        self._listings.setWordWrap(True)
        root.addWidget(self._listings)

        self._ignored_title = QLabel("IGNORED BY MARKET SEARCH")
        self._ignored_title.setObjectName("warningTitle")
        self._ignored = QLabel("")
        self._ignored.setWordWrap(True)
        self._ignored.setStyleSheet("color: #8a8074;")
        root.addWidget(self._ignored_title)
        root.addWidget(self._ignored)

        self.resize(460, 520)

    def load_hypothesis(self, hypothesis: PriceCheckHypothesis, presentation: dict[str, Any] | None = None) -> None:
        self._hypothesis = hypothesis
        self._subtitle.setText(hypothesis.search_basis)
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._boxes.clear()
        self._mins.clear()
        for driver in hypothesis.available_drivers:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            box = QCheckBox(driver.label)
            box.setChecked(driver.enabled)
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 99999.0)
            spin.setDecimals(1)
            spin.setValue(float(driver.search_min))
            actual = QLabel(f"item {driver.actual_value:g}")
            layout.addWidget(box, 1)
            layout.addWidget(spin)
            layout.addWidget(actual)
            self._rows.addWidget(row)
            self._boxes[driver.driver_id] = box
            self._mins[driver.driver_id] = spin
        selected_n = len(hypothesis.selected_drivers)
        if hypothesis.match_mode is MatchMode.COUNT:
            self._match_count.setChecked(True)
            self._match_count.setText(f"{hypothesis.count_min or 2} of {max(selected_n, 3)}")
        else:
            self._match_all.setChecked(True)
            self._match_count.setText("2 of 3")
        ignored = hypothesis.ignored_mod_texts
        self._ignored.setText("\n".join(ignored) if ignored else "(none)")
        self._ignored_title.setVisible(True)
        original = (presentation or {}).get("original_auto_summary") or ""
        origin = str((presentation or {}).get("auto_selected_from") or "")
        if (presentation or {}).get("auto_adjusted") and original:
            self._subtitle.setText(f"{hypothesis.search_basis}\nOriginal AUTO: {original}")
        elif origin:
            self._subtitle.setText(f"{hypothesis.search_basis}\nAuto-selected from: {origin}")
        self._render_listings(presentation or {})

    def current_hypothesis(self) -> PriceCheckHypothesis | None:
        if self._hypothesis is None:
            return None
        enabled = [driver_id for driver_id, box in self._boxes.items() if box.isChecked()]
        mins = {driver_id: float(spin.value()) for driver_id, spin in self._mins.items()}
        mode = MatchMode.COUNT if self._match_count.isChecked() else MatchMode.ALL
        count_min = 2 if mode is MatchMode.COUNT else None
        return self._hypothesis.refined(
            enabled_ids=enabled,
            search_mins=mins,
            match_mode=mode,
            count_min=count_min,
        )

    def _refresh_clicked(self) -> None:
        hypothesis = self.current_hypothesis()
        if hypothesis is None or self._on_refresh is None:
            return
        presentation = self._on_refresh(hypothesis)
        if presentation:
            self._hypothesis = hypothesis
            self._subtitle.setText(hypothesis.search_basis)
            self._render_listings(presentation)

    def _render_listings(self, presentation: dict[str, Any]) -> None:
        lines: list[str] = []
        for row in presentation.get("top_comparables") or []:
            text = str(row.get("display") or format_comparable_price(row) or "").strip()
            if text:
                lines.append(f"• {text}")
        title = str(presentation.get("title") or "")
        if title:
            lines.insert(0, title)
        self._listings.setText("\n".join(lines) if lines else "No listings yet — Refresh Price.")
