from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from poe2value.app.controller import EvaluationController
from poe2value.ui.market_capture_page import MarketCapturePage
from poe2value.ui.market_page import MarketPage


class MarketHubPage(QWidget):
    """MARKET dashboard with SEARCH/IMPORT, CAPTURE, RESULTS sub-navigation."""

    def __init__(self, controller: EvaluationController, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.settings = settings

        title = QLabel("MARKET")
        title.setObjectName("pageTitle")

        self._sub_nav: dict[str, QPushButton] = {}
        sub_row = QHBoxLayout()
        self._stack = QStackedWidget()
        self._search = MarketPage(controller)
        self._capture = MarketCapturePage(controller, settings)
        self._results = MarketResultsPage(controller)
        for key, label, widget in (
            ("search", "SEARCH / IMPORT", self._search),
            ("assistant", "MARKET ASSISTANT", self._capture),
            ("results", "CAPTURE RESULTS", self._results),
        ):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked=False, k=key: self.navigate(k))
            self._sub_nav[key] = btn
            sub_row.addWidget(btn)
            self._stack.addWidget(widget)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(sub_row)
        layout.addWidget(self._stack, 1)
        self.navigate("search")

        controller.market_finished.connect(lambda _payload: self._results.refresh())
        controller.market_capture_session_changed.connect(lambda _payload: self._results.refresh())


    @property
    def has_live_results(self) -> bool:
        return self._search.has_live_results

    @property
    def _provider_status(self):
        return self._search._provider_status

    def navigate(self, key: str) -> None:
        mapping = {"search": 0, "assistant": 1, "results": 2, "capture": 1}
        index = mapping.get(key, 0)
        self._stack.setCurrentIndex(index)
        nav_key = "assistant" if key == "capture" else key
        for nav_key_btn, btn in self._sub_nav.items():
            btn.setChecked(nav_key_btn == nav_key)

    def refresh(self) -> None:
        self._search.refresh()
        self._capture.refresh()
        self._results.refresh()


class MarketResultsPage(QWidget):
    def __init__(self, controller: EvaluationController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._list = QLabel("")
        self._list.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("RESULTS"))
        layout.addWidget(self._list)
        self.refresh()

    def refresh(self) -> None:
        lines: list[str] = []
        last_market = getattr(self.controller, "_last_market_result", None)
        if last_market:
            pool = last_market.get("pool") or {}
            lines.append(f"5B search: {pool.get('slot')} — {len(pool.get('candidates') or [])} candidates")
        snapshot = self.controller.market_capture_snapshot()
        if snapshot and not snapshot.get("active"):
            lines.append(
                f"Capture session {snapshot.get('session_id')}: "
                f"{snapshot.get('evaluated_count', 0)} evaluated"
            )
        registry = self.controller.pool_registry
        for slot in ("RING_1", "RING_2", "HELMET", "BOOTS"):
            pool = registry.get_pool(slot)
            if pool:
                lines.append(f"Pool {slot}: {len(pool.candidates)} candidates (registry)")
        self._list.setText("\n".join(lines) if lines else "No market or capture results yet.")
