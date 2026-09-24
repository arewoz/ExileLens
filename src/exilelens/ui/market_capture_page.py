from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from exilelens.app.build_state import BuildState
from exilelens.app.controller import EvaluationController
from exilelens.app.modules.registry import FeatureModule, is_enabled
from exilelens.ui.market_page import SLOT_OPTIONS


class MarketCapturePage(QWidget):
    """MARKET-ASSIST-01 — in-game capture session dashboard."""

    def __init__(self, controller: EvaluationController, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.settings = settings

        title = QLabel("MARKET ASSISTANT")
        title.setObjectName("pageTitle")
        self._empty = QLabel(
            "1. Enable Market Assistant in Settings → Features.\n"
            "2. Open MARKET → MARKET ASSISTANT and choose slot, profile, and optional budget.\n"
            "3. Click Start Capture, then Ctrl+C listings in the PoE2 trade UI.\n"
            "4. Stop & Finish to review captured results and hand off to Gear Optimizer."
        )
        self._empty.setWordWrap(True)
        self._empty.setObjectName("compactNote")
        self._status = QLabel("Market Assistant is disabled — enable it in Settings → Features.")
        self._status.setWordWrap(True)

        self._slot = QComboBox()
        for value, label in SLOT_OPTIONS:
            self._slot.addItem(label, value)
        self._budget = QDoubleSpinBox()
        self._budget.setRange(0, 10_000)
        self._budget.setDecimals(2)
        self._budget.setSpecialValueText("(none)")
        self._currency = QComboBox()
        for cur in ("Divine", "Exalted", "Chaos", "Alchemy"):
            self._currency.addItem(cur)

        self._start = QPushButton("Start Capture")
        self._start.clicked.connect(self._start_session)
        self._stop = QPushButton("Stop & Finish")
        self._stop.clicked.connect(self._stop_session)
        self._stop.setEnabled(False)
        self._copy_next = QPushButton("Copy NEXT SEARCH")
        self._copy_next.clicked.connect(self._copy_next_search)
        self._ideal = QPushButton("Analyze Ideal Target")
        self._ideal.clicked.connect(self._analyze_ideal)
        self._handoff = QPushButton("Use in Gear Optimizer")
        self._handoff.clicked.connect(self._handoff_pool)

        self._summary = QTextEdit()
        self._summary.setReadOnly(True)
        self._summary.setMaximumHeight(120)
        self._results = QListWidget()
        self._details = QTextEdit()
        self._details.setReadOnly(True)

        form_card = QWidget()
        form_card.setObjectName("placeholderCard")
        form = QFormLayout(form_card)
        form.addRow("Target slot", self._slot)
        form.addRow("Budget", self._budget)
        form.addRow("Currency", self._currency)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self._start)
        btn_row.addWidget(self._stop)
        btn_row.addWidget(self._copy_next)
        form.addRow(btn_row)
        form.addRow(self._ideal)
        form.addRow(self._handoff)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self._empty)
        layout.addWidget(self._status)
        layout.addWidget(form_card)
        layout.addWidget(QLabel("SESSION SUMMARY"))
        layout.addWidget(self._summary)
        layout.addWidget(QLabel("CAPTURED LISTINGS"))
        layout.addWidget(self._results, 1)
        layout.addWidget(self._details)

        controller.market_capture_updated.connect(self.refresh)
        controller.market_capture_session_changed.connect(lambda _payload: self.refresh())
        self._results.currentRowChanged.connect(self._show_detail)
        self.refresh()

    def refresh(self) -> None:
        enabled = is_enabled(FeatureModule.MARKET_ASSISTANT)
        active = self.controller.market_capture_active
        self._start.setEnabled(enabled and not active and self.controller.build_info.state == BuildState.READY)
        self._stop.setEnabled(enabled and active)
        self._copy_next.setEnabled(enabled and active)
        self._ideal.setEnabled(enabled and active)

        snapshot = self.controller.market_capture_snapshot()
        if not enabled:
            self._status.setText("Market Assistant module is disabled — enable it in Settings → Features.")
            self._empty.show()
            return
        self._empty.setVisible(not active and not snapshot)
        if active:
            self._status.setText("Session active — copy items in PoE2 market (Ctrl+C).")
        elif snapshot and not snapshot.get("active"):
            reason = snapshot.get("ended_reason") or "ended"
            self._status.setText(f"Last session {reason}.")
        else:
            self._status.setText("Ready to start capture session.")

        self._results.clear()
        if not snapshot:
            self._summary.setText("No capture session.")
            return

        evaluated = int(snapshot.get("evaluated_count") or 0)
        captured = int(snapshot.get("capture_count") or 0)
        guidance = snapshot.get("guidance") or {}
        search_status = snapshot.get("search_status") or {}
        lines = [
            f"Session {snapshot.get('session_id', '—')}",
            f"Captured {captured} · Evaluated {evaluated}",
            f"Status: {search_status.get('status', '—')}",
        ]
        next_rows = guidance.get("next_search") or []
        if next_rows:
            lines.append("Next: " + ", ".join(str(r.get("display") or r.get("stat")) for r in next_rows[:4]))
        self._summary.setText("\n".join(lines))

        for row in snapshot.get("observations") or []:
            state = row.get("queue_state")
            price = row.get("price") or {}
            price_txt = f"{price.get('amount')} {price.get('currency')}" if price else "no price"
            text = f"#{row.get('capture_index')} · {state} · {price_txt}"
            if int(row.get("seen_count") or 1) > 1:
                text += f" · Seen {row.get('seen_count')}×"
            self._results.addItem(QListWidgetItem(text))

    def _show_detail(self, row: int) -> None:
        snapshot = self.controller.market_capture_snapshot()
        if not snapshot or row < 0:
            return
        observations = list(snapshot.get("observations") or [])
        if row >= len(observations):
            return
        obs = observations[row]
        ev = obs.get("evaluation") or {}
        comparison = ev.get("comparison") or {}
        decision = comparison.get("decision") or {}
        lines = [
            f"State: {obs.get('queue_state')}",
            f"Price note: {obs.get('price_note_raw') or '—'}",
            f"Verdict: {ev.get('verdict') or '—'}",
            f"Build Value Δ: {ev.get('build_value_delta')}",
            f"Decision: {decision.get('headline') or '—'}",
        ]
        why = decision.get("why_reasons") or []
        for reason in why[:4]:
            if isinstance(reason, dict):
                lines.append(f"  · {reason.get('explanation') or reason.get('code')}")
        self._details.setText("\n".join(lines))

    def _start_session(self) -> None:
        slot = self._slot.currentData()
        budget = float(self._budget.value()) if self._budget.value() > 0 else None
        currency = self._currency.currentText()
        ok, message = self.controller.start_market_capture_session(
            slot=str(slot),
            budget_amount=budget,
            budget_currency=currency if budget else None,
        )
        self._status.setText(message)
        if ok:
            self.refresh()

    def _stop_session(self) -> None:
        payload = self.controller.stop_market_capture_session(finalize=True)
        if payload:
            self._status.setText("Session finalized to candidate pool.")
        self.refresh()

    def _copy_next_search(self) -> None:
        text = self.controller.market_capture_next_search_clipboard()
        if text:
            QGuiApplication.clipboard().setText(text)
            self._status.setText("Copied NEXT SEARCH to clipboard.")

    def _analyze_ideal(self) -> None:
        self.controller.analyze_market_ideal_target()
        self._status.setText("Ideal target analysis queued.")

    def _handoff_pool(self) -> None:
        ok = self.controller.handoff_market_capture_to_gear()
        self._status.setText("Pool registered for Gear Optimizer." if ok else "No finalized pool to hand off.")
