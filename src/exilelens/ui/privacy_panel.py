"""Privacy UI: the Settings section, the one-time dashboard card and the transparency dialog.

All logic lives in ``exilelens.cloud.consent`` / ``transparency``; this module only presents it with the
existing components. Turning a switch on or off takes effect immediately (and off deletes the queue and ID).
"""

from __future__ import annotations

import time

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from exilelens.cloud import consent, hooks, transparency
from exilelens.ui import theme
from exilelens.ui.components import ThemedCheckBox, button_row, make_button, make_link_button
from exilelens.ui.dashboard_widgets import SettingsGroup, SettingsRow, ThemedSwitch

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


class CollectedDialog(QDialog):
    """What is collected, which identifiers exist and what is never collected (generated from the contract)."""

    def __init__(self, cloud=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(SEE_COLLECTED)
        self.setMinimumSize(560, 520)
        model = transparency.describe(cloud)
        layout = QVBoxLayout(self)
        layout.addWidget(
            _label(
                "ExileLens works fully without any of this. Both switches are off by default and independent. "
                "Reports are pseudonymous (a random ID), not anonymous — see the identifiers below."
            )
        )
        tabs = QTabWidget()
        for category in model["categories"]:
            tabs.addTab(self._category_tab(category), category["title"])
        tabs.addTab(self._never_tab(model), "Never collected")
        layout.addWidget(tabs, 1)
        layout.addLayout(button_row([self._close_button()]))

    def _close_button(self):
        button = make_button("Close", "secondary")
        button.clicked.connect(self.accept)
        return button

    def _category_tab(self, category: dict) -> QWidget:
        content = QWidget()
        inner = QVBoxLayout(content)
        inner.setSpacing(theme.SPACE_SM)
        inner.addWidget(_label(category["summary"]))
        inner.addWidget(_label("Identifier: " + category["identifier"]))
        if category["queued"]:
            inner.addWidget(_label(f"Waiting to be sent: {category['queued']} item(s)."))
        for event in category["events"]:
            inner.addWidget(_label(event["name"], "cardTitle"))
            inner.addWidget(_label(event["description"]))
            inner.addWidget(_label("; ".join(f"{field['name']}: {field['allowed']}" for field in event["fields"]), "secondaryText"))
        title = "Your next upload (identifier shortened)" if category["example_is_real"] else "Example upload"
        inner.addWidget(_label(title, "cardTitle"))
        example = QPlainTextEdit(category["example"])
        example.setReadOnly(True)
        example.setMinimumHeight(180)
        inner.addWidget(example)
        inner.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _never_tab(self, model: dict) -> QWidget:
        content = QWidget()
        inner = QVBoxLayout(content)
        inner.addWidget(_label("These are never part of any upload:"))
        for line in model["never_collected"]:
            inner.addWidget(_label("• " + line))
        inner.addWidget(_label(model["retention"]))
        inner.addStretch(1)
        return content


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
