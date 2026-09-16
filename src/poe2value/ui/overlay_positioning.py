"""Overlay placement near copy-time cursor with monitor work-area clamping."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QPoint

from poe2value.platform.windows.cursor import get_cursor_pos_physical, monitor_work_area_at_physical
from poe2value.platform.windows.poe_window import physical_to_logical, poe_client_geometry
from poe2value.ui.overlay_geometry import max_overlay_height_logical

logger = logging.getLogger(__name__)

ANCHOR_SOURCE_COPY_TIME = "COPY_TIME"
ANCHOR_SOURCE_FALLBACK_CURRENT_CURSOR = "FALLBACK_CURRENT_CURSOR"
ANCHOR_SOURCE_FALLBACK_POE_MONITOR = "FALLBACK_POE_MONITOR"
ANCHOR_SOURCE_FALLBACK_LAST_VALID = "FALLBACK_LAST_VALID"

PLACEMENT_MARGIN_LOGICAL = 16


@dataclass(frozen=True)
class OverlayPlacement:
    logical_pos: QPoint
    anchor_source: str
    anchor_physical: tuple[int, int]
    monitor_work_area_physical: tuple[int, int, int, int]
    overlay_rect_logical: tuple[int, int, int, int]
    fallback_reason: str | None = None
    # Optional placement detail. The committed single-window planner fills in the
    # rect and strategy; the companion/group fields stay None unless a richer
    # planner supplies them.
    overlay_rect_physical: tuple[int, int, int, int] | None = None
    placement_strategy: str | None = None
    aux_logical_pos: QPoint | None = None
    aux_overlay_rect_logical: tuple[int, int, int, int] | None = None
    aux_overlay_rect_physical: tuple[int, int, int, int] | None = None
    group_rect_physical: tuple[int, int, int, int] | None = None
    group_layout_mode: str | None = None


@dataclass(frozen=True)
class OverlayExpansionPlan:
    """Captured once at first show. Expand/collapse uses this, never a fresh cursor place."""

    origin_logical: tuple[int, int]
    compact_size_logical: tuple[int, int]
    details_width_logical: int
    divider_width_logical: int
    expanded_width_logical: int
    max_height_logical: int
    work_rect_physical: tuple[int, int, int, int]
    anchor_physical: tuple[int, int]
    placement_strategy: str
    grow_horizontal: str = "right"


def _resolve_anchor_physical(
    copy_anchor_physical: tuple[int, int] | None,
    *,
    last_valid_anchor_physical: tuple[int, int] | None,
) -> tuple[tuple[int, int], str, str | None]:
    if copy_anchor_physical is not None and _valid_anchor(copy_anchor_physical):
        return copy_anchor_physical, ANCHOR_SOURCE_COPY_TIME, None

    reason_parts: list[str] = []
    if copy_anchor_physical is None:
        reason_parts.append("missing copy anchor")
    elif not _valid_anchor(copy_anchor_physical):
        reason_parts.append(f"invalid copy anchor {copy_anchor_physical}")

    current = get_cursor_pos_physical()
    if current is not None and _valid_anchor(current):
        reason = "; ".join(reason_parts) + "; using current cursor"
        logger.info("overlay anchor fallback: %s", reason)
        return current, ANCHOR_SOURCE_FALLBACK_CURRENT_CURSOR, reason

    poe = poe_client_geometry()
    if poe is not None:
        cx = (poe.client_rect_screen[0] + poe.client_rect_screen[2]) // 2
        cy = (poe.client_rect_screen[1] + poe.client_rect_screen[3]) // 2
        if _valid_anchor((cx, cy)):
            reason = "; ".join(reason_parts) + "; using PoE client center"
            logger.info("overlay anchor fallback: %s", reason)
            return (cx, cy), ANCHOR_SOURCE_FALLBACK_POE_MONITOR, reason

    if last_valid_anchor_physical is not None and _valid_anchor(last_valid_anchor_physical):
        reason = "; ".join(reason_parts) + "; using last valid copy anchor"
        logger.info("overlay anchor fallback: %s", reason)
        return last_valid_anchor_physical, ANCHOR_SOURCE_FALLBACK_LAST_VALID, reason

    # Last resort: primary screen center in physical pixels — never (0,0).
    try:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.geometry()
            dpr = float(screen.devicePixelRatio() or 1.0)
            cx = int((geo.x() + geo.width() / 2) * dpr)
            cy = int((geo.y() + geo.height() / 2) * dpr)
            if _valid_anchor((cx, cy)):
                reason = "; ".join(reason_parts) + "; using primary screen center"
                logger.warning("overlay anchor fallback: %s", reason)
                return (cx, cy), ANCHOR_SOURCE_FALLBACK_POE_MONITOR, reason
    except Exception:
        pass

    # Absolute last resort — offset from origin, not origin itself.
    reason = "; ".join(reason_parts) + "; using safe default offset"
    logger.warning("overlay anchor fallback: %s", reason)
    return (64, 64), ANCHOR_SOURCE_FALLBACK_POE_MONITOR, reason


def _valid_anchor(point: tuple[int, int]) -> bool:
    return not (point[0] == 0 and point[1] == 0)


def _work_area_logical(work: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    work_lx0, work_ly0 = physical_to_logical(float(work[0]), float(work[1]))
    work_lx1, work_ly1 = physical_to_logical(float(work[2]), float(work[3]))
    return int(round(work_lx0)), int(round(work_ly0)), int(round(work_lx1)), int(round(work_ly1))


def compute_overlay_placement(
    overlay_width: int,
    overlay_height: int,
    *,
    copy_anchor_physical: tuple[int, int] | None,
    offset_px: int = 20,
    last_valid_anchor_physical: tuple[int, int] | None = None,
    work_rect_physical: tuple[int, int, int, int] | None = None,
    device_pixel_ratio: float | None = None,
    aux_size_logical: tuple[int, int] | None = None,
    reserve_width_logical: int | None = None,
) -> OverlayPlacement:
    """Place the overlay near the copy-time anchor, clamped to that monitor's work area.

    `reserve_width_logical` is the width the window may grow to when More Info opens
    to the right. The compact pane is positioned so the full expanded width fits inside
    the work area without re-anchoring on toggle.
    """
    anchor_px, anchor_source, fallback_reason = _resolve_anchor_physical(
        copy_anchor_physical,
        last_valid_anchor_physical=last_valid_anchor_physical,
    )
    if work_rect_physical is not None:
        work = work_rect_physical
    else:
        monitor = monitor_work_area_at_physical(anchor_px[0], anchor_px[1])
        work = (0, 0, 1920, 1080) if monitor is None else monitor.work_rect

    work_lx0, work_ly0, work_lx1, work_ly1 = _work_area_logical(work)
    margin = PLACEMENT_MARGIN_LOGICAL
    offset = max(16, min(24, int(offset_px)))
    reserve_w = max(int(overlay_width), int(reserve_width_logical or overlay_width))

    anchor_lx, anchor_ly = physical_to_logical(float(anchor_px[0]), float(anchor_px[1]))
    anchor_lx = int(round(anchor_lx))
    anchor_ly = int(round(anchor_ly))

    # Preferred: below-right of anchor in logical space.
    x = anchor_lx + offset
    y = anchor_ly + offset
    horizontal = "right"
    vertical = "below"

    if x + reserve_w > work_lx1 - margin:
        x = anchor_lx - reserve_w - offset
        horizontal = "left"
    if y + overlay_height > work_ly1 - margin:
        y = anchor_ly - overlay_height - offset
        vertical = "above"

    clamped_x = max(work_lx0 + margin, min(x, work_lx1 - reserve_w - margin))
    clamped_y = max(work_ly0 + margin, min(y, work_ly1 - overlay_height - margin))
    strategy = "clamp" if (clamped_x, clamped_y) != (x, y) else f"{vertical}-{horizontal}"
    x, y = clamped_x, clamped_y

    logical_br_x = x + overlay_width
    logical_br_y = y + overlay_height

    return OverlayPlacement(
        logical_pos=QPoint(int(x), int(y)),
        anchor_source=anchor_source,
        anchor_physical=anchor_px,
        monitor_work_area_physical=work,
        overlay_rect_logical=(int(x), int(y), int(logical_br_x - x), int(logical_br_y - y)),
        fallback_reason=fallback_reason,
        overlay_rect_physical=(int(x), int(y), int(logical_br_x), int(logical_br_y)),
        placement_strategy=strategy,
    )


def plan_overlay_expansion(
    placement: OverlayPlacement,
    *,
    compact_width_logical: int,
    compact_height_logical: int,
    details_width_logical: int,
    divider_width_logical: int = 1,
) -> OverlayExpansionPlan:
    """Lock origin + horizontal growth from the compact placement. Never re-query the cursor."""
    origin = (int(placement.logical_pos.x()), int(placement.logical_pos.y()))
    work = placement.monitor_work_area_physical
    work_lx0, work_ly0, work_lx1, work_ly1 = _work_area_logical(work)
    margin = PLACEMENT_MARGIN_LOGICAL

    expanded_natural = compact_width_logical + divider_width_logical + details_width_logical
    max_expanded = max(compact_width_logical, work_lx1 - work_lx0 - 2 * margin)
    expanded_width = min(expanded_natural, max_expanded)
    details_width = expanded_width - compact_width_logical - divider_width_logical
    details_width = max(120, min(details_width_logical, details_width))
    expanded_width = min(
        compact_width_logical + divider_width_logical + details_width,
        max_expanded,
    )

    # Pre-shift left so right-side expansion stays inside the work area.
    overflow = origin[0] + expanded_width - (work_lx1 - margin)
    if overflow > 0:
        origin = (max(work_lx0 + margin, origin[0] - overflow), origin[1])

    max_height = max_overlay_height_logical(
        placement.anchor_physical,
        work_rect_physical=work,
    )

    return OverlayExpansionPlan(
        origin_logical=origin,
        compact_size_logical=(compact_width_logical, compact_height_logical),
        details_width_logical=details_width,
        divider_width_logical=divider_width_logical,
        expanded_width_logical=expanded_width,
        max_height_logical=max(compact_height_logical, max_height),
        work_rect_physical=work,
        anchor_physical=placement.anchor_physical,
        placement_strategy=str(placement.placement_strategy or "right"),
        grow_horizontal="right",
    )


def apply_expansion_plan(
    plan: OverlayExpansionPlan,
    *,
    content_height_logical: int,
    expanded: bool,
) -> tuple[int, int, int, int]:
    """Return (x, y, width, height) for compact or expanded state.

    The window origin stays fixed; More Info grows to the right. Height is capped;
    extra content scrolls inside the drawer.
    """
    x, compact_y = plan.origin_logical
    compact_w, compact_h = plan.compact_size_logical
    height = min(max(int(content_height_logical), 1), plan.max_height_logical)
    _work_lx0, _work_ly0, _work_lx1, work_ly1 = _work_area_logical(plan.work_rect_physical)
    remaining = work_ly1 - PLACEMENT_MARGIN_LOGICAL - compact_y
    height = min(height, max(1, remaining))
    if not expanded:
        return x, compact_y, compact_w, height
    width = plan.expanded_width_logical
    return x, compact_y, width, height
