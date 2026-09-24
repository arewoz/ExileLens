"""Click-through live tree overlay. Guidance only — no SendInput, OCR, or game memory."""

from __future__ import annotations

import logging

from typing import Any, Callable

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from exilelens.platform.windows.poe_window import (
    PoeClientGeometry,
    describe_widget_hwnd,
    poe_client_geometry,
    set_hwnd_topmost,
)
from exilelens.tree.overlay_frame import LiveTreeOverlayFrame, OverlayAppearance, OverlayMarker
from exilelens.tree.overlay_mode import OverlayMode
from exilelens.tree.transform import TreeOverlayCalibration, TreeScreenTransform, current_display_env
from exilelens.tree.view_model import TreeCoachViewModel
from exilelens.ui.window_policy import WindowInteractionPolicy, apply_native_extended_style, apply_window_interaction_policy, describe_interaction

logger = logging.getLogger(__name__)

OUTER_STROKE = QColor(8, 10, 16, 255)
INNER_PATH = QColor(126, 240, 255, 255)
TEST_YELLOW = QColor(255, 220, 40, 255)
TEST_TEXT = QColor(255, 255, 255, 255)


class LiveTreeOverlayWindow(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("liveTreeOverlay")
        self.setWindowTitle("TREE OVERLAY")
        apply_window_interaction_policy(self, WindowInteractionPolicy.PERSISTENT_TREE_OVERLAY)
        self._frame: LiveTreeOverlayFrame | None = None
        self._visible_requested = False
        self._test_pattern = False
        self._debug = False
        self._appearance = OverlayAppearance()
        self._client: PoeClientGeometry | None = None
        self._geometry_provider: Callable[[], PoeClientGeometry | None] = poe_client_geometry
        self._follow = QTimer(self)
        self._follow.setInterval(250)
        self._follow.timeout.connect(self._sync_to_poe_client)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setWindowOpacity(1.0)
        self.setAutoFillBackground(False)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_native_extended_style(self, WindowInteractionPolicy.PERSISTENT_TREE_OVERLAY)
        try:
            set_hwnd_topmost(int(self.winId()), topmost=True)
        except Exception:
            pass

    def set_geometry_provider(self, provider: Callable[[], PoeClientGeometry | None]) -> None:
        self._geometry_provider = provider

    def set_frame(self, frame: LiveTreeOverlayFrame | None) -> None:
        self._frame = frame
        self.update()
        if self._visible_requested:
            self._sync_to_poe_client()
            self.show()

    def set_overlay_visible(self, visible: bool) -> None:
        self._visible_requested = visible
        if not visible:
            self._follow.stop()
            self.hide()
            return
        self._sync_to_poe_client()
        self._follow.start()
        self.show()
        apply_native_extended_style(self, WindowInteractionPolicy.PERSISTENT_TREE_OVERLAY)
        try:
            set_hwnd_topmost(int(self.winId()), topmost=True)
        except Exception:
            pass

    def set_test_pattern(self, enabled: bool) -> None:
        self._test_pattern = bool(enabled)
        if enabled:
            self.set_overlay_visible(True)
        self.update()

    def set_debug(self, enabled: bool) -> None:
        self._debug = bool(enabled)
        self.update()

    def set_appearance(self, appearance: OverlayAppearance) -> None:
        self._appearance = appearance
        self.update()

    def clear_markers(self) -> None:
        self._frame = None
        self.update()

    def client_logical_rect(self) -> tuple[int, int, int, int]:
        if self._client is not None:
            return self._client.client_logical
        geo = self.geometry()
        return (geo.x(), geo.y(), geo.x() + geo.width(), geo.y() + geo.height())

    def _fallback_screen_rect(self) -> QRect:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, 1280, 720)
        return screen.geometry()

    def _sync_to_poe_client(self) -> None:
        if not self._visible_requested:
            return
        client = None
        try:
            client = self._geometry_provider()
        except Exception:
            client = None
        self._client = client
        if client is not None:
            x0, y0, x1, y1 = client.client_logical
            self.setGeometry(int(x0), int(y0), max(64, int(x1 - x0)), max(64, int(y1 - y0)))
        else:
            geo = self._fallback_screen_rect()
            self.setGeometry(geo)
        apply_native_extended_style(self, WindowInteractionPolicy.PERSISTENT_TREE_OVERLAY)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if self._test_pattern:
            self._paint_test_pattern(painter)
            return
        frame = self._frame
        if frame is None:
            if self._debug:
                self._paint_debug(painter, empty=True)
            return
        for edge in frame.edges:
            self._paint_edge(painter, edge.ax, edge.ay, edge.bx, edge.by)
        for marker in frame.markers:
            self._paint_marker(painter, marker)
        if frame.status_line:
            self._paint_outlined_text(painter, 16, 28, frame.status_line)
        if frame.misalignment:
            self._paint_outlined_text(painter, 16, 56, frame.misalignment, QColor(255, 80, 80, 255))
        if self._debug:
            self._paint_debug(painter, empty=False)

    def _alpha(self, color: QColor, extra: int = 255) -> QColor:
        scaled = int(round(extra * max(0.35, min(1.0, self._appearance.opacity))))
        out = QColor(color)
        out.setAlpha(max(90, min(255, scaled)))
        return out

    def _paint_edge(self, painter: QPainter, ax: float, ay: float, bx: float, by: float) -> None:
        width = max(2.0, float(self._appearance.line_width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self._alpha(OUTER_STROKE, 255), width + 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPoint(int(ax), int(ay)), QPoint(int(bx), int(by)))
        inner = QColor(INNER_PATH)
        painter.setPen(QPen(self._alpha(inner, 240), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPoint(int(ax), int(ay)), QPoint(int(bx), int(by)))

    def _paint_marker(self, painter: QPainter, marker: OverlayMarker) -> None:
        origin = QPoint(int(marker.screen_x), int(marker.screen_y))
        scale = max(0.6, float(self._appearance.marker_size))
        radius = 10.0 * scale
        if marker.size_class == "notable":
            radius = 14.0 * scale
        if marker.size_class == "keystone" or marker.kind.startswith("anchor"):
            radius = 18.0 * scale
        if marker.best_next:
            radius += 4
        fill = QColor(marker.fill_hex)
        outer = self._alpha(OUTER_STROKE, 255)
        inner = self._alpha(fill, 255)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if marker.breakpoint:
            self._draw_diamond(painter, origin, radius, outer, inner)
        elif marker.best_next:
            self._draw_star(painter, origin, radius + 6, outer, inner)
            painter.setPen(QPen(outer, 4))
            painter.drawEllipse(origin, int(radius), int(radius))
            painter.setPen(QPen(inner, 2.5))
            painter.drawEllipse(origin, int(radius), int(radius))
        else:
            painter.setPen(QPen(outer, 5 if marker.kind == "path" else 4))
            painter.drawEllipse(origin, int(radius), int(radius))
            painter.setPen(QPen(inner, 2.5))
            painter.drawEllipse(origin, int(radius), int(radius))
        if marker.kind.startswith("anchor"):
            label = "A" if marker.kind.endswith("a") else "B"
            self._paint_outlined_text(painter, origin.x() + int(radius) + 4, origin.y() - 4, label, inner)

    def _draw_star(self, painter: QPainter, origin: QPoint, size: float, outer: QColor, inner: QColor) -> None:
        from math import cos, pi, sin

        pts = []
        for i in range(10):
            ang = -pi / 2 + i * pi / 5
            r = size if i % 2 == 0 else size * 0.45
            pts.append(QPointF(origin.x() + r * cos(ang), origin.y() + r * sin(ang)))
        painter.setPen(QPen(outer, 3))
        painter.setBrush(inner)
        painter.drawPolygon(QPolygonF(pts))

    def _draw_diamond(self, painter: QPainter, origin: QPoint, size: float, outer: QColor, inner: QColor) -> None:
        pts = QPolygonF(
            [
                QPointF(origin.x(), origin.y() - size),
                QPointF(origin.x() + size, origin.y()),
                QPointF(origin.x(), origin.y() + size),
                QPointF(origin.x() - size, origin.y()),
            ]
        )
        painter.setPen(QPen(outer, 4))
        painter.setBrush(inner)
        painter.drawPolygon(pts)

    def _paint_test_pattern(self, painter: QPainter) -> None:
        rect = self.rect().adjusted(4, 4, -4, -4)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(TEST_YELLOW, 10))
        painter.drawRect(rect)
        cx, cy = rect.center().x(), rect.center().y()
        painter.setPen(QPen(QColor(255, 40, 80, 255), 6))
        painter.drawLine(cx, rect.top(), cx, rect.bottom())
        painter.drawLine(rect.left(), cy, rect.right(), cy)
        corners = [
            (rect.left() + 18, rect.top() + 18, QColor(255, 40, 40, 255)),
            (rect.right() - 18, rect.top() + 18, QColor(40, 255, 80, 255)),
            (rect.left() + 18, rect.bottom() - 18, QColor(40, 120, 255, 255)),
            (rect.right() - 18, rect.bottom() - 18, QColor(255, 0, 220, 255)),
        ]
        for x, y, color in corners:
            painter.setBrush(color)
            painter.setPen(QPen(OUTER_STROKE, 3))
            painter.drawRect(x - 16, y - 16, 32, 32)
        self._paint_outlined_text(painter, cx - 140, cy - 24, "TREE OVERLAY TEST", TEST_TEXT, point=22)

    def _paint_debug(self, painter: QPainter, *, empty: bool) -> None:
        geo = self.geometry()
        client = self._client
        frame = self._frame
        hwnd = describe_widget_hwnd(self)
        lines = [
            "TREE OVERLAY DEBUG",
            f"window: {geo.width()}x{geo.height()} @ ({geo.x()},{geo.y()})",
            f"PoE client: {self._client_debug_line(client)}",
            f"markers: {0 if frame is None else len(frame.markers)}",
            f"calibration: {(frame.calibration_status if frame else 'n/a')}",
            f"hwnd: {hwnd.get('hwnd')} topmost={hwnd.get('topmost')}",
            f"click-through: {describe_interaction(self).get('click_through')}",
            f"opacity: {self.windowOpacity():.2f}",
            f"origin: (0,0) local → global ({geo.x()},{geo.y()})",
        ]
        if empty:
            lines.append("frame: empty")
        y = 80
        for line in lines:
            self._paint_outlined_text(painter, 16, y, line, QColor(255, 240, 180, 255))
            y += 20
        painter.setPen(QPen(QColor(255, 255, 255, 255), 3))
        painter.drawRect(self.rect().adjusted(2, 2, -2, -2))
        cx, cy = self.rect().center().x(), self.rect().center().y()
        painter.drawLine(cx - 24, cy, cx + 24, cy)
        painter.drawLine(cx, cy - 24, cx, cy + 24)

    def _client_debug_line(self, client: PoeClientGeometry | None) -> str:
        if client is None:
            return "not detected (using fallback screen)"
        x0, y0, x1, y1 = client.client_logical
        return f"{x1 - x0}x{y1 - y0} @ ({x0},{y0})"

    def _paint_outlined_text(
        self,
        painter: QPainter,
        x: int,
        y: int,
        text: str,
        color: QColor | None = None,
        *,
        point: int = 12,
    ) -> None:
        font = QFont("Segoe UI", point, QFont.Weight.Bold)
        painter.setFont(font)
        path = QPainterPath()
        path.addText(x, y, font, text)
        painter.setPen(QPen(OUTER_STROKE, 3))
        painter.setBrush(OUTER_STROKE)
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color or TEST_TEXT)
        painter.drawPath(path)

    def render_probe_alpha(self) -> int:
        """Max painted alpha of the current widget (visibility proof)."""
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QImage

        image = QImage(max(8, self.width()), max(8, self.height()), QImage.Format.Format_ARGB32)
        image.fill(0)
        self.render(image, QPoint(0, 0))
        peak = 0
        for y in range(0, image.height(), 4):
            for x in range(0, image.width(), 4):
                peak = max(peak, QColor(image.pixel(x, y)).alpha())
        return peak

    def hwnd_diagnostic(self) -> dict[str, Any]:
        info = describe_interaction(self)
        info.update(describe_widget_hwnd(self))
        info["test_pattern"] = self._test_pattern
        info["debug"] = self._debug
        info["client"] = None if self._client is None else {
            "hwnd": self._client.hwnd,
            "title": self._client.title,
            "client_logical": self._client.client_logical,
        }
        info["paint_alpha"] = 255 if self._test_pattern else (200 if self._frame and self._frame.markers else 0)
        return info


def calibration_status_for(saved: dict[str, Any] | None) -> str:
    if not saved:
        return "REQUIRED"
    try:
        cal = TreeOverlayCalibration.from_dict(saved)
    except Exception:
        return "REQUIRED"
    if saved.get("stale_reason") or not cal.valid:
        return "STALE"
    env = current_display_env()
    if not cal.matches_environment(env["display_id"], env["geometry"], env["dpi"]):
        return "STALE"
    return "OK"


def frame_from_model(
    model: TreeCoachViewModel,
    *,
    baseline_generation: int,
    calibration: dict[str, Any] | None,
    viewport: tuple[float, float, float, float] | None = None,
    mode: OverlayMode = OverlayMode.BUILD_PATH,
    transform: TreeScreenTransform | None = None,
    anchors: tuple[int | None, int | None] = (None, None),
    preview: bool = False,
    debug: dict[str, Any] | None = None,
    tracked_snapshot=None,
    tracked_generation: int = 0,
):
    from exilelens.tree.overlay_frame import compose_overlay_frame

    status = calibration_status_for(calibration)
    fitted = transform
    if fitted is None and calibration:
        try:
            fitted = TreeOverlayCalibration.from_dict(calibration).transform
        except Exception:
            fitted = None
            status = "REQUIRED"
    path_snapshot = tracked_snapshot
    eval_model = model
    if mode is OverlayMode.BUILD_PATH:
        path_snapshot = tracked_snapshot or model.tracking_snapshot or model.snapshot
        eval_model = None
    elif mode is OverlayMode.CALIBRATION_ANCHORS:
        path_snapshot = tracked_snapshot or model.tracking_snapshot or model.snapshot
        eval_model = None
    else:
        path_snapshot = model.snapshot
    generation = tracked_generation if mode is OverlayMode.BUILD_PATH and tracked_generation else baseline_generation
    return compose_overlay_frame(
        snapshot=path_snapshot,
        transform=fitted,
        mode=mode,
        baseline_generation=generation,
        calibration_status=status,
        overlay_rect=viewport,
        model=eval_model,
        anchors=anchors,
        preview=preview,
        debug=debug,
    )


def stack_item_above_tree(*, tree: QWidget, item: QWidget | None) -> None:
    """Required layering: PoE < Tree Overlay < Item Overlay.

    Z-order only. A window that is not on screen is left alone — restacking must
    never be able to bring back an overlay the user dismissed.
    """
    logger.info(
        "overlay_topmost_refresh tree_visible=%s item_visible=%s item_requested=%s",
        bool(tree.isVisible()),
        bool(item is not None and item.isVisible()),
        bool(item is not None and getattr(item, "requested_visible", False)),
    )
    if tree.isVisible():
        tree.raise_()
        try:
            set_hwnd_topmost(int(tree.winId()), topmost=True)
        except Exception:
            pass
    if item is not None and item.isVisible() and getattr(item, "requested_visible", True):
        item.raise_()
        apply_native_extended_style(item, WindowInteractionPolicy.PASSIVE_OVERLAY)
        try:
            set_hwnd_topmost(int(item.winId()), topmost=True)
        except Exception:
            pass
