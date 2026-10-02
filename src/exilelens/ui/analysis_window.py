"""Analyze Build page: what the loaded PoB build responds to, at a glance.

Reading order is the product order: which build and how fresh, the strongest measured responses, urgent problems
(FIX FIRST), then the priorities and per-slot detail. All wording comes from `analysis.view`; this module only lays it out.
The analysis itself is explicit (the button) and asynchronous; nothing here runs on Item Check.
"""

from __future__ import annotations

import html
import json
import time
from typing import Any, Callable

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
from exilelens.analysis.view import build_analysis_view, progress_text
from exilelens.ui import theme
from exilelens.ui.components import StatusValue, ThemedCheckBox, button_row, make_button
from exilelens.ui.styles import DASHBOARD_STYLESHEET, apply_exile_lens_chrome
from exilelens.ui.window_policy import WindowInteractionPolicy, apply_native_extended_style, apply_window_interaction_policy

IDLE, RUNNING, CURRENT, STALE, ERROR = "IDLE", "RUNNING", "CURRENT", "STALE", "ERROR"

_INTRO = (
    "Analyze Build tests how your Path of Building build responds to common stats. "
    "It takes a few seconds, runs in the background and never runs during Item Check."
)
_MAX_FIX_FIRST = 4
_RES_NAMES = {"fire_res": "Fire", "cold_res": "Cold", "lightning_res": "Lightning", "chaos_res": "Chaos"}


def _fmt_need(need: dict[str, Any]) -> str:
    element = _RES_NAMES.get(str(need.get("metric") or ""))
    deficit = need.get("deficit")
    if element and deficit is not None:
        return f"{element} Resistance: +{float(deficit):g}% reaches cap"
    return str(need.get("explanation") or "").rstrip(".") or str(need.get("metric") or "")


def _esc(text: Any) -> str:
    return html.escape(str(text or ""))


class _ResponseTile(QFrame):
    """One strongest measured response: what was measured, how much, and the tested change that produced it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("responseTile")
        self.caption = QLabel("")
        self.caption.setObjectName("tileCaption")
        self.value = QLabel("")
        self.value.setObjectName("tileValue")
        self.value.setWordWrap(True)
        self.change = QLabel("")
        self.change.setObjectName("tileChange")
        self.change.setWordWrap(True)
        column = QVBoxLayout(self)
        column.setContentsMargins(theme.SPACE_MD, theme.SPACE_SM, theme.SPACE_MD, theme.SPACE_SM)
        column.setSpacing(2)
        column.addWidget(self.caption)
        column.addWidget(self.value)
        column.addWidget(self.change)
        column.addStretch(1)

    def set_tile(self, tile: dict[str, Any]) -> None:
        self.caption.setText(str(tile.get("caption") or ""))
        self.value.setText(str(tile.get("value") or ""))
        if not tile.get("measured"):
            name = "tileValueEmpty"
        else:  # several axes on one tile read as a line of text, not as one headline number
            name = "tileValueSmall" if "·" in str(tile.get("value") or "") and tile.get("key") == "multi_impact" else "tileValue"
        self.value.setObjectName(name)
        self.value.style().unpolish(self.value)
        self.value.style().polish(self.value)
        change = str(tile.get("change") or "")
        note = str(tile.get("note") or "")
        self.change.setText(f"{change}\n{note}" if note else change)

    def text(self) -> str:
        return " ".join(part for part in (self.caption.text(), self.value.text(), self.change.text()) if part)


class AnalysisWindow(QWidget):
    def __init__(
        self,
        controller: Any,
        parent: QWidget | None = None,
        *,
        embedded: bool = False,
        navigate: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._navigate = navigate
        self._embedded = embedded
        self.setObjectName("analysisPage")
        if not embedded:
            self.setWindowTitle("Analyze Build")
            apply_window_interaction_policy(self, WindowInteractionPolicy.INTERACTIVE_TOOL)
            self.setStyleSheet(DASHBOARD_STYLESHEET)
            apply_exile_lens_chrome(self)
            self.resize(920, 640)
        self._result: dict[str, Any] | None = None
        self._view: dict[str, Any] = {}
        self._slots: list[dict[str, Any]] = []
        # M5.3: row 0 is the Build Priorities summary when present; slot rows follow.
        self._has_priorities = False
        self._state = IDLE
        self._analyzed_at: float | None = None
        self._run_id: Any = None
        self._probe_labels = {d.probe_id: d.label for d in ProbeCatalog().all()}

        # --- header: which build, how fresh, and the one action ---------------------
        title = QLabel("Analyze Build")
        title.setObjectName("pageTitle")
        self._analyze_btn = make_button("Analyze Build", "primary")
        self._analyze_btn.clicked.connect(self._rerun)
        self._diagnostics_btn = make_button("Open Diagnostics", "tertiary")
        self._diagnostics_btn.clicked.connect(lambda: self._navigate("diagnostics") if self._navigate else None)
        self._diagnostics_btn.setVisible(False)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(theme.SPACE_SM)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._diagnostics_btn)
        head.addWidget(self._analyze_btn)

        self._header = QLabel("")
        self._header.setObjectName("cardTitle")
        self._status = StatusValue("Not analyzed yet", "neutral")
        self._status.set_word_wrap(False)
        self._progress = QLabel(_INTRO)
        self._progress.setObjectName("helperText")
        self._progress.setWordWrap(True)

        # --- strongest measured responses ------------------------------------------
        self._strongest_title = QLabel("STRONGEST MEASURED RESPONSES")
        self._strongest_title.setObjectName("sectionTitle")
        self._strongest_note = QLabel("")
        self._strongest_note.setObjectName("helperText")
        self._strongest_note.setWordWrap(True)
        self._tiles: list[_ResponseTile] = []
        self._tile_row = QHBoxLayout()
        self._tile_row.setContentsMargins(0, 0, 0, 0)
        self._tile_row.setSpacing(theme.SPACE_SM)
        self._strongest_host = QWidget()
        strongest = QVBoxLayout(self._strongest_host)
        strongest.setContentsMargins(0, 0, 0, 0)
        strongest.setSpacing(theme.SPACE_XS)
        strongest.addWidget(self._strongest_title)
        strongest.addLayout(self._tile_row)
        strongest.addWidget(self._strongest_note)
        self._strongest_host.setVisible(False)

        # --- fix first: actionable problems, kept apart from optimisation ----------
        self._fix_first_panel = QFrame()
        self._fix_first_panel.setObjectName("fixFirstPanel")
        self._fix_first_layout = QVBoxLayout(self._fix_first_panel)
        self._fix_first_layout.setContentsMargins(theme.SPACE_MD, theme.SPACE_SM, theme.SPACE_MD, theme.SPACE_SM)
        self._fix_first_layout.setSpacing(2)
        self._fix_first_labels: list[QLabel] = []
        self._fix_first_panel.setVisible(False)

        # --- priorities and slots ----------------------------------------------------
        self._list = QListWidget()
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        splitter = QSplitter()
        splitter.addWidget(self._list)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        self._copy_btn = make_button("Copy Search Intent", "secondary")
        self._copy_btn.clicked.connect(self._copy_intent)
        self._set_copy_available(False)
        self._export_btn = make_button("Export JSON", "tertiary")
        self._export_btn.clicked.connect(self._export_json)
        self._export_btn.setEnabled(False)
        self._details_toggle = ThemedCheckBox("Show measurement details")
        self._details_toggle.toggled.connect(lambda _checked: self._show_slot(self._list.currentRow()))
        footer = button_row([self._copy_btn, self._export_btn])
        footer.addWidget(self._details_toggle)

        layout = QVBoxLayout(self)
        margin = 0 if embedded else theme.PAGE_GUTTER
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(theme.SPACE_SM)
        identity = QHBoxLayout()
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(theme.SPACE_LG)
        identity.addWidget(self._header)
        identity.addWidget(self._status)
        identity.addStretch(1)

        # Nothing to browse before the first analysis: no empty list, no empty detail pane.
        self._body = QWidget()
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(theme.SPACE_SM)
        body.addWidget(splitter, 1)
        body.addLayout(footer)
        self._body.setVisible(False)

        layout.addLayout(head)
        layout.addLayout(identity)
        layout.addWidget(self._progress)
        layout.addWidget(self._strongest_host)
        layout.addWidget(self._fix_first_panel)
        layout.addWidget(self._body, 100)
        layout.addStretch(1)  # keeps the header at the top while there is no result to show

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
        return str(getattr(getattr(self.controller, "build_info", None), "name", "") or "")

    def _set_state(self, state: str, detail: str = "") -> None:
        self._state = state
        self._refresh_chrome(detail)

    def _refresh_chrome(self, detail: str = "") -> None:
        """Header, freshness and the action button for the current state. No technical identifiers."""
        build = self._view.get("build") or {}
        parts = [self._build_name() or "No build loaded", build.get("main_skill"), build.get("loadout"), build.get("context")]
        self._header.setText(" · ".join(str(part) for part in parts if part))
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
        self._render_strongest()
        self._render_fix_first()
        self._list.clear()
        self._has_priorities = bool(self._view["has_priorities"])
        if self._has_priorities:
            self._list.addItem(QListWidgetItem("BUILD PRIORITIES"))
        for slot in self._slots:
            opp = slot.get("opportunity") or {}
            score = opp.get("score")
            band = opp.get("band") or ""
            label = slot.get("product_slot")
            if score is None:
                text = f"{label}    {band}"
            else:
                text = f"{label}    {band}    {score}"
            self._list.addItem(QListWidgetItem(text))
        self._export_btn.setEnabled(True)
        if self._has_priorities or self._slots:
            self._list.setCurrentRow(0)  # priorities first, then the existing slot entries
        self._set_state(CURRENT)

    def _render_strongest(self) -> None:
        tiles = self._view.get("tiles") or []
        while len(self._tiles) < len(tiles):
            tile = _ResponseTile()
            self._tiles.append(tile)
            self._tile_row.addWidget(tile, 1)
        for index, tile in enumerate(self._tiles):
            tile.setVisible(index < len(tiles))
            if index < len(tiles):
                tile.set_tile(tiles[index])
                self._tile_row.setStretch(index, 2 if tiles[index]["key"] == "multi_impact" else 1)
        self._strongest_note.setText(f"{self._view.get('basis')} {self._view.get('caveat')}".strip())
        self._strongest_host.setVisible(bool(tiles))

    def _render_fix_first(self) -> None:
        for label in self._fix_first_labels:
            self._fix_first_layout.removeWidget(label)
            label.deleteLater()
        self._fix_first_labels.clear()
        rows = self._view.get("fix_first") or []
        if rows:
            lines = [("fixFirstTitle", "FIX FIRST")]
            for row in rows[:_MAX_FIX_FIRST]:
                urgency = f"  ·  {row['urgency']}" if row.get("urgency") else ""
                lines.append(("fixFirstRow", f"▲ {row['title']} — {row['detail']}{urgency}"))
            if len(rows) > _MAX_FIX_FIRST:
                lines.append(("helperText", f"and {len(rows) - _MAX_FIX_FIRST} more"))
            for object_name, text in lines:
                label = QLabel(text)
                label.setObjectName(object_name)
                label.setWordWrap(True)
                self._fix_first_layout.addWidget(label)
                self._fix_first_labels.append(label)
        self._fix_first_panel.setVisible(bool(rows))

    def strongest_text(self) -> list[str]:
        return [tile.text() for tile in self._tiles if not tile.isHidden()]

    def fix_first_text(self) -> list[str]:
        return [label.text() for label in self._fix_first_labels]

    def _priorities_html(self) -> str:
        view = self._view
        muted, text, good = theme.TEXT_MUTED, theme.TEXT, theme.OK
        out: list[str] = []
        for lane in view.get("lanes") or []:
            note = f" <span style='color:{muted};font-weight:400'>— {_esc(lane['note'])}</span>" if lane.get("note") else ""
            out.append(f"<p style='margin:10px 0 2px 0;color:{muted};font-weight:700'>{_esc(lane['title'])}{note}</p>")
            out.append("<table cellspacing='0' cellpadding='2' width='100%'>")
            for row in lane["rows"]:
                also = f"<span style='color:{muted}'>{_esc(row['also'])}</span>" if row.get("also") else ""
                response = f"<b style='color:{good}'>{_esc(row['response'])}</b>" if row.get("response") else ""
                out.append(
                    f"<tr><td style='color:{text}'>{_esc(row['change'])}</td>"
                    f"<td align='right' width='70'>{response}</td><td style='padding-left:10px'>{also}</td></tr>"
                )
            out.append("</table>")
        if not view.get("lanes"):
            out.append(f"<p style='color:{text}'>No measured response among the tested stats.</p>")
        out.append(f"<p style='margin:14px 0 2px 0;color:{muted};font-weight:700'>WHAT EXILELENS MEASURED</p>")
        for line in view.get("coverage") or []:
            out.append(f"<p style='margin:0 0 3px 0;color:{text}'>{_esc(line)}</p>")
        if self._details_toggle.isChecked():
            out.append(f"<p style='margin:14px 0 2px 0;color:{muted};font-weight:700'>MEASUREMENT DETAILS</p>")
            for line in view.get("details") or []:
                out.append(f"<p style='margin:0 0 3px 0;color:{muted}'>{_esc(line)}</p>")
        out.append(f"<p style='margin:14px 0 0 0;color:{muted}'>{_esc(view.get('coverage_basis'))}</p>")
        return "".join(out)

    def _slot_index(self, row: int) -> int:
        return row - 1 if self._has_priorities else row

    def _show_slot(self, row: int) -> None:
        if self._has_priorities and row == 0:
            self._set_copy_available(False)
            self._detail.setHtml(self._priorities_html())
            return
        row = self._slot_index(row)
        if row < 0 or row >= len(self._slots):
            self._set_copy_available(False)
            self._detail.clear()
            return
        self._set_copy_available(True)
        slot = self._slots[row]
        item = slot.get("current_item") or {}
        opp = slot.get("opportunity") or {}
        intent = slot.get("search_intent") or {}
        lines = [
            "CURRENT ITEM",
            f"{item.get('name') or '(unnamed)'}  ({item.get('base_name') or ''})",
            "",
            "UPGRADE OPPORTUNITY",
            f"{opp.get('band')}  {opp.get('score') if opp.get('score') is not None else '—'}",
        ]
        for driver in opp.get("drivers") or []:
            lines.append(f"  · {driver.get('text')}")
        lines.append("")
        lines.append("BUILD NEEDS THIS SLOT CAN ADDRESS")
        urgent = [need for need in (self._result or {}).get("needs") or [] if need.get("severity") in {"critical", "high"}]
        if not urgent:
            lines.append("  (none)")
        for need in urgent:
            lines.append(f"  · {_fmt_need(need)}")
        lines.append("")
        lines.append("TESTED STATS ON THIS SLOT")
        shown = 0
        for probe in slot.get("probes") or []:
            if probe.get("status") not in {"ok", "NO_SIGNAL"}:
                continue
            if not probe.get("slot_compatible"):
                continue
            bp = probe.get("breakpoints") or []
            cap = " → reaches cap" if any(event.get("code") == "CAP_REACHED" for event in bp) else ""
            lines.append(
                f"  {probe.get('line') or probe.get('display_name')}"
                f" → Damage {probe.get('offense_percent') or 0:+.1f}%"
                f" · Build Value {probe.get('score_delta') or 0:+.1f}{cap}"
            )
            shown += 1
            if shown >= 12:
                break
        if shown == 0 and slot.get("analysis_limited"):
            lines.append("  Weapon slots are not analyzed yet.")
        lines.append("")
        lines.append("SEARCH INTENT")
        for tier in ("required", "high_value", "useful", "low_value", "avoid"):
            rows = intent.get(tier) or []
            names = ", ".join(r.get("display_name") or r.get("stat") or "?" for r in rows) or "—"
            lines.append(f"  {tier.replace('_', ' ').title()}: {names}")
        lines.append("")
        lines.append("Not a market price. Not a trade URL.")
        self._detail.setPlainText("\n".join(lines))

    def _current_intent(self) -> dict[str, Any]:
        row = self._slot_index(self._list.currentRow())
        if row < 0 or row >= len(self._slots):
            return {}
        return self._slots[row].get("search_intent") or {}

    def _notify(self, text: str) -> None:
        self._progress.setText(text)
        self._progress.setVisible(True)

    def _set_copy_available(self, available: bool) -> None:
        self._copy_btn.setEnabled(available)
        self._copy_btn.setVisible(available)  # Search Intent belongs to a slot; it is not offered on the priorities row

    def _copy_intent(self) -> None:
        intent = self._current_intent()
        QApplication.clipboard().setText(json.dumps(intent, indent=2))
        self._notify("Search Intent copied to the clipboard.")

    def _export_json(self) -> None:
        if self._result is None:
            return
        QApplication.clipboard().setText(json.dumps(self._result, indent=2, default=str))
        self._notify("Full analysis copied to the clipboard as JSON.")
