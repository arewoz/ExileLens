"""UIUX-01 design tokens for the desktop dashboard.

Colours are re-exported from :mod:`exilelens.ui.styles` rather than redefined, so the
dashboard and the Item Check overlay can never drift apart. Only tokens that had no
equivalent (``SURFACE_RAISED``, ``BORDER_STRONG``) are introduced here.

Spacing, radii and control sizes used to be inline literals scattered across the UI
modules; they live here now so a density change is one edit instead of thirty.
"""

from __future__ import annotations

from exilelens.ui.styles import (
    DASHBOARD_ACCENT,
    DASHBOARD_BORDER,
    DASHBOARD_BUTTON_BG,
    DASHBOARD_DISABLED_FG,
    DASHBOARD_ERROR_FG,
    DASHBOARD_INPUT_BG,
    DASHBOARD_INPUT_FG,
    DASHBOARD_MUTED_FG,
    DASHBOARD_NAV_BG,
    DASHBOARD_TEXT_EMPHASIS,
    DASHBOARD_WARNING_FG,
    DASHBOARD_WINDOW_BG,
    DASHBOARD_WINDOW_FG,
)

# --- colour tokens ---------------------------------------------------------------

BG = DASHBOARD_WINDOW_BG
SURFACE = "rgba(255,255,255,6)"
SURFACE_RAISED = "rgba(255,255,255,10)"
TEXT = DASHBOARD_WINDOW_FG
TEXT_EMPHASIS = DASHBOARD_TEXT_EMPHASIS
TEXT_MUTED = DASHBOARD_MUTED_FG
TEXT_DISABLED = DASHBOARD_DISABLED_FG
ACCENT = DASHBOARD_ACCENT
OK = "#7dcf7d"
WARN = DASHBOARD_WARNING_FG
ERROR = DASHBOARD_ERROR_FG
NEUTRAL = DASHBOARD_MUTED_FG
BORDER = DASHBOARD_BORDER
BORDER_STRONG = "rgba(203,184,146,90)"
INPUT_BG = DASHBOARD_INPUT_BG
INPUT_FG = DASHBOARD_INPUT_FG
BUTTON_BG = DASHBOARD_BUTTON_BG
NAV_BG = DASHBOARD_NAV_BG

#: Status name -> colour. Every status renders as dot + text, never colour alone.
STATUS_COLORS = {
    "ok": OK,
    "warn": WARN,
    "error": ERROR,
    "neutral": NEUTRAL,
}

# --- spacing scale ---------------------------------------------------------------

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_XXL = 32

PAGE_GUTTER = SPACE_LG
SECTION_GAP = SPACE_XL
ROW_GAP = SPACE_SM
LABEL_GAP = SPACE_XS

# --- radii -----------------------------------------------------------------------

RADIUS_SM = 4
RADIUS_MD = 8

# --- control / shell sizing ------------------------------------------------------

CONTROL_HEIGHT = 28
SEGMENT_HEIGHT = 30
NAV_ITEM_HEIGHT = 34
HEADER_HEIGHT = 56
SIDEBAR_WIDTH = 184
STATUS_DOT_SIZE = 8

#: Window geometry. ``LEGACY_DEFAULT_WINDOW_SIZE`` is the pre-UIUX-01 default that
#: every existing install has persisted; see ``DashboardWindow._resolve_window_size``.
DEFAULT_WINDOW_SIZE = (980, 640)
MINIMUM_WINDOW_SIZE = (900, 640)
LEGACY_DEFAULT_WINDOW_SIZE = (1280, 860)
