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

import re

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

# Zone treatments (Settings / Diagnostics regroup). One neutral raised card for setup and health, a faintly plum-warmed
# zone for the optional supporter feature (identified by the shipped Patreon mark; a red or burgundy surface reads as
# warning or danger), and one honey-tinted help zone. The honey tint is alpha 0-255 over the page background (5.5%);
# line 24%; inner rule 14%.
CARD_LINE = "rgba(255,255,255,28)"
CARD_RULE = "rgba(255,255,255,17)"
PATREON = "#ff424d"                       # the shipped mark's own colour; used nowhere else, never as a surface
# The supporter zone is the raised neutral surface (SURFACE_1) with about 5% plum mixed in: a faint warm undertone that
# marks it as one intentional, optional feature without reading as warning or danger. Opaque on purpose, and nowhere
# near the error salmon of Reset configuration (hue ~280 vs ~5, saturation ~0.09). Its border stays the neutral card line.
SUPPORT_SURFACE = "#27232a"
HELP = "#e6b84f"                          # honey: yellower than WARN, more saturated than ACCENT
HELP_TINT = "rgba(230,184,79,14)"
HELP_LINE = "rgba(230,184,79,61)"
HELP_RULE = "rgba(230,184,79,36)"

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


# --- Windows Text Size ------------------------------------------------------------
#
# Qt does not follow Settings > Accessibility > Text size (it keeps reporting the 9pt system
# font), and every size in the dashboard stylesheet is a pixel value, so by default the
# dashboard ignores that setting. ``apply_text_scale`` is the one place that fixes it: it
# scales the tokens that hold text (control heights, label columns, the rail width) and
# ``scale_stylesheet`` scales the pixel font sizes. At 100% nothing changes.

_BASE_TOKENS = {
    "CONTROL_HEIGHT": CONTROL_HEIGHT,
    "CONTROL_HEIGHT_COMPACT": CONTROL_HEIGHT_COMPACT,
    "SEGMENT_HEIGHT": SEGMENT_HEIGHT,
    "NAV_ITEM_HEIGHT": NAV_ITEM_HEIGHT,
    "ROW_MIN_HEIGHT": ROW_MIN_HEIGHT,
    "SETTINGS_SELECT_WIDTH": SETTINGS_SELECT_WIDTH,
}
_BASE_RAIL_WIDTH = RAIL_WIDTH
_MAX_RAIL_SCALE = 1.5   # a very large text size must not let the rail take over the window
TEXT_SCALE = 1.0


def system_text_scale() -> float:
    """The Windows Text size factor (1.0 to 2.25); 1.0 elsewhere or when it cannot be read.

    Settings > Accessibility > Text size stores a percentage in
    ``HKCU\\Software\\Microsoft\\Accessibility\\TextScaleFactor`` (absent means 100).
    """
    try:
        import sys

        if sys.platform != "win32":
            return 1.0
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Accessibility") as key:
            value, _kind = winreg.QueryValueEx(key, "TextScaleFactor")
        return max(1.0, min(2.25, int(value) / 100.0))
    except Exception:  # noqa: BLE001 - a missing key or value just means 100%
        return 1.0


def scaled_px(value: float) -> int:
    """A pixel size that holds text, scaled by the current text size."""
    return max(1, int(round(value * TEXT_SCALE)))


def apply_text_scale(factor: float) -> float:
    """Set the text scale and rescale the text-bearing size tokens from their 100% values."""
    global TEXT_SCALE, RAIL_WIDTH, SIDEBAR_WIDTH
    TEXT_SCALE = max(1.0, min(2.25, float(factor)))
    for name, base in _BASE_TOKENS.items():
        globals()[name] = int(round(base * TEXT_SCALE))
    RAIL_WIDTH = SIDEBAR_WIDTH = int(round(_BASE_RAIL_WIDTH * min(TEXT_SCALE, _MAX_RAIL_SCALE)))
    return TEXT_SCALE


_TEXT_BASE_RULE = (
    "QLabel, QAbstractButton, QComboBox, QLineEdit, QTextEdit, QPlainTextEdit, QAbstractItemView { font-size: 12px; }\n"
)
_FONT_PX = re.compile(r"font-size:\s*(\d+(?:\.\d+)?)px")


def scale_stylesheet(css: str) -> str:
    """Scale every ``font-size: Npx`` in a stylesheet by the current text scale."""
    if TEXT_SCALE == 1.0:
        return css
    # Qt resolves a widget that a style sheet gives a font rule (say a weight) against the application
    # font, not its parent's, so text with no explicit size would stay at the unscaled 9pt (12px).
    # A lowest-specificity base rule gives every such widget the default size, which then scales.
    css = _TEXT_BASE_RULE + css
    return _FONT_PX.sub(lambda m: f"font-size: {scaled_px(float(m.group(1)))}px", css)
