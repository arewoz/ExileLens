"""The What's New dialog: a release summary on the shared :class:`~exilelens.ui.info_dialog.InfoDialog` shell.

It only presents a :class:`~exilelens.whats_new.content.Summary`. Whether it is due, and whether the release counts
as seen, are decided elsewhere: this dialog reports a normal dismissal (Done, Enter, Esc, the title-bar close button,
or a highlight link that navigates) through ``on_dismissed`` and never before then.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from exilelens.ui.components import make_link_button
from exilelens.ui.dashboard_widgets import Hairline, Notice, WrapLabel
from exilelens.ui.info_dialog import InfoDialog
from exilelens.whats_new.content import Link, Summary

FULL_NOTES = "Full release notes"
FULL_NOTES_ACCESSIBLE = "Full release notes, opens GitHub in your browser"
SMALLER_HEADING = "Fixes and smaller improvements"
LIMITATIONS_HEADING = "Known limitations"
ACTION_LEAD = "One thing to check."


class WhatsNewDialog(InfoDialog):
    """Fixed header and footer, scrolling body. ``Full release notes`` opens GitHub and leaves the dialog open."""

    max_height_share = 0.75

    def __init__(
        self,
        summary: Summary,
        *,
        on_dismissed: Callable[[str | None], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            summary.title,
            summary.meta,
            close_text="Done",
            link_text=FULL_NOTES,
            link_icon="github",
            on_link=self.open_full_notes,
            parent=parent,
        )
        self.setObjectName("infoDialog")
        self.summary = summary
        self._on_dismissed = on_dismissed
        self._destination: str | None = None
        self._dismissed = False
        self.opened_urls: list[str] = []
        self.setAccessibleName(summary.title)
        self.setAccessibleDescription(summary.meta)
        if self.link_button is not None:
            self.link_button.setAccessibleName(FULL_NOTES_ACCESSIBLE)
            self.link_button.setToolTip("Open the release page on GitHub")
        self.close_button.setAccessibleName("Done")
        # The body is a keyboard stop (arrows, Page Up/Down, Home/End scroll it); the ring shows for keyboard focus only.
        self._scroll.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.links: list[QPushButton] = []
        self._build(summary)
        self._arrange_tab_order()

    # --- body --------------------------------------------------------------------------------

    def _build(self, summary: Summary) -> None:
        if summary.action is not None:
            self._add_action(summary.action.text, summary.action.link)
        for index, item in enumerate(summary.highlights):
            self._add_highlight(item.title, item.text, item.link, item.since, first=index == 0 and summary.action is None)
        if summary.minor:
            self._add_list(SMALLER_HEADING, summary.minor)
        if summary.limitations:
            self._add_list(LIMITATIONS_HEADING, summary.limitations)
        if summary.note:
            self.add_note(summary.note)
        self.body.addStretch(1)

    def _rule(self) -> None:
        self.body.addSpacing(12)
        self.body.addWidget(Hairline())
        self.body.addSpacing(12)

    def _add_action(self, text: str, link: Link | None) -> None:
        self.body.addSpacing(2)
        notice = Notice(f"<b>{ACTION_LEAD}</b> {_escape(text)}", "warn")
        notice.setObjectName("notice")
        notice.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.body.addWidget(notice)
        if link is not None:
            self._add_link(link)
        self.body.addSpacing(4)

    def _add_highlight(self, title: str, text: str, link: Link | None, since: str, *, first: bool) -> None:
        if not first:
            self._rule()
        else:
            self.body.addSpacing(4)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("whatsNewHeadline")
        heading.setWordWrap(True)
        head.addWidget(heading, 1, Qt.AlignmentFlag.AlignTop)
        if since:
            arrived = QLabel(since)
            arrived.setObjectName("whatsNewSince")
            arrived.setAccessibleName(f"Arrived in {since}")
            head.addWidget(arrived, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        self.body.addLayout(head)
        sentence = WrapLabel(text)
        sentence.setObjectName("whatsNewText")
        sentence.setContentsMargins(0, 2, 0, 0)
        self.body.addWidget(sentence)
        if link is not None:
            self._add_link(link)

    def _add_list(self, heading: str, items: tuple[str, ...]) -> None:
        if self.body.count():
            self._rule()
        else:
            self.body.addSpacing(4)
        label = QLabel(heading)
        label.setObjectName("whatsNewListHeading")
        self.body.addWidget(label)
        for text in items:
            self.body.addLayout(self._bullet(text))

    def _add_link(self, link: Link) -> None:
        self.body.addSpacing(4)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addSpacing(-4)   # the link's 2px border + 2px padding would otherwise indent its text
        row.addWidget(self._link_button(link))
        row.addStretch(1)
        self.body.addLayout(row)

    def _link_button(self, link: Link) -> QPushButton:
        button = make_link_button(link.label)
        button.clicked.connect(lambda _c=False, dest=link.destination: self.navigate_to(dest))
        self.links.append(button)
        return button

    def _arrange_tab_order(self) -> None:
        """Body, then any link, then Full release notes, then Done."""
        chain = [self._scroll, *self.links]
        if self.link_button is not None:
            chain.append(self.link_button)
        chain.append(self.close_button)
        for first, second in zip(chain, chain[1:]):
            self.setTabOrder(first, second)

    # --- actions -----------------------------------------------------------------------------

    def open_full_notes(self) -> None:
        """The exact GitHub Release page of the installed version. The dialog stays open and nothing is marked seen."""
        url = self.summary.github_url
        if not url:
            return
        self.opened_urls.append(url)
        QDesktopServices.openUrl(QUrl(url))

    def navigate_to(self, destination: str) -> None:
        """Close the dialog as a normal dismissal, then let the owner navigate."""
        self._destination = destination
        self.accept()

    def done(self, result: int) -> None:
        # Done, Enter, Esc and the title-bar close button all end here, exactly once.
        super().done(result)
        if self._dismissed:
            return
        self._dismissed = True
        if self._on_dismissed is not None:
            self._on_dismissed(self._destination)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
