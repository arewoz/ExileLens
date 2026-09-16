"""Two-surface calibration: Tree Coach picks node identity, capture overlay records clicks."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from poe2value.tree.build_path import MIN_ANCHOR_SEPARATION, anchors_too_close, layout_identity, tree_distance
from poe2value.tree.models import NodeType, PassiveTreeSnapshot, TreeNode
from poe2value.tree.transform import (
    TreeOverlayCalibration,
    TreeScreenTransform,
    TransformError,
    current_display_env,
    fit_two_point,
)

CLOSE_WARN = "Choose a node farther away for better calibration."
SAME_NODE = "Anchor A and Anchor B must be different nodes."
NO_COORDS = "That node has no PoB tree coordinates."
GOOD_ERROR_PX = 12.0
RECAL_ERROR_PX = 24.0


class CalibrationUiStatus(str, Enum):
    NOT_CALIBRATED = "NOT_CALIBRATED"
    PREVIEW = "PREVIEW"
    READY = "READY"
    STALE = "STALE"


class CapturePhase(str, Enum):
    IDLE = "IDLE"
    CAPTURE_A = "CAPTURE_A"
    CAPTURE_B = "CAPTURE_B"
    REALIGN = "REALIGN"
    RECALIBRATE_SCALE_A = "RECALIBRATE_SCALE_A"
    RECALIBRATE_SCALE_B = "RECALIBRATE_SCALE_B"
    VERIFY_C = "VERIFY_C"


@dataclass
class CalibrationAnchor:
    node_id: int
    name: str
    tree_xy: tuple[float, float]
    screen_xy: tuple[float, float] | None = None

    @property
    def captured(self) -> bool:
        return self.screen_xy is not None


def _node_anchor(node: TreeNode) -> CalibrationAnchor | None:
    if node.x is None or node.y is None:
        return None
    return CalibrationAnchor(node_id=node.id, name=node.name or f"Node {node.id}", tree_xy=(float(node.x), float(node.y)))


def suggest_anchors(snapshot: PassiveTreeSnapshot | None, *, limit: int = 2) -> list[CalibrationAnchor]:
    if snapshot is None:
        return []
    candidates: list[TreeNode] = []
    for node in snapshot.nodes.values():
        if not node.allocated or node.x is None or node.y is None:
            continue
        if node.type in {NodeType.NOTABLE, NodeType.KEYSTONE}:
            candidates.append(node)
    if len(candidates) < 2:
        candidates = [n for n in snapshot.nodes.values() if n.allocated and n.x is not None and n.y is not None]
    if len(candidates) < 2:
        return []
    ranked = sorted(candidates, key=lambda n: (0 if n.type is NodeType.KEYSTONE else 1 if n.type is NodeType.NOTABLE else 2, n.name))
    first = ranked[0]
    rest = ranked[1:]
    rest.sort(key=lambda n: tree_distance((float(first.x or 0), float(first.y or 0)), (float(n.x or 0), float(n.y or 0))), reverse=True)
    picked = [first, rest[0]]
    out = []
    for node in picked[:limit]:
        anchor = _node_anchor(node)
        if anchor:
            out.append(anchor)
    return out


@dataclass
class CalibrationSession:
    anchor_a: CalibrationAnchor | None = None
    anchor_b: CalibrationAnchor | None = None
    anchor_c: CalibrationAnchor | None = None
    transform: TreeScreenTransform | None = None
    phase: CapturePhase = CapturePhase.IDLE
    layout_id: str = ""
    warning: str = ""
    verify_error_px: float | None = None
    looks_good: bool = False
    client_logical: tuple[int, int, int, int] = (0, 0, 0, 0)
    display_id: str = ""
    dpi: float = 1.0
    geometry: tuple[int, int, int, int] = (0, 0, 0, 0)
    saved: dict[str, Any] = field(default_factory=dict)

    def ui_status(self) -> CalibrationUiStatus:
        if self.transform is None:
            return CalibrationUiStatus.NOT_CALIBRATED
        if self.saved.get("stale_reason"):
            return CalibrationUiStatus.STALE
        if self.looks_good:
            return CalibrationUiStatus.READY
        return CalibrationUiStatus.PREVIEW

    def assign_from_node(self, node: TreeNode | None, *, slot: str) -> str | None:
        if node is None:
            return "Select a node in Tree Coach first."
        anchor = _node_anchor(node)
        if anchor is None:
            return NO_COORDS
        other = self.anchor_b if slot == "A" else self.anchor_a
        if other is not None and other.node_id == anchor.node_id:
            return SAME_NODE
        if other is not None and anchors_too_close(anchor.tree_xy, other.tree_xy):
            self.warning = CLOSE_WARN
            return CLOSE_WARN
        self.warning = ""
        if slot == "A":
            self.anchor_a = anchor
        else:
            self.anchor_b = anchor
        self.looks_good = False
        return None

    def apply_suggestions(self, snapshot: PassiveTreeSnapshot | None) -> str | None:
        picked = suggest_anchors(snapshot)
        if len(picked) < 2:
            return "Need two allocated nodes with coordinates to suggest anchors."
        self.anchor_a = picked[0]
        self.anchor_b = picked[1]
        if anchors_too_close(self.anchor_a.tree_xy, self.anchor_b.tree_xy):
            self.warning = CLOSE_WARN
        else:
            self.warning = ""
        self.looks_good = False
        return None

    def begin_capture(self, phase: CapturePhase) -> str | None:
        if phase is CapturePhase.CAPTURE_A and self.anchor_a is None:
            return "Assign Anchor A in Tree Coach first."
        if phase is CapturePhase.CAPTURE_B and self.anchor_b is None:
            return "Assign Anchor B in Tree Coach first."
        if phase is CapturePhase.REALIGN and (self.transform is None or self.anchor_a is None):
            return "Calibrate A and B before Quick Re-align."
        if phase in {CapturePhase.RECALIBRATE_SCALE_A, CapturePhase.RECALIBRATE_SCALE_B} and (
            self.anchor_a is None or self.anchor_b is None
        ):
            return "Need both PoB anchors to recalibrate scale."
        if phase is CapturePhase.VERIFY_C and (self.transform is None or self.anchor_c is None):
            return "Select a third node in Tree Coach first."
        self.phase = phase
        return None

    def cancel_capture(self) -> None:
        self.phase = CapturePhase.IDLE

    def record_client_click(self, x: float, y: float) -> str | None:
        pt = (float(x), float(y))
        if self.phase is CapturePhase.CAPTURE_A and self.anchor_a:
            self.anchor_a.screen_xy = pt
            self.phase = CapturePhase.IDLE
            self._try_fit()
            return None
        if self.phase is CapturePhase.CAPTURE_B and self.anchor_b:
            self.anchor_b.screen_xy = pt
            self.phase = CapturePhase.IDLE
            self._try_fit()
            return None
        if self.phase is CapturePhase.REALIGN and self.transform is not None and self.anchor_a:
            self.transform = self.transform.realign_translation(self.anchor_a.tree_xy, pt)
            self.anchor_a.screen_xy = pt
            self.phase = CapturePhase.IDLE
            return None
        if self.phase is CapturePhase.RECALIBRATE_SCALE_A and self.anchor_a:
            self.anchor_a.screen_xy = pt
            self.phase = CapturePhase.RECALIBRATE_SCALE_B
            return None
        if self.phase is CapturePhase.RECALIBRATE_SCALE_B and self.anchor_b:
            self.anchor_b.screen_xy = pt
            self.phase = CapturePhase.IDLE
            return self._try_fit()
        if self.phase is CapturePhase.VERIFY_C and self.anchor_c and self.transform is not None:
            self.anchor_c.screen_xy = pt
            mapped = self.transform.map_tree(*self.anchor_c.tree_xy)
            self.verify_error_px = tree_distance(mapped, pt)
            self.phase = CapturePhase.IDLE
            return None
        return "Not capturing."

    def assign_verify_node(self, node: TreeNode | None) -> str | None:
        if node is None:
            return "Select a node in Tree Coach first."
        anchor = _node_anchor(node)
        if anchor is None:
            return NO_COORDS
        self.anchor_c = anchor
        return None

    def _try_fit(self) -> str | None:
        if (
            self.anchor_a is None
            or self.anchor_b is None
            or self.anchor_a.screen_xy is None
            or self.anchor_b.screen_xy is None
        ):
            return None
        try:
            self.transform = fit_two_point(
                [self.anchor_a.tree_xy, self.anchor_b.tree_xy],
                [self.anchor_a.screen_xy, self.anchor_b.screen_xy],
            )
        except TransformError as exc:
            self.transform = None
            return str(exc)
        self.looks_good = False
        return None

    def nudge(self, *, ddx: float = 0.0, ddy: float = 0.0, dscale: float = 0.0) -> None:
        if self.transform is None:
            return
        self.transform = self.transform.nudge(ddx=ddx, ddy=ddy, dscale=dscale)

    def reset(self) -> None:
        self.anchor_a = None
        self.anchor_b = None
        self.anchor_c = None
        self.transform = None
        self.phase = CapturePhase.IDLE
        self.warning = ""
        self.verify_error_px = None
        self.looks_good = False
        self.saved = {}

    def mark_layout(self, snapshot: PassiveTreeSnapshot | None) -> None:
        new_id = layout_identity(snapshot)
        if self.layout_id and new_id and self.layout_id != new_id and self.transform is not None:
            self.saved["stale_reason"] = "tree layout identity changed"
            self.saved["valid"] = False
        if new_id:
            self.layout_id = new_id

    def verify_label(self) -> str:
        if self.verify_error_px is None:
            return ""
        err = self.verify_error_px
        quality = "GOOD" if err <= GOOD_ERROR_PX else "RECALIBRATION RECOMMENDED" if err >= RECAL_ERROR_PX else "OK"
        return f"Calibration error: {err:.0f} px\n{quality}"

    def capture_prompt(self) -> str:
        if self.phase is CapturePhase.CAPTURE_A and self.anchor_a:
            return (
                f"ANCHOR A — {self.anchor_a.name.upper()}\n\n"
                f"Find {self.anchor_a.name} on the PoE passive tree\n"
                "and click the CENTER of the node."
            )
        if self.phase is CapturePhase.CAPTURE_B and self.anchor_b:
            return (
                f"ANCHOR B — {self.anchor_b.name.upper()}\n\n"
                f"Find {self.anchor_b.name} on the PoE passive tree\n"
                "and click the CENTER of the node."
            )
        if self.phase is CapturePhase.REALIGN and self.anchor_a:
            return (
                f"QUICK REALIGN — {self.anchor_a.name.upper()}\n\n"
                f"Click the CENTER of {self.anchor_a.name} at its new location."
            )
        if self.phase is CapturePhase.RECALIBRATE_SCALE_A and self.anchor_a:
            return f"RECALIBRATE SCALE — click {self.anchor_a.name}"
        if self.phase is CapturePhase.RECALIBRATE_SCALE_B and self.anchor_b:
            return f"RECALIBRATE SCALE — click {self.anchor_b.name}"
        if self.phase is CapturePhase.VERIFY_C and self.anchor_c:
            return f"VERIFY — click {self.anchor_c.name}"
        return ""

    def to_calibration_payload(self) -> dict[str, Any] | None:
        if self.transform is None or self.anchor_a is None or self.anchor_b is None:
            return None
        if self.anchor_a.screen_xy is None or self.anchor_b.screen_xy is None:
            return None
        env = current_display_env()
        cal = TreeOverlayCalibration(
            display_id=self.display_id or str(env["display_id"]),
            geometry=self.geometry or tuple(env["geometry"]),
            dpi=self.dpi or float(env["dpi"]),
            transform=self.transform,
            anchor_node_ids=[self.anchor_a.node_id, self.anchor_b.node_id],
            anchor_tree=[self.anchor_a.tree_xy, self.anchor_b.tree_xy],
            anchor_screen=[self.anchor_a.screen_xy, self.anchor_b.screen_xy],
            created_at=time.time(),
            valid=True,
            version=2,
        )
        payload = cal.to_dict()
        payload["coordinate_space"] = "poe_client_logical"
        payload["layout_identity"] = self.layout_id
        payload["stale_reason"] = ""
        self.saved = payload
        return payload

    def load_saved(self, data: dict[str, Any] | None, snapshot: PassiveTreeSnapshot | None = None) -> None:
        if not data:
            return
        try:
            cal = TreeOverlayCalibration.from_dict(data)
        except Exception:
            return
        self.saved = dict(data)
        self.transform = cal.transform
        self.display_id = cal.display_id
        self.geometry = tuple(cal.geometry)
        self.dpi = cal.dpi
        self.layout_id = str(data.get("layout_identity") or "")
        self.looks_good = bool(cal.valid) and not cal.stale_reason
        ids = list(cal.anchor_node_ids)
        trees = list(cal.anchor_tree)
        screens = list(cal.anchor_screen)
        names = ["Anchor A", "Anchor B"]
        if snapshot is not None and ids:
            na = snapshot.node(ids[0]) if len(ids) > 0 else None
            nb = snapshot.node(ids[1]) if len(ids) > 1 else None
            if na:
                names[0] = na.name or names[0]
            if nb:
                names[1] = nb.name or names[1]
        if len(ids) >= 1 and len(trees) >= 1:
            self.anchor_a = CalibrationAnchor(
                ids[0], names[0], (float(trees[0][0]), float(trees[0][1])), screens[0] if screens else None
            )
        if len(ids) >= 2 and len(trees) >= 2:
            self.anchor_b = CalibrationAnchor(
                ids[1], names[1], (float(trees[1][0]), float(trees[1][1])), screens[1] if len(screens) > 1 else None
            )
        self.mark_layout(snapshot)
