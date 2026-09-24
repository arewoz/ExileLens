from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QColor, QGuiApplication, QKeySequence, QLinearGradient, QMoveEvent, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import QVBoxLayout, QWidget

from poe2value.app.settings import AppSettings, OverlayPositionMode
from poe2value.items.presentation import (
    PopupDensity,
    SurfaceMode,
    build_presentation,
)
from poe2value.items.presentation import has_passive_detail_drawer
from poe2value.ui.overlay_aux_companion import AuxEdgeCompanion
from poe2value.ui.overlay_aux_policy import (
    apply_aux_companion_policy,
    aux_policy_source,
    build_aux_trace,
    build_surface_presentation,
    sync_current_edge,
)
from poe2value.ui.overlay_geometry import max_overlay_height_logical
from poe2value.ui.overlay_positioning import OverlayExpansionPlan, apply_expansion_plan, compute_overlay_placement, plan_overlay_expansion
from poe2value.ui.overlay_presentation import ItemOverlayPanel, PriceCheckPanel
from poe2value.ui.overlay_visibility import (
    OverlayHideReason,
    OverlayLifecycleState,
    OverlayShowReason,
    OverlayVisibilityState,
)
from poe2value.ui.styles import (
    OVERLAY_WINDOW_BORDER_RGBA,
    OVERLAY_WINDOW_GRADIENT_BOTTOM,
    OVERLAY_WINDOW_GRADIENT_MID,
    OVERLAY_WINDOW_GRADIENT_TOP,
    apply_overlay_theme,
    overlay_compact_width,
    overlay_detail_width,
    overlay_stylesheet,
)
from poe2value.ui.window_policy import WindowInteractionPolicy, apply_native_extended_style, apply_window_interaction_policy, describe_interaction

logger = logging.getLogger(__name__)


class OverlayWindow(QWidget):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._visibility = OverlayVisibilityState()
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self._on_auto_hide)
        # Item Check and legacy price tooltip track separate request ids. A Shift+C that
        # runs both must not let the price surface mark the item result stale.
        self._latest_item_request_id = 0
        self._latest_price_request_id = 0
        self._latest_request_id = 0
        self._presentation_generation = 0
        self._anchor_physical: tuple[int, int] | None = None
        self._anchor_request_id = 0
        self._last_valid_anchor_physical: tuple[int, int] | None = None
        self._last_placement: dict[str, object] = {}
        self._placement_callback = None
        self._pin_callback: Callable[[], bool] | None = None
        self._can_pin_checker: Callable[[], bool] | None = None
        self._retry_callback: Callable[[], None] | None = None
        self._layout_refresh_timer = QTimer(self)
        self._layout_refresh_timer.setSingleShot(True)
        self._layout_refresh_timer.setInterval(50)
        self._layout_refresh_timer.timeout.connect(self._run_layout_refresh)
        self._pending_layout_request_id: int | None = None
        self._last_aux_trace: dict[str, object] = {}
        self._rarity_accent = QColor(74, 63, 50)
        self._overlay_mode = "build_eval"
        self._expansion_plan: OverlayExpansionPlan | None = None
        self._geometry_request_id = 0
        self._geometry_transient = False
        self._ui_scale = 1.0
        # Clamped scale the stylesheet/palette were last applied at. None until the
        # first apply, so the first render always gets a real stylesheet.
        self._styled_ui_scale: float | None = None

        self.setObjectName("overlayRoot")
        from poe2value.security_audit import overlay_disabled

        if not overlay_disabled():
            apply_window_interaction_policy(self, WindowInteractionPolicy.INTERACTIVE_OVERLAY_CHROME)
        self.apply_ui_scale(float(getattr(settings, "ui_scale", 1.0) or 1.0))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._panel = ItemOverlayPanel(self)
        layout.addWidget(self._panel)
        self._price_check_panel = PriceCheckPanel(self)
        layout.addWidget(self._price_check_panel)
        self._price_check_panel.hide()

        self._aux_companion = AuxEdgeCompanion(self)
        self._aux_companion.hide()
        self._aux_visible = False
        self._panel.detail_toggled.connect(self._on_detail_drawer_toggled)
        self._panel.pin_clicked.connect(self._on_pin_clicked)
        self._panel.retry_clicked.connect(self._on_retry_clicked)
        self._panel.hint_dismissed.connect(self._on_hint_dismissed)
        self._panel.close_clicked.connect(self.dismiss)
        # WindowShortcut only: ApplicationShortcut steals P/Esc from other ExileLens
        # widgets, and neither fires while Path of Exile is the foreground app.
        self._esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._esc_shortcut.activated.connect(self._on_escape)
        self._esc_shortcut.setEnabled(False)
        self._pin_shortcut = QShortcut(QKeySequence(Qt.Key.Key_P), self)
        self._pin_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._pin_shortcut.activated.connect(self._on_pin_hotkey)
        self._pin_shortcut.setEnabled(False)
        self.hide()
        logger.info("overlay_aux_policy source=%s", aux_policy_source())

    @property
    def OVERLAY_COMPACT_WIDTH(self) -> int:
        return overlay_compact_width(self._ui_scale)

    def apply_ui_scale(self, ui_scale: float) -> None:
        from poe2value.ui.styles import clamp_ui_scale

        self._ui_scale = clamp_ui_scale(ui_scale)
        # PERF-01: setStyleSheet makes Qt re-resolve and re-polish the whole panel
        # tree (~15 ms p50), and _position_and_show calls this on every tooltip even
        # though the scale almost never changes. Both the stylesheet and the palette
        # are pure functions of the clamped scale, so re-apply them only when that
        # actually moved. The width reset stays unconditional: callers rely on it to
        # collapse an expanded tooltip back to compact, and it costs ~0.02 ms.
        if self._styled_ui_scale != self._ui_scale:
            self._styled_ui_scale = self._ui_scale
            self.setStyleSheet(overlay_stylesheet(self._ui_scale))
            apply_overlay_theme(self)
        self.setFixedWidth(self.OVERLAY_COMPACT_WIDTH)

    def set_pin_handlers(
        self,
        *,
        on_pin: Callable[[], bool] | None = None,
        can_pin: Callable[[], bool] | None = None,
    ) -> None:
        self._pin_callback = on_pin
        self._can_pin_checker = can_pin

    def set_retry_handler(self, on_retry: Callable[[], None] | None) -> None:
        self._retry_callback = on_retry

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_native_extended_style(self, WindowInteractionPolicy.INTERACTIVE_OVERLAY_CHROME)
        self._esc_shortcut.setEnabled(True)
        self._pin_shortcut.setEnabled(self._overlay_mode == "build_eval")
        self._sync_pin_control()

    def moveEvent(self, event: QMoveEvent) -> None:  # noqa: N802
        super().moveEvent(event)
        self._sync_pin_control()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_pin_control()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._release_overlay_shortcuts()
        self._aux_companion.hide()
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._release_overlay_lifecycle()
        super().closeEvent(event)

    def _release_overlay_shortcuts(self) -> None:
        self._esc_shortcut.setEnabled(False)
        self._pin_shortcut.setEnabled(False)

    def _release_overlay_lifecycle(self) -> None:
        self._auto_hide_timer.stop()
        self._layout_refresh_timer.stop()
        self._release_overlay_shortcuts()
        self._aux_companion.hide()
        self._aux_companion.close()

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
        accent.setColorAt(
            1.0,
            QColor(self._rarity_accent.red(), self._rarity_accent.green(), self._rarity_accent.blue(), 40),
        )
        painter.setClipPath(path)
        painter.fillRect(QRect(rect.left(), rect.top(), rect.width(), 3), accent)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(*OVERLAY_WINDOW_BORDER_RGBA), 1))
        painter.drawPath(path)
        super().paintEvent(event)

    def set_overlay_enabled(self, enabled: bool) -> None:
        if not enabled:
            self.dismiss(reason=OverlayHideReason.OVERLAY_DISABLED)

    def set_presentation_generation(self, generation: int) -> None:
        self._presentation_generation = generation

    def handle_observed_click(self) -> None:
        self.dismiss(reason=OverlayHideReason.CLICK_THROUGH)

    @property
    def requested_visible(self) -> bool:
        """Logically open. A live HWND alone never means the overlay is open."""
        return self._visibility.requested_visible

    @property
    def lifecycle_state(self) -> OverlayLifecycleState:
        return self._visibility.state

    def visibility_snapshot(self) -> dict[str, object]:
        return self._visibility.snapshot()

    def _on_auto_hide(self) -> None:
        self.dismiss(reason=OverlayHideReason.AUTO_HIDE)

    def dismiss(self, *, reason: OverlayHideReason = OverlayHideReason.CLOSE_BUTTON) -> None:
        self._visibility.request_hide(
            reason,
            request_id=max(self._latest_request_id, self._latest_item_request_id, self._latest_price_request_id),
        )
        self._auto_hide_timer.stop()
        self._layout_refresh_timer.stop()
        self._release_overlay_shortcuts()
        self._aux_companion.clear()
        self._aux_companion.hide()
        self._aux_visible = False
        self._panel.reset_detail_drawer()
        self._overlay_mode = "build_eval"
        self._price_check_panel.hide()
        self._panel.show()
        self.setFixedWidth(self.OVERLAY_COMPACT_WIDTH)
        self._expansion_plan = None
        self.hide()

    def _begin_show(self, reason: OverlayShowReason, request_id: int) -> bool:
        """Gate every path that would put the overlay on screen.

        Returns False when the overlay was dismissed and `reason` is only a
        continuation of the dismissed session — a late worker result, a user
        timeout, a rescore. Those must repaint nothing.
        """
        return self._visibility.request_show(reason, request_id)

    def authorize_show(
        self,
        request_id: int,
        reason: OverlayShowReason = OverlayShowReason.EXPLICIT_ITEM_CHECK,
    ) -> None:
        """An ExileLens-owned capture started: its paints may open the overlay.

        Nothing is shown here. Called from the evaluation-started signal, which
        fires once per real Item Check before any paint.
        """
        self._visibility.authorize(reason, request_id)

    def _presentation_stale(self, request_id: int, result: dict[str, Any] | None = None) -> bool:
        if request_id < self._latest_item_request_id:
            return True
        if result is not None:
            meta = result.get("request_meta") or {}
            gen = meta.get("presentation_generation")
            if gen is not None and gen != self._presentation_generation:
                return True
        return False

    def set_placement_callback(self, callback) -> None:
        self._placement_callback = callback

    def set_anchor_cursor(
        self,
        request_id: int,
        cursor: QPoint | tuple[int, int] | None,
        *,
        physical_anchor: tuple[int, int] | None = None,
    ) -> None:
        anchor = physical_anchor
        if anchor is None and cursor is not None:
            if isinstance(cursor, QPoint):
                anchor = (int(cursor.x()), int(cursor.y()))
            else:
                anchor = (int(cursor[0]), int(cursor[1]))
        if anchor is None or (anchor[0] == 0 and anchor[1] == 0):
            return
        self._anchor_physical = anchor
        self._anchor_request_id = request_id
        self._last_valid_anchor_physical = anchor

    def show_analyzing(self, request_id: int) -> None:
        if request_id < self._latest_item_request_id:
            return
        if not self._begin_show(OverlayShowReason.EXPLICIT_ITEM_CHECK, request_id):
            return
        self._overlay_mode = "build_eval"
        self._auto_hide_timer.stop()
        self._price_check_panel.hide()
        self._panel.show()
        self._panel.show_analyzing()
        self._latest_item_request_id = request_id
        self._latest_request_id = max(self._latest_request_id, request_id)
        self._geometry_transient = True
        self._capture_first_show_geometry(request_id)
        self._position_and_show(request_id, resize=True)
        self._schedule_layout_refresh(request_id)

    def show_warming(self, request_id: int) -> None:
        if request_id < self._latest_item_request_id:
            return
        if not self._begin_show(OverlayShowReason.EXPLICIT_ITEM_CHECK_WARMING, request_id):
            return
        self._overlay_mode = "build_eval"
        self._price_check_panel.hide()
        self._panel.show()
        self._panel.show_warming()
        self._latest_item_request_id = request_id
        self._latest_request_id = max(self._latest_request_id, request_id)
        self._geometry_transient = True
        self._capture_first_show_geometry(request_id)
        self._position_and_show(request_id, resize=True)
        self._schedule_layout_refresh(request_id)

    def show_timeout(self, request_id: int) -> None:
        if self._presentation_stale(request_id):
            return
        if not self._begin_show(OverlayShowReason.USER_TIMEOUT, request_id):
            return
        self._latest_item_request_id = request_id
        self._latest_request_id = max(self._latest_request_id, request_id)
        self._overlay_mode = "build_eval"
        self._price_check_panel.hide()
        self._panel.show()
        self._panel.show_timeout()
        if self._geometry_transient or self._expansion_plan is None or self._geometry_request_id != request_id:
            self._geometry_transient = False
            self._expansion_plan = None
            self._capture_first_show_geometry(request_id)
            self._position_and_show(request_id, resize=True)
        else:
            self._apply_frozen_geometry(expanded=False)
            self.show()
        self._schedule_layout_refresh(request_id)

    def show_price_check_analyzing(self, request_id: int) -> None:
        if request_id < self._latest_price_request_id:
            return
        if not self._begin_show(OverlayShowReason.EXPLICIT_PRICE_CHECK, request_id):
            return
        self._latest_price_request_id = request_id
        self._latest_request_id = max(self._latest_request_id, request_id)
        self._overlay_mode = "price_check"
        self._panel.hide()
        self._aux_companion.clear()
        self._aux_visible = False
        self._price_check_panel.show_analyzing()
        self._price_check_panel.show()
        self._position_and_show(request_id, resize=True)
        self._schedule_layout_refresh(request_id)

    def show_price_check(self, request_id: int, presentation: dict[str, Any]) -> None:
        if request_id < self._latest_price_request_id:
            return
        if not self._begin_show(OverlayShowReason.EXPLICIT_PRICE_CHECK, request_id):
            return
        self._latest_price_request_id = request_id
        self._latest_request_id = max(self._latest_request_id, request_id)
        self._overlay_mode = "price_check"
        self._panel.hide()
        self._aux_companion.clear()
        self._aux_visible = False
        self._price_check_panel.render(presentation)
        self._price_check_panel.show()
        self._rarity_accent = QColor("#6a8fc7")
        self.update()
        self._position_and_show(request_id, resize=True)
        self._schedule_layout_refresh(request_id)
        self._reset_auto_hide()

    def show_titled_error(self, request_id: int, title: str, message: str) -> None:
        """LANG-01: an error that carries its own headline (e.g. unsupported language)."""
        self.show_error(request_id, message, title=title)

    def show_error(self, request_id: int, message: str, *, retry: bool = False, title: str = "") -> None:
        if self._presentation_stale(request_id):
            return
        if not self._begin_show(OverlayShowReason.EVALUATION_ERROR, request_id):
            return
        self._latest_item_request_id = request_id
        self._latest_request_id = max(self._latest_request_id, request_id)
        self._overlay_mode = "build_eval"
        self._price_check_panel.hide()
        self._panel.show()
        self._panel.show_error(message, retry=retry, title=title)
        if self._geometry_transient or self._expansion_plan is None:
            self._geometry_transient = False
            self._expansion_plan = None
            self._capture_first_show_geometry(request_id)
            self._position_and_show(request_id, resize=True)
        else:
            self._schedule_layout_refresh(request_id)
            self.show()
        self._reset_auto_hide()

    def _resolve_presentation(self, result: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
        if result.get("recommendation") or result.get("slot_comparisons"):
            surface_model = build_surface_presentation(
                result,
                surface=SurfaceMode.PASSIVE_COMPACT,
                build_name=str(meta.get("build_name") or ""),
                loadout_name=str(meta.get("loadout_name") or ""),
                item_set_name=str(meta.get("item_set_name") or ""),
                context=str(meta.get("context") or self.settings.context),
                value_profile=str(result.get("value_profile") or self.settings.value_profile),
            )
            if surface_model is not None:
                return surface_model
        presentation = result.get("presentation")
        if presentation is not None:
            model = dict(presentation)
            model["surface_mode"] = SurfaceMode.PASSIVE_COMPACT.value
            sync_current_edge(model, result)
            apply_aux_companion_policy(model)
            return model
        model = build_presentation(
            result,
            build_name=str(meta.get("build_name") or ""),
            loadout_name=str(meta.get("loadout_name") or ""),
            item_set_name=str(meta.get("item_set_name") or ""),
            context=str(meta.get("context") or self.settings.context),
            value_profile=str(result.get("value_profile") or self.settings.value_profile),
            popup_density=PopupDensity.COMPACT.value,
        )
        model["surface_mode"] = SurfaceMode.PASSIVE_COMPACT.value
        apply_aux_companion_policy(model)
        return model

    def show_result(self, request_id: int, result: dict[str, Any]) -> None:
        if self._presentation_stale(request_id, result):
            return
        meta = result.get("request_meta") or {}
        if meta.get("request_id") and meta["request_id"] < self._latest_item_request_id:
            return
        if not self._begin_show(OverlayShowReason.RESULT_READY, request_id):
            return
        self._latest_item_request_id = request_id
        self._latest_request_id = max(self._latest_request_id, request_id)
        self._overlay_mode = "build_eval"
        self._price_check_panel.hide()
        self._panel.show()
        self._panel.reset_detail_drawer()
        presentation = self._resolve_presentation(result, meta)
        self._render_presentation(presentation, result=result)
        self._sync_hotkey_hint()
        if self._geometry_transient or self._expansion_plan is None or self._geometry_request_id != request_id:
            self._geometry_transient = False
            self._expansion_plan = None
            self._capture_first_show_geometry(request_id)
            self._position_and_show(request_id, resize=True)
        else:
            self._apply_frozen_geometry(expanded=self._panel.detail_expanded)
        self._schedule_layout_refresh(request_id)
        self._reset_auto_hide()

    def show_last_result(self, result: dict[str, Any] | None) -> None:
        if result:
            self.show_result(self._latest_item_request_id + 1, result)

    def update_result_in_place(self, request_id: int, result: dict[str, Any]) -> None:
        if self._presentation_stale(request_id, result):
            return
        if not self._visibility.requested_visible or not self.isVisible():
            return
        meta = result.get("request_meta") or {}
        if meta.get("request_id") and meta["request_id"] < self._latest_item_request_id:
            return
        presentation = self._resolve_presentation(result, meta)
        self._render_presentation(presentation, result=result)
        self._schedule_layout_refresh(request_id)
        self._reset_auto_hide()

    def _render_presentation(self, model: dict[str, Any], *, result: dict[str, Any] | None = None) -> None:
        model = dict(model)
        if result is not None and (model.get("more_info") or {}).get("sections"):
            # Internal-only source for the allowlisted CP-07 serializer. It is
            # never copied wholesale and never becomes part of presentation.
            model["_diagnostics_result"] = result
        accent = model.get("rarity") or ""
        from poe2value.ui.styles import RARITY_COLOR

        has_detail = has_passive_detail_drawer(model)
        self._aux_visible = False
        self._aux_companion.clear()
        self._aux_companion.hide()
        self._panel.render_presentation(model, inline_current_edge=not has_detail)
        if result is not None:
            self._last_aux_trace = build_aux_trace(
                model,
                result,
                overlay_generation=self._presentation_generation,
                aux_visible=False,
                aux_show_called=False,
                aux_visible_after_show=False,
            )
            logger.info("overlay aux trace: %s", self._last_aux_trace)
        self._sync_drawer_geometry()
        self._rarity_accent = QColor(RARITY_COLOR.get(accent, "#c9a227"))
        self.update()

    def _on_detail_drawer_toggled(self, expanded: bool) -> None:
        self._sync_drawer_geometry()
        self._apply_frozen_geometry(expanded=expanded)
        self._schedule_layout_refresh(self._latest_request_id)

    def toggle_more_info(self) -> None:
        self._panel.set_detail_expanded(not self._panel.detail_expanded)

    def simulate_detail_hover_at(self, point: QPoint) -> None:
        """Compatibility for older screenshot tests — click-toggles More info."""
        self.toggle_more_info()

    def clear_detail_hover_override(self) -> None:
        return

    def _sync_drawer_geometry(self) -> None:
        self._panel.apply_drawer_layout("right")
        if self._expansion_plan is not None:
            plan = self._expansion_plan
            self._panel._drawer.set_target_width(plan.details_width_logical)
            width = plan.expanded_width_logical if self._panel.detail_expanded else plan.compact_size_logical[0]
            self.setFixedWidth(width)
        else:
            self.setFixedWidth(self.OVERLAY_COMPACT_WIDTH)

    @property
    def _name(self):
        return self._panel._name

    @property
    def _why_not_upgrade_title(self):
        return self._panel._why_not_upgrade_title

    def _reset_auto_hide(self) -> None:
        self._auto_hide_timer.stop()
        seconds = self.settings.overlay_auto_hide_seconds
        if seconds > 0:
            self._auto_hide_timer.start(int(seconds * 1000))

    def _position_and_show(self, request_id: int, *, resize: bool) -> None:
        if not self.settings.overlay_enabled:
            return
        if not self._visibility.requested_visible:
            # Reached only if a caller bypassed _begin_show. Topmost/z-order and
            # focus work must never imply visibility.
            logger.info(
                "overlay_show_suppressed reason=position_and_show_without_request request_id=%s",
                request_id,
            )
            return
        logger.info("item_check_overlay requested request_id=%s mode=%s", request_id, self._overlay_mode)
        self.apply_ui_scale(float(getattr(self.settings, "ui_scale", 1.0) or 1.0))
        if resize:
            self._apply_layout_refresh(request_id)
        if self._expansion_plan is not None and self._geometry_request_id == request_id:
            self._apply_frozen_geometry(expanded=self._panel.detail_expanded)
        else:
            self._apply_position(request_id)
        self.show()
        apply_native_extended_style(self, WindowInteractionPolicy.INTERACTIVE_OVERLAY_CHROME)
        if self._overlay_mode == "price_check":
            logger.info(
                "price_check_overlay_show request_id=%s interaction=%s",
                request_id,
                describe_interaction(self),
            )
        else:
            screen = self.screen()
            logger.info(
                "item_check_overlay shown request_id=%s rect=%s screen=%s dpr=%s visible=%s interaction=%s",
                request_id,
                (self.x(), self.y(), self.width(), self.height()),
                screen.name() if screen is not None else "",
                float(screen.devicePixelRatio() or 1.0) if screen is not None else 1.0,
                self.isVisible(),
                describe_interaction(self),
            )
        self.raise_()
        self._sync_pin_control()

    def _schedule_layout_refresh(self, request_id: int) -> None:
        self._pending_layout_request_id = request_id
        if self._layout_refresh_timer.isActive():
            return
        self._layout_refresh_timer.start()

    def _run_layout_refresh(self) -> None:
        request_id = self._pending_layout_request_id
        self._pending_layout_request_id = None
        if request_id is None or not self.isVisible():
            return
        if not self._visibility.requested_visible:
            # A refresh queued before a dismissal must not repaint a closed overlay.
            return
        if self._presentation_stale(request_id):
            # A deferred refresh that arrives after a newer presentation would resize the
            # new content to the old content's measurements.
            return
        self._apply_layout_refresh(request_id)
        if self._expansion_plan is None or self._geometry_request_id != request_id:
            self._apply_position(request_id)
        else:
            self._apply_frozen_geometry(expanded=self._panel.detail_expanded)
        self._sync_pin_control()

    def _apply_layout_refresh(self, request_id: int) -> None:
        """Size the overlay to what it is showing *now*, in both directions.

        Two things make this less obvious than it looks. The previous pass left the
        window at a fixed height, so the constraint has to be released before anything
        can be measured. And Qt caches a layout's size hint, so after the panel's content
        has been replaced the cached hint still describes the old content until the
        layout is invalidated — which is why a taller result used to leave the window
        short, and a shorter one used to leave it tall.

        The height therefore comes from the freshly computed hint alone. Folding the
        current height into it (``max(hint, self.height())``) would make the overlay able
        to grow but never shrink, so a tall build comparison would leave a one-line
        "Checking market..." inheriting its height.
        """
        anchor = self._anchor_physical if self._anchor_request_id == request_id else None
        cap = 16777215
        if anchor is not None:
            cap = max_overlay_height_logical(anchor)

        self.setMinimumHeight(0)
        self.setMaximumHeight(cap)

        # Drop the cached hints for the content that is on screen now.
        for widget in self._content_widgets():
            widget.updateGeometry()
            layout = widget.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
        layout = self.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()

        self.adjustSize()
        natural = self.sizeHint().height()
        if natural <= 0:
            # Nothing measurable yet; keep whatever is on screen rather than collapsing
            # the window to nothing.
            natural = max(self.height(), 1)
        self.setFixedHeight(max(1, min(natural, cap)))

    def _content_widgets(self) -> tuple[QWidget, ...]:
        """The panels whose content decides the height, visible ones first.

        Both panels are asked, not just the active one: a hidden panel that was just
        swapped out still holds a stale hint, and leaving it cached is what let the old
        size leak into the new presentation.
        """
        return tuple(
            widget for widget in (self._panel, self._price_check_panel) if widget is not None
        )

    def _sync_pin_control(self) -> None:
        allowed = True
        if self._can_pin_checker is not None:
            allowed = bool(self._can_pin_checker())
        self._panel._pin_button.setEnabled(allowed and not self._panel._pinned)
        self._panel._pin_button.setToolTip("" if allowed else "Maximum 4 pinned items.")

    def _on_pin_clicked(self) -> None:
        if self._pin_callback is not None:
            if self._pin_callback():
                self.dismiss()

    def _on_pin_hotkey(self) -> None:
        if not self.isVisible() or self._overlay_mode != "build_eval":
            return
        self._on_pin_clicked()

    def _on_escape(self) -> None:
        if not self.isVisible():
            return
        if self._panel.detail_expanded:
            self._panel.set_detail_expanded(False)
            self._sync_drawer_geometry()
            self._schedule_layout_refresh(self._latest_request_id)
            return
        self.dismiss(reason=OverlayHideReason.ESCAPE)

    def _on_retry_clicked(self) -> None:
        if self._retry_callback is not None:
            self._retry_callback()

    def _on_hint_dismissed(self) -> None:
        self.settings.show_hotkey_hints = False
        self.settings.hotkey_hints_dismissed = True
        from poe2value.app.settings import save_settings

        save_settings(self.settings)

    def _sync_hotkey_hint(self) -> None:
        from poe2value.ui.health import hotkey_display

        show = bool(getattr(self.settings, "show_hotkey_hints", True))
        dismissed = bool(getattr(self.settings, "hotkey_hints_dismissed", False))
        count = int(getattr(self.settings, "hotkey_hints_success_count", 0) or 0)
        visible = show and not dismissed and count < 5
        self._panel.set_hotkey_hint_text(f"{hotkey_display(self.settings)} to analyze")
        self._panel.set_hotkey_hint_visible(visible)

    def _capture_first_show_geometry(self, request_id: int) -> None:
        """Store origin + expansion plan once. Later expand/collapse reuse it."""
        if self._expansion_plan is not None and self._geometry_request_id == request_id:
            return
        self._geometry_request_id = request_id
        self._expansion_plan = None

    def _apply_frozen_geometry(self, *, expanded: bool) -> None:
        plan = self._expansion_plan
        if plan is None:
            return
        cap = plan.max_height_logical
        self.setMinimumHeight(0)
        self.setMaximumHeight(cap)
        self._panel._drawer.set_target_width(plan.details_width_logical)
        for widget in self._content_widgets():
            widget.updateGeometry()
            layout = widget.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
        self.adjustSize()
        natural = max(self.sizeHint().height(), 1)
        x, y, width, height = apply_expansion_plan(plan, content_height_logical=natural, expanded=expanded)
        self.setFixedWidth(width)
        self.setFixedHeight(max(1, min(height, cap)))
        self.move(QPoint(x, y))
        if not expanded:
            from dataclasses import replace

            self._expansion_plan = replace(plan, compact_size_logical=(plan.compact_size_logical[0], height))
        self._panel._drawer.setMaximumHeight(max(80, height - 8))

    def _apply_position(self, request_id: int) -> None:
        mode = self.settings.overlay_position_mode
        if mode == OverlayPositionMode.NEAR_ITEM.value and self._anchor_physical and self._anchor_request_id == request_id:
            self._apply_near_anchor(self._anchor_physical)
            return
        self._apply_fixed_corner()

    def _apply_near_anchor(self, anchor_physical: tuple[int, int]) -> None:
        compact_w = self.OVERLAY_COMPACT_WIDTH
        detail_w = overlay_detail_width(self._ui_scale)
        reserve_w = compact_w + detail_w + 1
        placement = compute_overlay_placement(
            compact_w,
            self.height(),
            copy_anchor_physical=anchor_physical,
            offset_px=int(self.settings.overlay_near_offset_px),
            last_valid_anchor_physical=self._last_valid_anchor_physical,
            aux_size_logical=None,
            reserve_width_logical=reserve_w,
        )
        self.move(placement.logical_pos)
        self._aux_companion.hide()
        self._last_placement = {
            "anchor_source": placement.anchor_source,
            "anchor_physical": placement.anchor_physical,
            "overlay_rect_logical": placement.overlay_rect_logical,
            "overlay_rect_physical": placement.overlay_rect_physical,
            "placement_strategy": placement.placement_strategy,
            "monitor_work_area_physical": placement.monitor_work_area_physical,
            "fallback_reason": placement.fallback_reason,
            "aux_logical_pos": placement.aux_logical_pos,
            "aux_overlay_rect_physical": placement.aux_overlay_rect_physical,
            "group_rect_physical": placement.group_rect_physical,
            "group_layout_mode": placement.group_layout_mode,
        }
        plan = plan_overlay_expansion(
            placement,
            compact_width_logical=compact_w,
            compact_height_logical=self.height(),
            details_width_logical=detail_w,
        )
        self._expansion_plan = plan
        self.move(QPoint(plan.origin_logical[0], plan.origin_logical[1]))
        if self._placement_callback is not None:
            self._placement_callback(self._last_placement)

    def _apply_fixed_corner(self) -> None:
        pos = self.settings.overlay_position
        screen = None
        try:
            from poe2value.platform.windows.poe_window import poe_client_geometry

            poe = poe_client_geometry()
            if poe is not None:
                x0, y0, x1, y1 = poe.client_logical
                screen = QGuiApplication.screenAt(QPoint((x0 + x1) // 2, (y0 + y1) // 2))
        except Exception:
            logger.debug("could not resolve PoE screen for fixed-corner overlay", exc_info=True)
        screen = screen or QGuiApplication.primaryScreen()
        if not screen:
            return
        available: QRect = screen.availableGeometry()
        margin = 16
        x = pos.x
        y = pos.y
        if x is None or y is None:
            corner = pos.corner or "top_right"
            if corner == "top_left":
                x = available.left() + margin
                y = available.top() + margin
            elif corner == "bottom_left":
                x = available.left() + margin
                y = available.bottom() - self.height() - margin
            elif corner == "bottom_right":
                x = available.right() - self.width() - margin
                y = available.bottom() - self.height() - margin
            else:
                x = available.right() - self.width() - margin
                y = available.top() + margin
        self.move(QPoint(int(x), int(y)))
        self._aux_companion.hide()
        from poe2value.ui.overlay_positioning import OverlayPlacement

        fake = OverlayPlacement(
            logical_pos=QPoint(int(x), int(y)),
            anchor_source="FIXED_CORNER",
            anchor_physical=self._anchor_physical or (int(x), int(y)),
            monitor_work_area_physical=(
                available.left(),
                available.top(),
                available.right(),
                available.bottom(),
            ),
            overlay_rect_logical=(int(x), int(y), self.width(), self.height()),
            placement_strategy="fixed-corner",
        )
        detail_w = overlay_detail_width(self._ui_scale)
        plan = plan_overlay_expansion(
            fake,
            compact_width_logical=self.width(),
            compact_height_logical=self.height(),
            details_width_logical=detail_w,
        )
        self._expansion_plan = plan
        self.move(QPoint(plan.origin_logical[0], plan.origin_logical[1]))

    def remember_position(self) -> None:
        if self.settings.overlay_position_mode != OverlayPositionMode.FIXED_CORNER.value:
            return
        pos = self.pos()
        from poe2value.app.settings import OverlayPosition

        self.settings.overlay_position = OverlayPosition(
            corner=self.settings.overlay_position.corner,
            x=pos.x(),
            y=pos.y(),
        )
