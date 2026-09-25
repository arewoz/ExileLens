from __future__ import annotations

import json
from typing import Any

from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from exilelens.app.controller import EvaluationController
from exilelens.ui.styles import OVERLAY_STYLESHEET
from exilelens.ui.window_policy import WindowInteractionPolicy, apply_native_extended_style, apply_window_interaction_policy


def _fmt_need(need: dict[str, Any]) -> str:
    deficit = need.get("deficit")
    extra = f" +{deficit:g} to cap" if deficit is not None else ""
    return f"{need.get('code')} ({need.get('metric')}){extra}"


class AnalysisWindow(QWidget):
    def __init__(self, controller: EvaluationController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Analyze Build — Upgrade Opportunities")
        self.setObjectName("analysisRoot")
        apply_window_interaction_policy(self, WindowInteractionPolicy.INTERACTIVE_TOOL)
        self.setStyleSheet(OVERLAY_STYLESHEET)
        self.resize(920, 640)
        self._result: dict[str, Any] | None = None
        self._slots: list[dict[str, Any]] = []

        self._header = QLabel("No analysis yet")
        self._header.setObjectName("nameLabel")
        self._status = QLabel("Use Analyze Build from the tray. This does not run on Ctrl+C.")
        self._status.setObjectName("compactNote")
        self._progress = QLabel("")
        self._progress.setObjectName("baselineLabel")

        self._list = QListWidget()
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)

        copy_btn = QPushButton("Copy Search Intent")
        copy_btn.clicked.connect(self._copy_intent)
        export_btn = QPushButton("Export JSON")
        export_btn.clicked.connect(self._export_json)
        rerun_btn = QPushButton("Analyze Build")
        rerun_btn.clicked.connect(self._rerun)

        buttons = QHBoxLayout()
        buttons.addWidget(rerun_btn)
        buttons.addWidget(copy_btn)
        buttons.addWidget(export_btn)
        buttons.addStretch(1)

        splitter = QSplitter()
        splitter.addWidget(self._list)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.addWidget(self._header)
        layout.addWidget(self._status)
        layout.addWidget(self._progress)
        layout.addLayout(buttons)
        layout.addWidget(splitter)

        self._list.currentRowChanged.connect(self._show_slot)
        controller.analysis_started.connect(self._on_started)
        controller.analysis_progress.connect(self._on_progress)
        controller.analysis_finished.connect(self.show_result)
        controller.analysis_error.connect(self._on_error)
        controller.analysis_stale.connect(self._on_stale)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_native_extended_style(self, WindowInteractionPolicy.INTERACTIVE_TOOL)

    def _rerun(self) -> None:
        self.controller.submit_analyze_build()

    def _on_started(self, request_id: int) -> None:
        self._status.setText(f"Analyzing build in background (#{request_id})… Ctrl+C stays available.")
        self._progress.setText("Stage: starting")

    def _on_progress(self, payload: object) -> None:
        if isinstance(payload, dict):
            stage = payload.get("stage")
            extra = payload.get("probe_id") or payload.get("slot") or ""
            self._progress.setText(f"Stage: {stage} {extra}".strip())

    def _on_error(self, message: str) -> None:
        self._status.setText(f"Analysis failed: {message}")

    def _on_stale(self) -> None:
        self._status.setText("Analysis is stale — baseline changed. Run Analyze Build again.")
        self._result = None

    def show_result(self, result: dict[str, Any]) -> None:
        self._result = result
        baseline = result.get("baseline") or {}
        self._header.setText("UPGRADE OPPORTUNITIES")
        self._status.setText(
            f"{baseline.get('build_name') or baseline.get('build_path')} · "
            f"{baseline.get('loadout') or 'default'} · {baseline.get('context')} · {baseline.get('profile')}"
        )
        perf = result.get("performance") or {}
        self._progress.setText(
            f"Done in {float(perf.get('elapsed_ms') or 0) / 1000:.1f}s · "
            f"{perf.get('pob_recalcs', 0)} PoB probes · cache {perf.get('cache')}"
        )
        self._slots = list(result.get("slots") or [])
        self._list.clear()
        for slot in self._slots:
            opp = slot.get("opportunity") or {}
            score = opp.get("score")
            band = opp.get("band") or ""
            label = slot.get("product_slot")
            if score is None:
                text = f"{label}    {band}"
            else:
                text = f"{label}    {band}    {score}"
            item = QListWidgetItem(text)
            self._list.addItem(item)
        if self._slots:
            self._list.setCurrentRow(0)

    def _show_slot(self, row: int) -> None:
        if row < 0 or row >= len(self._slots):
            self._detail.clear()
            return
        slot = self._slots[row]
        item = slot.get("current_item") or {}
        opp = slot.get("opportunity") or {}
        intent = slot.get("search_intent") or {}
        lines = [
            f"CURRENT ITEM",
            f"{item.get('name') or '(unnamed)'}  ({item.get('base_name') or ''})",
            "",
            "UPGRADE OPPORTUNITY",
            f"{opp.get('band')}  {opp.get('score') if opp.get('score') is not None else '—'}",
        ]
        for driver in opp.get("drivers") or []:
            lines.append(f"  · {driver.get('text')}")
        lines.append("")
        lines.append("BUILD NEEDS THIS SLOT CAN ADDRESS")
        needs = (self._result or {}).get("needs") or []
        if not needs:
            lines.append("  (none)")
        for need in needs:
            if need.get("severity") in {"critical", "high"}:
                lines.append(f"  · {_fmt_need(need)}")
        lines.append("")
        lines.append("MARGINAL STAT VALUE")
        shown = 0
        for probe in slot.get("probes") or []:
            if probe.get("status") not in {"ok", "NO_SIGNAL"}:
                continue
            if not probe.get("slot_compatible"):
                continue
            bp = probe.get("breakpoints") or []
            cap = " → CAP RESTORED" if any(event.get("code") == "CAP_REACHED" for event in bp) else ""
            lines.append(
                f"  {probe.get('display_name')} +{probe.get('magnitude'):g}"
                f" → {probe.get('offense_percent', 0):+.1f}% offense"
                f" → {probe.get('score_delta', 0):+.1f} Build Value"
                f"{cap}  [{probe.get('confidence')}]"
            )
            shown += 1
            if shown >= 12:
                break
        if shown == 0 and slot.get("analysis_limited"):
            lines.append("  WEAPON ANALYSIS LIMITED")
        lines.append("")
        lines.append("SEARCH INTENT")
        for tier in ("required", "high_value", "useful", "low_value", "avoid"):
            rows = intent.get(tier) or []
            lines.append(f"  {tier.upper()}: " + (", ".join(r.get("display_name") or r.get("stat") or "?" for r in rows) or "—"))
        lines.append("")
        lines.append("Not a market price. Not a trade URL.")
        self._detail.setPlainText("\n".join(lines))

    def _current_intent(self) -> dict[str, Any]:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._slots):
            return {}
        return self._slots[row].get("search_intent") or {}

    def _copy_intent(self) -> None:
        intent = self._current_intent()
        QApplication.clipboard().setText(json.dumps(intent, indent=2))
        self._progress.setText("Search Intent JSON copied.")

    def _export_json(self) -> None:
        self._copy_intent()
