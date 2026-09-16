"""Interactive calibration layer for the live tree overlay."""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from poe2value.tree.models import NodeType
from poe2value.tree.transform import (
    TreeOverlayCalibration,
    TreeScreenTransform,
    TransformError,
    current_display_env,
    fit_anchors,
)
from poe2value.tree.view_model import TreeCoachViewModel
from poe2value.ui.window_policy import WindowInteractionPolicy, apply_native_extended_style, apply_window_interaction_policy


def propose_anchors(model: TreeCoachViewModel, limit: int = 8) -> list[dict[str, Any]]:
    snapshot = model.snapshot
    if snapshot is None:
        return []
    candidates = []
    for node in snapshot.nodes.values():
        if not node.allocated or node.x is None or node.y is None:
            continue
        if node.type not in {NodeType.NOTABLE, NodeType.KEYSTONE}:
            continue
        candidates.append({"node_id": node.id, "name": node.name, "x": float(node.x), "y": float(node.y), "type": node.type.value})
    candidates.sort(key=lambda row: (0 if row["type"] == NodeType.KEYSTONE.value else 1, row["name"]))
    # Prefer geographically spread: first, farthest from first, farthest from both.
    if len(candidates) < 2:
        extra = [
            {"node_id": n.id, "name": n.name, "x": float(n.x), "y": float(n.y), "type": n.type.value}
            for n in snapshot.nodes.values()
            if n.allocated and n.x is not None and n.y is not None
        ]
        candidates = extra
    picked: list[dict[str, Any]] = []
    if candidates:
        picked.append(candidates[0])
        rest = candidates[1:]
        rest.sort(key=lambda row: (row["x"] - picked[0]["x"]) ** 2 + (row["y"] - picked[0]["y"]) ** 2, reverse=True)
        if rest:
            picked.append(rest[0])
        if len(rest) > 1:
            a, b = picked[0], picked[1]
            rest[1:].sort(
                key=lambda row: min(
                    (row["x"] - a["x"]) ** 2 + (row["y"] - a["y"]) ** 2,
                    (row["x"] - b["x"]) ** 2 + (row["y"] - b["y"]) ** 2,
                ),
                reverse=True,
            )
            if rest[1:]:
                picked.append(rest[1])
    return picked[:limit]


class ClickCaptureLayer(QWidget):
    clicked_at = Signal(float, float)

    def __init__(self) -> None:
        super().__init__(None)
        apply_window_interaction_policy(
            self,
            WindowInteractionPolicy.INTERACTIVE_TRANSPARENT_CAPTURE,
            activate_on_show=True,
        )
        self.setWindowTitle("Click the matching in-game node")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_native_extended_style(self, WindowInteractionPolicy.INTERACTIVE_TOOL)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        global_pos = event.globalPosition()
        self.clicked_at.emit(float(global_pos.x()), float(global_pos.y()))
        event.accept()


class TreeOverlayCalibrationDialog(QDialog):
    def __init__(self, model: TreeCoachViewModel, saved: dict[str, Any] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        apply_window_interaction_policy(self, WindowInteractionPolicy.INTERACTIVE_TOOL, activate_on_show=True)
        self.setWindowTitle("Calibrate Tree Overlay")
        self.resize(520, 560)
        self.model = model
        self._saved = saved or {}
        self._transform: TreeScreenTransform | None = None
        self._tree_pts: list[tuple[float, float]] = []
        self._screen_pts: list[tuple[float, float]] = []
        self._anchor_ids: list[int] = []
        self._pending_anchor: dict[str, Any] | None = None
        self._layer: ClickCaptureLayer | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Live overlay uses PoB tree coordinates plus this calibration.\n"
            "There is no OCR, screenshot matching, or game-memory sync.\n"
            "If you pan or zoom the PoE tree, use Re-align."
        ))
        self._list = QListWidget()
        for row in propose_anchors(model):
            item = QListWidgetItem(f"{row['name']} ({row['type']})")
            item.setData(Qt.ItemDataRole.UserRole, row)
            self._list.addItem(item)
        layout.addWidget(QLabel("Proposed anchors (allocated notables / keystones)"))
        layout.addWidget(self._list)
        row = QHBoxLayout()
        click_a = QPushButton("Click in-game for selected anchor")
        click_a.clicked.connect(self._capture_selected)
        realign = QPushButton("Re-align translation from selected")
        realign.clicked.connect(self._realign)
        row.addWidget(click_a)
        row.addWidget(realign)
        layout.addLayout(row)
        self._status = QLabel("Select two distant anchors, then click each matching in-game node.")
        layout.addWidget(self._status)

        self._dx = QSlider(Qt.Orientation.Horizontal)
        self._dy = QSlider(Qt.Orientation.Horizontal)
        self._scale = QSlider(Qt.Orientation.Horizontal)
        for slider, lo, hi, val in ((self._dx, -400, 400, 0), (self._dy, -400, 400, 0), (self._scale, 50, 200, 100)):
            slider.setRange(lo, hi)
            slider.setValue(val)
            slider.valueChanged.connect(self._nudge)
        layout.addWidget(QLabel("Fine tune X"))
        layout.addWidget(self._dx)
        layout.addWidget(QLabel("Fine tune Y"))
        layout.addWidget(self._dy)
        layout.addWidget(QLabel("Fine tune scale %"))
        layout.addWidget(self._scale)

        buttons = QHBoxLayout()
        save = QPushButton("Save calibration")
        save.clicked.connect(self._save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        if saved:
            try:
                cal = TreeOverlayCalibration.from_dict(saved)
                self._transform = cal.transform
                self._tree_pts = list(cal.anchor_tree)
                self._screen_pts = list(cal.anchor_screen)
                self._anchor_ids = list(cal.anchor_node_ids)
                self._dx.setValue(int(cal.transform.dx))
                self._dy.setValue(int(cal.transform.dy))
                self._scale.setValue(int(round(cal.transform.extra_scale * 100)))
                self._status.setText("Loaded saved calibration. Fine-tune or recapture anchors.")
            except Exception:
                pass

    def result_calibration(self) -> dict[str, Any] | None:
        if self._transform is None:
            return None
        env = current_display_env()
        cal = TreeOverlayCalibration(
            display_id=str(env["display_id"]),
            geometry=tuple(env["geometry"]),
            dpi=float(env["dpi"]),
            transform=self._transform,
            anchor_node_ids=list(self._anchor_ids),
            anchor_tree=list(self._tree_pts),
            anchor_screen=list(self._screen_pts),
            created_at=time.time(),
            valid=True,
        )
        return cal.to_dict()

    def _capture_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            QMessageBox.information(self, "Calibrate", "Select an anchor node first.")
            return
        self._pending_anchor = item.data(Qt.ItemDataRole.UserRole)
        self._layer = ClickCaptureLayer()
        self._layer.clicked_at.connect(self._on_game_click)
        self._layer.showFullScreen()
        self._status.setText(f"Click the in-game node: {self._pending_anchor.get('name')}")

    def _on_game_click(self, x: float, y: float) -> None:
        if self._layer is not None:
            self._layer.close()
            self._layer = None
        row = self._pending_anchor
        if not row:
            return
        self._anchor_ids.append(int(row["node_id"]))
        self._tree_pts.append((float(row["x"]), float(row["y"])))
        self._screen_pts.append((x, y))
        self._pending_anchor = None
        self._fit()

    def _fit(self) -> None:
        if len(self._tree_pts) < 2:
            self._status.setText(f"Captured {len(self._tree_pts)} / 2 anchors.")
            return
        try:
            self._transform = fit_anchors(self._tree_pts, self._screen_pts)
            self._nudge()
            self._status.setText(f"Fitted {len(self._tree_pts)}-point transform in Qt logical pixels.")
        except TransformError as exc:
            self._status.setText(f"Invalid anchors: {exc}")
            self._transform = None

    def _nudge(self) -> None:
        if self._transform is None:
            return
        self._transform = self._transform.with_nudge(
            dx=float(self._dx.value()),
            dy=float(self._dy.value()),
            extra_scale=max(0.05, self._scale.value() / 100.0),
        )

    def _realign(self) -> None:
        if self._transform is None or len(self._tree_pts) < 1:
            QMessageBox.information(self, "Re-align", "Fit at least one anchor first.")
            return
        self._pending_anchor = {
            "node_id": self._anchor_ids[0] if self._anchor_ids else 0,
            "name": "realign",
            "x": self._tree_pts[0][0],
            "y": self._tree_pts[0][1],
        }
        self._layer = ClickCaptureLayer()
        self._layer.clicked_at.connect(self._on_realign_click)
        self._layer.showFullScreen()
        self._status.setText("Click the same in-game node to update translation only.")

    def _on_realign_click(self, x: float, y: float) -> None:
        if self._layer is not None:
            self._layer.close()
            self._layer = None
        if self._transform is None or not self._tree_pts:
            return
        self._transform = self._transform.realign_translation(self._tree_pts[0], (x, y))
        self._dx.setValue(int(self._transform.dx))
        self._dy.setValue(int(self._transform.dy))
        self._status.setText("Translation realigned. Scale kept.")

    def _save(self) -> None:
        if self.result_calibration() is None:
            QMessageBox.warning(self, "Calibrate", "Need a valid 2- or 3-point fit before saving.")
            return
        self.accept()
