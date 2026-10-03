"""Settings → Patreon supporter: link/unlink and the supporter update options.

Patreon is optional and never needed for any ExileLens feature; every non-active state says that manual
updates still work. The panel never shows a Patreon name or email because the app never receives one.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QSignalBlocker, QTimer, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from exilelens.app.settings import save_settings
from exilelens.cloud import hooks
from exilelens.cloud.patreon import PatreonState, PatreonView
from exilelens.ui import theme
from exilelens.ui.components import ThemedCheckBox, button_row, make_button

MANUAL_NOTE = "Manual updates still work."


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


class PatreonPanel(QWidget):
    def __init__(self, settings, cloud=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.cloud = cloud if cloud is not None else hooks.get()
        self.link = self.cloud.patreon if self.cloud is not None else None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.ROW_GAP)
        self.status = QLabel("")
        self.status.setObjectName("helperText")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.note = QLabel("")
        self.note.setObjectName("secondaryText")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.auto_download = ThemedCheckBox("Automatically download updates")
        self.install_on_exit = ThemedCheckBox("Install updates when ExileLens closes")
        layout.addWidget(self.auto_download)
        layout.addWidget(self.install_on_exit)
        self.link_button = make_button("Link Patreon", "primary")
        self.cancel_button = make_button("Cancel", "tertiary")
        self.reconnect_button = make_button("Reconnect", "primary")
        self.retry_button = make_button("Retry", "secondary")
        self.disconnect_button = make_button("Disconnect Patreon", "secondary")
        layout.addLayout(
            button_row([self.link_button, self.cancel_button, self.reconnect_button, self.retry_button, self.disconnect_button])
        )
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

    def render(self) -> None:
        view = self.link.view() if self.link is not None else PatreonView(PatreonState.NOT_CONNECTED)
        state = view.state
        self.status.setText(describe_view(view, available=self.available()))
        self.note.setText(link_failure_note(view.detail) if state in (PatreonState.NOT_CONNECTED, PatreonState.SERVICE_UNAVAILABLE) else "")
        self.note.setVisible(bool(self.note.text()))
        connected = state in (
            PatreonState.ACTIVE, PatreonState.NOT_ELIGIBLE, PatreonState.OFFLINE_GRACE, PatreonState.EXPIRED, PatreonState.RECONNECT_REQUIRED
        )
        supporter = state in (PatreonState.ACTIVE, PatreonState.OFFLINE_GRACE)
        self.link_button.setVisible(state in (PatreonState.NOT_CONNECTED, PatreonState.SERVICE_UNAVAILABLE))
        self.link_button.setEnabled(self.available())
        self.cancel_button.setVisible(state is PatreonState.LINKING)
        self.reconnect_button.setVisible(state in (PatreonState.RECONNECT_REQUIRED, PatreonState.EXPIRED))
        self.retry_button.setVisible(state is PatreonState.EXPIRED)
        self.disconnect_button.setVisible(connected)
        for box, name in ((self.auto_download, "updates_auto_download"), (self.install_on_exit, "updates_install_on_exit")):
            with QSignalBlocker(box):
                box.setChecked(bool(getattr(self.settings, name, True)))
            box.setVisible(supporter)

    # -- actions --------------------------------------------------------------------------------
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
