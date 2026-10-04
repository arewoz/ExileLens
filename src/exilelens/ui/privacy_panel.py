"""Privacy UI: the Settings section, the one-time dashboard card and the transparency dialog.

All logic lives in ``exilelens.cloud.consent``; this module only presents it with the
existing components. Turning a switch on or off takes effect immediately (and off deletes the queue and ID).
"""

from __future__ import annotations

import time

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from exilelens.cloud import consent, hooks
from exilelens.ui.components import ThemedCheckBox, make_button, make_link_button
from exilelens.ui.dashboard_widgets import SettingsGroup, SettingsRow, ThemedSwitch
from exilelens.ui.info_dialog import InfoDialog

USAGE_LABEL = "Send privacy-friendly usage stats"
ERRORS_LABEL = "Send crash and error reports"
SEE_COLLECTED = "See what is collected"
OFF_NOTE = "Turning either off deletes its queued data and ID."
ERRORS_SHORT = "Error code, component, exception type and module names. Never messages, paths or item data."
USAGE_SHORT = "App starts, setup, result categories, speed buckets and update outcomes. Never items, builds or files."
UNAVAILABLE_NOTE = "Not available in this build — nothing is collected or sent."


def _label(text: str, name: str = "helperText") -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(True)
    return widget


#: What each contract usage event is summarised as. The summary is deliberately short; this map exists so that a
#: new event in ``events.v1.json`` fails a test until someone decides how the summary should mention it.
USAGE_TOPICS = {
    "app_started": "start",
    "onboarding_completed": "start",
    "pob_connected": "start",
    "item_checks_summary": "counts",
    "analyze_build_completed": "counts",
    "update_detected": "update",
    "update_download_completed": "update",
    "update_install_completed": "update",
}
USAGE_BULLETS = {
    "start": "App starts, setup, and whether Path of Building starts",
    "counts": "Counts of item checks and build analyses, with speed ranges",
    "update": "Update outcomes",
}
ERROR_BULLETS = (
    "Registered error codes, component and exception type",
    "Module and function names where it happened, and the Path of Building version",
)
#: One short line per entry of the contract's ``never_collected`` list, in the same order.
NEVER_BULLETS = (
    "Item or clipboard contents",
    "Builds, characters, skills or equipment",
    "Trade searches or prices",
    "File paths, logs or settings",
    "IP addresses (not stored; the host still sees them in any web request)",
    "Hardware, accounts, email or Patreon identity",
)
COLLECTED_TITLE = "What ExileLens collects"
COLLECTED_INTRO = "Both options are off by default and work independently."
ERRORS_NOT_SENT = "Error messages, stack traces and file paths are not sent."
CLOSING_NOTE = (
    "Each option has its own random ID, created only when you turn it on. Uploads include the ExileLens version, "
    "release type and Windows version. Turn either off at any time; its queued data and ID are deleted."
)
FULL_PRIVACY = "Full privacy details"


class CollectedDialog(InfoDialog):
    """What can be sent, what never is, that it is optional and how to control it. One short page, no schemas."""

    def __init__(self, cloud=None, parent: QWidget | None = None) -> None:
        from exilelens.ui.recovery_actions import open_privacy_details

        super().__init__(
            COLLECTED_TITLE,
            COLLECTED_INTRO,
            link_text=FULL_PRIVACY,
            link_icon="github",
            on_link=open_privacy_details,
            parent=parent,
        )
        self.add_section("Usage statistics", bullets=tuple(USAGE_BULLETS.values()))
        self.add_section("Crash and error reports", bullets=ERROR_BULLETS, note=ERRORS_NOT_SENT)
        self.add_section("Never collected", bullets=NEVER_BULLETS)
        self.add_note(CLOSING_NOTE)


def open_collected_dialog(parent: QWidget | None = None, cloud=None) -> None:
    CollectedDialog(cloud if cloud is not None else hooks.get(), parent).exec()


def category_summary(key: str) -> str:
    """The one-line summary of a consent category, straight from the canonical contract.

    ``events.v1.json`` is what the Worker validates against and what the transparency dialog
    renders, so the Settings and consent-card text cannot drift from what is collected.
    """
    try:
        from exilelens.cloud import contract

        return str(contract.schema()["categories"][key]["summary"])
    except Exception:  # noqa: BLE001 - never break Settings over a summary line
        return ""


class PrivacyPanel(QWidget):
    """Settings → Privacy: two independent switches, the off-note and the transparency button."""

    INTRO = ""

    def __init__(self, settings, cloud=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.cloud = cloud if cloud is not None else hooks.get()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.errors_box = ThemedSwitch(ERRORS_LABEL)
        self.usage_box = ThemedSwitch(USAGE_LABEL)
        self.see_button = make_button(SEE_COLLECTED, "secondary", compact=True)
        self.see_button.clicked.connect(lambda: open_collected_dialog(self, self.cloud))

        self.group = SettingsGroup()
        self.errors_row = SettingsRow(ERRORS_LABEL, ERRORS_SHORT)
        self.errors_row.setToolTip(category_summary("errors"))  # the contract wording, in full
        self.errors_row.add_control(self.errors_box)
        self.usage_row = SettingsRow(USAGE_LABEL, USAGE_SHORT)
        self.usage_row.setToolTip(category_summary("usage"))
        self.usage_row.add_control(self.usage_box)
        self.note_row = SettingsRow("", OFF_NOTE)
        self.note_row.add_control(self.see_button)
        for row in (self.errors_row, self.usage_row, self.note_row):
            self.group.add_row(row)
        layout.addWidget(self.group)
        self.note = self.note_row.helper
        self.status = _label("", "secondaryText")
        self.status.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(self.status)
        self.errors_box.toggled.connect(lambda on: self._changed(errors=on))
        self.usage_box.toggled.connect(lambda on: self._changed(usage=on))
        self.refresh()

    def available(self) -> bool:
        return self.cloud is not None and self.cloud.configured()

    def refresh(self) -> None:
        """Re-sync from settings (e.g. after Reset configuration)."""
        for box, value in (
            (self.errors_box, consent_value(self.settings, "errors")),
            (self.usage_box, consent_value(self.settings, "usage")),
        ):
            with QSignalBlocker(box):
                box.setChecked(value)
            box.setEnabled(self.available())
        self.note_row.set_helper(OFF_NOTE if self.available() else UNAVAILABLE_NOTE)
        self._update_status()

    def _changed(self, *, usage: bool | None = None, errors: bool | None = None) -> None:
        consent.set_consent(self.settings, usage=usage, errors=errors, cloud=self.cloud)
        self._update_status()

    def _update_status(self) -> None:
        if not self.available() or self.cloud is None:
            self.status.setText("")
            self.status.setVisible(False)
            return
        status = self.cloud.status()
        parts = []
        for key, title in (("errors", "Error reports"), ("usage", "Usage stats")):
            info = status[key]
            if info["active"]:
                text = f"{title}: on, {info['queued']} waiting"
                if info.get("disabled"):
                    text = f"{title}: paused (this version is no longer supported by the service)"
                elif info.get("last_attempt"):
                    text += f", last upload {time.strftime('%H:%M', time.localtime(info['last_attempt']))}"
                parts.append(text)
        self.status.setText(" · ".join(parts))
        self.status.setVisible(bool(parts))


def consent_value(settings, category: str) -> bool:
    from exilelens.cloud.service import effective_consent

    return effective_consent(settings, category)


class ConsentCard(QFrame):
    """The one-time, non-modal card shown after onboarding. Both boxes start unchecked.

    The only card-like surface on the dashboard, because it is a temporary decision. Save is
    a secondary button so it never competes with the page's primary action.
    """

    def __init__(self, settings, cloud, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("consentCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.settings = settings
        self.cloud = cloud
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(2)
        layout.addWidget(_label("Help improve ExileLens?", "cardTitle"))
        body = _label(
            "Optional. Both are off unless you turn them on, and ExileLens works the same either way. "
            "Nothing from your items, builds or files is ever sent.",
            "helperText",
        )
        body.setMaximumWidth(600)
        layout.addWidget(body)
        self.errors_box = ThemedCheckBox(ERRORS_LABEL)
        self.usage_box = ThemedCheckBox(USAGE_LABEL)
        self.errors_box.setChecked(False)
        self.usage_box.setChecked(False)
        boxes = QHBoxLayout()
        boxes.setContentsMargins(0, 12, 0, 0)
        boxes.setSpacing(28)
        boxes.addWidget(self.errors_box)
        boxes.addWidget(self.usage_box)
        boxes.addStretch(1)
        layout.addLayout(boxes)
        self.save_button = make_button("Save", "secondary", compact=True)
        self.later_button = make_button("Not now", "tertiary", compact=True)
        self.see_button = make_link_button(SEE_COLLECTED)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 14, 0, 0)
        actions.setSpacing(10)
        actions.addWidget(self.save_button)
        actions.addWidget(self.later_button)
        actions.addSpacing(6)
        actions.addWidget(self.see_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.save_button.clicked.connect(self._save)
        self.later_button.clicked.connect(self._later)
        self.see_button.clicked.connect(lambda: open_collected_dialog(self, self.cloud))

    def _save(self) -> None:
        consent.set_consent(self.settings, usage=self.usage_box.isChecked(), errors=self.errors_box.isChecked(), cloud=self.cloud)
        self.hide()
        self.deleteLater()

    def _later(self) -> None:
        consent.dismiss_card(self.settings)
        self.hide()
        self.deleteLater()


__all__ = ["CollectedDialog", "ConsentCard", "PrivacyPanel", "open_collected_dialog"]
