"""Design tokens for the desktop dashboard (Status Rail redesign).

These are dashboard-only tokens. They are deliberately **not** derived from the Item
Check overlay constants in :mod:`exilelens.ui.styles` (``OVERLAY_*``), so tuning the
dashboard can never alter the in-game overlay. The legacy ``DASHBOARD_*`` constants in
``styles`` stay as they were for pages that still use the legacy stylesheet prefix.

Rules the tokens encode:

* two radii only: 4px for controls and notices, 6px for the rare card;
* a single champagne accent, used for the primary button, the selected-nav bar and
  switches/checks that are on -- never as a status colour;
* status colours (ok / warn / error) always travel with a word or a shape.
"""

from __future__ import annotations

# --- colour tokens ---------------------------------------------------------------

BG = "#17181b"            # window
RAIL_BG = "#1a1b1e"       # sidebar
SURFACE_1 = "#1f2024"     # consent card, tinted problem rows
SURFACE_2 = "#26272c"     # secondary buttons, selected nav
SURFACE_3 = "#31323a"     # selected segment, keycaps
WELL = "#0f1012"          # inputs, log, segmented track

# Legacy aliases kept so existing imports keep working. SURFACE and SURFACE_RAISED
# used to be translucent whites; they now map onto the opaque surface ladder.
SURFACE = SURFACE_1
SURFACE_RAISED = SURFACE_2

TEXT_EMPHASIS = "#f0ede6"
TEXT = "#f0ede6"
TEXT_BODY = "#c4c0b6"
TEXT_MUTED = "#97928a"     # >= 4.8:1 on every raised surface; the minimum for informational text
TEXT_DISABLED = "#6f6b64"  # disabled controls only, never informational copy
ACCENT = "#d2b176"
ACCENT_HOVER = "#e0c48f"
ON_ACCENT = "#1b1408"
FOCUS = "#f4e2b4"

OK = "#78c795"
WARN = "#f2a03d"
ERROR = "#ef8077"
INFO = "#86b3e6"
NEUTRAL = TEXT_MUTED

HAIRLINE = "rgba(255,255,255,18)"          # row dividers
HAIRLINE_STRONG = "rgba(255,255,255,36)"   # control outlines
BORDER = HAIRLINE
BORDER_STRONG = HAIRLINE_STRONG

WARN_TINT = "rgba(242,160,61,26)"
WARN_LINE = "rgba(242,160,61,97)"
ERROR_TINT = "rgba(239,128,119,26)"
ERROR_LINE = "rgba(239,128,119,97)"
INFO_TINT = "rgba(134,179,230,23)"
INFO_LINE = "rgba(134,179,230,87)"

INPUT_BG = WELL
INPUT_FG = TEXT
BUTTON_BG = SURFACE_2
NAV_BG = RAIL_BG

#: Status name -> colour. Every status renders as dot/shape + text, never colour alone.
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

PAGE_GUTTER = SPACE_XXL          # content side padding at full width
PAGE_GUTTER_COMPACT = SPACE_XL   # ... beside the 64px rail
PAGE_TOP = SPACE_XL
PAGE_BOTTOM = 28
SECTION_GAP = 28
ROW_GAP = SPACE_SM
LABEL_GAP = SPACE_XS
ROW_MIN_HEIGHT = 48
ROW_PAD = 9
SCROLLBAR_WIDTH = 10  # always-on vertical scrollbar gutter on scrolling pages
COLUMN_MAX_WIDTH = 716

# --- radii -----------------------------------------------------------------------

RADIUS_SM = 4   # controls, notices
RADIUS_MD = 6   # the rare card (one-time consent)

# --- control / shell sizing ------------------------------------------------------

CONTROL_HEIGHT = 32
CONTROL_HEIGHT_COMPACT = 28
SEGMENT_HEIGHT = 30
NAV_ITEM_HEIGHT = 34
HEADER_HEIGHT = 56  # legacy; the header bar no longer exists
RAIL_WIDTH = 208
COMPACT_RAIL_WIDTH = 64
SIDEBAR_WIDTH = RAIL_WIDTH
COMPACT_BREAKPOINT = 840   # window widths below this use the icon rail
STATUS_DOT_SIZE = 8
RAIL_TEXT_X = 24           # rail text/icon axis: 12px rail padding + 12px item padding
SETTINGS_SELECT_WIDTH = 140

#: Window geometry. ``LEGACY_DEFAULT_WINDOW_SIZE`` is the pre-UIUX-01 default that
#: every existing install may have persisted; see ``DashboardWindow._resolve_window_size``.
#: ``PREVIOUS_DEFAULT_WINDOW_SIZE`` is the default of the previous dashboard (0.7.0b1).
DEFAULT_WINDOW_SIZE = (980, 720)
MINIMUM_WINDOW_SIZE = (720, 560)
LEGACY_DEFAULT_WINDOW_SIZE = (1280, 860)
PREVIOUS_DEFAULT_WINDOW_SIZE = (980, 640)

# --- typography ------------------------------------------------------------------

#: System UI face for everything except the build name.
UI_FONT_FAMILY = '"Segoe UI Variable Text", "Segoe UI", sans-serif'
#: Used for exactly one string: the build name. Falls back to Georgia when the bundled
#: face is not present.
BUILD_NAME_FONT_FAMILY = '"Spectral", "Georgia", serif'
MONO_FONT_FAMILY = '"Cascadia Mono", "Consolas", monospace'
