"""Settings → Patreon supporter: link/unlink and the supporter update options.

Patreon is optional and never needed for any ExileLens feature; every non-active state says that manual
updates still work. The panel never shows a Patreon name, email, avatar or tier because the app never
receives one.

The two supporter switches (``auto_download`` / ``install_on_exit``) are created here because this panel
owns their persistence, but Settings places them under *Updates › Seamless automatic updates*, where they
are always visible and simply disabled until a valid supporter lease exists.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from exilelens.app.settings import save_settings
from exilelens.cloud import hooks
from exilelens.cloud.patreon import PatreonState, PatreonView
from exilelens.ui.components import StatusDot, make_button
from exilelens.ui.dashboard_widgets import SettingsGroup, SettingsRow, ThemedSwitch

MANUAL_NOTE = "Manual updates still work."

#: Shown wherever linking is offered. Matches PRIVACY.md: the desktop never receives a Patreon name or
#: email; the service stores only what it needs to confirm supporter status, in a store separate from
#: usage stats and error reports.
PRIVACY_LINE = (
    "ExileLens never receives your Patreon name or email in the desktop app. The ExileLens service "
    "keeps only what it needs to confirm supporter status, separate from usage stats and error reports."
)
FREE_LINE = "Manual updates and every core ExileLens feature remain free."
SUPPORT_HEADLINE = "Support ExileLens"
SUPPORT_HELP = "Help fund continued development and get seamless automatic updates."
THANKS_LINE = "Thanks for supporting ExileLens."


def describe_view(view: PatreonView, *, available: bool) -> str:
    """User-facing status text for a Patreon state (kept pure for tests)."""
    state = view.state
    if state is PatreonState.NOT_CONNECTED:
        if not available:
            return "Patreon linking is not available in this build."
        return "Support ExileLens and enable seamless automatic updates."
    if state is PatreonState.LINKING:
        return "Finish connecting in your browser… (this can take a few minutes)"
    if state is PatreonState.ACTIVE:
        return "Connected. Seamless automatic updates are active."
    if state is PatreonState.NOT_ELIGIBLE:
        return f"Connected. Your current membership doesn't include seamless updates. {MANUAL_NOTE}"
    if state is PatreonState.OFFLINE_GRACE:
        until = time.strftime("%d %b %Y", time.localtime(view.expires_at)) if view.expires_at else "the lease expires"
        return f"Connected. Couldn't reach the ExileLens service; seamless updates stay active until {until}. {MANUAL_NOTE}"
    if state is PatreonState.EXPIRED:
        return f"Seamless updates are paused — your membership couldn't be confirmed. {MANUAL_NOTE}"
    if state is PatreonState.RECONNECT_REQUIRED:
        return f"Please reconnect Patreon. {MANUAL_NOTE}"
    if state is PatreonState.SERVICE_UNAVAILABLE:
        return f"Patreon linking is temporarily unavailable. {MANUAL_NOTE}"
    return ""


def link_failure_note(detail: str) -> str:
    return {
        "denied": "Patreon authorization was cancelled.",
        "expired": "The link expired — try again.",
        "timeout": "Linking timed out — try again.",
        "cancelled": "Linking was cancelled.",
        "browser_unavailable": "Couldn't open your browser.",
        "failed": "Patreon couldn't be reached — try again later.",
        "network": "Couldn't reach the ExileLens service.",
    }.get(detail, "")


class _Bridge(QObject):
    changed = Signal(object)


#: state -> dot tone for the status row (neutral states carry no dot)
_STATE_TONE = {
    PatreonState.ACTIVE: "ok",
    PatreonState.OFFLINE_GRACE: "warn",
    PatreonState.EXPIRED: "warn",
    PatreonState.RECONNECT_REQUIRED: "warn",
}


def _open_patreon_page() -> None:
    from exilelens.ui.recovery_actions import open_patreon

    open_patreon()


def _set_tier(button, object_name: str) -> None:
    if button.objectName() == object_name:
        return
    button.setObjectName(object_name)
    button.style().unpolish(button)
    button.style().polish(button)


class PatreonPanel(QWidget):
    #: Emitted after every render with the PatreonState value, so Updates can word the seamless row.
    view_rendered = Signal(str)

    def __init__(self, settings, cloud=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.cloud = cloud if cloud is not None else hooks.get()
        self.link = self.cloud.patreon if self.cloud is not None else None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Buttons are attributes: Settings, the tray and tests read them.
        self.support_button = make_button("Support on Patreon", "branded", compact=True, icon="patreon")
        self.link_button = make_button("Link Patreon", "tertiary", compact=True)
        self.cancel_button = make_button("Cancel", "tertiary", compact=True)
        self.reconnect_button = make_button("Reconnect", "secondary", compact=True)
        self.retry_button = make_button("Retry", "tertiary", compact=True)
        self.view_button = make_button("View Patreon", "tertiary", compact=True)
        self.disconnect_button = make_button("Disconnect Patreon", "secondary", compact=True)

        # The two supporter switches. Standalone they sit at the end of this panel; Settings re-homes
        # them under Updates with ``detach_seamless_controls``.
        self.auto_download = ThemedSwitch("Automatically download updates")
        self.install_on_exit = ThemedSwitch("Install updates when ExileLens closes")
        self.seamless_host = SettingsGroup()
        self._auto_row = SettingsRow("Automatically download updates")
        self._auto_row.add_control(self.auto_download)
        self._exit_row = SettingsRow("Install updates when ExileLens closes", "ExileLens never restarts by itself.")
        self._exit_row.add_control(self.install_on_exit)
        self.seamless_host.add_row(self._auto_row)
        self.seamless_host.add_row(self._exit_row)

        # Status row: headline + help in the not-linked entry state, a status sentence otherwise.
        self._status_row = SettingsRow(SUPPORT_HEADLINE)
        self._dot = StatusDot("neutral")
        self.status = QLabel("")
        self.status.setObjectName("bodyText")
        self.status.setWordWrap(True)
        status_left = QHBoxLayout()
        status_left.setContentsMargins(0, 0, 0, 0)
        status_left.setSpacing(8)
        status_left.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignTop)
        status_left.addWidget(self.status, 1)
        status_host = QWidget()
        status_host.setLayout(status_left)
        self._status_row.add_left(status_host)
        for button in (
            self.support_button, self.view_button, self.retry_button, self.cancel_button,
            self.reconnect_button, self.link_button, self.disconnect_button,
        ):
            self._status_row.add_control(button)
        self.group = SettingsGroup()
        self.group.add_row(self._status_row)
        layout.addWidget(self.group)

        self.note = QLabel("")
        self.free_line = QLabel(FREE_LINE)
        self.privacy_line = QLabel(PRIVACY_LINE)
        self.thanks_line = QLabel(THANKS_LINE)
        for widget in (self.note, self.free_line, self.privacy_line, self.thanks_line):
            widget.setObjectName("helperText")
            widget.setWordWrap(True)
            widget.setContentsMargins(0, 8, 0, 0)
            layout.addWidget(widget)
        self.privacy_line.setMaximumWidth(640)
        layout.addWidget(self.seamless_host)

        self.support_button.clicked.connect(_open_patreon_page)
        self.view_button.clicked.connect(_open_patreon_page)
        self.link_button.clicked.connect(self._start)
        self.reconnect_button.clicked.connect(self._start)
        self.cancel_button.clicked.connect(lambda: self.link and self.link.cancel_link())
        self.retry_button.clicked.connect(self._retry)
        self.disconnect_button.clicked.connect(self._disconnect)
        self.auto_download.toggled.connect(self._toggle_auto_download)
        self.install_on_exit.toggled.connect(self._toggle_install_on_exit)
        self._bridge = _Bridge(self)
        self._bridge.changed.connect(lambda _view: self.render())
        if self.link is not None:
            self.link.add_listener(self._bridge.changed.emit)
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self.render)
        self._timer.start()
        self.render()

    def available(self) -> bool:
        return self.link is not None and self.link.available()

    def current_state(self) -> str:
        view = self.link.view() if self.link is not None else PatreonView(PatreonState.NOT_CONNECTED)
        return view.state.value

    def detach_seamless_controls(self) -> QWidget:
        """Hand the two supporter switches (and their rows) to Settings › Updates."""
        self.layout().removeWidget(self.seamless_host)
        self.seamless_host.setParent(None)
        return self.seamless_host

    def render(self) -> None:
        view = self.link.view() if self.link is not None else PatreonView(PatreonState.NOT_CONNECTED)
        state = view.state
        available = self.available()
        not_linked = state is PatreonState.NOT_CONNECTED
        entry = not_linked and available  # the stronger "Support ExileLens" entry state

        self.status.setText(describe_view(view, available=available))
        self.status.setVisible(not entry)
        tone = _STATE_TONE.get(state, "neutral")
        self._dot.set_status(tone)
        self._dot.setVisible(tone != "neutral" and not entry)
        self._status_row.label.setVisible(entry)
        self._status_row.set_helper(SUPPORT_HELP if entry else "")

        note = link_failure_note(view.detail) if state in (PatreonState.NOT_CONNECTED, PatreonState.SERVICE_UNAVAILABLE) else ""
        self.note.setText(note)
        self.note.setVisible(bool(note))
        connected = state in (
            PatreonState.ACTIVE, PatreonState.NOT_ELIGIBLE, PatreonState.OFFLINE_GRACE, PatreonState.EXPIRED, PatreonState.RECONNECT_REQUIRED
        )
        supporter = state in (PatreonState.ACTIVE, PatreonState.OFFLINE_GRACE)

        self.support_button.setVisible(entry)
        self.view_button.setVisible(state is PatreonState.NOT_ELIGIBLE)
        self.link_button.setVisible(state in (PatreonState.NOT_CONNECTED, PatreonState.SERVICE_UNAVAILABLE))
        self.link_button.setEnabled(available)
        _set_tier(self.link_button, "btnSecondary" if state is PatreonState.SERVICE_UNAVAILABLE else "btnTertiary")
        self.cancel_button.setVisible(state is PatreonState.LINKING)
        self.reconnect_button.setVisible(state in (PatreonState.RECONNECT_REQUIRED, PatreonState.EXPIRED))
        self.retry_button.setVisible(state is PatreonState.EXPIRED)
        self.disconnect_button.setVisible(connected)
        self.free_line.setVisible(entry)
        self.privacy_line.setVisible(entry or state is PatreonState.ACTIVE)
        self.thanks_line.setVisible(state is PatreonState.ACTIVE)

        # The switches are always shown; they are only usable while a supporter lease is valid.
        for box, name in ((self.auto_download, "updates_auto_download"), (self.install_on_exit, "updates_install_on_exit")):
            with QSignalBlocker(box):
                box.setChecked(bool(getattr(self.settings, name, True)) and supporter)
            box.setEnabled(supporter)
        self._auto_row.set_disabled_look(not supporter)
        self._exit_row.set_disabled_look(not supporter)
        self.view_rendered.emit(state.value)

    # -- actions -------------------------------------------------------------------------------
    def _start(self) -> None:
        if self.link is not None:
            self.link.start_link()
        self.render()

    def _retry(self) -> None:
        if self.link is not None:
            import threading

            threading.Thread(target=self.link.refresh, name="exilelens-patreon-retry", daemon=True).start()

    def _disconnect(self) -> None:
        if self.link is not None:
            self.link.unlink()
        self.render()

    def _toggle_auto_download(self, on: bool) -> None:
        self.settings.updates_auto_download = bool(on)
        save_settings(self.settings)

    def _toggle_install_on_exit(self, on: bool) -> None:
        self.settings.updates_install_on_exit = bool(on)
        save_settings(self.settings)
