from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from poe2value.app.settings import AppSettings
from poe2value.ui.managed_window import ManagedToolWindow, clamp_window_to_screen
from poe2value.ui.styles import OVERLAY_STYLESHEET
from poe2value.ui.window_policy import WindowInteractionPolicy, apply_window_interaction_policy


class MarketAssistantOverlay(ManagedToolWindow):
    """Always-on-top click-through overlay for active market capture sessions."""

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(
            policy=WindowInteractionPolicy.PASSIVE_OVERLAY,
            parent=parent,
        )
        self.settings = settings
        self._last_payload: dict[str, Any] = {}
        self._new_best_flash = False
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._flush_pending)
        self._pending_payload: dict[str, Any] | None = None

        self.setObjectName("marketAssistOverlay")
        self.setWindowTitle("Market Assistant")
        apply_window_interaction_policy(self, WindowInteractionPolicy.PASSIVE_OVERLAY)
        self.setFixedWidth(int(settings.market_assist_overlay_width or 360))
        self.setStyleSheet(OVERLAY_STYLESHEET)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(6)

        self._header = QLabel("MARKET CAPTURE")
        self._header.setObjectName("pageTitle")
        self._session = QLabel("")
        self._session.setObjectName("baselineLabel")
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setTextVisible(True)
        self._best = QLabel("Best: —")
        self._best.setWordWrap(True)
        self._best_value = QLabel("Best value: —")
        self._best_value.setWordWrap(True)
        self._guidance = QLabel("NEXT SEARCH: —")
        self._guidance.setWordWrap(True)
        self._guidance.setObjectName("compactNote")
        self._status = QLabel("Status: —")
        self._status.setWordWrap(True)
        self._status.setObjectName("compactNote")
        self._event = QLabel("")
        self._event.setObjectName("flagChip")
        self._event.hide()

        row = QHBoxLayout()
        self._captured = QLabel("Captured: 0")
        self._captured.setObjectName("compactNote")
        self._queued = QLabel("Queued: 0")
        self._queued.setObjectName("compactNote")
        row.addWidget(self._captured)
        row.addWidget(self._queued)

        root.addWidget(self._header)
        root.addWidget(self._session)
        root.addWidget(self._progress)
        root.addLayout(row)
        root.addWidget(self._best)
        root.addWidget(self._best_value)
        root.addWidget(self._guidance)
        root.addWidget(self._status)
        root.addWidget(self._event)

        self.restore_geometry(
            x=settings.market_assist_overlay_x,
            y=settings.market_assist_overlay_y,
            width=int(settings.market_assist_overlay_width or 360),
            height=int(settings.market_assist_overlay_height or 420),
        )
        self.lock_current_size()

    def show_session(self, payload: dict[str, Any]) -> None:
        self._pending_payload = payload
        if not self._update_timer.isActive():
            self._update_timer.start(80)

    def hide_session(self) -> None:
        self._pending_payload = None
        self.hide()

    def remember_geometry_to_settings(self) -> None:
        geo = self.geometry()
        self.settings.market_assist_overlay_x = geo.x()
        self.settings.market_assist_overlay_y = geo.y()
        self.settings.market_assist_overlay_width = geo.width()
        self.settings.market_assist_overlay_height = geo.height()

        self._new_best_flash = True
        self._event.setText("NEW BEST")
        self._event.show()

    def _flush_pending(self) -> None:
        payload = self._pending_payload
        if not payload:
            return
        self._last_payload = payload
        slot = payload.get("target_slot") or "—"
        profile = payload.get("profile") or "BALANCED"
        self._session.setText(f"{slot} · {profile}")
        captured = int(payload.get("capture_count") or 0)
        evaluated = int(payload.get("evaluated_count") or 0)
        queued = int(payload.get("queued_count") or 0)
        self._captured.setText(f"Captured: {captured}")
        self._queued.setText(f"Queued: {queued}")
        pct = int((evaluated / captured) * 100) if captured else 0
        self._progress.setValue(pct)
        self._progress.setFormat(f"Evaluated {evaluated}/{captured} ({pct}%)")

        best_id = payload.get("best_observation_id")
        observations = {row.get("observation_id"): row for row in (payload.get("observations") or [])}
        best_row = observations.get(best_id) if best_id else None
        if best_row:
            delta = ((best_row.get("evaluation") or {}).get("build_value_delta")) or 0
            price = best_row.get("price") or {}
            self._best.setText(f"Best: +{float(delta):.1f} Build Value · #{best_row.get('capture_index')}")
            if price:
                self._best.setText(self._best.text() + f" @ {price.get('amount')} {price.get('currency')}")
        else:
            self._best.setText("Best: —")

        value_id = payload.get("best_value_observation_id")
        value_row = observations.get(value_id) if value_id else None
        if value_row:
            ppc = (value_row.get("evaluation") or {}).get("power_per_currency") or {}
            self._best_value.setText(
                f"Best value: {ppc.get('power_per_currency', '—')} power/{ppc.get('currency', 'unit')}"
            )
        else:
            self._best_value.setText("Best value: —")

        guidance = payload.get("guidance") or {}
        next_rows = guidance.get("next_search") or []
        if next_rows:
            parts = [str(row.get("display") or row.get("stat")) for row in next_rows[:4]]
            self._guidance.setText("NEXT SEARCH: " + ", ".join(parts))
        else:
            self._guidance.setText("NEXT SEARCH: —")

        status = payload.get("search_status") or {}
        self._status.setText(f"Status: {status.get('status', '—')} — {status.get('reason', '')}")

        if self._new_best_flash:
            self._new_best_flash = False
        else:
            self._event.hide()

        if not self.isVisible():
            self.show()
        clamp_window_to_screen(self)
