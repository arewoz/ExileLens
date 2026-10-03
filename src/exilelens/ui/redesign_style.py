"""Stylesheet for the Status Rail dashboard.

Appended *after* the legacy ``DASHBOARD_STYLESHEET`` so pages that were not redesigned
(the parked Market / Tree / Gear pages) keep their look, while every redesigned widget is
styled here. Every rule is scoped under ``QWidget#dashboardRoot`` so it out-ranks the
legacy objectName rules without editing them, and nothing here can reach the Item Check
overlay (which never uses ``dashboardRoot``).

Tokens come from :mod:`exilelens.ui.theme`; no overlay constants are imported.
"""

from __future__ import annotations

from exilelens.ui import theme

_ROOT = "QWidget#dashboardRoot"

_TEMPLATE = """
@ROOT@ {
    background: @BG@;
    color: @TEXT@;
    font-family: @UI_FONT@;
    font-size: 14px;
}
@ROOT@ QLabel { background: transparent; }
@ROOT@ QToolTip {
    background: #2b2c32; color: @TEXT@; border: 1px solid @HAIRLINE_STRONG@;
    padding: 4px 8px; font-size: 12px;
}

/* ---------------- rail ---------------- */
@ROOT@ QWidget#statusRail { background: @RAIL_BG@; border-right: 1px solid @HAIRLINE@; }
@ROOT@ QPushButton#railStatus {
    background: transparent; border: 2px solid transparent; border-radius: @R4@px;
    text-align: left; padding: 0; margin: 0;
}
@ROOT@ QPushButton#railStatus:hover { background: @SURFACE_1@; }
@ROOT@ QPushButton#railStatus:focus { border-color: @FOCUS@; }
@ROOT@ QLabel#railStatusWord { font-size: 12px; font-weight: 600; }
@ROOT@ QLabel#railBuildName { font-size: 14px; font-weight: 600; color: @TEXT@; }
@ROOT@ QLabel#railPobLine { font-size: 12px; color: @TEXT_MUTED@; }
@ROOT@ QFrame#railDivider { background: @HAIRLINE@; border: 0; max-height: 1px; min-height: 1px; }
@ROOT@ QPushButton#railNav {
    background: transparent; color: @TEXT_BODY@; text-align: left;
    border: 2px solid transparent; border-left: 3px solid transparent;
    border-radius: @R4@px; padding: 0 9px; font-size: 14px; font-weight: 500;
}
@ROOT@ QPushButton#railNav:hover { background: @SURFACE_1@; color: @TEXT@; }
@ROOT@ QPushButton#railNav:checked { background: @SURFACE_2@; color: @TEXT@; font-weight: 600; border-left: 3px solid @ACCENT@; }
@ROOT@ QPushButton#railNav:focus { border-color: @FOCUS@; }
@ROOT@ QPushButton#railNav:checked:focus { border-color: @FOCUS@; border-left: 3px solid @ACCENT@; }
@ROOT@ QLabel#railNavCount { color: @WARN@; font-size: 12px; font-weight: 700; }
@ROOT@ QPushButton#railLink, @ROOT@ QPushButton#railSupport {
    background: transparent; color: @TEXT_BODY@; text-align: left;
    border: 2px solid transparent; border-radius: @R4@px; padding: 0 10px; font-size: 13px;
}
@ROOT@ QPushButton#railSupport { color: @TEXT@; font-size: 14px; font-weight: 600; }
@ROOT@ QPushButton#railLink:hover, @ROOT@ QPushButton#railSupport:hover { background: @SURFACE_1@; color: @TEXT@; }
@ROOT@ QPushButton#railLink:focus, @ROOT@ QPushButton#railSupport:focus { border-color: @FOCUS@; }
@ROOT@ QLabel#railVersion { color: @TEXT_MUTED@; font-size: 12px; }
@ROOT@ QPushButton#railUpdate {
    background: transparent; border: 2px solid transparent; border-radius: @R4@px;
    color: @ACCENT@; font-size: 12px; font-weight: 600; padding: 0 4px; text-align: left;
}
@ROOT@ QPushButton#railUpdate:hover { color: @ACCENT_HOVER@; }
@ROOT@ QPushButton#railUpdate:focus { border-color: @FOCUS@; }

/* ---------------- content ---------------- */
@ROOT@ QWidget#contentPane, @ROOT@ QWidget#pageBody, @ROOT@ QWidget#pageColumn, @ROOT@ QStackedWidget { background: @BG@; }
@ROOT@ QWidget#pageHeader { background: @BG@; border-bottom: 1px solid @HAIRLINE@; }
@ROOT@ QLabel#pageTitle { font-size: 20px; font-weight: 600; color: @TEXT@; }
@ROOT@ QLabel#pageSubtitle { font-size: 13px; color: @TEXT_MUTED@; }
@ROOT@ QLabel#sectionHeading { font-size: 15px; font-weight: 600; color: @TEXT@; }
@ROOT@ QLabel#sectionTitle { font-size: 15px; font-weight: 600; color: @TEXT@; }
@ROOT@ QLabel#helperText { color: @TEXT_MUTED@; font-size: 13px; }
@ROOT@ QLabel#secondaryText { color: @TEXT_MUTED@; font-size: 13px; }
@ROOT@ QLabel#bodyText { color: @TEXT_BODY@; font-size: 14px; }
@ROOT@ QLabel#fieldLabel { color: @TEXT@; font-size: 14px; font-weight: 500; }
@ROOT@ QLabel#monoText { color: @TEXT_MUTED@; font-family: @MONO_FONT@; font-size: 12px; }
@ROOT@ QLabel#statusOk { color: @OK@; font-weight: 600; }
@ROOT@ QLabel#statusWarn { color: @WARN@; font-weight: 600; }
@ROOT@ QLabel#statusError { color: @ERROR@; font-weight: 600; }
@ROOT@ QLabel#statusNeutral { color: @TEXT_BODY@; font-weight: 600; }
@ROOT@ QLabel#buildName { font-family: @BUILD_FONT@; font-size: 28px; font-weight: 600; color: @TEXT@; }
@ROOT@ QLabel#headline { font-size: 24px; font-weight: 600; color: @TEXT@; }
@ROOT@ QLabel#focusHeadline { font-size: 22px; font-weight: 600; color: @TEXT@; }
@ROOT@ QLabel#leadText { font-size: 14px; color: @TEXT_BODY@; }
@ROOT@ QLabel#keycap {
    background: @SURFACE_3@; color: @TEXT@; border: 1px solid @HAIRLINE_STRONG@; border-bottom: 2px solid @HAIRLINE_STRONG@;
    border-radius: @R4@px; padding: 0 9px; font-size: 12px; font-weight: 600; min-height: 24px;
}
@ROOT@ QFrame#hairline { background: @HAIRLINE@; border: 0; min-height: 1px; max-height: 1px; }

/* rows */
@ROOT@ QWidget#rowGroup { border-top: 1px solid @HAIRLINE@; background: transparent; }
@ROOT@ QWidget#settingsRow { border-bottom: 1px solid @HAIRLINE@; background: transparent; }
@ROOT@ QWidget#settingsRow[disabledRow="true"] QLabel#fieldLabel { color: @TEXT_MUTED@; }
@ROOT@ QWidget#healthRowGrid { border-bottom: 1px solid @HAIRLINE@; background: transparent; }
@ROOT@ QWidget#healthRowGrid[problem="true"] { background: rgba(255,255,255,7); }
@ROOT@ QLabel#healthLabel { color: @TEXT_BODY@; font-weight: 500; }
@ROOT@ QLabel#healthValue { color: @TEXT@; font-weight: 500; }
@ROOT@ QLabel#healthValue[problem="true"] { font-weight: 600; }
@ROOT@ QLabel#healthDetail { color: @TEXT_MUTED@; font-size: 13px; }

@ROOT@ QLabel#measureLead { color: @TEXT_MUTED@; font-weight: 500; }
@ROOT@ QLabel#measureValue { color: @TEXT@; font-weight: 600; }
@ROOT@ QLabel#measureValue[tone="ok"] { color: @OK@; }
@ROOT@ QLabel#measureValue[tone="warn"] { color: @WARN@; font-weight: 500; }
@ROOT@ QLabel#measureValue[tone="muted"] { color: @TEXT_MUTED@; font-weight: 400; }
@ROOT@ QLabel#boldValue { color: @TEXT@; font-weight: 500; }

/* notices: tinted only when they ask for action */
@ROOT@ QWidget#notice { border: 1px solid @HAIRLINE_STRONG@; border-radius: @R4@px; background: @SURFACE_1@; }
@ROOT@ QWidget#notice[tone="warn"] { background: @WARN_TINT@; border-color: @WARN_LINE@; }
@ROOT@ QWidget#notice[tone="error"] { background: @ERROR_TINT@; border-color: @ERROR_LINE@; }
@ROOT@ QWidget#notice[tone="info"] { background: @INFO_TINT@; border-color: @INFO_LINE@; }
@ROOT@ QWidget#consentCard { background: @SURFACE_1@; border: 1px solid @HAIRLINE@; border-radius: @R6@px; }
@ROOT@ QWidget#consentCard QLabel#cardTitle { font-size: 14px; font-weight: 600; }
@ROOT@ QWidget#updateNotice { background: @INFO_TINT@; border: 1px solid @INFO_LINE@; border-radius: @R4@px; }

/* buttons */
@ROOT@ QPushButton#btnPrimary, @ROOT@ QPushButton#btnSecondary, @ROOT@ QPushButton#btnTertiary,
@ROOT@ QPushButton#btnDestructive, @ROOT@ QPushButton#btnBranded {
    min-height: @CONTROL_H@px; padding: 0 14px; border-radius: @R4@px; border: 1px solid transparent;
    font-size: 13px; font-weight: 600; background: transparent; color: @TEXT@;
}
@ROOT@ QPushButton#btnPrimary { background: @ACCENT@; color: @ON_ACCENT@; border-color: @ACCENT@; }
@ROOT@ QPushButton#btnPrimary:hover { background: @ACCENT_HOVER@; border-color: @ACCENT_HOVER@; }
@ROOT@ QPushButton#btnPrimary:disabled { background: @SURFACE_2@; color: @TEXT_DISABLED@; border-color: @HAIRLINE@; }
@ROOT@ QPushButton#btnSecondary, @ROOT@ QPushButton#btnBranded { background: @SURFACE_2@; border-color: @HAIRLINE_STRONG@; }
@ROOT@ QPushButton#btnSecondary:hover, @ROOT@ QPushButton#btnBranded:hover { background: @SURFACE_3@; }
@ROOT@ QPushButton#btnSecondary:disabled, @ROOT@ QPushButton#btnBranded:disabled { color: @TEXT_DISABLED@; border-color: @HAIRLINE@; }
@ROOT@ QPushButton#btnTertiary { color: @TEXT_BODY@; padding: 0 10px; }
@ROOT@ QPushButton#btnTertiary:hover { background: @SURFACE_2@; color: @TEXT@; }
@ROOT@ QPushButton#btnTertiary:disabled { color: @TEXT_DISABLED@; }
@ROOT@ QPushButton#btnDestructive { color: #f3a7a0; border-color: rgba(239,128,119,115); }
@ROOT@ QPushButton#btnDestructive:hover { background: @ERROR_TINT@; }
@ROOT@ QPushButton[compact="true"] { min-height: @CONTROL_HC@px; padding: 0 12px; }
@ROOT@ QPushButton#btnTertiary[compact="true"] { padding: 0 8px; }
@ROOT@ QPushButton#btnPrimary:focus, @ROOT@ QPushButton#btnSecondary:focus, @ROOT@ QPushButton#btnTertiary:focus,
@ROOT@ QPushButton#btnDestructive:focus, @ROOT@ QPushButton#btnBranded:focus, @ROOT@ QPushButton#linkButton:focus { border: 2px solid @FOCUS@; }
@ROOT@ QPushButton#linkButton {
    background: transparent; border: 2px solid transparent; color: @TEXT@; font-size: 13px; font-weight: 500;
    padding: 0 2px; text-align: left; border-radius: @R4@px;
}
@ROOT@ QPushButton#linkButton:hover { color: #ffffff; }

/* segmented control */
@ROOT@ QWidget#segmentGroup { background: @WELL@; border: 1px solid @HAIRLINE@; border-radius: 5px; }
@ROOT@ QPushButton#segmentButton {
    background: transparent; border: 1px solid transparent; border-radius: 3px; color: @TEXT_BODY@;
    font-size: 13px; font-weight: 500; padding: 0 14px;
}
@ROOT@ QPushButton#segmentButton:hover { color: @TEXT@; }
@ROOT@ QPushButton#segmentButton:checked { background: @SURFACE_3@; color: @TEXT@; font-weight: 600; border: 1px solid @HAIRLINE_STRONG@; }
@ROOT@ QPushButton#segmentButton:focus { border: 2px solid @FOCUS@; }

/* inputs */
@ROOT@ QComboBox, @ROOT@ QLineEdit, @ROOT@ QPlainTextEdit, @ROOT@ QTextEdit {
    background: @WELL@; color: @TEXT@; border: 1px solid @HAIRLINE_STRONG@; border-radius: @R4@px;
    padding: 0 10px 0 12px; min-height: @CONTROL_H@px; font-size: 13px; selection-background-color: @SURFACE_3@;
}
@ROOT@ QPlainTextEdit, @ROOT@ QTextEdit { padding: 8px 12px; min-height: 0; }
@ROOT@ QComboBox:focus, @ROOT@ QLineEdit:focus, @ROOT@ QPlainTextEdit:focus, @ROOT@ QTextEdit:focus { border: 2px solid @FOCUS@; }
@ROOT@ QComboBox::drop-down { border: 0; width: 28px; }
@ROOT@ QComboBox::down-arrow { image: none; }
@ROOT@ QComboBox QAbstractItemView { background: @SURFACE_1@; color: @TEXT@; border: 1px solid @HAIRLINE_STRONG@; selection-background-color: @SURFACE_3@; outline: 0; }

/* disclosure */
@ROOT@ QToolButton#disclosureToggle {
    background: transparent; border: 2px solid transparent; border-radius: @R4@px; color: @TEXT@;
    font-size: 14px; font-weight: 500; padding: 4px 4px;
}
@ROOT@ QToolButton#disclosureToggle:hover { background: @SURFACE_1@; }
@ROOT@ QToolButton#disclosureToggle:focus { border-color: @FOCUS@; }

/* analysis lists */
@ROOT@ QListWidget {
    background: transparent; border: 0; outline: 0; color: @TEXT_BODY@; font-size: 13px;
}
@ROOT@ QListWidget::item { padding: 6px 10px; border-radius: @R4@px; }
@ROOT@ QListWidget::item:hover { background: @SURFACE_1@; }
@ROOT@ QListWidget::item:selected { background: @SURFACE_2@; color: @TEXT@; }
@ROOT@ QSplitter::handle { background: @HAIRLINE@; width: 1px; }

/* scrollbars: thin, quiet */
@ROOT@ QScrollArea { background: transparent; border: 0; }
/* the border carries the focus ring; suppress the style's own inner focus rectangle */
@ROOT@ QPushButton, @ROOT@ QToolButton, @ROOT@ QComboBox, @ROOT@ QAbstractItemView { outline: none; }
@ROOT@ QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
@ROOT@ QScrollBar::handle:vertical { background: rgba(255,255,255,40); border-radius: 3px; min-height: 28px; margin: 0 2px; }
@ROOT@ QScrollBar::handle:vertical:disabled { background: transparent; }
@ROOT@ QScrollBar::handle:vertical:hover { background: rgba(255,255,255,70); }
@ROOT@ QScrollBar::add-line:vertical, @ROOT@ QScrollBar::sub-line:vertical { height: 0; }
@ROOT@ QScrollBar::add-page:vertical, @ROOT@ QScrollBar::sub-page:vertical { background: transparent; }
@ROOT@ QScrollBar:horizontal { height: 0; }

/* progress */
@ROOT@ QProgressBar#thinProgress { background: @SURFACE_3@; border: 0; border-radius: 2px; max-height: 4px; min-height: 4px; text-align: center; color: transparent; }
@ROOT@ QProgressBar#thinProgress::chunk { background: @ACCENT@; border-radius: 2px; }
"""


def build_stylesheet() -> str:
    tokens = {
        "ROOT": _ROOT,
        "BG": theme.BG, "RAIL_BG": theme.RAIL_BG, "SURFACE_1": theme.SURFACE_1, "SURFACE_2": theme.SURFACE_2,
        "SURFACE_3": theme.SURFACE_3, "WELL": theme.WELL,
        "TEXT": theme.TEXT, "TEXT_BODY": theme.TEXT_BODY, "TEXT_MUTED": theme.TEXT_MUTED, "TEXT_DISABLED": theme.TEXT_DISABLED,
        "ACCENT": theme.ACCENT, "ACCENT_HOVER": theme.ACCENT_HOVER, "ON_ACCENT": theme.ON_ACCENT, "FOCUS": theme.FOCUS,
        "OK": theme.OK, "WARN": theme.WARN, "ERROR": theme.ERROR,
        "HAIRLINE": theme.HAIRLINE, "HAIRLINE_STRONG": theme.HAIRLINE_STRONG,
        "WARN_TINT": theme.WARN_TINT, "WARN_LINE": theme.WARN_LINE, "ERROR_TINT": theme.ERROR_TINT,
        "ERROR_LINE": theme.ERROR_LINE, "INFO_TINT": theme.INFO_TINT, "INFO_LINE": theme.INFO_LINE,
        "R4": str(theme.RADIUS_SM), "R6": str(theme.RADIUS_MD),
        "CONTROL_H": str(theme.CONTROL_HEIGHT), "CONTROL_HC": str(theme.CONTROL_HEIGHT_COMPACT),
        "UI_FONT": theme.UI_FONT_FAMILY, "BUILD_FONT": theme.BUILD_NAME_FONT_FAMILY, "MONO_FONT": theme.MONO_FONT_FAMILY,
    }
    out = _TEMPLATE
    # Longest names first so ``CONTROL_HC`` is not eaten by ``CONTROL_H``.
    for key in sorted(tokens, key=len, reverse=True):
        out = out.replace(f"@{key}@", tokens[key])
    return out


REDESIGN_STYLESHEET = build_stylesheet()
