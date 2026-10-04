"""Analyze Build page: what the loaded PoB build responds to, at a glance.

Reading order is the product order: which build and how fresh, the current focus and the next actions, the strongest
measured responses, then build health, stat priorities and per-slot detail. All wording comes from `analysis.view`; this module only lays it out.
The analysis itself is explicit (the button) and asynchronous; nothing here runs on Item Check.
"""

from __future__ import annotations

import html
import json
import time
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from exilelens.analysis.catalog import ProbeCatalog
from exilelens.analysis.view import build_analysis_view, build_slot_view, display_name, progress_text, slot_row_texts
from exilelens.ui import theme
import re

from exilelens.ui.components import StatusValue, ThemedCheckBox, make_button
from exilelens.ui.dashboard_widgets import ColumnPage, MeasureRow, SettingsGroup, WrapLabel, set_property
from exilelens.ui.redesign_style import REDESIGN_STYLESHEET
from exilelens.ui.styles import DASHBOARD_STYLESHEET, apply_exile_lens_chrome
from exilelens.ui.window_policy import WindowInteractionPolicy, apply_native_extended_style, apply_window_interaction_policy

IDLE, RUNNING, CURRENT, STALE, ERROR = "IDLE", "RUNNING", "CURRENT", "STALE", "ERROR"

_INTRO = (
    "Tests how your build responds to common stats. Runs in the background, never during Item Check."
)
_MAX_FIX_FIRST = 4


def _esc(text: Any) -> str:
    return html.escape(str(text or ""))


class _ResponseRow(MeasureRow):
    """One strongest measured response: what was measured, the tested change, and its measured result."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", "", "", "", parent=parent)
        # Keep the attribute names the tile had: callers and tests read caption / value / change / note.
        self.caption = self.lead
        self.change = self.title
        self.note = self.sub

    def set_tile(self, tile: dict[str, Any]) -> None:
        caption = str(tile.get("caption") or "")
        self._raw_caption = caption  # the view model's own wording, kept for text()
        # Captions arrive upper-case from the view model ("EHP · MAX HIT"); the page shows sentence case.
        shown = caption.title().replace("Ehp", "EHP") if caption.isupper() else caption
        self.caption.setText(shown)
        measured = bool(tile.get("measured"))
        value = str(tile.get("value") or "")
        self.value.setText(value or "—")
        set_property(self.value, "tone", "" if measured else "muted")
        self.change.setText(str(tile.get("change") or ""))
        self.note.setText(str(tile.get("note") or ""))
        self.note.setVisible(bool(self.note.text()))
        self.setToolTip(str(tile.get("tested_change") or ""))  # the exact tested line behind the short form

    def text(self) -> str:
        parts = (getattr(self, "_raw_caption", self.caption.text()), self.value.text() if self.value.text() != "—" else "", self.change.text(), self.note.text())
        return " ".join(part for part in parts if part)


class _ActionRow(MeasureRow):
    """One next action: rank, title with its summary beneath, and the measured result at the right axis."""

    _RESULT = re.compile(r"\s*→\s*([+-]?\d+(?:\.\d+)?%)\s*$")

    def __init__(self, number: Any, title: str, summary: str, fix: bool, parent: QWidget | None = None) -> None:
        match = self._RESULT.search(summary or "")
        value = match.group(1) if match else ""
        sub = self._RESULT.sub("", summary or "") if match else (summary or "")
        super().__init__(f"{number}", title, sub, value, lead_width=22, tone="ok" if value else "", title_name="fieldLabel", parent=parent)
        self._plain = f"{number}. {title} — {summary}"
        self.setObjectName("settingsRow")
        self.setProperty("fix", bool(fix))

    def text(self) -> str:  # the shipped one-line form, used by tests and accessibility
        return self._plain


class _HealthLine(MeasureRow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", "", "", "", lead_width=132, value_width=170, parent=parent)

    def set_row(self, row: dict[str, Any]) -> None:
        tone = {"warn": "warn", "ok": "ok", "neutral": "muted", "muted": "muted"}.get(str(row.get("tone")), "")
        self.set_texts(str(row.get("title") or ""), str(row.get("reason") or ""), "", str(row.get("state") or ""), tone)
        self.lead.setObjectName("fieldLabel")


class AnalysisWindow(ColumnPage):
    def __init__(
        self,
        controller: Any,
        parent: QWidget | None = None,
        *,
        embedded: bool = False,
        navigate: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__("Analyze Build", sticky_header=True, object_name="analysisPage", parent=parent)
        self.controller = controller
        self._navigate = navigate
        self._embedded = embedded
        if not embedded:
            self.setWindowTitle("Analyze Build")
            apply_window_interaction_policy(self, WindowInteractionPolicy.INTERACTIVE_TOOL)
            self.setObjectName("dashboardRoot")
            self.setStyleSheet(DASHBOARD_STYLESHEET + REDESIGN_STYLESHEET)
            apply_exile_lens_chrome(self)
            self.resize(920, 640)
        self._result: dict[str, Any] | None = None
        self._view: dict[str, Any] = {}
        self._slots: list[dict[str, Any]] = []
        self._rows: list[int] = []
        # M5.3: row 0 is the Build Priorities summary when present; slot rows follow.
        self._has_priorities = False
        self._state = IDLE
        self._analyzed_at: float | None = None
        self._run_id: Any = None
        self._probe_labels = {d.probe_id: d.label for d in ProbeCatalog().all()}
        self.set_max_width(808)

        # --- header: which build, how fresh, and the one action ---------------------
        self._analyze_btn = make_button("Analyze Build", "primary")
        self._analyze_btn.clicked.connect(self._rerun)
        self._diagnostics_btn = make_button("Open Diagnostics", "tertiary")
        self._diagnostics_btn.clicked.connect(lambda: self._navigate("diagnostics") if self._navigate else None)
        self._diagnostics_btn.setVisible(False)
        self._header = self.header.subtitle_label  # "[build] · [main skill] · [context]"; the full path is its tooltip
        self._header.setVisible(True)
        self._status = StatusValue("Not analyzed yet", "neutral")
        self._status.set_word_wrap(False)
        self.header.actions.addWidget(self._status)
        self.header.actions.addSpacing(6)
        self.header.actions.addWidget(self._diagnostics_btn)
        self.header.actions.addWidget(self._analyze_btn)
        self._progress = WrapLabel(_INTRO)
        self._progress.setObjectName("bodyText")
        self._progress.setMaximumWidth(620)
        self._progress.setContentsMargins(0, 0, 0, 14)  # breathing room above the first section
        self.column.addWidget(self._progress)
        self.column.setSpacing(0)

        def section(title: str, caption: str = "") -> tuple[QWidget, QVBoxLayout]:
            host = QWidget()
            layout = QVBoxLayout(host)
            layout.setContentsMargins(0, theme.SECTION_GAP, 0, 0)
            layout.setSpacing(0)
            heading = QLabel(title)
            heading.setObjectName("sectionHeading")
            layout.addWidget(heading)
            if caption:
                note = QLabel(caption)
                note.setObjectName("helperText")
                note.setWordWrap(True)
                layout.addWidget(note)
            layout.addSpacing(8)
            host.setVisible(False)
            host.heading = heading  # type: ignore[attr-defined]
            return host, layout

        # --- current focus and next actions --------------------------------------------------
        self._overview_host = QWidget()
        overview = QVBoxLayout(self._overview_host)
        overview.setContentsMargins(0, 0, 0, 0)
        overview.setSpacing(0)
        self._focus_card = QWidget()  # kept as an attribute name; no longer a card
        self._focus_card.setObjectName("analysisFocus")
        focus = QVBoxLayout(self._focus_card)
        focus.setContentsMargins(0, 4, 0, 0)
        focus.setSpacing(2)
        self._focus_title = QLabel("Current focus")
        self._focus_title.setObjectName("helperText")
        self._focus_headline = QLabel("")
        self._focus_headline.setObjectName("focusHeadline")
        self._focus_headline.setWordWrap(True)
        self._focus_detail = QLabel("")
        self._focus_detail.setObjectName("leadText")
        self._focus_detail.setWordWrap(True)
        for widget in (self._focus_title, self._focus_headline, self._focus_detail):
            focus.addWidget(widget)
        overview.addWidget(self._focus_card)
        self._actions_card = QWidget()
        self._actions_card.setObjectName("analysisActions")
        actions_host = QVBoxLayout(self._actions_card)
        actions_host.setContentsMargins(0, theme.SECTION_GAP, 0, 0)
        actions_host.setSpacing(0)
        actions_title = QLabel("Next actions")
        actions_title.setObjectName("sectionHeading")
        actions_host.addWidget(actions_title)
        actions_host.addSpacing(8)
        self._actions_group = SettingsGroup()
        actions_host.addWidget(self._actions_group)
        overview.addWidget(self._actions_card)
        self._action_labels: list[Any] = []
        self._overview_host.setVisible(False)
        self.column.addWidget(self._overview_host)

        # --- strongest measured responses ------------------------------------------------------
        self._strongest_host, strongest_layout = section("Strongest measured responses")
        self._strongest_title = self._strongest_host.heading  # type: ignore[attr-defined]
        self._tiles: list[_ResponseRow] = []
        self._strongest_group = SettingsGroup()
        strongest_layout.addWidget(self._strongest_group)
        self._strongest_note = QLabel("")
        self._strongest_note.setObjectName("helperText")
        self._strongest_note.setWordWrap(True)
        self._strongest_note.setContentsMargins(0, 8, 0, 0)
        strongest_layout.addWidget(self._strongest_note)
        self.column.addWidget(self._strongest_host)

        # --- build health --------------------------------------------------------------------------
        self._health_host, health_layout = section("Build health")
        self._health_group = SettingsGroup()
        health_layout.addWidget(self._health_group)
        self._health_lines: list[_HealthLine] = []
        self.column.addWidget(self._health_host)

        # --- analysis coverage -----------------------------------------------------------------------
        self._coverage_host, coverage_layout = section("Analysis coverage")
        self._coverage_lines = QVBoxLayout()
        self._coverage_lines.setContentsMargins(0, 0, 0, 0)
        self._coverage_lines.setSpacing(4)
        coverage_layout.addLayout(self._coverage_lines)
        self.column.addWidget(self._coverage_host)

        # --- upgrade opportunities and details ------------------------------------------------------------
        self._list = QListWidget()
        self._list.setAccessibleName("Upgrade opportunities")
        self._list.setWordWrap(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setMinimumWidth(190)
        self._detail = QTextEdit()
        self._detail.setAccessibleName("Upgrade opportunity details")
        self._detail.setReadOnly(True)
        # Text wraps to the pane; the page never needs a horizontal scrollbar.
        self._detail.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._detail.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        splitter = QSplitter()
        splitter.addWidget(self._list)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setChildrenCollapsible(False)
        splitter.setFixedHeight(380)

        # Advanced actions: quiet by default, and the two exports only appear with the measurement details.
        self._slot_selected = False
        self._details_toggle = ThemedCheckBox("Show measurement details")
        self._details_toggle.setObjectName("advancedToggle")
        self._details_toggle.toggled.connect(self._on_details_toggled)
        self._copy_btn = make_button("Copy Search Intent", "tertiary", compact=True)
        self._copy_btn.clicked.connect(self._copy_intent)
        self._export_btn = make_button("Export JSON", "tertiary", compact=True)
        self._export_btn.clicked.connect(self._export_json)
        self._export_btn.setEnabled(False)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(theme.SPACE_SM)
        footer.addWidget(self._details_toggle)
        footer.addStretch(1)
        footer.addWidget(self._copy_btn)
        footer.addWidget(self._export_btn)
        self._set_copy_available(False)

        # Nothing to browse before the first analysis: no empty list, no empty detail pane.
        self._body = QWidget()
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, theme.SECTION_GAP, 0, 0)
        body.setSpacing(0)
        self._upgrade_heading = QLabel("Upgrade opportunities")
        self._upgrade_heading.setObjectName("sectionHeading")
        body.addWidget(self._upgrade_heading)
        body.addSpacing(8)
        body.addWidget(splitter)
        body.addSpacing(8)
        body.addLayout(footer)
        self._body.setVisible(False)
        self.column.addWidget(self._body)
        self.finish()

        self._list.currentRowChanged.connect(self._show_slot)
        started = getattr(controller, "build_analysis_started", None) or controller.analysis_started
        started.connect(self._on_started)
        controller.analysis_progress.connect(self._on_progress)
        controller.analysis_finished.connect(self.show_result)
        controller.analysis_error.connect(self._on_error)
        controller.analysis_stale.connect(self._on_stale)
        for name in ("build_changed", "baseline_state_changed"):
            signal = getattr(controller, name, None)
            if signal is not None:
                signal.connect(lambda *_args: self._refresh_chrome())
        self._refresh_chrome()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._embedded:
            apply_native_extended_style(self, WindowInteractionPolicy.INTERACTIVE_TOOL)
        self._refresh_chrome()

    # --- state -------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    def _build_ready(self) -> bool:
        info = getattr(self.controller, "build_info", None)
        return True if info is None else bool(getattr(info, "is_ready", False))

    def _build_name(self) -> str:
        if self._view:
            return str(self._view["build"]["name"])
        return display_name(getattr(getattr(self.controller, "build_info", None), "name", ""))

    def _set_state(self, state: str, detail: str = "") -> None:
        self._state = state
        self._refresh_chrome(detail)

    def _refresh_chrome(self, detail: str = "") -> None:
        """Header, freshness and the action button for the current state. No technical identifiers."""
        build = self._view.get("build") or {}
        parts = [self._build_name() or "No build loaded", build.get("main_skill"), build.get("loadout"), build.get("context")]
        self._header.setText(" · ".join(str(part) for part in parts if part))
        self._header.setToolTip(str(build.get("source_path") or ""))  # the file path is one hover away, not in the header
        ready = self._build_ready()
        state = self._state
        self._diagnostics_btn.setVisible(state == ERROR and self._navigate is not None)
        self._analyze_btn.setEnabled(ready and state != RUNNING)
        if state == RUNNING:
            self._analyze_btn.setText("Analyzing…")
            self._status.set_value("Analyzing in the background — Item Check stays available", "neutral")
            self._progress.setText(detail or self._progress.text())
        elif state == CURRENT:
            self._analyze_btn.setText("Re-analyze")
            when = time.strftime("%H:%M", time.localtime(self._analyzed_at)) if self._analyzed_at else ""
            self._status.set_value(f"Up to date · analyzed at {when}" if when else "Up to date", "ok")
            self._progress.setText(detail)
        elif state == STALE:
            self._analyze_btn.setText("Re-analyze")
            self._status.set_value("Out of date — your build changed after this analysis", "warn")
            self._progress.setText("Showing the previous analysis. Item Check does not use it until you re-analyze.")
        elif state == ERROR:
            self._analyze_btn.setText("Retry")
            self._status.set_value("Analysis could not complete", "error")
            self._progress.setText(f"{detail or 'Path of Building did not finish the analysis'}. Item Check still works.")
        else:
            self._analyze_btn.setText("Analyze Build")
            self._status.set_value("Not analyzed yet" if ready else "No build loaded", "neutral")
            self._progress.setText(_INTRO if ready else "Choose a build on the Overview page first.")
        self._progress.setVisible(bool(self._progress.text()))
        self._body.setVisible(self._result is not None)

    def _rerun(self) -> None:
        self.controller.submit_analyze_build()

    def _on_started(self, request_id: int) -> None:
        self._set_state(RUNNING, "Starting")

    def _on_progress(self, payload: object) -> None:
        if not isinstance(payload, dict) or str(payload.get("kind") or "").startswith("tree"):
            return
        if self._state == RUNNING:
            self._progress.setText(progress_text(payload, self._probe_labels))

    def _on_error(self, message: str) -> None:
        if self._state != RUNNING:
            return  # an error from another kind of analysis is not this page's failure
        self._set_state(ERROR, str(message or "").strip().rstrip("."))

    def _on_stale(self) -> None:
        # The previous analysis stays readable but is marked; nothing consumes a stale analysis.
        self._set_state(STALE if self._result is not None else IDLE)

    # --- rendering ---------------------------------------------------------------

    def show_result(self, result: dict[str, Any]) -> None:
        if not isinstance(result, dict) or str(result.get("kind") or "").startswith("tree") or "slots" not in result:
            return  # tree analyses share the signal; they are not a build analysis
        # A profile change re-emits the same analysis rescored: it is not a new run, so the time stays.
        run_id = (result.get("request_meta") or {}).get("request_id")
        if self._result is None or run_id is None or run_id != self._run_id or self._state != CURRENT:
            self._analyzed_at = time.time()
        self._run_id = run_id
        self._result = result
        self._view = build_analysis_view(result)
        self._slots = list(result.get("slots") or [])
        self._render_overview_cards()
        self._render_strongest()
        self._render_health()
        self._render_coverage()
        self._list.clear()
        self._has_priorities = bool(self._view["has_priorities"])
        # Row map: the priorities summary, then a heading, then one row per slot in the existing opportunity order.
        self._rows = []
        if self._has_priorities:
            self._list.addItem(QListWidgetItem("Overview"))  # stat priorities and focus for the whole build
            self._rows.append(-1)
        if self._slots:
            heading = QListWidgetItem("UPGRADE OPPORTUNITIES")
            heading.setFlags(Qt.ItemFlag.NoItemFlags)
            font = heading.font()
            font.setPointSizeF(max(font.pointSizeF() - 1.5, 6.0))
            font.setBold(True)
            heading.setFont(font)
            heading.setForeground(QColor(theme.TEXT_MUTED))
            self._list.addItem(heading)
            self._rows.append(-2)
        for index, text in enumerate(slot_row_texts(self._slots)):
            self._list.addItem(QListWidgetItem(text))
            self._rows.append(index)
        self._export_btn.setEnabled(True)
        if self._rows:
            self._list.setCurrentRow(0 if self._has_priorities else 1)  # priorities first, else the first slot
        self._set_state(CURRENT)

    def _render_strongest(self) -> None:
        tiles = self._view.get("tiles") or []
        while len(self._tiles) < len(tiles):
            row = _ResponseRow()
            self._tiles.append(row)
            self._strongest_group.add_row(row)
        for index, row in enumerate(self._tiles):
            row.setVisible(index < len(tiles))
            if index < len(tiles):
                row.set_tile(tiles[index])
        self._strongest_note.setText(str(self._view.get("caveat") or ""))
        self._strongest_note.setToolTip(f"{self._view.get('basis')} {self._view.get('caveat')}".strip())
        self._strongest_host.setVisible(bool(tiles))

    def _render_health(self) -> None:
        rows = self._view.get("health") or []
        while len(self._health_lines) < len(rows):
            line = _HealthLine()
            self._health_lines.append(line)
            self._health_group.add_row(line)
        for index, line in enumerate(self._health_lines):
            line.setVisible(index < len(rows))
            if index < len(rows):
                line.set_row(rows[index])
        self._health_host.setVisible(bool(rows))

    def _render_coverage(self) -> None:
        while self._coverage_lines.count():
            item = self._coverage_lines.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        summary = self._view.get("coverage_summary") or {}
        label = str(summary.get("label") or "")
        self._coverage_host.heading.setText(f"Analysis coverage · {label}" if label else "Analysis coverage")  # type: ignore[attr-defined]
        lines = [summary.get("summary", ""), *summary.get("notes", []), *(self._view.get("coverage") or [])]
        for line in lines:
            if line:
                text = QLabel(str(line))
                text.setObjectName("bodyText")
                text.setWordWrap(True)
                text.setMaximumWidth(680)
                self._coverage_lines.addWidget(text)
        self._coverage_host.setVisible(bool(self._view.get("has_priorities") or lines))

    def _render_overview_cards(self) -> None:
        for row in self._action_labels:
            row.setParent(None)
            row.deleteLater()
        self._action_labels.clear()
        view = self._view
        if not view.get("has_actionable"):
            self._overview_host.setVisible(False)
            return
        focus = view["focus"]
        self._focus_title_raw = str(focus["title"])  # the view model's wording; the page shows sentence case
        self._focus_title.setText(self._focus_title_raw.capitalize())
        self._focus_card.setProperty("issue", bool(focus["issue"]))
        self._focus_headline.setText(focus["headline"])
        self._focus_detail.setText(focus["detail"])
        self._focus_detail.setVisible(bool(focus["detail"]))
        actions = view.get("actions") or []
        for action in actions:
            row = _ActionRow(action["number"], action["title"], action["summary"], bool(action["fix"]))
            row.setObjectName("settingsRow")
            self._actions_group.add_row(row)
            self._action_labels.append(row)
        if not actions:
            row = _ActionRow("", "No action could be established from this analysis.", "", False)
            self._actions_group.add_row(row)
            self._action_labels.append(row)
        self._overview_host.setVisible(True)

    def strongest_text(self) -> list[str]:
        return [tile.text() for tile in self._tiles if not tile.isHidden()]

    def focus_text(self) -> list[str]:
        return [getattr(self, "_focus_title_raw", self._focus_title.text()), self._focus_headline.text(), self._focus_detail.text()] if not self._overview_host.isHidden() else []

    def actions_text(self) -> list[str]:
        return [row.text() for row in self._action_labels]

    def health_text(self) -> list[str]:
        return [line.text() for line in self._health_lines if not line.isHidden()]

    def coverage_text(self) -> list[str]:
        texts = [self._coverage_host.heading.text()]  # type: ignore[attr-defined]
        for index in range(self._coverage_lines.count()):
            item = self._coverage_lines.itemAt(index)
            if item.widget() is not None:
                texts.append(item.widget().text())
        return texts

    def _heading(self, title: str, note: str = "") -> str:
        extra = f" <span style='color:{theme.TEXT_MUTED};font-weight:400'>— {_esc(note)}</span>" if note else ""
        return f"<p style='margin:12px 0 3px 0;color:{theme.TEXT_MUTED};font-weight:700'>{_esc(title)}{extra}</p>"

    def _priorities_html(self) -> str:
        """The Overview: what changed, build health, stat priorities, stat focus, coverage. Details stay behind the toggle."""
        view = self._view
        muted, text, good, warn = theme.TEXT_MUTED, theme.TEXT, theme.OK, theme.WARN
        tones = {"warn": warn, "ok": good, "neutral": text, "muted": muted}
        out: list[str] = []
        if view.get("changes"):
            out.append(self._heading("WHAT CHANGED", "since your previous analysis"))
            out.extend(f"<p style='margin:0 0 3px 0;color:{text}'>{_esc(line)}</p>" for line in view["changes"])
        if view.get("ladders"):
            out.append(self._heading("STAT PRIORITIES", "strongest measured responses, each at its tested amount"))
        for ladder in view.get("ladders") or []:
            out.append(f"<p style='margin:6px 0 1px 0;color:{muted};font-weight:700'>{_esc(ladder['title'])}</p>")
            out.append("<table cellspacing='0' cellpadding='2' width='100%'>")
            for row in ladder["rows"]:
                curve = f"<span style='color:{muted}'>{_esc(row['curve'])}</span>" if row.get("curve") else ""
                out.append(
                    f"<tr><td width='18' style='color:{muted}'>{row['position']}.</td><td style='color:{text}'>{_esc(row['change'])}</td>"
                    f"<td align='right' width='64'><b style='color:{good}'>{_esc(row['response'])}</b></td>"
                    f"<td style='padding-left:10px'>{curve}</td></tr>"
                )
            out.append("</table>")
        if not view.get("ladders"):
            out.append(f"<p style='color:{text}'>No measured response among the tested stats.</p>")
        if view.get("packages"):
            out.append(self._heading("STAT FOCUS", "each stat keeps its own measured result; they are not added together"))
        for package in view.get("packages") or []:
            out.append(f"<p style='margin:6px 0 1px 0;color:{muted};font-weight:700'>{_esc(package['title'])}</p>")
            for stat in package["stats"]:
                out.append(f"<p style='margin:0 0 2px 0;color:{text}'>{_esc(stat['change'])} "
                           f"<span style='color:{muted}'>· {_esc(stat['evidence'])}</span></p>")
        if self._details_toggle.isChecked():
            out.append(self._heading("MEASUREMENT DETAILS"))
            for line in [*(view.get("curve_details") or []), *(view.get("breakpoint_details") or []),
                         *(view.get("package_details") or []), *(view.get("details") or [])]:
                out.append(f"<p style='margin:0 0 3px 0;color:{muted}'>{_esc(line)}</p>")
        out.append(f"<p style='margin:14px 0 0 0;color:{muted}'>{_esc(view.get('coverage_basis'))}</p>")
        return "".join(out)

    def _slot_index(self, row: int) -> int:
        """Slot index for a list row, or -1 for the priorities summary, the heading, or no row."""
        return self._rows[row] if 0 <= row < len(self._rows) and self._rows[row] >= 0 else -1

    def _section(self, title: str, lines: list[str], *, muted: bool = False, bullets: bool = True) -> str:
        if not lines:
            return ""
        colour = theme.TEXT_MUTED if muted else theme.TEXT
        mark = "• " if bullets else ""
        body = "".join(f"<p style='margin:0 0 3px 0;color:{colour}'>{mark}{_esc(line)}</p>" for line in lines)
        return f"<p style='margin:12px 0 3px 0;color:{theme.TEXT_MUTED};font-weight:700'>{_esc(title)}</p>{body}"

    def _slot_html(self, slot: dict[str, Any]) -> str:
        view = build_slot_view(self._result or {}, slot)
        base = f" <span style='color:{theme.TEXT_MUTED}'>· {_esc(view['item_base'])}</span>" if view["item_base"] else ""
        place = " · ".join(part for part in (view["slot"], view["summary"]) if part)
        summary = f"<p style='margin:0 0 2px 0;color:{theme.TEXT_MUTED}'>{_esc(place)}</p>"
        out = [
            f"<p style='margin:0 0 3px 0;color:{theme.TEXT_MUTED};font-weight:700'>CURRENT ITEM</p>",
            f"<p style='margin:0 0 2px 0;color:{theme.TEXT_EMPHASIS};font-weight:700'>{_esc(view['item_name'])}{base}</p>",
            summary,
            self._section("WHY THIS SLOT MATTERS", view["why"]),
            self._section("USEFUL STATS", [" · ".join(view["useful_stats"])] if view["useful_stats"] else [], bullets=False),
            self._section("MEASURED ON THIS SLOT", view["measured"]),
            self._section("LIMITATIONS", view["limitations"], bullets=False),
        ]
        if self._details_toggle.isChecked():
            out.append(self._section("MORE REASONS", view["why_more"], muted=True))
            out.append(self._section("MEASUREMENT DETAILS", view["details"], muted=True, bullets=False))
        return "".join(out)

    def _show_slot(self, row: int) -> None:
        if 0 <= row < len(self._rows) and self._rows[row] == -1:
            self._set_copy_available(False)
            self._detail.setHtml(self._priorities_html())
            return
        index = self._slot_index(row)
        if index < 0:
            self._set_copy_available(False)
            self._detail.clear()
            return
        self._set_copy_available(True)
        self._detail.setHtml(self._slot_html(self._slots[index]))

    def _current_intent(self) -> dict[str, Any]:
        index = self._slot_index(self._list.currentRow())
        return (self._slots[index].get("search_intent") or {}) if index >= 0 else {}

    def _notify(self, text: str) -> None:
        self._progress.setText(text)
        self._progress.setVisible(True)

    def _on_details_toggled(self, _checked: bool) -> None:
        self._refresh_advanced()
        self._show_slot(self._list.currentRow())

    def _refresh_advanced(self) -> None:
        """Copy Search Intent and Export JSON are advanced: offered only alongside the measurement details."""
        advanced = self._details_toggle.isChecked()
        self._copy_btn.setVisible(advanced and self._slot_selected)
        self._export_btn.setVisible(advanced)

    def _set_copy_available(self, available: bool) -> None:
        self._slot_selected = available  # Search Intent belongs to a slot, not to the priorities row
        self._copy_btn.setEnabled(available)
        self._refresh_advanced()

    def _copy_intent(self) -> None:
        intent = self._current_intent()
        QApplication.clipboard().setText(json.dumps(intent, indent=2))
        self._notify("Search Intent copied to the clipboard.")

    def _export_json(self) -> None:
        if self._result is None:
            return
        QApplication.clipboard().setText(json.dumps(self._result, indent=2, default=str))
        self._notify("Full analysis copied to the clipboard as JSON.")
