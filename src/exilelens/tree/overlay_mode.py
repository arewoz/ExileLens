"""Live tree overlay visual modes. BUILD PATH is the product default."""

from __future__ import annotations

from enum import Enum


class OverlayMode(str, Enum):
    BUILD_PATH = "BUILD_PATH"
    NEXT_POINTS = "NEXT_POINTS"
    VALUE_HEATMAP = "VALUE_HEATMAP"
    CALIBRATION_ANCHORS = "CALIBRATION_ANCHORS"


DEFAULT_OVERLAY_MODE = OverlayMode.BUILD_PATH
