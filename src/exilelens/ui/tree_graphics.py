"""QGraphicsView Tree Coach canvas. Lightweight batched drawing — no QWidget per node."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF, QWheelEvent
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView, QWidget

from exilelens.tree.heatmap import BAND_FILL_HEX
from exilelens.tree.models import HeatmapBand
from exilelens.tree.view_model import NodePresentation, TreeCoachViewModel, allocated_bounds

MIN_ZOOM = 0.04
MAX_ZOOM = 8.0
LABEL_LOD = 1.15
DOT_LOD = 0.18


def _qcolor(hex_color: str, alpha: int = 255) -> QColor:
    color = QColor(hex_color)
    color.setAlpha(alpha)
    return color


def _node_radius(pres: NodePresentation, lod: float) -> float:
    base = {"keystone": 22.0, "notable": 14.0, "small": 6.5}.get(pres.size_class, 6.5)
    if pres.allocated:
        base *= 1.15
    if lod < DOT_LOD:
        return max(2.2, base * 0.35)
    if lod < 0.45:
        return max(3.0, base * 0.55)
    return base


class TreeGraphItem(QGraphicsItem):
    def __init__(self) -> None:
        super().__init__()
        self.setAcceptHoverEvents(True)
        self.nodes: dict[int, NodePresentation] = {}
        self.edges: list[tuple[int, int]] = []
        self.highlighted_path: tuple[int, ...] = ()
        self.hover_id: int | None = None
        self.selected_id: int | None = None
        self.anchor_a_id: int | None = None
        self.anchor_b_id: int | None = None
        self._bounds = QRectF(-5000, -5000, 10000, 10000)
        self._grid: dict[tuple[int, int], list[int]] = {}
        self._cell = 80.0

    def set_graph(
        self,
        nodes: list[NodePresentation],
        edges: list[tuple[int, int]],
        *,
        path: tuple[int, ...] = (),
        hover_id: int | None = None,
        selected_id: int | None = None,
        anchor_a_id: int | None = None,
        anchor_b_id: int | None = None,
    ) -> None:
        self.nodes = {n.node_id: n for n in nodes}
        self.edges = edges
        self.highlighted_path = path
        self.hover_id = hover_id
        self.selected_id = selected_id
        self.anchor_a_id = anchor_a_id
        self.anchor_b_id = anchor_b_id
        self._rebuild_grid()
        if nodes:
            xs = [n.x for n in nodes]
            ys = [n.y for n in nodes]
            pad = 80
            self._bounds = QRectF(min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad)
        self.prepareGeometryChange()
        self.update()

    def boundingRect(self) -> QRectF:
        return self._bounds

    def _rebuild_grid(self) -> None:
        grid: dict[tuple[int, int], list[int]] = {}
        for node in self.nodes.values():
            key = (int(node.x // self._cell), int(node.y // self._cell))
            grid.setdefault(key, []).append(node.node_id)
        self._grid = grid

    def node_at(self, pos: QPointF, lod: float = 1.0) -> int | None:
        gx, gy = int(pos.x() // self._cell), int(pos.y() // self._cell)
        best = None
        best_d = 1e18
        for ix in range(gx - 1, gx + 2):
            for iy in range(gy - 1, gy + 2):
                for nid in self._grid.get((ix, iy), []):
                    node = self.nodes[nid]
                    dx = node.x - pos.x()
                    dy = node.y - pos.y()
                    dist = (dx * dx + dy * dy) ** 0.5
                    radius = _node_radius(node, lod) + 4
                    if dist <= radius and dist < best_d:
                        best = nid
                        best_d = dist
        return best

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: ARG002
        lod = option.levelOfDetailFromTransform(painter.worldTransform())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, lod >= 0.35)
        path_set = set(self.highlighted_path)
        allocated = {n.node_id for n in self.nodes.values() if n.allocated}

        painter.setPen(QPen(_qcolor("#2a2620", 160), 1.2))
        for a, b in self.edges:
            na, nb = self.nodes.get(a), self.nodes.get(b)
            if na is None or nb is None:
                continue
            both = a in allocated and b in allocated
            on_path = a in path_set and b in path_set
            if both:
                painter.setPen(QPen(_qcolor("#d8cbb6", 210), 2.4 if lod >= 0.4 else 1.6))
            elif on_path:
                painter.setPen(QPen(_qcolor("#f0c35a", 230), 2.8))
            else:
                if lod < DOT_LOD:
                    continue
                painter.setPen(QPen(_qcolor("#3f3a34", 90), 1.0))
            painter.drawLine(QPointF(na.x, na.y), QPointF(nb.x, nb.y))

        for node in self.nodes.values():
            if not node.visible and not node.allocated:
                continue
            radius = _node_radius(node, lod)
            fill = _qcolor(node.fill_hex if not node.allocated else "#cfc3b0")
            if node.allocated:
                fill = _qcolor("#e8dcc4")
            elif not node.evaluated and not node.unsupported:
                fill = _qcolor(BAND_FILL_HEX[HeatmapBand.UNKNOWN])
            if node.unsupported:
                fill = _qcolor("#5a5360")
            painter.setBrush(fill)
            outline = QPen(_qcolor("#1a1814"), 1.0)
            if node.allocated:
                outline = QPen(_qcolor("#f6edd4"), 2.2)
            painter.setPen(outline)
            painter.drawEllipse(QPointF(node.x, node.y), radius, radius)

            if node.frontier and not node.allocated and lod >= 0.3:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(_qcolor("#f0e2c4", 200), 1.6))
                painter.drawEllipse(QPointF(node.x, node.y), radius + 4, radius + 4)

            if node.best_next and lod >= 0.25:
                self._draw_star(painter, node.x, node.y, radius + 10)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(_qcolor("#ffd27a"), 2.0))
                painter.drawEllipse(QPointF(node.x, node.y), radius + 7, radius + 7)

            if node.breakpoint and lod >= 0.3:
                self._draw_diamond(painter, node.x + radius + 6, node.y - radius - 4, 5)

            if node.band is HeatmapBand.NEGATIVE and node.evaluated and lod >= 0.4:
                painter.setPen(QPen(_qcolor("#8ec4d4"), 1.6))
                painter.drawLine(QPointF(node.x - 4, node.y), QPointF(node.x + 4, node.y))

            if node.node_id in {self.hover_id, self.selected_id}:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(_qcolor("#fff6dc"), 1.8))
                painter.drawEllipse(QPointF(node.x, node.y), radius + 6, radius + 6)

            if node.node_id == self.anchor_a_id:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(_qcolor("#ff6b4a"), 3.0))
                painter.drawEllipse(QPointF(node.x, node.y), radius + 10, radius + 10)
                painter.setPen(_qcolor("#ff6b4a"))
                painter.drawText(QPointF(node.x + radius + 8, node.y - 8), "A")
            if node.node_id == self.anchor_b_id:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(_qcolor("#4ae0a0"), 3.0))
                painter.drawEllipse(QPointF(node.x, node.y), radius + 10, radius + 10)
                painter.setPen(_qcolor("#4ae0a0"))
                painter.drawText(QPointF(node.x + radius + 8, node.y + 12), "B")

        if lod >= LABEL_LOD:
            self._draw_labels(painter, lod)

    def _draw_labels(self, painter: QPainter, lod: float) -> None:
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        painter.setPen(_qcolor("#e4d8c4", 220))
        drawn = 0
        view = self.scene().views()[0] if self.scene() and self.scene().views() else None
        vis = None
        if view is not None:
            vis = view.mapToScene(view.viewport().rect()).boundingRect()
        for node in self.nodes.values():
            if node.size_class == "small" and node.node_id not in {self.hover_id, self.selected_id}:
                continue
            if vis is not None and not vis.contains(QPointF(node.x, node.y)):
                continue
            if node.node_id in {self.hover_id, self.selected_id} or node.best_next or node.size_class in {"notable", "keystone"}:
                painter.drawText(QPointF(node.x + 10, node.y - 8), node.name)
                drawn += 1
            if drawn >= 80:
                break

    def _draw_star(self, painter: QPainter, x: float, y: float, size: float) -> None:
        painter.setBrush(_qcolor("#ffd27a"))
        painter.setPen(QPen(_qcolor("#8a6a20"), 0.8))
        pts = []
        from math import cos, pi, sin

        for i in range(10):
            ang = -pi / 2 + i * pi / 5
            r = size if i % 2 == 0 else size * 0.45
            pts.append(QPointF(x + r * cos(ang), y + r * sin(ang)))
        painter.drawPolygon(QPolygonF(pts))

    def _draw_diamond(self, painter: QPainter, x: float, y: float, size: float) -> None:
        painter.setBrush(_qcolor("#7dcf7d"))
        painter.setPen(QPen(_qcolor("#1a1814"), 0.8))
        pts = QPolygonF(
            [
                QPointF(x, y - size),
                QPointF(x + size, y),
                QPointF(x, y + size),
                QPointF(x - size, y),
            ]
        )
        painter.drawPolygon(pts)


class TreeCoachView(QGraphicsView):
    nodeHovered = Signal(object)
    nodeSelected = Signal(object)
    viewMoved = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._graph = TreeGraphItem()
        self._scene.addItem(self._graph)
        self.setBackgroundBrush(_qcolor("#141210"))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.model: TreeCoachViewModel | None = None
        self._path: tuple[int, ...] = ()
        self.hover_id: int | None = None
        self.selected_id: int | None = None
        self.anchor_a_id: int | None = None
        self.anchor_b_id: int | None = None

    def set_model(self, model: TreeCoachViewModel) -> None:
        self.model = model
        self.rebuild()

    def rebuild(self) -> None:
        if self.model is None or self.model.graph_snapshot() is None:
            return
        nodes = self.model.all_presentations()
        graph = self.model.graph_snapshot() or self.model.snapshot
        self._graph.set_graph(
            nodes,
            list(graph.edges) if graph is not None else [],
            path=self._path,
            hover_id=self.hover_id,
            selected_id=self.selected_id,
            anchor_a_id=self.anchor_a_id,
            anchor_b_id=self.anchor_b_id,
        )
        self._scene.setSceneRect(self._graph.boundingRect())

    def set_highlighted_path(self, path: tuple[int, ...] | list[int]) -> None:
        self._path = tuple(int(n) for n in path)
        self.rebuild()

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        self.zoom_by(factor)
        event.accept()

    def zoom_by(self, factor: float) -> None:
        current = self.transform().m11()
        target = max(MIN_ZOOM, min(MAX_ZOOM, current * factor))
        applied = target / current if current else target
        self.scale(applied, applied)
        self.viewMoved.emit()

    def pan_by(self, dx: float, dy: float) -> None:
        self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() + dx))
        self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() + dy))
        self.viewMoved.emit()

    def center_on_node(self, node_id: int) -> None:
        if self.model is None:
            return
        pres = self.model.presentation(int(node_id))
        if pres is None:
            return
        self.centerOn(pres.x, pres.y)
        self.viewMoved.emit()

    def fit_allocated(self) -> None:
        graph = self.model.graph_snapshot() if self.model is not None else None
        if self.model is None or graph is None:
            return
        geom = self.model.tracking_geometry if self.model.tracking_snapshot is not None else self.model.geometry
        bounds = allocated_bounds(geom, graph.allocated_ids())
        if bounds is None:
            self.fitInView(self._graph.boundingRect(), Qt.AspectRatioMode.KeepAspectRatio)
            return
        x0, y0, x1, y1 = bounds
        pad = 180
        self.fitInView(QRectF(x0 - pad, y0 - pad, (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad), Qt.AspectRatioMode.KeepAspectRatio)
        self.viewMoved.emit()

    def fit_relevant(self) -> None:
        if self.model is None:
            return
        geom = self.model.geometry
        ids = self.model.relevant_node_ids()
        bounds = allocated_bounds(geom, ids)
        if bounds is None:
            self.fit_entire_tree()
            return
        x0, y0, x1, y1 = bounds
        pad = 180
        self.fitInView(QRectF(x0 - pad, y0 - pad, (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad), Qt.AspectRatioMode.KeepAspectRatio)
        self.viewMoved.emit()

    def fit_entire_tree(self) -> None:
        if self.model is None:
            return
        rect = self._graph.boundingRect()
        if rect.isNull():
            return
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.viewMoved.emit()

    def visible_node_ids(self) -> list[int]:
        rect = self.mapToScene(self.viewport().rect()).boundingRect()
        ids = []
        for node in self._graph.nodes.values():
            if rect.contains(QPointF(node.x, node.y)):
                ids.append(node.node_id)
        return ids

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        lod = self.transform().m11()
        nid = self._graph.node_at(self.mapToScene(event.position().toPoint()), lod)
        if nid != self.hover_id:
            self.hover_id = nid
            self._graph.hover_id = nid
            self._graph.update()
            self.nodeHovered.emit(nid)

    def mouseDoubleClickEvent(self, event) -> None:
        self.fit_allocated()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            lod = self.transform().m11()
            nid = self._graph.node_at(self.mapToScene(event.position().toPoint()), lod)
            if nid is not None:
                self.select_node(nid)
                event.accept()
                return
        super().mousePressEvent(event)

    def set_calibration_anchors(self, anchor_a: int | None, anchor_b: int | None) -> None:
        self.anchor_a_id = None if anchor_a is None else int(anchor_a)
        self.anchor_b_id = None if anchor_b is None else int(anchor_b)
        self.rebuild()

    def select_node(self, node_id: int | None) -> None:
        self.selected_id = None if node_id is None else int(node_id)
        self._graph.selected_id = self.selected_id
        if self.model is not None and self.selected_id is not None:
            pres = self.model.presentation(self.selected_id)
            if pres is not None and pres.path:
                self._path = pres.path
            elif pres is not None:
                self._path = ()
        self.rebuild()
        self.nodeSelected.emit(self.selected_id)
