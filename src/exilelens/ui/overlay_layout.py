"""Tooltip layout coordinator — physical work-area placement (Phase D)."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint

from exilelens.platform.windows.cursor import monitor_work_area_at_physical
from exilelens.platform.windows.poe_window import physical_to_logical
from exilelens.ui.overlay_positioning import OverlayPlacement, _resolve_anchor_physical

DEFAULT_WORK_AREA_FRACTION = 0.90
_GROUP_GAP_LOGICAL = 8
_PLACEMENT_OFFSET_MIN = 16
_PLACEMENT_OFFSET_MAX = 24


@dataclass(frozen=True)
class PlacementCandidate:
    name: str
    x: int
    y: int


def _rect_fits(x: int, y: int, width: int, height: int, work_rect: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = work_rect
    return left <= x and top <= y and (x + width) <= right and (y + height) <= bottom


def _clamp_rect(
    x: int,
    y: int,
    width: int,
    height: int,
    work_rect: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    left, top, right, bottom = work_rect
    max_x = max(left, right - width)
    max_y = max(top, bottom - height)
    clamped_x = max(left, min(x, max_x))
    clamped_y = max(top, min(y, max_y))
    return (clamped_x, clamped_y, clamped_x + width, clamped_y + height)


@dataclass(frozen=True)
class GroupArrangement:
    name: str
    group_width: int
    group_height: int
    main_x: int
    main_y: int
    aux_x: int
    aux_y: int


def _group_arrangements(
    main_size_physical: tuple[int, int],
    aux_size_physical: tuple[int, int],
    gap_physical: int,
) -> list[GroupArrangement]:
    mw, mh = main_size_physical
    aw, ah = aux_size_physical
    gap = max(4, gap_physical)
    horiz_w, horiz_h = mw + gap + aw, max(mh, ah)
    vert_w, vert_h = max(mw, aw), mh + gap + ah
    return [
        GroupArrangement("main-right", horiz_w, horiz_h, 0, 0, mw + gap, 0),
        GroupArrangement("aux-right", horiz_w, horiz_h, aw + gap, 0, 0, 0),
        GroupArrangement("main-top", vert_w, vert_h, 0, 0, 0, mh + gap),
        GroupArrangement("aux-top", vert_w, vert_h, 0, ah + gap, 0, 0),
    ]


def _physical_rect(l: int, t: int, w: int, h: int) -> tuple[int, int, int, int]:
    return (l, t, l + w, t + h)


def place_group_in_work_area(
    *,
    anchor_physical: tuple[int, int],
    main_size_physical: tuple[int, int],
    aux_size_physical: tuple[int, int],
    work_rect_physical: tuple[int, int, int, int],
    offset_px: int = 20,
    gap_physical: int | None = None,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int], tuple[int, int, int, int], str, str]:
    """Return main_rect, aux_rect, group_rect (physical ltrb), strategy, layout_mode."""
    gap = gap_physical if gap_physical is not None else max(4, _GROUP_GAP_LOGICAL)
    arrangements = _group_arrangements(main_size_physical, aux_size_physical, gap)
    work_w = work_rect_physical[2] - work_rect_physical[0]
    horiz_w = main_size_physical[0] + gap + aux_size_physical[0]
    if horiz_w > work_w:
        arrangements = [item for item in arrangements if item.name in {"main-top", "aux-top"}] or arrangements
    anchor_mid_x = (work_rect_physical[0] + work_rect_physical[2]) // 2
    if anchor_physical[0] > anchor_mid_x:
        preferred = ("aux-right", "main-right", "main-top", "aux-top")
    else:
        preferred = ("main-right", "aux-right", "main-top", "aux-top")
    arrangements = [item for name in preferred for item in arrangements if item.name == name]
    for arrangement in arrangements:
        for candidate in placement_candidates(
            anchor_physical,
            (arrangement.group_width, arrangement.group_height),
            offset_px,
        ):
            if _rect_fits(
                candidate.x,
                candidate.y,
                arrangement.group_width,
                arrangement.group_height,
                work_rect_physical,
            ):
                gx, gy = candidate.x, candidate.y
                main_rect = _physical_rect(
                    gx + arrangement.main_x,
                    gy + arrangement.main_y,
                    main_size_physical[0],
                    main_size_physical[1],
                )
                aux_rect = _physical_rect(
                    gx + arrangement.aux_x,
                    gy + arrangement.aux_y,
                    aux_size_physical[0],
                    aux_size_physical[1],
                )
                group_rect = _physical_rect(gx, gy, arrangement.group_width, arrangement.group_height)
                return main_rect, aux_rect, group_rect, candidate.name, arrangement.name

    arrangement = arrangements[0]
    first = placement_candidates(
        anchor_physical,
        (arrangement.group_width, arrangement.group_height),
        offset_px,
    )[0]
    group_rect = _clamp_rect(
        first.x,
        first.y,
        arrangement.group_width,
        arrangement.group_height,
        work_rect_physical,
    )
    gx, gy = group_rect[0], group_rect[1]
    main_rect = _physical_rect(
        gx + arrangement.main_x,
        gy + arrangement.main_y,
        main_size_physical[0],
        main_size_physical[1],
    )
    aux_rect = _physical_rect(
        gx + arrangement.aux_x,
        gy + arrangement.aux_y,
        aux_size_physical[0],
        aux_size_physical[1],
    )
    return main_rect, aux_rect, group_rect, "clamp", arrangement.name


def _logical_rect_from_physical(rect: tuple[int, int, int, int]) -> tuple[QPoint, tuple[int, int, int, int]]:
    logical_x, logical_y = physical_to_logical(float(rect[0]), float(rect[1]))
    logical_br_x, logical_br_y = physical_to_logical(float(rect[2]), float(rect[3]))
    pos = QPoint(int(round(logical_x)), int(round(logical_y)))
    size = (
        int(round(logical_x)),
        int(round(logical_y)),
        max(1, int(round(logical_br_x - logical_x))),
        max(1, int(round(logical_br_y - logical_y))),
    )
    return pos, size


def placement_candidates(
    anchor_physical: tuple[int, int],
    overlay_size_physical: tuple[int, int],
    offset_px: int,
) -> list[PlacementCandidate]:
    ax, ay = anchor_physical
    width, height = overlay_size_physical
    offset = max(_PLACEMENT_OFFSET_MIN, min(_PLACEMENT_OFFSET_MAX, int(offset_px)))
    return [
        PlacementCandidate("below-right", ax + offset, ay + offset),
        PlacementCandidate("below-left", ax - width - offset, ay + offset),
        PlacementCandidate("above-right", ax + offset, ay - height - offset),
        PlacementCandidate("above-left", ax - width - offset, ay - height - offset),
    ]


def place_overlay_in_work_area(
    *,
    anchor_physical: tuple[int, int],
    overlay_size_physical: tuple[int, int],
    work_rect_physical: tuple[int, int, int, int],
    offset_px: int = 20,
) -> tuple[int, int, int, int, str]:
    """Return physical rect (l, t, r, b) fully inside work area."""
    width, height = overlay_size_physical
    for candidate in placement_candidates(anchor_physical, overlay_size_physical, offset_px):
        if _rect_fits(candidate.x, candidate.y, width, height, work_rect_physical):
            return (candidate.x, candidate.y, candidate.x + width, candidate.y + height, candidate.name)
    first = placement_candidates(anchor_physical, overlay_size_physical, offset_px)[0]
    rect = _clamp_rect(first.x, first.y, width, height, work_rect_physical)
    return (rect[0], rect[1], rect[2], rect[3], "clamp")


def device_pixel_ratio_at_physical(anchor_physical: tuple[int, int]) -> float:
    lx, ly = physical_to_logical(float(anchor_physical[0]), float(anchor_physical[1]))
    try:
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication
    except Exception:
        return 1.0
    screen = QGuiApplication.screenAt(QPoint(int(round(lx)), int(round(ly)))) or QGuiApplication.primaryScreen()
    if screen is None:
        return 1.0
    dpr = float(screen.devicePixelRatio() or 1.0)
    return dpr if dpr > 0 else 1.0


def logical_size_to_physical(
    width_logical: int,
    height_logical: int,
    *,
    anchor_physical: tuple[int, int],
    device_pixel_ratio: float | None = None,
) -> tuple[int, int]:
    dpr = float(device_pixel_ratio if device_pixel_ratio is not None else device_pixel_ratio_at_physical(anchor_physical))
    if dpr <= 0:
        dpr = 1.0
    return (int(round(width_logical * dpr)), int(round(height_logical * dpr)))


def max_overlay_height_logical(
    anchor_physical: tuple[int, int],
    *,
    work_rect_physical: tuple[int, int, int, int] | None = None,
    fraction: float = DEFAULT_WORK_AREA_FRACTION,
    device_pixel_ratio: float | None = None,
) -> int:
    if work_rect_physical is None:
        monitor = monitor_work_area_at_physical(anchor_physical[0], anchor_physical[1])
        work_rect_physical = monitor.work_rect if monitor is not None else (0, 0, 1920, 1080)
    work_height_physical = work_rect_physical[3] - work_rect_physical[1]
    dpr = float(device_pixel_ratio if device_pixel_ratio is not None else device_pixel_ratio_at_physical(anchor_physical))
    if dpr <= 0:
        dpr = 1.0
    cap = int((work_height_physical * fraction) / dpr)
    return max(120, cap)


class TooltipLayoutCoordinator:
    """Plans passive tooltip placement; aux sizing reserved for Phase E."""

    def plan_main_placement(
        self,
        *,
        overlay_width_logical: int,
        overlay_height_logical: int,
        copy_anchor_physical: tuple[int, int] | None,
        offset_px: int = 20,
        last_valid_anchor_physical: tuple[int, int] | None = None,
        work_rect_physical: tuple[int, int, int, int] | None = None,
        device_pixel_ratio: float | None = None,
        aux_size_logical: tuple[int, int] | None = None,
    ) -> OverlayPlacement:
        anchor_px, anchor_source, fallback_reason = _resolve_anchor_physical(
            copy_anchor_physical,
            last_valid_anchor_physical=last_valid_anchor_physical,
        )
        if work_rect_physical is None:
            monitor = monitor_work_area_at_physical(anchor_px[0], anchor_px[1])
            work = monitor.work_rect if monitor is not None else (0, 0, 1920, 1080)
        else:
            work = work_rect_physical

        dpr = float(device_pixel_ratio if device_pixel_ratio is not None else device_pixel_ratio_at_physical(anchor_px))
        overlay_w_phys, overlay_h_phys = logical_size_to_physical(
            overlay_width_logical,
            overlay_height_logical,
            anchor_physical=anchor_px,
            device_pixel_ratio=dpr,
        )
        if aux_size_logical is not None and aux_size_logical[0] > 0 and aux_size_logical[1] > 0:
            aux_w_phys, aux_h_phys = logical_size_to_physical(
                aux_size_logical[0],
                aux_size_logical[1],
                anchor_physical=anchor_px,
                device_pixel_ratio=dpr,
            )
            gap_physical = max(4, int(round(_GROUP_GAP_LOGICAL * dpr)))
            main_rect, aux_rect, group_rect, strategy, layout_mode = place_group_in_work_area(
                anchor_physical=anchor_px,
                main_size_physical=(overlay_w_phys, overlay_h_phys),
                aux_size_physical=(aux_w_phys, aux_h_phys),
                work_rect_physical=work,
                offset_px=offset_px,
                gap_physical=gap_physical,
            )
            logical_pos, main_logical = _logical_rect_from_physical(main_rect)
            aux_logical_pos, aux_logical = _logical_rect_from_physical(aux_rect)
            return OverlayPlacement(
                logical_pos=logical_pos,
                anchor_source=anchor_source,
                anchor_physical=anchor_px,
                monitor_work_area_physical=work,
                overlay_rect_logical=main_logical,
                fallback_reason=fallback_reason,
                overlay_rect_physical=main_rect,
                placement_strategy=strategy,
                aux_logical_pos=aux_logical_pos,
                aux_overlay_rect_logical=aux_logical,
                aux_overlay_rect_physical=aux_rect,
                group_rect_physical=group_rect,
                group_layout_mode=layout_mode,
            )

        rect_l, rect_t, rect_r, rect_b, strategy = place_overlay_in_work_area(
            anchor_physical=anchor_px,
            overlay_size_physical=(overlay_w_phys, overlay_h_phys),
            work_rect_physical=work,
            offset_px=offset_px,
        )
        logical_x, logical_y = physical_to_logical(float(rect_l), float(rect_t))
        logical_br_x, logical_br_y = physical_to_logical(float(rect_r), float(rect_b))

        placement = OverlayPlacement(
            logical_pos=QPoint(int(round(logical_x)), int(round(logical_y))),
            anchor_source=anchor_source,
            anchor_physical=anchor_px,
            monitor_work_area_physical=work,
            overlay_rect_logical=(
                int(round(logical_x)),
                int(round(logical_y)),
                max(1, int(round(logical_br_x - logical_x))),
                max(1, int(round(logical_br_y - logical_y))),
            ),
            fallback_reason=fallback_reason,
            overlay_rect_physical=(rect_l, rect_t, rect_r, rect_b),
            placement_strategy=strategy,
        )
        return placement


def placement_within_work_area(placement: OverlayPlacement) -> bool:
    rect = placement.group_rect_physical or placement.overlay_rect_physical
    work = placement.monitor_work_area_physical
    if rect is None:
        x, y, w, h = placement.overlay_rect_logical
        dpr = device_pixel_ratio_at_physical(placement.anchor_physical)
        rect = (int(x * dpr), int(y * dpr), int((x + w) * dpr), int((y + h) * dpr))
    left, top, right, bottom = work
    return rect[0] >= left and rect[1] >= top and rect[2] <= right and rect[3] <= bottom
