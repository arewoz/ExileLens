from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
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

from exilelens.app.build_state import BuildState
from exilelens.app.controller import EvaluationController
from exilelens.market.trade_url import official_trade_site_url


SLOT_OPTIONS = [
    ("RING_1", "Ring 1"),
    ("RING_2", "Ring 2"),
    ("AMULET", "Amulet"),
    ("HELMET", "Helmet"),
    ("BOOTS", "Boots"),
    ("GLOVES", "Gloves"),
    ("BODY_ARMOUR", "Body Armour"),
    ("BELT", "Belt"),
]


class MarketPage(QWidget):
    """Phase 5B — Market Candidate Engine UI."""

    def __init__(self, controller: EvaluationController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._import_path: str | None = None
        self._result: dict[str, Any] | None = None
        self._show_pareto_only = False

        title = QLabel("MARKET")
        title.setObjectName("pageTitle")

        self._provider_status = QLabel("LIVE MARKET NOT AVAILABLE — fixture/import only")
        self._provider_status.setObjectName("staleBanner")
        self._provider_status.setWordWrap(True)

        self._slot = QComboBox()
        for value, label in SLOT_OPTIONS:
            self._slot.addItem(label, value)

        self._budget = QDoubleSpinBox()
        self._budget.setRange(0, 10_000)
        self._budget.setDecimals(2)
        self._budget.setSpecialValueText("(none)")
        self._budget.setValue(0)

        self._currency = QComboBox()
        for cur in ("Divine", "Exalted", "Chaos"):
            self._currency.addItem(cur)

        self._depth = QComboBox()
        for depth in ("FAST", "BALANCED", "DEEP"):
            self._depth.addItem(depth)

        self._source = QComboBox()
        self._source.addItem("Fixture corpus", "fixture")
        self._source.addItem("Imported JSON/NDJSON", "import")

        self._profile = QLabel("")
        self._intent = QTextEdit()
        self._intent.setReadOnly(True)
        self._intent.setMaximumHeight(160)

        self._import_btn = QPushButton("Import listings…")
        self._import_btn.clicked.connect(self._import_listings)
        self._find_btn = QPushButton("Find Best")
        self._find_btn.clicked.connect(self._find_best)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._cancel)
        self._cancel_btn.setEnabled(False)
        self._trade_btn = QPushButton("Open Official Trade Site")
        self._trade_btn.clicked.connect(self._open_trade_site)
        self._copy_plan_btn = QPushButton("Copy Search Plan")
        self._copy_plan_btn.clicked.connect(self._copy_plan)

        self._progress = QLabel("Ready.")
        self._progress.setObjectName("compactNote")

        self._results = QListWidget()
        self._details = QTextEdit()
        self._details.setReadOnly(True)
        self._pareto_filter = QPushButton("Show Pareto only")
        self._pareto_filter.setCheckable(True)
        self._pareto_filter.toggled.connect(self._toggle_pareto)

        controls = QWidget()
        controls.setObjectName("placeholderCard")
        form = QFormLayout(controls)
        form.addRow("Slot", self._slot)
        form.addRow("Budget", self._budget)
        form.addRow("Currency", self._currency)
        form.addRow("Depth", self._depth)
        form.addRow("Source", self._source)
        form.addRow("Profile", self._profile)
        form.addRow(self._import_btn)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self._find_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._trade_btn)
        btn_row.addWidget(self._copy_plan_btn)
        form.addRow(btn_row)

        intent_card = QWidget()
        intent_card.setObjectName("placeholderCard")
        intent_l = QVBoxLayout(intent_card)
        intent_l.addWidget(QLabel("SEARCH INTENT"))
        intent_l.addWidget(self._intent)

        left = QVBoxLayout()
        left.addWidget(controls)
        left.addWidget(intent_card)
        left.addWidget(self._progress)

        right_split = QSplitter(Qt.Vertical)
        results_wrap = QWidget()
        results_l = QVBoxLayout(results_wrap)
        results_l.addWidget(QLabel("CANDIDATES"))
        results_l.addWidget(self._pareto_filter)
        results_l.addWidget(self._results, 1)
        right_split.addWidget(results_wrap)
        right_split.addWidget(self._details)
        right_split.setStretchFactor(0, 2)
        right_split.setStretchFactor(1, 1)

        body = QHBoxLayout()
        body.addLayout(left, 1)
        body.addWidget(right_split, 2)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self._provider_status)
        layout.addLayout(body, 1)

        self._results.currentItemChanged.connect(self._show_details)
        controller.baseline_state_changed.connect(lambda _s: self.refresh())
        controller.analysis_finished.connect(lambda _r: self.refresh())
        controller.market_started.connect(lambda _rid: self._on_started())
        controller.market_progress.connect(self._on_progress)
        controller.market_finished.connect(self._on_finished)
        controller.market_error.connect(self._on_error)
        controller.market_stale.connect(lambda: self._progress.setText("Stale — baseline changed. Re-run search."))
        self.refresh()

    @property
    def has_live_results(self) -> bool:
        return False

    def refresh(self) -> None:
        baseline = self.controller.baseline_state
        self._profile.setText(self.controller.settings.value_profile)
        if baseline.state != BuildState.READY:
            self._intent.setPlainText("Load a build and run Analyze Build to populate Search Intent.")
            self._find_btn.setEnabled(False)
            return
        self._find_btn.setEnabled(True)
        slot = self._slot.currentData()
        intent = self.controller.search_intent_for_slot(str(slot))
        if intent:
            self._intent.setPlainText(json.dumps(intent, indent=2))
        else:
            self._intent.setPlainText(
                "No cached Search Intent for this slot.\n"
                "Run Analyze Build on Overview, or Find Best will derive intent via PoB."
            )

    def _import_listings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import market listings",
            "",
            "Listings (*.json *.ndjson);;All files (*)",
        )
        if path:
            self._import_path = path
            self._source.setCurrentIndex(1)
            self._progress.setText(f"Imported: {path}")

    def _find_best(self) -> None:
        slot = str(self._slot.currentData())
        budget = self._budget.value()
        budget_amount = None if budget <= 0 else float(budget)
        source = str(self._source.currentData())
        import_path = self._import_path if source == "import" else None
        if source == "import" and not import_path:
            self._progress.setText("Select a JSON/NDJSON file to import.")
            return
        self._results.clear()
        self._details.clear()
        self.controller.submit_market_search(
            slot=slot,
            budget_amount=budget_amount,
            budget_currency=self._currency.currentText(),
            depth=self._depth.currentText(),
            source=source,
            import_path=import_path,
        )

    def _cancel(self) -> None:
        self.controller.cancel_market_search()
        self._cancel_btn.setEnabled(False)
        self._find_btn.setEnabled(True)

    def _on_started(self) -> None:
        self._find_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._progress.setText("Market search running…")

    def _on_progress(self, payload: dict[str, Any]) -> None:
        phase = payload.get("phase") or ""
        msg = payload.get("message") or ""
        evaluated = payload.get("evaluated")
        total = payload.get("total")
        if evaluated and total:
            self._progress.setText(f"{phase}: {msg} ({evaluated}/{total})")
        else:
            self._progress.setText(f"{phase}: {msg}")

    def _on_finished(self, result: dict[str, Any]) -> None:
        self._result = result
        self._find_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._provider_status.setText(result.get("provider_status") or "LIVE MARKET NOT AVAILABLE")
        perf = result.get("performance") or {}
        self._progress.setText(
            f"Done in {float(perf.get('elapsed_ms') or 0) / 1000:.1f}s · "
            f"{perf.get('pob_recalcs', 0)} PoB evals · {perf.get('deduped', 0)} unique listings"
        )
        self._populate_results(result)

    def _on_error(self, message: str) -> None:
        self._find_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._progress.setText(f"Error: {message}")

    def _populate_results(self, result: dict[str, Any]) -> None:
        self._results.clear()
        pool = result.get("pool") or {}
        categories = pool.get("categories") or {}
        rows = list(pool.get("candidates") or [])
        if not rows:
            self._results.addItem(QListWidgetItem("No candidates matched this search."))
            return
        for row in rows:
            if self._show_pareto_only and not row.get("on_frontier"):
                continue
            ev = row.get("evaluation") or {}
            listing = ev.get("listing") or {}
            ident = listing.get("identity") or {}
            lid = ident.get("listing_id") or "?"
            label = listing.get("label") or lid
            price = listing.get("price") or {}
            price_txt = ""
            if price:
                price_txt = f" · {price.get('amount')} {price.get('currency')}"
            cats = [c for c, i in categories.items() if i == lid]
            cat_txt = f" [{', '.join(cats)}]" if cats else ""
            text = (
                f"{label}{cat_txt} · Δ{ev.get('build_value_delta', 0):.1f} · "
                f"{ev.get('verdict', '—')}{price_txt}"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, row)
            self._results.addItem(item)

    def _show_details(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if not current:
            return
        row = current.data(Qt.UserRole)
        if not isinstance(row, dict):
            self._details.setPlainText(str(row))
            return
        self._details.setPlainText(json.dumps(row, indent=2))

    def _toggle_pareto(self, checked: bool) -> None:
        self._show_pareto_only = checked
        if self._result:
            self._populate_results(self._result)

    def _open_trade_site(self) -> None:
        hint = ""
        if self._result:
            hint = str((self._result.get("query_plan") or {}).get("trade_site_hint") or "")
        QDesktopServices.openUrl(QUrl(official_trade_site_url(query_hint=hint)))

    def _copy_plan(self) -> None:
        from PySide6.QtWidgets import QApplication

        plan = (self._result or {}).get("query_plan")
        if not plan:
            intent = self.controller.search_intent_for_slot(str(self._slot.currentData()))
            plan = {"search_intent": intent, "slot": self._slot.currentData()}
        QApplication.clipboard().setText(json.dumps(plan, indent=2))
        self._progress.setText("Search plan copied to clipboard.")
