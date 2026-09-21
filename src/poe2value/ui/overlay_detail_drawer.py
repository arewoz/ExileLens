"""Expanded More Info pane — right side of the same tooltip window."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from poe2value.items.diagnostics import serialize_item_diagnostics
from poe2value.items.more_info import ADVANCED_SECTION_IDS, more_info_for_choice
from poe2value.ui.styles import EMPHASIS_DELTA_COLOR, OVERLAY_WARNING_BODY, VERDICT_CLASS, VERDICT_COLOR

#: Extra vertical gap inserted before each section title beyond the layout's
#: own item spacing, so major sections read as visually separated without
#: loosening the spacing between individual lines inside one section.
_SECTION_GAP = 6

MAX_DRAWER_SECTIONS = 12
MAX_LINES_PER_SECTION = 12
# Not read here -- actual width comes from styles.overlay_detail_width() via
# set_target_width(). Kept in sync for anyone reading this file in isolation.
DETAIL_DRAWER_WIDTH = 350


class DetailAnalysisDrawer(QWidget):
    """Inline expanded analysis to the right of the compact pane."""

    ring_choice_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("detailAnalysisDrawer")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(8)

        self._ring_host = QWidget()
        self._ring_layout = QHBoxLayout(self._ring_host)
        self._ring_layout.setContentsMargins(0, 0, 0, 0)
        self._ring_layout.setSpacing(6)
        self._ring_title = QLabel("COMPARE REPLACEMENT")
        self._ring_title.setObjectName("warningTitle")
        self._ring_buttons: list[QPushButton] = []
        self._ring_host.hide()
        root.addWidget(self._ring_title)
        root.addWidget(self._ring_host)
        self._ring_title.hide()

        self._scroll = QScrollArea()
        self._scroll.setObjectName("moreInfoScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body = QWidget()
        self._body.setObjectName("moreInfoBody")
        self._line_layout = QVBoxLayout(self._body)
        self._line_layout.setContentsMargins(0, 0, 4, 0)
        self._line_layout.setSpacing(8)
        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll, 1)

        self._copy_diagnostics = QPushButton("Copy diagnostics")
        self._copy_diagnostics.setObjectName("copyDiagnosticsButton")
        self._copy_diagnostics.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_diagnostics.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._copy_diagnostics.clicked.connect(self._on_copy_diagnostics)
        self._copy_diagnostics.hide()
        root.addWidget(self._copy_diagnostics, 0, Qt.AlignmentFlag.AlignLeft)

        self._section_widgets: list[QWidget] = []
        self._section_ids: list[str] = []
        self._choices: list[dict[str, Any]] = []
        self._selected_index = 0
        self._base_model: dict[str, Any] = {}
        self._diagnostics_result: dict[str, Any] = {}
        # P1.1c: collapsed by default for a new Item Check result (reset in
        # clear()); preserved across select_choice() (switching which Jewel
        # socket is shown) since that is the same result, just a different
        # replacement candidate within it.
        self._advanced_expanded = False
        self._advanced_toggle: QPushButton | None = None
        self._advanced_container: QWidget | None = None

    @property
    def section_ids(self) -> list[str]:
        return list(self._section_ids)

    @property
    def selected_choice_index(self) -> int:
        return self._selected_index

    def set_target_width(self, width_logical: int) -> None:
        width = max(120, int(width_logical))
        self.setFixedWidth(width)

    def clear(self) -> None:
        self._clear_body()
        self._section_ids.clear()
        self._clear_ring_buttons()
        self._choices = []
        self._selected_index = 0
        self._base_model = {}
        self._diagnostics_result = {}
        self._advanced_expanded = False
        self._copy_diagnostics.setText("Copy diagnostics")
        self._copy_diagnostics.hide()
        self._ring_host.hide()
        self._ring_title.hide()

    def _clear_body(self) -> None:
        for widget in self._section_widgets:
            self._line_layout.removeWidget(widget)
            widget.deleteLater()
        self._section_widgets.clear()
        self._advanced_toggle = None
        self._advanced_container = None

    def _clear_ring_buttons(self) -> None:
        for button in self._ring_buttons:
            self._ring_layout.removeWidget(button)
            button.deleteLater()
        self._ring_buttons.clear()

    def set_content(self, block: dict[str, Any], *, model: dict[str, Any] | None = None) -> None:
        previous_slot = ""
        if self._choices and 0 <= self._selected_index < len(self._choices):
            previous_slot = str(self._choices[self._selected_index].get("slot") or "")
        self.clear()
        block = dict(block or {})
        self._base_model = dict(model or {})
        self._diagnostics_result = dict(self._base_model.pop("_diagnostics_result", {}) or {})
        self._copy_diagnostics.setText("Copy diagnostics")
        self._copy_diagnostics.setVisible(bool(self._diagnostics_result))
        self._choices = list(block.get("replacement_choices") or self._base_model.get("replacement_choices") or [])
        if len(self._choices) > 1:
            self._render_ring_selector()
            if previous_slot:
                restored = next(
                    (
                        index
                        for index, choice in enumerate(self._choices)
                        if str(choice.get("slot") or "") == previous_slot
                    ),
                    None,
                )
                if restored is not None:
                    self._selected_index = restored
                    self._sync_ring_buttons()
                    block = more_info_for_choice(
                        self._base_model or {"replacement_choices": self._choices},
                        self._choices[restored],
                    )
        self._render_sections(block)

    def select_choice(self, index: int, *, notify: bool = True) -> None:
        if not self._choices or index < 0 or index >= len(self._choices):
            return
        if index == self._selected_index and self._section_ids:
            self._sync_ring_buttons()
            return
        self._selected_index = index
        choice = self._choices[index]
        payload = more_info_for_choice(self._base_model or {"replacement_choices": self._choices}, choice)
        self._sync_ring_buttons()
        self._clear_body()
        self._section_ids.clear()
        self._render_sections(payload)
        if notify:
            self.ring_choice_changed.emit(index)

    def _selected_outcome(self) -> dict[str, Any]:
        if self._choices and 0 <= self._selected_index < len(self._choices):
            choice = self._choices[self._selected_index]
            return dict(choice.get("evaluation_outcome") or choice.get("outcome") or {})
        return dict(self._base_model.get("evaluation_outcome") or {})

    def _on_copy_diagnostics(self) -> None:
        if not self._diagnostics_result:
            return
        payload = serialize_item_diagnostics(
            self._diagnostics_result,
            self._base_model,
            selected_outcome=self._selected_outcome(),
        )
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        clipboard.setText(payload)
        self._copy_diagnostics.setText("Copied")

    def _render_ring_selector(self) -> None:
        from poe2value.items.slots import is_jewel_socket_pob_slot, jewel_socket_display_label

        self._ring_title.show()
        self._ring_host.show()
        best_index = 0
        # Jewel sockets are dynamic, per-build tree-node ids ("Jewel 11184") --
        # never player copy (Copy diagnostics carries the raw slot name). An
        # ordinal ("Socket 1", "Socket 2", ...) still lets the player switch
        # between the sockets that were actually checked without exposing
        # implementation identity PoB does not give a real name for.
        is_jewel = bool(self._choices) and is_jewel_socket_pob_slot(str(self._choices[0].get("slot") or ""))
        for index, choice in enumerate(self._choices):
            if choice.get("selected") or choice.get("best"):
                best_index = index
            slot = jewel_socket_display_label(index) if is_jewel else str(choice.get("slot") or f"Slot {index + 1}")
            star = " ★" if choice.get("selected") or choice.get("best") else ""
            verdict = str(choice.get("verdict_label") or "").strip()
            score = choice.get("final_score")
            score_text = f" · {float(score):.0f}" if score is not None else ""
            empty = " · Equip to empty slot" if choice.get("empty") or choice.get("replacing_empty_slot") else ""
            caption = f"{slot}{star}\n{verdict}{score_text}{empty}".strip()
            button = QPushButton(caption)
            button.setObjectName("ringChoiceButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _checked=False, idx=index: self.select_choice(idx))
            self._ring_layout.addWidget(button, 1)
            self._ring_buttons.append(button)
        self._selected_index = best_index
        self._sync_ring_buttons()

    def _sync_ring_buttons(self) -> None:
        for index, button in enumerate(self._ring_buttons):
            button.setChecked(index == self._selected_index)

    def _delta_color(self, row: dict[str, Any]) -> str:
        emphasis = str(row.get("emphasis") or "medium")
        direction = str(row.get("direction") or "neutral")
        palette = EMPHASIS_DELTA_COLOR.get(emphasis, EMPHASIS_DELTA_COLOR["medium"])
        return palette.get(direction, palette["neutral"])

    def _target_layout(self, layout: QVBoxLayout | None) -> QVBoxLayout:
        return layout if layout is not None else self._line_layout

    def _add_section_title(self, title: str, *, advanced: bool = False, layout: QVBoxLayout | None = None) -> None:
        target = self._target_layout(layout)
        if target.count() > 0:
            # Extra breathing room before a new section, on top of the
            # layout's own item spacing -- separates major sections without
            # loosening the spacing between lines inside one section (P1.1c).
            target.addSpacing(_SECTION_GAP)
        label = QLabel(title)
        # P1.1b: advanced/PoB-provenance sections (score drivers, damage
        # reference, native component detail, build flexibility) get a
        # quieter title style so they read as secondary detail -- see
        # items.more_info.ADVANCED_SECTION_IDS. P1.1c additionally renders
        # them inside a collapsed-by-default Advanced disclosure rather than
        # inline (see _render_sections), so this styling now only matters
        # once the player has actually expanded it.
        label.setObjectName("detailSectionTitleAdvanced" if advanced else "detailSectionTitle")
        target.addWidget(label)
        self._section_widgets.append(label)

    def _add_text_block(
        self, text: str, *, object_name: str, color: str = "", layout: QVBoxLayout | None = None
    ) -> None:
        target = self._target_layout(layout)
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        if color:
            label.setStyleSheet(f"color: {color};")
        target.addWidget(label)
        self._section_widgets.append(label)

    def _render_verdict_header(
        self, section: dict[str, Any], block: dict[str, Any], *, layout: QVBoxLayout | None = None
    ) -> None:
        lines = list(section.get("lines") or [])
        if not lines:
            return
        verdict = str((block.get("outcome") or {}).get("verdict") or "")
        css = VERDICT_CLASS.get(verdict, "neutral")
        color = VERDICT_COLOR.get(css, "#b0a890")
        self._add_text_block(lines[0], object_name="verdictLabel", color=color, layout=layout)
        for line in lines[1:]:
            object_name = "scoreSecondary" if line.startswith("Score ") else "whyLabel"
            self._add_text_block(line, object_name=object_name, layout=layout)

    def _render_key_impact(self, section: dict[str, Any], *, layout: QVBoxLayout | None = None) -> None:
        rows = list(section.get("impact_rows") or [])
        if not rows:
            for line in section.get("lines") or []:
                self._add_text_block(str(line), object_name="detailImpactLine", layout=layout)
            return
        for row in rows:
            marker = str(row.get("marker") or "").strip()
            label = str(row.get("label") or "").strip()
            delta = str(row.get("delta_text") or "").strip()
            cap = str(row.get("cap_label") or "").strip()
            color = self._delta_color(row)
            parts = [part for part in (marker, label, delta, cap) if part]
            self._add_text_block("  ".join(parts), object_name="detailImpactLine", color=color, layout=layout)

    def _render_table(self, section: dict[str, Any], *, layout: QVBoxLayout | None = None) -> None:
        target = self._target_layout(layout)
        rows = list(section.get("table_rows") or [])
        if not rows:
            for line in section.get("lines") or []:
                self._add_text_block(str(line), object_name="whyLabel", layout=layout)
            return
        panel = QWidget()
        grid = QGridLayout(panel)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        stat_header = QLabel("")
        stat_header.setObjectName("detailTableHeader")
        grid.addWidget(stat_header, 0, 0)
        for col, heading in enumerate(("CURRENT", "NEW", "CHANGE"), start=1):
            header = QLabel(heading)
            header.setObjectName("detailTableHeader")
            header.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(header, 0, col)
        for row_index, row in enumerate(rows[:MAX_LINES_PER_SECTION], start=1):
            label = QLabel(str(row.get("label") or ""))
            label.setObjectName("detailTableLabel")
            current = QLabel(str(row.get("current") or "—"))
            current.setObjectName("detailTableValue")
            current.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            new = QLabel(str(row.get("new") or "—"))
            new.setObjectName("detailTableValue")
            new.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            change = QLabel(str(row.get("change") or "—"))
            change.setObjectName("detailTableChange")
            change.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            change.setStyleSheet(f"color: {self._delta_color(row)};")
            grid.addWidget(label, row_index, 0)
            grid.addWidget(current, row_index, 1)
            grid.addWidget(new, row_index, 2)
            grid.addWidget(change, row_index, 3)
        target.addWidget(panel)
        self._section_widgets.append(panel)

    def _render_resists(self, section: dict[str, Any], *, layout: QVBoxLayout | None = None) -> None:
        rows = list(section.get("resist_rows") or [])
        if not rows:
            for line in section.get("lines") or []:
                self._add_text_block(str(line), object_name="whyLabel", layout=layout)
            return
        for row in rows:
            marker = str(row.get("marker") or "").strip()
            element = str(row.get("element") or "").strip()
            summary = str(row.get("summary") or "").strip()
            text = f"{marker} {element}: {summary}".strip()
            color = OVERLAY_WARNING_BODY if row.get("warning") else ""
            self._add_text_block(text, object_name="whyLabel", color=color, layout=layout)

    def _render_text_section(self, section: dict[str, Any], *, layout: QVBoxLayout | None = None) -> None:
        for line in section.get("lines") or []:
            self._add_text_block(str(line), object_name="whyLabel", layout=layout)

    def _render_one_section(
        self, section: dict[str, Any], block: dict[str, Any], *, layout: QVBoxLayout, advanced: bool
    ) -> None:
        title = str(section.get("title") or "").strip()
        section_id = str(section.get("id") or title)
        if title:
            self._add_section_title(title, advanced=advanced, layout=layout)
        if section_id == "verdict_header":
            self._render_verdict_header(section, block, layout=layout)
        elif section_id == "key_impact":
            self._render_key_impact(section, layout=layout)
        elif section_id in {"offense", "defense"}:
            self._render_table(section, layout=layout)
        elif section_id == "resists":
            self._render_resists(section, layout=layout)
        else:
            self._render_text_section(section, layout=layout)
        self._section_ids.append(section_id)

    def _advanced_toggle_label(self) -> str:
        arrow = "▾" if self._advanced_expanded else "▸"
        return f"{arrow} Advanced"

    def _on_advanced_toggle_clicked(self) -> None:
        self._advanced_expanded = not self._advanced_expanded
        if self._advanced_container is not None:
            self._advanced_container.setVisible(self._advanced_expanded)
        if self._advanced_toggle is not None:
            self._advanced_toggle.setText(self._advanced_toggle_label())

    def _render_sections(self, block: dict[str, Any]) -> None:
        sections = list(block.get("sections") or [])
        if not sections:
            lines = list(block.get("lines") or [])
            if not lines:
                return
            sections = [{"id": "lines", "title": str(block.get("title") or ""), "lines": lines}]

        normal_sections: list[dict[str, Any]] = []
        advanced_sections: list[dict[str, Any]] = []
        for section in sections[:MAX_DRAWER_SECTIONS]:
            lines = [
                str(line.get("text") if isinstance(line, dict) else line).strip()
                for line in (section.get("lines") or [])
            ]
            lines = [line for line in lines if line]
            if not lines and not section.get("table_rows") and not section.get("impact_rows"):
                continue
            section_id = str(section.get("id") or section.get("title") or "").strip()
            if section_id in ADVANCED_SECTION_IDS:
                advanced_sections.append(section)
            else:
                normal_sections.append(section)

        for section in normal_sections:
            self._render_one_section(section, block, layout=self._line_layout, advanced=False)

        # P1.1c: technical/PoB-provenance detail (build flexibility, score
        # drivers, damage reference, native components) lives behind a
        # collapsed-by-default disclosure rather than inline, so More Info
        # reads as a player-facing explanation of the result first. Nothing
        # is deleted or diagnostics-only -- still one click away, and `Copy
        # diagnostics` is unaffected either way.
        if advanced_sections:
            self._advanced_toggle = QPushButton(self._advanced_toggle_label())
            self._advanced_toggle.setObjectName("advancedToggleButton")
            self._advanced_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            self._advanced_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._advanced_toggle.clicked.connect(self._on_advanced_toggle_clicked)
            if self._line_layout.count() > 0:
                self._line_layout.addSpacing(_SECTION_GAP)
            self._line_layout.addWidget(self._advanced_toggle, 0, Qt.AlignmentFlag.AlignLeft)
            self._section_widgets.append(self._advanced_toggle)

            self._advanced_container = QWidget()
            advanced_layout = QVBoxLayout(self._advanced_container)
            advanced_layout.setContentsMargins(0, 0, 0, 0)
            advanced_layout.setSpacing(8)
            self._advanced_container.setVisible(self._advanced_expanded)
            self._line_layout.addWidget(self._advanced_container)
            self._section_widgets.append(self._advanced_container)

            for section in advanced_sections:
                self._render_one_section(section, block, layout=advanced_layout, advanced=True)
