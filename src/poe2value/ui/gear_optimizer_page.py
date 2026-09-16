from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from poe2value.app.build_state import BuildState
from poe2value.app.controller import EvaluationController
from poe2value.gear.models import GearSearchPreset, PlanConstraint
from poe2value.gear.slots import GEAR_OPTIMIZER_SLOTS, GEAR_SLOT_LABELS


class GearOptimizerPage(QWidget):
    """Phase 5C — Budget Gear Optimizer."""

    def __init__(self, controller: EvaluationController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._result: dict[str, Any] | None = None
        self._slot_checks: dict[str, QCheckBox] = {}

        title = QLabel("GEAR OPTIMIZER")
        title.setObjectName("pageTitle")
        self._status = QLabel("BEST FOUND IN AVAILABLE CANDIDATE POOLS")
        self._status.setObjectName("compactNote")
        self._status.setWordWrap(True)

        self._budget = QDoubleSpinBox()
        self._budget.setRange(1, 100_000)
        self._budget.setDecimals(1)
        self._budget.setValue(100)

        self._currency = QComboBox()
        for cur in ("Divine", "Exalted", "Chaos"):
            self._currency.addItem(cur)

        self._preset = QComboBox()
        for preset in GearSearchPreset:
            self._preset.addItem(preset.value, preset.value)

        self._max_purchases = QSpinBox()
        self._max_purchases.setRange(0, 10)
        self._max_purchases.setSpecialValueText("(none)")
        self._max_purchases.setValue(0)

        self._profile = QLabel("")

        slot_box = QWidget()
        slot_layout = QVBoxLayout(slot_box)
        slot_layout.addWidget(QLabel("ENABLED SLOTS"))
        for slot in GEAR_OPTIMIZER_SLOTS:
            check = QCheckBox(GEAR_SLOT_LABELS.get(slot.value, slot.value))
            check.setChecked(slot.value in {"RING_1", "RING_2", "HELMET", "BOOTS"})
            self._slot_checks[slot.value] = check
            slot_layout.addWidget(check)

        self._pool_list = QListWidget()
        self._pool_list.setMaximumHeight(180)

        self._optimize_btn = QPushButton("Optimize")
        self._optimize_btn.clicked.connect(self._optimize)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._cancel)
        self._cancel_btn.setEnabled(False)
        self._market_btn = QPushButton("Open Market…")
        self._market_btn.clicked.connect(self._open_market)
        self._copy_btn = QPushButton("Copy Plan")
        self._copy_btn.clicked.connect(self._copy_plan)

        self._progress = QLabel("Ready.")
        self._progress.setObjectName("compactNote")

        self._best = QTextEdit()
        self._best.setReadOnly(True)
        self._alternatives = QListWidget()
        self._curve = QTextEdit()
        self._curve.setReadOnly(True)
        self._curve.setMaximumHeight(120)
        self._details = QTextEdit()
        self._details.setReadOnly(True)

        controls = QWidget()
        form = QFormLayout(controls)
        form.addRow("Budget", self._budget)
        form.addRow("Currency", self._currency)
        form.addRow("Search preset", self._preset)
        form.addRow("Profile", self._profile)
        form.addRow("Max purchases", self._max_purchases)
        form.addRow(slot_box)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._optimize_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._market_btn)
        btn_row.addWidget(self._copy_btn)

        left = QVBoxLayout()
        left.addWidget(controls)
        left.addLayout(btn_row)
        left.addWidget(QLabel("POOL STATUS"))
        left.addWidget(self._pool_list)
        left.addWidget(self._progress)

        right = QVBoxLayout()
        right.addWidget(QLabel("BEST PLAN"))
        right.addWidget(self._best, 2)
        right.addWidget(QLabel("ALTERNATIVES"))
        right.addWidget(self._alternatives, 1)
        right.addWidget(QLabel("BUDGET CURVE"))
        right.addWidget(self._curve)
        right.addWidget(QLabel("PLAN DETAILS"))
        right.addWidget(self._details, 2)

        splitter = QSplitter(Qt.Horizontal)
        left_widget = QWidget()
        left_widget.setLayout(left)
        right_widget = QWidget()
        right_widget.setLayout(right)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self._status)
        layout.addWidget(splitter, 1)

        controller.baseline_state_changed.connect(lambda _s: self.refresh())
        controller.market_finished.connect(lambda _p: self.refresh())
        controller.gear_started.connect(self._on_started)
        controller.gear_progress.connect(self._on_progress)
        controller.gear_finished.connect(self._on_finished)
        controller.gear_error.connect(self._on_error)
        controller.gear_stale.connect(self._on_stale)
        self.refresh()

    def refresh(self) -> None:
        baseline = self.controller.baseline_state
        self._profile.setText(self.controller.settings.value_profile)
        self._pool_list.clear()
        if baseline.state != BuildState.READY:
            self._pool_list.addItem(QListWidgetItem("Load a build to optimize gear."))
            return
        fingerprint = baseline.fingerprint or ""
        generation = self.controller._baseline_generation
        profile = self.controller.settings.value_profile
        enabled = tuple(slot for slot, check in self._slot_checks.items() if check.isChecked())
        rows = self.controller.pool_registry.status(
            baseline_fingerprint=fingerprint,
            baseline_generation=generation,
            profile=profile,
            enabled_slots=enabled or None,
        )
        for row in rows:
            label = GEAR_SLOT_LABELS.get(row.product_slot, row.product_slot)
            text = f"{label}: {row.state.value} — {row.message}"
            item = QListWidgetItem(text)
            if row.state.value in {"MISSING", "STALE", "EMPTY"}:
                item.setForeground(Qt.GlobalColor.yellow)
            self._pool_list.addItem(item)

    def _enabled_slots(self) -> tuple[str, ...]:
        return tuple(slot for slot, check in self._slot_checks.items() if check.isChecked())

    def _optimize(self) -> None:
        slots = self._enabled_slots()
        if not slots:
            self._progress.setText("Select at least one slot.")
            return
        max_purchases = self._max_purchases.value() or None
        self.controller.submit_gear_optimization(
            budget_amount=float(self._budget.value()),
            budget_currency=self._currency.currentText(),
            search_preset=self._preset.currentData(),
            enabled_slots=slots,
            max_purchases=max_purchases,
        )

    def _cancel(self) -> None:
        self.controller.cancel_gear_optimization()

    def _open_market(self) -> None:
        window = self.window()
        if hasattr(window, "navigate"):
            window.navigate("market")

    def _copy_plan(self) -> None:
        if not self._result or not self._result.get("best_plan"):
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(json.dumps(self._result["best_plan"], indent=2))

    def _on_started(self, _request_id: int) -> None:
        self._optimize_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._progress.setText("Optimizing gear plans…")

    def _on_progress(self, payload: dict[str, Any]) -> None:
        msg = payload.get("message") or payload.get("phase") or "Working…"
        evaluated = payload.get("evaluated")
        total = payload.get("total")
        best = payload.get("best_build_value")
        bits = [str(msg)]
        if evaluated is not None and total:
            bits.append(f"{evaluated}/{total}")
        if best is not None:
            bits.append(f"best Build Value {best:.1f}")
        self._progress.setText(" · ".join(bits))

    def _on_finished(self, payload: dict[str, Any]) -> None:
        self._optimize_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._result = payload
        self._status.setText(str(payload.get("label") or payload.get("provider_status") or ""))
        search_mode = payload.get("search_mode") or ""
        best = payload.get("best_plan") or {}
        if best:
            lines = [
                f"Mode: {search_mode}",
                f"Build Value Δ: {best.get('build_value_delta')}",
                f"Offense Δ: {best.get('offense_delta')}",
                f"Defense Δ: {best.get('defense_delta')}",
                f"Price: {best.get('total_price')} {best.get('price_currency')}",
                f"Verdict: {best.get('verdict')}",
            ]
            self._best.setPlainText("\n".join(lines))
        else:
            self._best.setPlainText(f"No valid plan found.\nMode: {search_mode}")
        self._alternatives.clear()
        for alt in payload.get("alternatives") or []:
            self._alternatives.addItem(
                QListWidgetItem(
                    f"Build Value {alt.get('build_value_delta')} · {alt.get('total_price')} · {alt.get('verdict')}"
                )
            )
        curve_lines = []
        for point in payload.get("budget_curve") or []:
            curve_lines.append(
                f"{point.get('price')} → Build Value {point.get('build_value_delta')} ({point.get('purchase_count')} items)"
            )
        self._curve.setPlainText("\n".join(curve_lines) or "—")
        opp = payload.get("opportunity_cost")
        detail_bits = [json.dumps(payload.get("categories") or {}, indent=2)]
        if opp:
            detail_bits.append("\nOpportunity cost vs best single purchase:")
            detail_bits.append(json.dumps(opp, indent=2))
        self._details.setPlainText("\n".join(detail_bits))
        perf = payload.get("performance") or {}
        self._progress.setText(
            f"Done in {float(perf.get('elapsed_ms') or 0) / 1000:.1f}s · {perf.get('pob_recalcs', 0)} PoB plan evals"
        )
        self.refresh()

    def _on_error(self, message: str) -> None:
        self._optimize_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._progress.setText(f"Error: {message}")

    def _on_stale(self) -> None:
        self._optimize_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._progress.setText("Baseline changed — refresh Market pools and retry.")
