"""Generic overlay geometry primitives.

Minimal shared foundation extracted for MARKET-01B9A. The passive overlay — including
the Price Check surface — must cap its height to the monitor the anchor sits on, in
logical pixels. That is generic window geometry with no product behaviour, so it lives
here rather than inside any one feature's layout module.

Kept behaviourally identical to the in-progress tooltip layout work so that both trees
compute the same cap.
"""

from __future__ import annotations

from exilelens.platform.windows.cursor import monitor_work_area_at_physical
from exilelens.platform.windows.poe_window import physical_to_logical

DEFAULT_WORK_AREA_FRACTION = 0.90
MIN_OVERLAY_HEIGHT_LOGICAL = 120
_FALLBACK_WORK_RECT = (0, 0, 1920, 1080)


def device_pixel_ratio_at_physical(anchor_physical: tuple[int, int]) -> float:
    """Device pixel ratio of the screen containing a physical point (1.0 if unknown)."""
    lx, ly = physical_to_logical(float(anchor_physical[0]), float(anchor_physical[1]))
    try:
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication
    except Exception:  # pragma: no cover - Qt always present in the app
        return 1.0
    screen = QGuiApplication.screenAt(QPoint(int(round(lx)), int(round(ly)))) or QGuiApplication.primaryScreen()
    if screen is None:
        return 1.0
    dpr = float(screen.devicePixelRatio() or 1.0)
    return dpr if dpr > 0 else 1.0


def max_overlay_height_logical(
    anchor_physical: tuple[int, int],
    *,
    work_rect_physical: tuple[int, int, int, int] | None = None,
    fraction: float = DEFAULT_WORK_AREA_FRACTION,
    device_pixel_ratio: float | None = None,
) -> int:
    """Tallest the overlay may grow, in logical pixels, on the anchor's monitor."""
    if work_rect_physical is None:
        monitor = monitor_work_area_at_physical(anchor_physical[0], anchor_physical[1])
        work_rect_physical = monitor.work_rect if monitor is not None else _FALLBACK_WORK_RECT
    work_height_physical = work_rect_physical[3] - work_rect_physical[1]
    dpr = float(
        device_pixel_ratio
        if device_pixel_ratio is not None
        else device_pixel_ratio_at_physical(anchor_physical)
    )
    if dpr <= 0:
        dpr = 1.0
    cap = int((work_height_physical * fraction) / dpr)
    return max(MIN_OVERLAY_HEIGHT_LOGICAL, cap)
