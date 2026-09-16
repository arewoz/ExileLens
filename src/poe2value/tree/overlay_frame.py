"""Live tree overlay presentation. BUILD PATH does not use TreeHeatmapData."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from poe2value.tree.build_path import BuildPathModel, build_path_from_snapshot
from poe2value.tree.heatmap import BAND_FILL_HEX, BAND_LABEL
from poe2value.tree.models import HeatmapBand
from poe2value.tree.overlay_mode import OverlayMode
from poe2value.tree.transform import TreeScreenTransform
from poe2value.tree.view_model import TreeCoachViewModel

PATH_FILL = "#7EF0FF"
NEXT_FILL = "#FFD27A"
BREAKPOINT_FILL = "#7DCF7D"
ANCHOR_A_FILL = "#FF6B4A"
ANCHOR_B_FILL = "#4AE0A0"


@dataclass
class OverlayAppearance:
    opacity: float = 0.95
    marker_size: float = 1.0
    line_width: float = 3.0


@dataclass
class OverlayMarker:
    node_id: int
    screen_x: float
    screen_y: float
    state: str
    value_band: str
    frontier: bool
    best_next: bool
    breakpoint: bool
    pending: bool
    fill_hex: str
    name: str = ""
    kind: str = "path"
    size_class: str = "small"

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "screen_x": self.screen_x,
            "screen_y": self.screen_y,
            "state": self.state,
            "value_band": self.value_band,
            "frontier": self.frontier,
            "best_next": self.best_next,
            "breakpoint": self.breakpoint,
            "pending": self.pending,
            "fill_hex": self.fill_hex,
            "name": self.name,
            "kind": self.kind,
            "size_class": self.size_class,
        }


@dataclass
class OverlayEdge:
    ax: float
    ay: float
    bx: float
    by: float


@dataclass
class LiveTreeOverlayFrame:
    baseline_generation: int
    profile: str
    coverage: dict[str, Any]
    calibration_status: str
    best_next_label: str
    markers: list[OverlayMarker] = field(default_factory=list)
    edges: list[OverlayEdge] = field(default_factory=list)
    status_line: str = ""
    mode: str = OverlayMode.BUILD_PATH.value
    debug: dict[str, Any] = field(default_factory=dict)
    misalignment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_generation": self.baseline_generation,
            "profile": self.profile,
            "coverage": self.coverage,
            "calibration_status": self.calibration_status,
            "best_next_label": self.best_next_label,
            "markers": [m.to_dict() for m in self.markers],
            "edges": [{"ax": e.ax, "ay": e.ay, "bx": e.bx, "by": e.by} for e in self.edges],
            "status_line": self.status_line,
            "mode": self.mode,
            "debug": self.debug,
            "misalignment": self.misalignment,
        }


def _in_rect(x: float, y: float, rect: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = rect
    return x0 <= x <= x1 and y0 <= y <= y1


def _map_point(transform: TreeScreenTransform, x: float, y: float) -> tuple[float, float]:
    return transform.map_tree(float(x), float(y))


def compose_overlay_frame(
    *,
    snapshot,
    transform: TreeScreenTransform | None,
    mode: OverlayMode,
    baseline_generation: int,
    calibration_status: str,
    overlay_rect: tuple[float, float, float, float] | None = None,
    model: TreeCoachViewModel | None = None,
    anchors: tuple[int | None, int | None] = (None, None),
    preview: bool = False,
    debug: dict[str, Any] | None = None,
) -> LiveTreeOverlayFrame:
    """Compose a paint frame. BUILD PATH uses snapshot only — no heatmap / PoB evals."""
    rect = overlay_rect or (0.0, 0.0, 1e12, 1e12)
    path = build_path_from_snapshot(snapshot)
    markers: list[OverlayMarker] = []
    edges: list[OverlayEdge] = []
    mapped = 0
    inside = 0
    outside = 0
    nxt = model.best_next() if model is not None else None
    best_id = None
    if nxt:
        best_id = int(nxt.get("node_id") or 0) or None
    label = ""
    if mode is OverlayMode.BUILD_PATH:
        label = "PoB BUILD PATH"
        if transform is not None:
            for edge in path.edges:
                a = _map_point(transform, edge.ax, edge.ay)
                b = _map_point(transform, edge.bx, edge.by)
                edges.append(OverlayEdge(a[0], a[1], b[0], b[1]))
            for node in path.nodes:
                sx, sy = _map_point(transform, node.x, node.y)
                mapped += 1
                vis = _in_rect(sx, sy, rect)
                if vis:
                    inside += 1
                else:
                    outside += 1
                size = "keystone" if node.keystone else "notable" if node.notable else "small"
                markers.append(
                    OverlayMarker(
                        node_id=node.node_id,
                        screen_x=sx,
                        screen_y=sy,
                        state="PoB BUILD PATH",
                        value_band="",
                        frontier=False,
                        best_next=False,
                        breakpoint=False,
                        pending=False,
                        fill_hex=PATH_FILL,
                        name=node.name,
                        kind="path",
                        size_class=size,
                    )
                )
        if preview:
            label = "CALIBRATION PREVIEW · PoB BUILD PATH"
    elif mode is OverlayMode.CALIBRATION_ANCHORS:
        label = "CALIBRATION ANCHORS"
        if transform is not None:
            for slot, nid, fill in (("A", anchors[0], ANCHOR_A_FILL), ("B", anchors[1], ANCHOR_B_FILL)):
                if nid is None or snapshot is None:
                    continue
                node = snapshot.node(int(nid))
                if node is None or node.x is None or node.y is None:
                    continue
                sx, sy = _map_point(transform, float(node.x), float(node.y))
                mapped += 1
                vis = _in_rect(sx, sy, rect)
                inside += 1 if vis else 0
                outside += 0 if vis else 1
                markers.append(
                    OverlayMarker(
                        node_id=int(nid),
                        screen_x=sx,
                        screen_y=sy,
                        state=f"ANCHOR {slot}",
                        value_band="",
                        frontier=False,
                        best_next=False,
                        breakpoint=False,
                        pending=False,
                        fill_hex=fill,
                        name=node.name,
                        kind=f"anchor_{slot.lower()}",
                        size_class="keystone",
                    )
                )
    elif mode in {OverlayMode.NEXT_POINTS, OverlayMode.VALUE_HEATMAP} and model is not None and transform is not None:
        ranked = model.ranked_rows()
        best_eval = int(ranked[0]["node_id"]) if ranked else None
        for node in model.snapshot.nodes.values() if model.snapshot else []:
            if node.x is None or node.y is None:
                continue
            pres = model.presentation(node.id, best_id=best_eval)
            if pres is None:
                continue
            evaluated = pres.evaluated
            pending = pres.pending
            frontier = pres.frontier
            if mode is OverlayMode.NEXT_POINTS:
                if not frontier:
                    continue
                if not evaluated and not pending:
                    continue
            else:
                if not evaluated:
                    continue
                if pres.band == HeatmapBand.UNKNOWN:
                    continue
            sx, sy = _map_point(transform, float(node.x), float(node.y))
            mapped += 1
            vis = _in_rect(sx, sy, rect)
            if vis:
                inside += 1
            else:
                outside += 1
            if not vis and not pres.best_next:
                continue
            band = pres.band
            state = "PENDING" if pending else BAND_LABEL.get(band, band.value)
            markers.append(
                OverlayMarker(
                    node_id=node.id,
                    screen_x=sx,
                    screen_y=sy,
                    state=state,
                    value_band=band.value,
                    frontier=frontier,
                    best_next=pres.best_next,
                    breakpoint=pres.breakpoint,
                    pending=pending,
                    fill_hex=pres.fill_hex or BAND_FILL_HEX.get(band, "#5a6a88"),
                    name=pres.name,
                    kind="heatmap",
                    size_class=pres.size_class,
                )
            )
        if nxt:
            label = str(nxt.get("label") or "BEST ANALYZED NEXT POINT")
    coverage = {
        "allocated_target": path.allocated_count,
        "mapped": mapped,
        "inside_client": inside,
        "outside_client": outside,
        "edges": len(edges),
    }
    misalignment = ""
    if transform is not None and mode is OverlayMode.BUILD_PATH and path.allocated_count and inside == 0:
        misalignment = f"0 build nodes inside overlay bounds\nLIKELY MISALIGNMENT"
    if calibration_status == "REQUIRED":
        status = "PoB BUILD PATH · ALIGNMENT REQUIRED"
    elif mode is OverlayMode.BUILD_PATH:
        status = (
            f"{label} · {path.allocated_count} nodes · mapped {mapped} · "
            f"visible in PoE client {inside} · outside {outside}"
        )
    else:
        status = f"{mode.value.replace('_', ' ')} · {inside} visible"
    dbg = dict(debug or {})
    dbg.update(
        {
            "markers": len(markers),
            "calibration": calibration_status,
            "mode": mode.value,
            "allocated": path.allocated_count,
            "inside": inside,
            "outside": outside,
        }
    )
    return LiveTreeOverlayFrame(
        baseline_generation=baseline_generation,
        profile=(model.profile if model is not None else ""),
        coverage=coverage,
        calibration_status=calibration_status,
        best_next_label=label,
        markers=markers,
        edges=edges,
        status_line=status,
        mode=mode.value,
        debug=dbg,
        misalignment=misalignment,
    )


def build_overlay_frame(
    model: TreeCoachViewModel,
    transform: TreeScreenTransform | None,
    *,
    baseline_generation: int,
    viewport: tuple[float, float, float, float] | None = None,
    calibration_status: str = "REQUIRED",
    overlay_rect: tuple[float, float, float, float] | None = None,
    mode: OverlayMode = OverlayMode.BUILD_PATH,
) -> LiveTreeOverlayFrame:
    return compose_overlay_frame(
        snapshot=model.snapshot,
        transform=transform,
        mode=mode,
        baseline_generation=baseline_generation,
        calibration_status=calibration_status,
        overlay_rect=overlay_rect or viewport,
        model=model,
    )
