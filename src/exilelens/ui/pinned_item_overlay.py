"""Interactive draggable pinned item overlay windows."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QCloseEvent, QLinearGradient, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from exilelens.app.settings import AppSettings
from exilelens.items.presentation import build_presentation
from exilelens.ui.managed_window import ManagedToolWindow, clamp_window_to_screen
from exilelens.ui.overlay_presentation import ItemOverlayPanel
from exilelens.ui.styles import (
    OVERLAY_WINDOW_BORDER_RGBA,
    OVERLAY_WINDOW_GRADIENT_BOTTOM,
    OVERLAY_WINDOW_GRADIENT_MID,
    OVERLAY_WINDOW_GRADIENT_TOP,
    apply_overlay_theme,
    overlay_compact_width,
    overlay_stylesheet,
)
from exilelens.ui.window_policy import WindowInteractionPolicy, apply_native_extended_style, apply_window_interaction_policy


class PinnedItemOverlay(ManagedToolWindow):
    def __init__(
        self,
        settings: AppSettings,
        *,
        entry_id: str,
        pin_label: str,
        result: dict[str, Any],
        on_unpin: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(policy=WindowInteractionPolicy.INTERACTIVE_TOOL, parent=parent)
        self.settings = settings
        self.entry_id = entry_id
        self.pin_label = pin_label
        self._result = result
        self._on_unpin = on_unpin
        self._drag_origin: QPoint | None = None
        self._window_origin: QPoint | None = None
        self._stale_reason = ""
        self._unpin_called = False

        self.setObjectName("pinnedItemOverlay")
        self.setWindowTitle(f"Pinned {pin_label}")
        apply_window_interaction_policy(self, WindowInteractionPolicy.INTERACTIVE_TOOL, activate_on_show=False)
        scale = float(getattr(settings, "ui_scale", 1.0) or 1.0)
        self.setStyleSheet(overlay_stylesheet(scale))
        apply_overlay_theme(self)
        self.setFixedWidth(overlay_compact_width(scale))
        self._rarity_accent = QColor(74, 63, 50)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = QWidget()
        self._header.setObjectName("baselineStrip")
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(12, 8, 8, 8)
        self._title = QLabel(f"📌 {pin_label}")
        self._title.setObjectName("nameLabel")
        self._unpin_btn = QPushButton("Unpin")
        self._unpin_btn.setObjectName("navButtonSecondary")
        self._unpin_btn.clicked.connect(self._unpin)
        header_layout.addWidget(self._title, 1)
        header_layout.addWidget(self._unpin_btn, 0)

        self._panel = ItemOverlayPanel(self)
        self._compare_host = QWidget()
        self._compare_host.setObjectName("baselineStrip")
        compare_layout = QVBoxLayout(self._compare_host)
        compare_layout.setContentsMargins(12, 8, 12, 10)
        compare_layout.setSpacing(4)
        self._compare_title = QLabel("PINNED ITEMS")
        self._compare_title.setObjectName("warningTitle")
        self._compare_strip = QLabel("")
        self._compare_strip.setObjectName("whyLabel")
        self._compare_strip.setWordWrap(True)
        self._compare_best = QLabel("")
        self._compare_best.setObjectName("compactNote")
        compare_layout.addWidget(self._compare_title)
        compare_layout.addWidget(self._compare_strip)
        compare_layout.addWidget(self._compare_best)
        self._compare_host.hide()

        root.addWidget(self._header)
        root.addWidget(self._panel, 1)
        root.addWidget(self._compare_host)

        self._render()
        self.adjustSize()
        self.lock_current_size()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_native_extended_style(self, WindowInteractionPolicy.INTERACTIVE_TOOL)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._unpin()
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, QColor(*OVERLAY_WINDOW_GRADIENT_TOP))
        gradient.setColorAt(0.16, QColor(*OVERLAY_WINDOW_GRADIENT_MID))
        gradient.setColorAt(1.0, QColor(*OVERLAY_WINDOW_GRADIENT_BOTTOM))
        painter.fillPath(path, gradient)
        accent = QLinearGradient(rect.topLeft(), rect.topRight())
        accent.setColorAt(0.0, self._rarity_accent)
        accent.setColorAt(1.0, QColor(self._rarity_accent.red(), self._rarity_accent.green(), self._rarity_accent.blue(), 40))
        painter.setClipPath(path)
        painter.fillRect(rect.left(), rect.top(), rect.width(), 3, accent)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(*OVERLAY_WINDOW_BORDER_RGBA), 1))
        painter.drawPath(path)
        super().paintEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._header.geometry().contains(event.pos()):
            self._drag_origin = event.globalPosition().toPoint()
            self._window_origin = self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_origin is not None and self._window_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_origin
            self.move(self._window_origin + delta)
            clamp_window_to_screen(self)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_origin = None
        self._window_origin = None
        super().mouseReleaseEvent(event)

    def set_stale(self, reason: str) -> None:
        self._stale_reason = reason
        self._render()

    def update_result(self, result: dict[str, Any], *, stale_reason: str = "") -> None:
        self._result = result
        self._stale_reason = stale_reason
        self._render()

    def remember_geometry_to_settings(self) -> dict[str, int]:
        geo = self.geometry()
        payload = {
            "x": geo.x(),
            "y": geo.y(),
            "width": geo.width(),
            "height": geo.height(),
            "pin_label": self.pin_label,
        }
        self.settings.pinned_overlays[str(self.entry_id)] = payload
        return payload

    def restore_saved_geometry(self, saved: dict[str, Any] | None = None) -> None:
        saved = saved or self.settings.pinned_overlays.get(str(self.entry_id)) or {}
        width = int(saved.get("width") or 408)
        height = int(saved.get("height") or max(self.height(), 320))
        x = saved.get("x")
        y = saved.get("y")
        ManagedToolWindow.restore_geometry(self, x=x, y=y, width=width, height=height)
        clamp_window_to_screen(self)

    def _unpin(self) -> None:
        if self._unpin_called:
            return
        self._unpin_called = True
        self.remember_geometry_to_settings()
        if self._on_unpin:
            self._on_unpin(self.entry_id)
        self.hide()
        self.deleteLater()

    def _render(self) -> None:
        from exilelens.items.compact_tooltip import verdict_headline
        from exilelens.items.presentation import SurfaceMode

        meta = self._result.get("request_meta") or {}
        presentation = dict(
            self._result.get("presentation")
            or build_presentation(
                self._result,
                build_name=str(meta.get("build_name") or ""),
                loadout_name=str(meta.get("loadout_name") or ""),
                item_set_name=str(meta.get("item_set_name") or ""),
                context=str(meta.get("context") or self.settings.context),
                value_profile=str(self._result.get("value_profile") or self.settings.value_profile),
            )
        )
        outcome = dict(
            presentation.get("evaluation_outcome")
            or (self._result.get("recommendation") or {}).get("evaluation_outcome")
            or {}
        )
        if outcome:
            presentation["evaluation_outcome"] = outcome
            presentation["verdict_headline"] = verdict_headline(presentation)
            presentation["overall_line"] = presentation["verdict_headline"]
            presentation["score_class"] = str(outcome.get("verdict_class") or presentation.get("verdict_class") or "")
            score = outcome.get("final_score")
            presentation["value"] = {
                "rating": score,
                "rating_text": f"{float(score):.0f}" if score is not None else "",
                "caption": "Score",
            }
            presentation["compact_surface"] = True
        name = presentation.get("item_name") or "Item"
        self._title.setText(f"📌 {self.pin_label}  {name}")
        accent = presentation.get("rarity") or ""
        from exilelens.ui.styles import RARITY_COLOR

        self._rarity_accent = QColor(RARITY_COLOR.get(accent, "#c9a227"))
        self._panel.render_presentation(
            presentation,
            stale_reason=self._stale_reason,
            pin_label="",
            surface_mode=SurfaceMode.PINNED_EXTENDED.value,
        )
        self._render_compare_strip(self._result.get("compare_summary") or {})

    def _render_compare_strip(self, summary: dict[str, Any]) -> None:
        rows = list(summary.get("rows") or [])
        if not rows:
            self._compare_host.hide()
            return
        lines = []
        for row in rows:
            rating = row.get("rating")
            rating_text = f"{float(rating):.0f}" if rating is not None else "—"
            label = str(row.get("pin_label") or "?")
            name = str(row.get("item_name") or "Item")
            lines.append(f"{label}  {name}  {rating_text}")
        self._compare_strip.setText("\n".join(lines))
        best = summary.get("best_current_option") or {}
        if summary.get("comparable") and best.get("label"):
            self._compare_title.setText("")
            self._compare_best.setText(str(best.get("label")))
            self._compare_best.show()
        else:
            self._compare_title.setText(str(summary.get("title") or "PINNED ITEMS"))
            self._compare_best.hide()
        self._compare_host.show()
