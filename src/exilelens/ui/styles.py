"""Dark graphite overlay styling (no copyrighted assets).

P1.1b: retoned from the original warm brown/tan "premium" palette to a neutral
graphite/off-white base. Color still carries meaning (green = gain, red = loss,
amber = warning/uncertain, gold = the one restrained ExileLens accent) but the
surfaces and body text are no longer sepia-tinted. See
docs/ITEM_CHECK_PRESENTATION.md's Visual hierarchy section for the rationale.
"""

# ExileLens opaque chrome. Overlay styles stay transparent; these tokens are the
# dashboard / Settings surface so unstyled Qt widgets do not fall back to the
# Windows QPalette (Light mode paints QScrollArea viewports white).
DASHBOARD_WINDOW_BG = "#17181b"
DASHBOARD_WINDOW_FG = "#e3e1dc"
DASHBOARD_TEXT_EMPHASIS = "#f5f3ee"
DASHBOARD_MUTED_FG = "#8b8a85"
DASHBOARD_DISABLED_FG = "#726f6c"
DASHBOARD_INPUT_BG = "#1d1e22"
DASHBOARD_INPUT_FG = "#e2e0da"
DASHBOARD_BUTTON_BG = "#26272b"
DASHBOARD_BUTTON_HOVER = "#323338"
DASHBOARD_NAV_BG = "#1a1b1e"
DASHBOARD_ACCENT = "#c9a227"
DASHBOARD_WARNING_FG = "#e0a040"
DASHBOARD_ERROR_FG = "#d97b7b"
DASHBOARD_BORDER = "rgba(255,255,255,12)"
DASHBOARD_SCROLL_HANDLE = "#323338"

# Item Check tooltip palette. The overlay paints its own dark chrome; these tokens
# keep every label/button off the Windows QPalette (Light mode = black text).
OVERLAY_TEXT_PRIMARY = "#e3e1dc"
OVERLAY_TEXT_EMPHASIS = "#f5f3ee"
OVERLAY_TEXT_SECONDARY = "#b2b0ab"
OVERLAY_TEXT_MUTED = "#84827d"
OVERLAY_SECTION_HEADING = "#a3a19b"
OVERLAY_WARNING_BODY = "#e0a040"
OVERLAY_WARNING_CRITICAL = "#e8a3a3"
OVERLAY_DELTA_POSITIVE = "#7dcf7d"
OVERLAY_DELTA_NEGATIVE = "#d97b7b"
OVERLAY_DELTA_NEUTRAL = "#9c9a95"
OVERLAY_ACTION_TEXT = "#b2b0ab"
OVERLAY_BORDER = "rgba(255,255,255,12)"

# The single painted window background (overlay.py/pinned_item_overlay.py
# paintEvent) and its border. Graphite, not brown -- these used to be raw
# QColor(34, 29, 24, ...) literals duplicated in three files.
OVERLAY_WINDOW_GRADIENT_TOP = (27, 28, 31, 244)
OVERLAY_WINDOW_GRADIENT_MID = (20, 21, 24, 242)
OVERLAY_WINDOW_GRADIENT_BOTTOM = (12, 12, 14, 244)
OVERLAY_WINDOW_BORDER_RGBA = (74, 75, 80, 205)

OVERLAY_STYLESHEET = """
QWidget#overlayRoot {
    background: transparent;
    color: #e3e1dc;
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}
QWidget#headerBand {
    background: transparent;
}
QLabel#nameLabel {
    font-size: 16px;
    font-weight: 700;
    color: #f5f3ee;
}
QLabel#rarityLabel {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.2px;
    color: #c9a227;
}
QLabel#baseLabel {
    color: #84827d;
    font-size: 12px;
}
QWidget#baselineStrip {
    background: rgba(255,255,255,8);
    border: 1px solid rgba(255,255,255,14);
    border-radius: 5px;
}
QLabel#baselineLabel {
    color: #e3e1dc;
    font-size: 12px;
    font-weight: 600;
}
QLabel#baselineMeta {
    color: #8b8a85;
    font-size: 10px;
}
QLabel#pobBaselineHint {
    color: #726f6c;
    font-size: 10px;
}
QLabel#profileChip {
    color: #b2b0ab;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.8px;
    padding: 1px 7px;
    border: 1px solid rgba(255,255,255,16);
    border-radius: 8px;
    background: rgba(255,255,255,8);
}
QLabel#metricLabel {
    color: #b2b0ab;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
}
QLabel#metricDelta {
    font-size: 15px;
    font-weight: 700;
    color: #9c9a95;
}
QLabel#metricRange {
    color: #83817c;
    font-size: 11px;
}
QLabel#capLabel {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.3px;
    color: #e0a040;
}
QLabel#compactNote {
    color: #84827d;
    font-size: 11px;
}
QLabel#flagChip {
    color: #9c9a95;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.3px;
    padding: 1px 6px;
    border: 1px solid rgba(255,255,255,16);
    border-radius: 7px;
    background: rgba(255,255,255,8);
}
QFrame#sectionRule {
    color: rgba(255,255,255,16);
    max-height: 1px;
}
QWidget#warningPanel {
    border-radius: 6px;
    padding: 2px;
}
QLabel#warningTitle {
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 1.1px;
    color: #a3a19b;
}
QLabel#whyLabel {
    color: #b2b0ab;
    font-size: 12px;
}
QLabel#bestSlotLabel {
    color: #e3e1dc;
    font-size: 12px;
    font-weight: 600;
}
QLabel#multiProfileRow {
    color: #b2b0ab;
    font-size: 11px;
}
QLabel#sectionTitle {
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 1.1px;
    color: #a3a19b;
}
QLabel#trustHigh {
    color: #7dcf7d;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.8px;
}
QLabel#trustAssisted {
    color: #dba748;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.8px;
}
QLabel#trustNeeds {
    color: #d68a54;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.8px;
}
QPushButton#moreInfoButton {
    color: #b2b0ab;
    font-size: 11px;
    font-weight: 700;
    padding: 2px 0;
    border: none;
    text-align: right;
}
QPushButton#moreInfoButton:hover {
    color: #f5f3ee;
}
QLabel#scoreSecondary {
    color: #84827d;
    font-size: 12px;
    font-weight: 600;
}
QLabel#slotVerdictLine {
    color: #b2b0ab;
    font-size: 12px;
    font-weight: 600;
}
QWidget#overlayFooter {
    background: transparent;
}
QPushButton#footerPinButton {
    color: #b2b0ab;
    font-size: 11px;
    font-weight: 700;
    padding: 2px 0;
    border: none;
    text-align: left;
}
QPushButton#footerPinButton:hover:enabled {
    color: #f5f3ee;
}
QPushButton#footerPinButton:disabled {
    color: #726f6c;
}
QPushButton#retryButton {
    background: #26272b;
    color: #e3e1dc;
    border: 1px solid rgba(255,255,255,16);
    border-radius: 4px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 700;
}
QPushButton#retryButton:hover {
    color: #f5f3ee;
}
QLabel#hotkeyHint {
    color: #8b8a85;
    font-size: 10px;
}
QPushButton#hintDismissButton {
    color: #8b8a85;
    border: none;
    font-size: 12px;
    padding: 0 4px;
}
QPushButton#overlayCloseButton {
    color: #b2b0ab;
    border: none;
    font-size: 16px;
    padding: 0 2px 0 6px;
    min-width: 20px;
}
QPushButton#overlayCloseButton:hover {
    color: #f5f3ee;
}
QPushButton#ringChoiceButton {
    background: #1f2024;
    color: #e3e1dc;
    border: 1px solid rgba(255,255,255,14);
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 11px;
    text-align: left;
}
QPushButton#ringChoiceButton:checked {
    border: 1px solid rgba(255,255,255,55);
    background: rgba(255,255,255,12);
}
QScrollArea#moreInfoScroll {
    background: transparent;
    border: none;
}
QWidget#moreInfoBody {
    background: transparent;
}
QFrame#detailDrawerDivider {
    color: rgba(201, 162, 39, 35);
    max-width: 1px;
}
QWidget#detailAnalysisDrawer {
    border-top: none;
    border-left: 1px solid rgba(201, 162, 39, 35);
    background: rgba(255,255,255,4);
}
QLabel#detailSectionTitle {
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 1.1px;
    color: #a3a19b;
}
QLabel#detailSectionTitleAdvanced {
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.9px;
    color: #726f6c;
}
QPushButton#advancedToggleButton {
    color: #83817c;
    background: transparent;
    border: none;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.6px;
    padding: 2px 0;
    text-align: left;
}
QPushButton#advancedToggleButton:hover {
    color: #b2b0ab;
}
QLabel#detailTableHeader {
    color: #83817c;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.6px;
}
QLabel#detailTableLabel {
    color: #b2b0ab;
    font-size: 11px;
    font-weight: 600;
}
QLabel#detailTableValue {
    color: #e3e1dc;
    font-size: 11px;
    font-weight: 600;
}
QLabel#detailTableChange {
    font-size: 11px;
    font-weight: 700;
    color: #e3e1dc;
}
QLabel#detailImpactLine {
    color: #e3e1dc;
    font-size: 12px;
    font-weight: 600;
}
QLabel#warningLabel {
    font-size: 12px;
    font-weight: 600;
    color: #e0a040;
}
QWidget#verdictBand {
    border-radius: 6px;
    background: rgba(255,255,255,7);
    border: 1px solid rgba(255,255,255,14);
}
QLabel#scoreHeadline {
    font-size: 19px;
    font-weight: 800;
    letter-spacing: 0.4px;
    padding: 2px 0 2px 0;
    color: #f5f3ee;
}
QLabel#verdictLabel {
    font-size: 15px;
    font-weight: 800;
    letter-spacing: 0.8px;
    color: #e3e1dc;
}
QLabel#explainLabel {
    color: #b2b0ab;
    font-size: 12px;
}
QWidget#valueBand {
    background: transparent;
}
QLabel#valueCaption {
    color: #83817c;
    font-size: 11px;
}
QLabel#valueLabel {
    color: #e3e1dc;
    font-size: 14px;
    font-weight: 700;
}
QLabel#priceLabel {
    color: #c4c2bc;
    font-size: 12px;
}
QLabel#errorLabel { color: #d97b7b; font-size: 12px; }
QLabel#analyzingLabel { color: #84827d; font-style: italic; }
"""

OVERLAY_THEME_INDEPENDENCE_STYLESHEET = f"""
/* Item Check tooltip root: never inherit Windows Light/Dark foreground roles. */
QWidget#overlayRoot,
QWidget#pinnedItemOverlay {{
    color: {OVERLAY_TEXT_PRIMARY};
    background: transparent;
}}
QWidget#overlayRoot QLabel,
QWidget#pinnedItemOverlay QLabel {{
    color: {OVERLAY_TEXT_PRIMARY};
    background-color: transparent;
}}
QWidget#overlayRoot QWidget,
QWidget#pinnedItemOverlay QWidget {{
    background-color: transparent;
    color: {OVERLAY_TEXT_PRIMARY};
}}
QWidget#overlayRoot QPushButton,
QWidget#pinnedItemOverlay QPushButton {{
    color: {OVERLAY_ACTION_TEXT};
}}
"""

TREE_COACH_STYLESHEET = OVERLAY_STYLESHEET + """
QWidget#treeCoachRoot, QWidget#treeWorkspaceRoot, QWidget#overlayRoot {
    background: #18191c;
    color: #e3e1dc;
}
QWidget#treeHeader {
    background: rgba(255,255,255,9);
    border: 1px solid rgba(255,255,255,14);
    border-radius: 6px;
}
QListWidget, QTextEdit, QLineEdit, QComboBox, QPlainTextEdit {
    background: #1d1e22;
    color: #e3e1dc;
    border: 1px solid rgba(255,255,255,16);
    border-radius: 4px;
}
QPushButton {
    background: #26272b;
    color: #e3e1dc;
    border: 1px solid rgba(255,255,255,16);
    border-radius: 4px;
    padding: 4px 10px;
}
QPushButton:hover { background: #323338; }
QProgressBar {
    background: #1d1e22;
    border: 1px solid rgba(255,255,255,16);
    color: #a3a19b;
    height: 12px;
}
QCheckBox, QRadioButton { color: #e3e1dc; }
QLabel#staleBanner {
    color: #e0a040;
    font-weight: 700;
    letter-spacing: 1px;
}
"""

DASHBOARD_SURFACE_STYLESHEET = f"""
/* Scroll surfaces, stacked pages, and group boxes are not covered by
   QWidget#dashboardRoot. Without these rules they keep the OS palette. */
QStackedWidget,
QScrollArea,
QScrollArea#settingsScrollArea,
QWidget#settingsScrollViewport,
QWidget#qt_scrollarea_viewport,
QWidget#settingsScrollContent,
QWidget#settingsPage,
/* UIUX-01 containers. Without these a Windows light palette paints them white,
   exactly as it did for the scroll viewport before this block existed. */
QWidget#overviewPage,
QWidget#diagnosticsPage,
QWidget#contentPane,
QWidget#diagnosticsScrollViewport,
QWidget#diagnosticsScrollContent,
QWidget#section,
QWidget#settingRow,
QWidget#healthRow,
QWidget#disclosureContent {{
    background-color: {DASHBOARD_WINDOW_BG};
    color: {DASHBOARD_WINDOW_FG};
    border: none;
}}
QGroupBox {{
    background-color: {DASHBOARD_WINDOW_BG};
    color: {DASHBOARD_WINDOW_FG};
    border: 1px solid {DASHBOARD_BORDER};
    border-radius: 6px;
    margin-top: 12px;
    padding: 10px 8px 8px 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    color: {DASHBOARD_TEXT_EMPHASIS};
    background-color: {DASHBOARD_WINDOW_BG};
}}
QLabel {{
    color: {DASHBOARD_WINDOW_FG};
    background-color: transparent;
}}
QLabel:disabled {{
    color: {DASHBOARD_DISABLED_FG};
}}
QPushButton:disabled {{
    color: {DASHBOARD_DISABLED_FG};
    background: rgba(255,255,255,6);
    border-color: rgba(255,255,255,18);
}}
QComboBox QAbstractItemView {{
    background-color: {DASHBOARD_INPUT_BG};
    color: {DASHBOARD_INPUT_FG};
    selection-background-color: {DASHBOARD_BUTTON_HOVER};
    selection-color: {DASHBOARD_TEXT_EMPHASIS};
    border: 1px solid {DASHBOARD_BORDER};
}}
QScrollBar:vertical {{
    background: {DASHBOARD_NAV_BG};
    width: 12px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {DASHBOARD_SCROLL_HANDLE};
    min-height: 24px;
    border-radius: 5px;
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: {DASHBOARD_NAV_BG};
}}
QScrollBar:horizontal {{
    background: {DASHBOARD_NAV_BG};
    height: 12px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {DASHBOARD_SCROLL_HANDLE};
    min-width: 24px;
    border-radius: 5px;
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {{
    background: {DASHBOARD_NAV_BG};
}}
"""

#: UIUX-01. Borders belong to interactive controls only; grouping is done with
#: spacing and a borderless surface. Selection is never colour alone -- it always
#: pairs the gold accent with a raised surface and a heavier font weight.
_V2_SURFACE = "rgba(255,255,255,6)"
_V2_SURFACE_RAISED = "rgba(255,255,255,10)"
_V2_BORDER_STRONG = "rgba(203,184,146,90)"
_V2_OK = "#7dcf7d"

DASHBOARD_V2_STYLESHEET = f"""
/* --- shell --------------------------------------------------------------- */
QWidget#appHeader {{
    background-color: {DASHBOARD_NAV_BG};
    border-bottom: 1px solid {DASHBOARD_BORDER};
}}
QLabel#appWordmark {{
    font-size: 15px;
    font-weight: 700;
    color: {DASHBOARD_TEXT_EMPHASIS};
    letter-spacing: 0.4px;
}}
QWidget#contentPane {{
    background-color: {DASHBOARD_WINDOW_BG};
}}
QWidget#progressStrip {{
    background-color: {_V2_SURFACE};
    border-top: 1px solid {DASHBOARD_BORDER};
}}

/* --- typography ---------------------------------------------------------- */
QLabel#sectionTitle {{
    font-size: 11px;
    font-weight: 700;
    color: {DASHBOARD_MUTED_FG};
    letter-spacing: 1.2px;
}}
QLabel#primaryValue {{
    font-size: 20px;
    font-weight: 700;
    color: {DASHBOARD_TEXT_EMPHASIS};
}}
QLabel#cardTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {DASHBOARD_WINDOW_FG};
}}
QLabel#secondaryText {{
    font-size: 12px;
    color: {DASHBOARD_MUTED_FG};
}}
QLabel#helperText {{
    font-size: 12px;
    color: {DASHBOARD_MUTED_FG};
}}
QLabel#fieldLabel {{
    font-size: 13px;
    color: {DASHBOARD_WINDOW_FG};
}}

/* --- status -------------------------------------------------------------- */
QLabel#statusOk {{ font-size: 12px; font-weight: 600; color: {_V2_OK}; }}
QLabel#statusWarn {{ font-size: 12px; font-weight: 600; color: {DASHBOARD_WARNING_FG}; }}
QLabel#statusError {{ font-size: 12px; font-weight: 600; color: {DASHBOARD_ERROR_FG}; }}
QLabel#statusNeutral {{ font-size: 12px; font-weight: 600; color: {DASHBOARD_MUTED_FG}; }}

/* --- buttons: four explicit tiers ---------------------------------------- */
QPushButton#btnPrimary {{
    background: rgba(203,184,146,40);
    border: 1px solid {_V2_BORDER_STRONG};
    border-radius: 4px;
    color: {DASHBOARD_TEXT_EMPHASIS};
    font-weight: 700;
    padding: 5px 14px;
    min-height: 18px;
}}
QPushButton#btnPrimary:hover:enabled {{ background: rgba(203,184,146,62); }}
QPushButton#btnPrimary:focus {{ border: 1px solid {DASHBOARD_ACCENT}; }}
QPushButton#btnSecondary {{
    background: {DASHBOARD_BUTTON_BG};
    border: 1px solid {DASHBOARD_BORDER};
    border-radius: 4px;
    color: {DASHBOARD_WINDOW_FG};
    font-weight: 600;
    padding: 5px 14px;
    min-height: 18px;
}}
QPushButton#btnSecondary:hover:enabled {{ background: {DASHBOARD_BUTTON_HOVER}; }}
QPushButton#btnSecondary:focus {{ border: 1px solid {_V2_BORDER_STRONG}; }}
QPushButton#btnTertiary {{
    background: transparent;
    /* Transparent rather than absent so hover/focus can show a border without
       shifting the button by a pixel. */
    border: 1px solid transparent;
    border-radius: 4px;
    color: {DASHBOARD_MUTED_FG};
    font-weight: 600;
    padding: 5px 10px;
    min-height: 18px;
}}
QPushButton#btnTertiary:hover:enabled {{
    background: {_V2_SURFACE_RAISED};
    color: {DASHBOARD_TEXT_EMPHASIS};
}}
QPushButton#btnTertiary:focus {{
    background: {_V2_SURFACE_RAISED};
    border: 1px solid {DASHBOARD_ACCENT};
    color: {DASHBOARD_TEXT_EMPHASIS};
}}
QPushButton#btnTertiary:disabled {{
    color: {DASHBOARD_DISABLED_FG};
    background: transparent;
    border-color: transparent;
}}
QPushButton#btnDestructive {{
    background: transparent;
    border: 1px solid rgba(211,122,122,60);
    border-radius: 4px;
    color: {DASHBOARD_ERROR_FG};
    font-weight: 600;
    padding: 5px 14px;
    min-height: 18px;
}}
QPushButton#btnDestructive:hover:enabled {{ background: rgba(211,122,122,26); }}
QPushButton#btnDestructive:focus {{ border: 1px solid {DASHBOARD_ERROR_FG}; }}

/* --- segmented control --------------------------------------------------- */
QWidget#segmentGroup {{
    /* Stronger than the generic surface token on purpose: at 6/255 alpha the
       container was invisible and the control read as one button beside three
       unrelated text links. */
    background: rgba(255,255,255,13);
    border: 1px solid rgba(255,255,255,30);
    border-radius: 5px;
}}
QPushButton#segmentButton {{
    background: transparent;
    /* Transparent, not absent: a border that appears only when selected would
       shift every segment by a pixel on selection. */
    border: 1px solid transparent;
    border-radius: 3px;
    color: {DASHBOARD_MUTED_FG};
    font-size: 12px;
    font-weight: 600;
    padding: 4px 14px;
}}
QPushButton#segmentButton:hover:!checked {{
    background: {_V2_SURFACE_RAISED};
    color: {DASHBOARD_WINDOW_FG};
}}
QPushButton#segmentButton:checked {{
    background: rgba(203,184,146,46);
    border: 1px solid {_V2_BORDER_STRONG};
    color: {DASHBOARD_TEXT_EMPHASIS};
    font-weight: 700;
}}
QPushButton#segmentButton:focus:!checked {{
    border: 1px solid {DASHBOARD_BORDER};
    background: {_V2_SURFACE_RAISED};
    color: {DASHBOARD_WINDOW_FG};
}}
QPushButton#segmentButton:checked:focus {{
    border: 1px solid {DASHBOARD_ACCENT};
}}

/* --- disclosure ---------------------------------------------------------- */
QToolButton#disclosureToggle {{
    background: transparent;
    border: none;
    color: {DASHBOARD_WINDOW_FG};
    font-size: 13px;
    font-weight: 600;
    padding: 4px 0;
}}
QToolButton#disclosureToggle:hover {{ color: {DASHBOARD_TEXT_EMPHASIS}; }}
QToolButton#disclosureToggle:focus {{ color: {DASHBOARD_ACCENT}; text-decoration: underline; }}

/* --- surfaces ------------------------------------------------------------ */
QWidget#cardSurface {{
    background: {_V2_SURFACE};
    border: none;
    border-radius: 8px;
}}
QFrame#sectionDivider {{
    background: {DASHBOARD_BORDER};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}

/* --- focus visibility on standard controls ------------------------------- */
QComboBox:focus, QLineEdit:focus {{
    border: 1px solid {_V2_BORDER_STRONG};
}}
QCheckBox:focus {{ color: {DASHBOARD_TEXT_EMPHASIS}; }}

/* The native Windows indicator is bright system blue, which is the one saturated
   colour in an otherwise warm dark UI. */
QCheckBox {{
    color: {DASHBOARD_WINDOW_FG};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid rgba(255,255,255,40);
    border-radius: 3px;
    background: {DASHBOARD_INPUT_BG};
}}
QCheckBox::indicator:hover {{
    border-color: {_V2_BORDER_STRONG};
}}
QCheckBox::indicator:checked {{
    background: rgba(203,184,146,60);
    border: 1px solid {DASHBOARD_ACCENT};
}}
QCheckBox::indicator:disabled {{
    border-color: rgba(255,255,255,18);
    background: rgba(255,255,255,6);
}}
"""

DASHBOARD_STYLESHEET = OVERLAY_STYLESHEET + TREE_COACH_STYLESHEET[len(OVERLAY_STYLESHEET):] + """
QWidget#dashboardRoot {
    background: #17181b;
    color: #e3e1dc;
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}
QWidget#navRail {
    background: #1a1b1e;
    border-right: 1px solid rgba(255,255,255,12);
}
QPushButton#navButton {
    text-align: left;
    padding: 8px 14px;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0;
    background: transparent;
    color: #8b8a85;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#navButton:hover:!checked {
    background: rgba(255,255,255,10);
    color: #e3e1dc;
}
QPushButton#navButton:checked {
    background: rgba(203,184,146,18);
    color: #f5f3ee;
    border-left: 3px solid #c9a227;
    font-weight: 700;
}
QPushButton#navButton:focus {
    background: rgba(255,255,255,10);
    color: #f5f3ee;
}
QPushButton#navButtonSecondary {
    text-align: left;
    padding: 7px 14px;
    border: none;
    border-left: 3px solid transparent;
    background: transparent;
    color: #8b8a85;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#navButtonSecondary:hover:!checked {
    background: rgba(255,255,255,10);
    color: #8b8a85;
}
QPushButton#navButtonSecondary:checked {
    background: rgba(203,184,146,18);
    color: #f5f3ee;
    border-left: 3px solid #c9a227;
    font-weight: 700;
}
QPushButton#navButtonSecondary:focus {
    background: rgba(255,255,255,10);
    color: #e3e1dc;
}
QLabel#pageTitle {
    font-size: 18px;
    font-weight: 700;
    color: #f5f3ee;
    letter-spacing: 0.3px;
}
QLabel#engineStateReady { color: #7dcf7d; font-weight: 700; }
QLabel#engineStateLoading { color: #d4bc6e; font-weight: 700; }
QLabel#engineStateFailed { color: #d37a7a; font-weight: 700; }
QWidget#statusFooter {
    background: rgba(255,255,255,6);
    border-top: 1px solid rgba(255,255,255,12);
}
QWidget#placeholderCard {
    background: rgba(255,255,255,8);
    border: 1px solid rgba(255,255,255,14);
    border-radius: 8px;
    padding: 16px;
}

/* PRODUCT-UX-01 Character page */
QLabel#charSectionHeading {
    color: #8b8a85;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 1.4px;
}
QWidget#charStatusStrip {
    background: rgba(255,255,255,6);
    border: 1px solid rgba(255,255,255,14);
    border-radius: 6px;
}
QLabel#charStatusLabel {
    color: #8b8a85;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.8px;
}
QLabel#charStatusValue {
    color: #e3e1dc;
    font-size: 12px;
    font-weight: 600;
}
QWidget#charCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(203,184,146,26), stop:1 rgba(255,255,255,6));
    border: 1px solid rgba(203,184,146,60);
    border-left: 3px solid #c9a227;
    border-radius: 8px;
}
QLabel#charName {
    font-size: 20px;
    font-weight: 700;
    color: #f5f3ee;
}
QLabel#charDetail {
    color: #e3e1dc;
    font-size: 13px;
}
QLabel#charLeague {
    color: #8b8a85;
    font-size: 12px;
    font-weight: 600;
}
QLabel#charSynced {
    color: #8b8a85;
    font-size: 11px;
}
QLabel#charEmpty {
    color: #8b8a85;
    font-size: 13px;
}
QLabel#resultSuccess { color: #7dcf7d; font-size: 12px; font-weight: 700; }
QLabel#resultPartial { color: #d4bc6e; font-size: 12px; font-weight: 700; }
QLabel#resultFailed  { color: #d37a7a; font-size: 12px; font-weight: 700; }
QLabel#resultSyncing { color: #e3e1dc; font-size: 12px; font-weight: 700; }
QLabel#leagueHeading {
    color: #c9a227;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
}
QLabel#charRowCurrent {
    color: #f5f3ee;
    font-size: 12px;
    font-weight: 600;
}
QLabel#charRow {
    color: #8b8a85;
    font-size: 12px;
}
QLabel#dataRowLabel {
    color: #8b8a85;
    font-size: 12px;
}
QLabel#dataRowValue {
    color: #e3e1dc;
    font-size: 12px;
    font-weight: 600;
}
QLabel#charError {
    color: #d37a7a;
    font-size: 12px;
}
QComboBox#charCombo {
    min-width: 220px;
    padding: 4px 8px;
}
QPushButton#charSyncButton {
    background: rgba(203,184,146,26);
    border: 1px solid rgba(203,184,146,90);
    border-radius: 5px;
    color: #f5f3ee;
    font-weight: 700;
    padding: 7px 18px;
}
QPushButton#charSyncButton:hover:enabled {
    background: rgba(203,184,146,44);
}
QPushButton#charSyncButton:disabled {
    color: #726f6c;
    border-color: rgba(255,255,255,18);
    background: rgba(255,255,255,6);
}
""" + DASHBOARD_SURFACE_STYLESHEET + DASHBOARD_V2_STYLESHEET


VERDICT_CLASS = {
    "STRONG_UPGRADE": "upgrade",
    "CLEAR_UPGRADE": "upgrade",
    "OFFENSE_UPGRADE": "upgrade",
    "DEFENSE_UPGRADE": "upgrade",
    "TRADEOFF": "tradeoff",
    "SIDEGRADE": "neutral",
    "NO_CHANGE": "neutral",
    "DOWNGRADE": "downgrade",
    "STRONG_DOWNGRADE": "downgrade",
    "UNRESOLVED": "neutral",
    "MAJOR_UPGRADE": "upgrade",
    "MEANINGFUL_UPGRADE": "upgrade",
    "MINOR_UPGRADE": "upgrade",
    "BUILD_FIX": "upgrade",
    "BLOCKED": "downgrade",
    "UNSAFE": "tradeoff",
    # EvaluationOutcome public verdicts (evaluation_outcome.PublicVerdict).
    "MINOR_DOWNGRADE": "downgrade",
    "MEANINGFUL_DOWNGRADE": "downgrade",
    "NOT_VIABLE": "downgrade",
    "POTENTIAL_UPGRADE": "tradeoff",
    "POTENTIAL_DOWNGRADE": "tradeoff",
    "UNCERTAIN": "tradeoff",
    "NOT_EVALUATED": "neutral",
}

VERDICT_COLOR = {
    "upgrade": "#7dcf7d",
    "downgrade": "#d97b7b",
    "tradeoff": "#e0a040",
    "neutral": "#9c9a95",
}

METRIC_DISPLAY = [
    ("primary_offense", "Damage"),
    ("cast_attack_speed", "Cast/Attack Speed"),
    ("ehp", "EHP"),
    ("worst_max_hit", "Max Hit"),
    ("life", "Life"),
    ("energy_shield", "ES"),
    ("fire_res", "Fire Res"),
    ("cold_res", "Cold Res"),
    ("lightning_res", "Lightning Res"),
    ("chaos_res", "Chaos Res"),
    ("movement_speed", "Move Speed"),
]

RARITY_COLOR = {
    "NORMAL": "#c8c8c8",
    "MAGIC": "#8888ff",
    "RARE": "#ffff77",
    "UNIQUE": "#af6025",
}

EMPHASIS_DELTA_COLOR = {
    "critical": {"positive": "#8ee08e", "negative": "#e58b8b", "neutral": "#e0a040"},
    "high": {"positive": "#7dcf7d", "negative": "#d97b7b", "neutral": "#dba748"},
    "medium": {"positive": "#6db86d", "negative": "#c47a7a", "neutral": "#9c9a95"},
    "low": {"positive": "#5a8f5a", "negative": "#a07070", "neutral": "#84827d"},
    "muted": {"positive": "#5a8f5a", "negative": "#8a6a6a", "neutral": "#726f6c"},
}

CAP_STATE_COLOR = {
    "CAP_LOST": "#e58b8b",
    "BELOW_CAP_WORSENED": "#e0a040",
    "BELOW_CAP_IMPROVED": "#7dcf7d",
    "BELOW_CAP_UNCHANGED": "#dba748",
    "CAPPED_STAYS_CAPPED": "#9c9a95",
    "OVER_CAP_REDUCED_BUT_STILL_CAPPED": "#dba748",
    "CAP_REACHED": "#7dcf7d",
    "FURTHER_BELOW_CAP": "#e0a040",
    "STILL_BELOW_CAP": "#dba748",
    "CAP_MAINTAINED": "#9c9a95",
    "CAP_GAINED": "#7dcf7d",
}

PIN_AFFORDANCE_STYLESHEET = """
QWidget#overlayPinControl {
    background: rgba(16, 17, 19, 235);
    border: 1px solid rgba(201, 162, 39, 110);
    border-radius: 13px;
}
QPushButton#pinAffordanceButton {
    background: transparent;
    border: none;
    color: #d0cec8;
    font-family: "Segoe UI", sans-serif;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.2px;
    padding: 0px 2px;
}
QPushButton#pinAffordanceButton:disabled {
    color: #63625e;
}
QPushButton#pinAffordanceButton:hover:enabled {
    color: #f5f3ee;
}
"""

UI_SCALE_CHOICES = (0.8, 1.0, 1.2, 1.4, 1.6)
OVERLAY_COMPACT_WIDTH_BASE = 408
# P1.1b: was 380 (clamped 340-430) -- screenshots with More Info open showed a
# very wide two-column surface (~790px total). The drawer only ever holds text
# lines/short tables, not anything that needs 380px+; narrowed toward the
# clamp's own floor rather than widening every future scale step further.
OVERLAY_DETAIL_WIDTH_BASE = 350
OVERLAY_DETAIL_DIVIDER = 1
_FONT_SIZE_RE = __import__("re").compile(r"font-size:\s*(\d+)px")


def clamp_ui_scale(value: object, default: float = 1.0) -> float:
    try:
        scale = float(value)
    except (TypeError, ValueError):
        return default
    nearest = min(UI_SCALE_CHOICES, key=lambda choice: abs(choice - scale))
    return float(nearest)


def overlay_compact_width(ui_scale: float = 1.0) -> int:
    return max(280, int(round(OVERLAY_COMPACT_WIDTH_BASE * clamp_ui_scale(ui_scale))))


def overlay_detail_width(ui_scale: float = 1.0) -> int:
    scaled = int(round(OVERLAY_DETAIL_WIDTH_BASE * clamp_ui_scale(ui_scale)))
    return max(310, min(400, scaled))


def overlay_stylesheet(ui_scale: float = 1.0) -> str:
    """User UI scale applied to overlay fonts only. Windows DPI is handled separately."""
    scale = clamp_ui_scale(ui_scale)
    sheet = OVERLAY_STYLESHEET
    if abs(scale - 1.0) >= 0.001:

        def _scale_font(match: object) -> str:
            px = int(match.group(1))  # type: ignore[attr-defined]
            return f"font-size: {max(8, int(round(px * scale)))}px"

        sheet = _FONT_SIZE_RE.sub(_scale_font, sheet)
    return sheet + OVERLAY_THEME_INDEPENDENCE_STYLESHEET


def overlay_palette():
    """Fixed Item Check palette so native QLabel painting ignores the OS theme."""
    from PySide6.QtGui import QColor, QPalette

    pal = QPalette()
    transparent = QColor(0, 0, 0, 0)
    primary = QColor(OVERLAY_TEXT_PRIMARY)
    secondary = QColor(OVERLAY_TEXT_SECONDARY)
    emphasis = QColor(OVERLAY_TEXT_EMPHASIS)
    muted = QColor(OVERLAY_TEXT_MUTED)
    action = QColor(OVERLAY_ACTION_TEXT)
    panel = QColor("#161412")

    pal.setColor(QPalette.ColorRole.Window, transparent)
    pal.setColor(QPalette.ColorRole.WindowText, primary)
    pal.setColor(QPalette.ColorRole.Base, panel)
    pal.setColor(QPalette.ColorRole.AlternateBase, panel)
    pal.setColor(QPalette.ColorRole.Text, primary)
    pal.setColor(QPalette.ColorRole.Button, panel)
    pal.setColor(QPalette.ColorRole.ButtonText, action)
    pal.setColor(QPalette.ColorRole.BrightText, emphasis)
    pal.setColor(QPalette.ColorRole.Highlight, QColor(DASHBOARD_ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, emphasis)
    pal.setColor(QPalette.ColorRole.PlaceholderText, muted)
    pal.setColor(QPalette.ColorRole.ToolTipBase, panel)
    pal.setColor(QPalette.ColorRole.ToolTipText, primary)
    pal.setColor(QPalette.ColorRole.Link, QColor(DASHBOARD_ACCENT))
    pal.setColor(QPalette.ColorRole.LinkVisited, QColor(DASHBOARD_ACCENT))

    disabled_roles = (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.PlaceholderText,
    )
    for role in disabled_roles:
        pal.setColor(QPalette.ColorGroup.Disabled, role, muted)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Window, transparent)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, panel)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, panel)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.BrightText, secondary)
    return pal


def apply_overlay_theme(widget, *, fill_background: bool = False) -> None:
    """Apply the Item Check tooltip palette without painting over the gradient chrome."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette

    widget.setPalette(overlay_palette())
    widget.setBackgroundRole(QPalette.ColorRole.Window)
    widget.setForegroundRole(QPalette.ColorRole.WindowText)
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    if fill_background:
        widget.setAutoFillBackground(True)


def exile_lens_palette():
    """Opaque ExileLens palette so native painting ignores Windows Light/Dark."""
    from PySide6.QtGui import QColor, QPalette

    pal = QPalette()
    window = QColor(DASHBOARD_WINDOW_BG)
    text = QColor(DASHBOARD_WINDOW_FG)
    base = QColor(DASHBOARD_INPUT_BG)
    button = QColor(DASHBOARD_BUTTON_BG)
    muted = QColor(DASHBOARD_MUTED_FG)
    disabled = QColor(DASHBOARD_DISABLED_FG)
    highlight = QColor(DASHBOARD_ACCENT)
    input_text = QColor(DASHBOARD_INPUT_FG)
    emphasis = QColor(DASHBOARD_TEXT_EMPHASIS)

    pal.setColor(QPalette.ColorRole.Window, window)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, base)
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(DASHBOARD_NAV_BG))
    pal.setColor(QPalette.ColorRole.Text, input_text)
    pal.setColor(QPalette.ColorRole.Button, button)
    pal.setColor(QPalette.ColorRole.ButtonText, input_text)
    pal.setColor(QPalette.ColorRole.BrightText, emphasis)
    pal.setColor(QPalette.ColorRole.Highlight, highlight)
    pal.setColor(QPalette.ColorRole.HighlightedText, window)
    pal.setColor(QPalette.ColorRole.PlaceholderText, muted)
    pal.setColor(QPalette.ColorRole.ToolTipBase, base)
    pal.setColor(QPalette.ColorRole.ToolTipText, text)
    pal.setColor(QPalette.ColorRole.Light, QColor(DASHBOARD_BUTTON_HOVER))
    pal.setColor(QPalette.ColorRole.Midlight, button)
    pal.setColor(QPalette.ColorRole.Mid, base)
    pal.setColor(QPalette.ColorRole.Dark, window)
    pal.setColor(QPalette.ColorRole.Shadow, QColor("#0c0b0a"))
    pal.setColor(QPalette.ColorRole.Link, highlight)
    pal.setColor(QPalette.ColorRole.LinkVisited, highlight)

    disabled_roles = (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.PlaceholderText,
    )
    for role in disabled_roles:
        pal.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Window, window)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, base)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, button)
    return pal


def apply_exile_lens_chrome(widget, *, fill_background: bool = True) -> None:
    """Apply ExileLens palette so widgets that miss a CSS rule stay dark."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette

    widget.setPalette(exile_lens_palette())
    widget.setBackgroundRole(QPalette.ColorRole.Window)
    widget.setForegroundRole(QPalette.ColorRole.WindowText)
    if fill_background:
        widget.setAutoFillBackground(True)
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)


def apply_scroll_area_theme(scroll, *, viewport_object_name: str | None = None) -> None:
    """Theme a QScrollArea viewport and content instead of the OS palette."""
    apply_exile_lens_chrome(scroll)
    viewport = scroll.viewport()
    if viewport_object_name:
        viewport.setObjectName(viewport_object_name)
    apply_exile_lens_chrome(viewport)
    content = scroll.widget()
    if content is not None:
        apply_exile_lens_chrome(content)

