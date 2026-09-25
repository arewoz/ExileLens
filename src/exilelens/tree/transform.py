"""PoB tree coordinates → Qt logical screen coordinates.

Coordinate space is Qt logical pixels (QCursor.pos / QWidget geometry), not
Win32 physical pixels. Persist the screen's devicePixelRatio with calibration
so a DPI change can mark the transform stale.

Supported models:
- two-point: translation + uniform scale + rotation
- three-point: affine (scale X/Y, rotation, shear, translation)

Fine nudge (dx, dy, extra scale) is applied after the fitted transform.
One-anchor realign updates translation only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

Point = tuple[float, float]


class TransformError(ValueError):
    pass


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _collinear(a: Point, b: Point, c: Point, eps: float = 1e-6) -> bool:
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) <= eps


@dataclass(frozen=True)
class TreeScreenTransform:
    a: float
    b: float
    c: float
    d: float
    tx: float
    ty: float
    dx: float = 0.0
    dy: float = 0.0
    extra_scale: float = 1.0
    coordinate_space: str = "qt_logical"

    def with_nudge(self, *, dx: float | None = None, dy: float | None = None, extra_scale: float | None = None) -> TreeScreenTransform:
        return TreeScreenTransform(
            a=self.a,
            b=self.b,
            c=self.c,
            d=self.d,
            tx=self.tx,
            ty=self.ty,
            dx=self.dx if dx is None else float(dx),
            dy=self.dy if dy is None else float(dy),
            extra_scale=self.extra_scale if extra_scale is None else float(extra_scale),
            coordinate_space=self.coordinate_space,
        )

    def nudge(self, *, ddx: float = 0.0, ddy: float = 0.0, dscale: float = 0.0) -> TreeScreenTransform:
        scale = max(0.05, self.extra_scale + dscale)
        return self.with_nudge(dx=self.dx + ddx, dy=self.dy + ddy, extra_scale=scale)

    def map_tree(self, x: float, y: float) -> Point:
        sx = self.a * x + self.b * y + self.tx
        sy = self.c * x + self.d * y + self.ty
        return (sx * self.extra_scale + self.dx, sy * self.extra_scale + self.dy)

    def map_screen(self, x: float, y: float) -> Point:
        """Inverse mapping. Raises if the matrix is singular."""
        px = (x - self.dx) / self.extra_scale
        py = (y - self.dy) / self.extra_scale
        det = self.a * self.d - self.b * self.c
        if abs(det) < 1e-12:
            raise TransformError("transform is not invertible")
        rx = px - self.tx
        ry = py - self.ty
        return ((self.d * rx - self.b * ry) / det, (-self.c * rx + self.a * ry) / det)

    def realign_translation(self, tree_xy: Point, screen_xy: Point) -> TreeScreenTransform:
        mapped = TreeScreenTransform(
            self.a, self.b, self.c, self.d, self.tx, self.ty, 0.0, 0.0, self.extra_scale, self.coordinate_space
        ).map_tree(*tree_xy)
        return self.with_nudge(dx=screen_xy[0] - mapped[0], dy=screen_xy[1] - mapped[1])

    def to_dict(self) -> dict[str, Any]:
        return {
            "a": self.a,
            "b": self.b,
            "c": self.c,
            "d": self.d,
            "tx": self.tx,
            "ty": self.ty,
            "dx": self.dx,
            "dy": self.dy,
            "extra_scale": self.extra_scale,
            "coordinate_space": self.coordinate_space,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TreeScreenTransform:
        return cls(
            a=float(data["a"]),
            b=float(data["b"]),
            c=float(data["c"]),
            d=float(data["d"]),
            tx=float(data["tx"]),
            ty=float(data["ty"]),
            dx=float(data.get("dx") or 0.0),
            dy=float(data.get("dy") or 0.0),
            extra_scale=float(data.get("extra_scale") or 1.0),
            coordinate_space=str(data.get("coordinate_space") or "qt_logical"),
        )


def fit_two_point(tree: Sequence[Point], screen: Sequence[Point]) -> TreeScreenTransform:
    if len(tree) < 2 or len(screen) < 2:
        raise TransformError("two distinct anchors are required")
    t0, t1 = tree[0], tree[1]
    s0, s1 = screen[0], screen[1]
    dt = _dist(t0, t1)
    ds = _dist(s0, s1)
    if dt < 1e-6 or ds < 1e-6:
        raise TransformError("degenerate anchors: points are coincident")
    scale = ds / dt
    ang_t = math.atan2(t1[1] - t0[1], t1[0] - t0[0])
    ang_s = math.atan2(s1[1] - s0[1], s1[0] - s0[0])
    ang = ang_s - ang_t
    cos_a = math.cos(ang) * scale
    sin_a = math.sin(ang) * scale
    # [cos -sin; sin cos] * tree + T = screen
    a, b, c, d = cos_a, -sin_a, sin_a, cos_a
    tx = s0[0] - (a * t0[0] + b * t0[1])
    ty = s0[1] - (c * t0[0] + d * t0[1])
    return TreeScreenTransform(a, b, c, d, tx, ty)


def fit_three_point(tree: Sequence[Point], screen: Sequence[Point]) -> TreeScreenTransform:
    if len(tree) < 3 or len(screen) < 3:
        raise TransformError("three anchors are required for affine fit")
    t0, t1, t2 = tree[0], tree[1], tree[2]
    s0, s1, s2 = screen[0], screen[1], screen[2]
    if _collinear(t0, t1, t2) or _collinear(s0, s1, s2):
        raise TransformError("degenerate anchors: points are collinear")
    # Solve affine: [x y 1] [a c tx; b d ty]^T wait:
    # x' = a x + b y + tx
    # y' = c x + d y + ty
    matrix = [
        [t0[0], t0[1], 1.0],
        [t1[0], t1[1], 1.0],
        [t2[0], t2[1], 1.0],
    ]
    inv = _invert3(matrix)
    a, b, tx = _mul3(inv, [s0[0], s1[0], s2[0]])
    c, d, ty = _mul3(inv, [s0[1], s1[1], s2[1]])
    return TreeScreenTransform(a, b, c, d, tx, ty)


def fit_anchors(tree: Sequence[Point], screen: Sequence[Point]) -> TreeScreenTransform:
    if len(tree) >= 3 and len(screen) >= 3:
        return fit_three_point(tree[:3], screen[:3])
    return fit_two_point(tree[:2], screen[:2])


def _invert3(m: list[list[float]]) -> list[list[float]]:
    a, b, c = m[0]
    d, e, f = m[1]
    g, h, i = m[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-12:
        raise TransformError("degenerate anchors: singular matrix")
    inv_det = 1.0 / det
    return [
        [(e * i - f * h) * inv_det, (c * h - b * i) * inv_det, (b * f - c * e) * inv_det],
        [(f * g - d * i) * inv_det, (a * i - c * g) * inv_det, (c * d - a * f) * inv_det],
        [(d * h - e * g) * inv_det, (b * g - a * h) * inv_det, (a * e - b * d) * inv_det],
    ]


def _mul3(m: list[list[float]], v: list[float]) -> tuple[float, float, float]:
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


@dataclass
class TreeOverlayCalibration:
    display_id: str
    geometry: tuple[int, int, int, int]
    dpi: float
    transform: TreeScreenTransform
    anchor_node_ids: list[int] = field(default_factory=list)
    anchor_tree: list[Point] = field(default_factory=list)
    anchor_screen: list[Point] = field(default_factory=list)
    created_at: float = 0.0
    version: int = 1
    valid: bool = True
    stale_reason: str = ""

    def environment_key(self) -> str:
        g = self.geometry
        return f"{self.display_id}|{g[0]},{g[1]},{g[2]},{g[3]}|{self.dpi:.3f}"

    def matches_environment(self, display_id: str, geometry: tuple[int, int, int, int], dpi: float) -> bool:
        if self.display_id != display_id:
            return False
        if tuple(self.geometry) != tuple(geometry):
            return False
        return abs(float(self.dpi) - float(dpi)) < 0.02

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_id": self.display_id,
            "geometry": list(self.geometry),
            "dpi": self.dpi,
            "transform": self.transform.to_dict(),
            "anchor_node_ids": list(self.anchor_node_ids),
            "anchor_tree": [list(p) for p in self.anchor_tree],
            "anchor_screen": [list(p) for p in self.anchor_screen],
            "created_at": self.created_at,
            "version": self.version,
            "valid": self.valid,
            "stale_reason": self.stale_reason,
            "coordinate_space": "qt_logical",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TreeOverlayCalibration:
        geom = data.get("geometry") or [0, 0, 0, 0]
        return cls(
            display_id=str(data.get("display_id") or ""),
            geometry=(int(geom[0]), int(geom[1]), int(geom[2]), int(geom[3])),
            dpi=float(data.get("dpi") or 1.0),
            transform=TreeScreenTransform.from_dict(data.get("transform") or {}),
            anchor_node_ids=[int(n) for n in (data.get("anchor_node_ids") or [])],
            anchor_tree=[(float(p[0]), float(p[1])) for p in (data.get("anchor_tree") or [])],
            anchor_screen=[(float(p[0]), float(p[1])) for p in (data.get("anchor_screen") or [])],
            created_at=float(data.get("created_at") or 0.0),
            version=int(data.get("version") or 1),
            valid=bool(data.get("valid", True)),
            stale_reason=str(data.get("stale_reason") or ""),
        )


def current_display_env(screen: Any | None = None) -> dict[str, Any]:
    if screen is None:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
    if screen is None:
        return {"display_id": "unknown", "geometry": (0, 0, 0, 0), "dpi": 1.0}
    geo = screen.geometry()
    handle = getattr(screen, "handle", None)
    ratio = float(screen.devicePixelRatio()) if hasattr(screen, "devicePixelRatio") else 1.0
    name = str(screen.name() if hasattr(screen, "name") else "primary")
    return {
        "display_id": name,
        "geometry": (int(geo.x()), int(geo.y()), int(geo.width()), int(geo.height())),
        "dpi": ratio,
    }


def nodes_in_rect(
    nodes: Iterable[Any],
    transform: TreeScreenTransform,
    rect: tuple[float, float, float, float],
) -> list[int]:
    x0, y0, x1, y1 = rect
    hits = []
    for node in nodes:
        nid = getattr(node, "id", None)
        x = getattr(node, "x", None)
        y = getattr(node, "y", None)
        if nid is None or x is None or y is None:
            continue
        sx, sy = transform.map_tree(float(x), float(y))
        if x0 <= sx <= x1 and y0 <= sy <= y1:
            hits.append(int(nid))
    return hits
