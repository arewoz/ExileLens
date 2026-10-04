"""The ExileLens information dialog shell.

One native dark dialog, about 560 px wide: a fixed header (title and an optional one-line muted intro), a body that
scrolls only when it has to, and a fixed footer with an optional secondary link on the left and a default **Close**
button on the right. No tabs, no cards per section, no nested boxes: short sections with concise headings.

``CollectedDialog`` ("What ExileLens collects") and ``WhatsNewDialog`` are built on it, so the two share one visual
language instead of growing two.

The dialog is styled by ``redesign_style`` (rules scoped under the dashboard root), so give it the dashboard window
or one of its widgets as parent.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from exilelens.branding import app_icon
from exilelens.platform.windows.dark_titlebar import apply_dark_title_bar
from exilelens.ui import theme
from exilelens.ui.components import make_button
from exilelens.ui.dashboard_widgets import Hairline, WrapLabel, set_property

DIALOG_WIDTH = 560
MAX_HEIGHT_SHARE = 0.8   # of the app window (a short page should fit at the default 980 x 720 without scrolling): the dialog never takes over the screen it was opened from


class InfoDialog(QDialog):
    """Fixed header, scrolling body, fixed footer. Esc, the title-bar close button and **Close** all dismiss it."""

    max_height_share = MAX_HEIGHT_SHARE

    def __init__(
        self,
        title: str,
        meta: str = "",
        *,
        close_text: str = "Close",
        link_text: str = "",
        link_icon: str = "",
        on_link: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("infoDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setSizeGripEnabled(False)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        icon = app_icon()
        if icon is not None:
            self.setWindowIcon(icon)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- header (fixed) ---------------------------------------------------------------------
        self._header = QWidget()
        self._header.setObjectName("infoHeader")
        self._header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header = QVBoxLayout(self._header)
        header.setContentsMargins(24, 18, 24, 12)
        header.setSpacing(3)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("infoTitle")
        self.title_label.setAccessibleName(title)
        header.addWidget(self.title_label)
        self.meta_label = WrapLabel(meta)
        self.meta_label.setObjectName("infoMeta")
        self.meta_label.setVisible(bool(meta))
        header.addWidget(self.meta_label)
        root.addWidget(self._header)

        # --- body (the only part that scrolls) ------------------------------------------------------
        self._scroll = QScrollArea()
        self._scroll.setObjectName("infoScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setAccessibleName(title)
        self._body = QWidget()
        self._body.setObjectName("infoBody")
        self.body = QVBoxLayout(self._body)
        self.body.setContentsMargins(24, 0, 24, 18)
        self.body.setSpacing(0)
        self._scroll.setWidget(self._body)
        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        root.addWidget(self._scroll, 1)

        # --- footer (fixed) ---------------------------------------------------------------------
        self._footer = QWidget()
        self._footer.setObjectName("infoFooter")
        self._footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        footer = QHBoxLayout(self._footer)
        footer.setContentsMargins(24, 12, 24, 12)
        footer.setSpacing(16)
        self.link_button = None
        if link_text:
            self.link_button = make_button(link_text, "tertiary", compact=True, icon=link_icon)
            if on_link is not None:
                self.link_button.clicked.connect(lambda _c=False: on_link())
            footer.addWidget(self.link_button, 0, Qt.AlignmentFlag.AlignVCenter)
        footer.addStretch(1)
        self.close_button = make_button(close_text, "primary", compact=True)
        self.close_button.setDefault(True)
        self.close_button.setAutoDefault(True)
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self._footer)

    # --- body building -----------------------------------------------------------------------

    def add_section(self, heading: str, *, intro: str = "", bullets: tuple[str, ...] = (), note: str = "") -> None:
        """A concise heading, an optional lead-in line, bullets and a muted one-line note. Hairline above all but the first."""
        if self.body.count():
            rule = Hairline()
            self.body.addSpacing(10)
            self.body.addWidget(rule)
            self.body.addSpacing(10)
        title = QLabel(heading)
        title.setObjectName("infoHeading")
        self.body.addWidget(title)
        if intro:
            lead = WrapLabel(intro)
            lead.setObjectName("infoItem")
            lead.setContentsMargins(0, 2, 0, 0)
            self.body.addWidget(lead)
        for text in bullets:
            self.body.addLayout(self._bullet(text))
        if note:
            muted = WrapLabel(note)
            muted.setObjectName("infoNote")
            muted.setContentsMargins(0, 4, 0, 0)
            self.body.addWidget(muted)

    def add_note(self, text: str) -> None:
        """A closing line under a hairline (no heading)."""
        self.body.addSpacing(12)
        self.body.addWidget(Hairline())
        self.body.addSpacing(10)
        note = WrapLabel(text)
        note.setObjectName("infoNote")
        self.body.addWidget(note)

    @staticmethod
    def _bullet(text: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(2, 2, 0, 0)
        row.setSpacing(8)
        mark = QLabel("•")
        mark.setObjectName("infoItem")
        mark.setFixedWidth(10)
        mark.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        mark.setAccessibleName("")
        label = WrapLabel(text)
        label.setObjectName("infoItem")
        row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(label, 1)
        return row

    def visible_text(self) -> str:
        """Every word the dialog shows (title, intro, body, footer), for copy-density checks."""
        parts = [self.windowTitle(), self.meta_label.text()]
        for label in self._body.findChildren(QLabel):
            if label.text() and label.text() != "•":
                parts.append(label.text())
        parts.extend(b.text() for b in self._footer.findChildren(type(self.close_button)) if b.text())
        return " ".join(p for p in parts if p)

    # --- sizing ------------------------------------------------------------------------------

    def _on_scrolled(self, value: int) -> None:
        # The hairline under the header appears only once the body has scrolled: a dialog that fits has no
        # divider except the one above the footer.
        set_property(self._header, "scrolled", value > 0)

    def fit_to_content(self) -> None:
        """Width ~560 (scaled with the Windows text size); height to the content, capped at 75% of the app window."""
        parent = self.parentWidget().window() if self.parentWidget() is not None else None
        screen = (parent.screen() if parent is not None else QApplication.primaryScreen()).availableGeometry()
        width = min(theme.scaled_px(DIALOG_WIDTH), int(screen.width() * 0.92))
        reference = parent.height() if parent is not None and parent.height() > 0 else screen.height()
        cap = min(int(reference * self.max_height_share), int(screen.height() * 0.92))
        inner = width - 48
        body_height = self.body.totalHeightForWidth(inner)           # both include their own margins
        header_height = self._header.layout().totalHeightForWidth(inner)
        footer_height = self._footer.sizeHint().height()
        wanted = header_height + body_height + footer_height + 2
        self.setFixedSize(width, max(theme.scaled_px(260), min(wanted, cap)))

    def showEvent(self, event) -> None:  # noqa: N802
        self.fit_to_content()
        super().showEvent(event)
        apply_dark_title_bar(int(self.winId()))
        self.close_button.setFocus(Qt.FocusReason.OtherFocusReason)   # opens with Close focused: Enter dismisses
