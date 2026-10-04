"""Settings → Updates › Seamless updates: the canonical home of everything Patreon.

One neutral supporter zone holds the two supporter switches, the link state, Link Patreon and
Support on Patreon. Patreon is optional and never needed for any ExileLens feature; every non-active state says
that manual updates still work. The panel never shows a Patreon name, email, avatar or tier because the app never
receives one.

The zone is neutral: no tint, no coloured border (red surfaces read as warning or danger). It is identified by the
shipped Patreon mark, its heading and its copy, and looks the same linked or not. State is carried by the word at the
top right, the switches (dashed and dimmed while locked) and one footer sentence. Buttons stay neutral.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from exilelens.app.settings import save_settings
from exilelens.cloud import hooks
from exilelens.cloud.patreon import PatreonState, PatreonView
from exilelens.ui.components import StatusDot, make_button
from exilelens.ui.dashboard_widgets import SettingsGroup, SettingsRow, ThemedSwitch, WrapLabel, ZoneFooter

MANUAL_NOTE = "Manual updates still work."

#: Shown wherever linking is offered. Matches PRIVACY.md: the desktop never receives a Patreon name or
#: email; the service stores only what it needs to confirm supporter status, in a store separate from
#: usage stats and error reports.
PRIVACY_LINE = (
    "ExileLens never receives your Patreon name or email in the desktop app. The ExileLens service "
    "keeps only what it needs to confirm supporter status, separate from usage stats and error reports."
)
FREE_LINE = "Manual updates and all core features stay free."
ZONE_TITLE = "Seamless updates"
ZONE_DESCRIPTION = "Supporters can download verified updates automatically and install them when ExileLens closes."
SUPPORT_HELP = "Help fund development and get seamless automatic updates."
LOCKED_TIP = "Needs an active Patreon link."
AUTO_DOWNLOAD_LABEL = "Automatically download updates"
INSTALL_ON_EXIT_LABEL = "Install when ExileLens closes"


def describe_view(view: PatreonView, *, available: bool) -> str:
    """The one footer sentence for a Patreon state (kept pure for tests)."""
    state = view.state
    if state is PatreonState.NOT_CONNECTED:
        if not available:
            return f"Patreon linking isn't available in this build. {MANUAL_NOTE}"
        return "Link Patreon to turn these on."
    if state is PatreonState.LINKING:
        return "Finish connecting in your browser. This can take a minute."
    if state is PatreonState.ACTIVE:
        return "Connected as a supporter. Thank you."
    if state is PatreonState.NOT_ELIGIBLE:
        return f"Your current membership doesn't include seamless updates. {MANUAL_NOTE}"
    if state is PatreonState.OFFLINE_GRACE:
        until = time.strftime("%d %b %Y", time.localtime(view.expires_at)) if view.expires_at else "the lease expires"
        return f"Couldn't reach the ExileLens service. Seamless updates stay on until {until}. {MANUAL_NOTE}"
    if state is PatreonState.EXPIRED:
        return f"Your membership couldn't be confirmed, so seamless updates are paused. {MANUAL_NOTE}"
    if state is PatreonState.RECONNECT_REQUIRED:
        return f"Please reconnect Patreon. {MANUAL_NOTE}"
    if state is PatreonState.SERVICE_UNAVAILABLE:
        return f"Patreon linking is temporarily unavailable. {MANUAL_NOTE}"
    return ""


def state_word(view: PatreonView, *, available: bool) -> tuple[str, str]:
    """The short word at the zone's top right and its tone (``ok`` / ``warn`` / ``neutral``). Never colour alone."""
    state = view.state
    if state is PatreonState.NOT_CONNECTED:
        return ("Not linked" if available else "Unavailable in this build"), "neutral"
    if state is PatreonState.LINKING:
        return "Waiting for Patreon…", "neutral"
    if state is PatreonState.ACTIVE:
        return "Active", "ok"
    if state is PatreonState.NOT_ELIGIBLE:
        return "Not in your membership", "neutral"
    if state is PatreonState.OFFLINE_GRACE:
        until = time.strftime("%d %b", time.localtime(view.expires_at)) if view.expires_at else ""
        return (f"Active until {until}" if until else "Active"), "warn"
    if state is PatreonState.EXPIRED:
        return "Paused", "warn"
    if state is PatreonState.RECONNECT_REQUIRED:
        return "Reconnect needed", "warn"
    if state is PatreonState.SERVICE_UNAVAILABLE:
        return "Linking unavailable", "neutral"
    return "", "neutral"


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


def _open_patreon_page() -> None:
    from exilelens.ui.recovery_actions import open_patreon

    open_patreon()


class PatreonPanel(QFrame):
    """The supporter zone (a ``QFrame#supporterZone``)."""

    #: Emitted after every render with the PatreonState value.
    view_rendered = Signal(str)

    def __init__(self, settings, cloud=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("supporterZone")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAccessibleName("Seamless updates, a Patreon supporter feature")
        self.settings = settings
        self.cloud = cloud if cloud is not None else hooks.get()
        self.link = self.cloud.patreon if self.cloud is not None else None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- header: the mark once, the title, and the state word (dot or glyph + text) ----------------------
        from exilelens.ui.ui_icons import load_icon

        head = QWidget()
        head_row = QHBoxLayout(head)
        head_row.setContentsMargins(16, 12, 16, 0)
        head_row.setSpacing(10)
        mark = QLabel()
        mark.setFixedSize(16, 16)
        icon = load_icon("patreon")
        if icon is not None:
            mark.setPixmap(icon.pixmap(16, 16))
        mark.setAccessibleName("")
        title = QLabel(ZONE_TITLE)
        title.setObjectName("zoneTitle")
        self._dot = StatusDot("neutral")
        self.state_label = QLabel("")
        self.state_label.setObjectName("secondaryText")
        head_row.addWidget(mark, 0, Qt.AlignmentFlag.AlignVCenter)
        head_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        head_row.addStretch(1)
        head_row.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        head_row.addWidget(self.state_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(head)
        description = WrapLabel(ZONE_DESCRIPTION)
        description.setObjectName("zoneText")
        description.setContentsMargins(42, 2, 16, 8)   # aligned to the title, past the mark
        layout.addWidget(description)

        # --- the two supporter switches ----------------------------------------------------------------------
        self.auto_download = ThemedSwitch(AUTO_DOWNLOAD_LABEL)
        self.install_on_exit = ThemedSwitch(INSTALL_ON_EXIT_LABEL)
        self.seamless_host = SettingsGroup()
        self._auto_row = SettingsRow(AUTO_DOWNLOAD_LABEL, h_pad=16)
        self._auto_row.add_control(self.auto_download)
        self._exit_row = SettingsRow(INSTALL_ON_EXIT_LABEL, "ExileLens never restarts by itself.", h_pad=16)
        self._exit_row.add_control(self.install_on_exit)
        self.seamless_host.add_row(self._auto_row)
        self.seamless_host.add_row(self._exit_row)
        layout.addWidget(self.seamless_host)

        # --- footer: one sentence, then the actions that apply to the state ---------------------------------
        # Buttons are attributes: Settings, the tray and tests read them.
        self.support_button = make_button("Support on Patreon", "secondary", compact=True, tooltip=SUPPORT_HELP)
        self.link_button = make_button("Link Patreon", "tertiary", compact=True, tooltip=PRIVACY_LINE)
        self.cancel_button = make_button("Cancel", "tertiary", compact=True)
        self.reconnect_button = make_button("Reconnect", "secondary", compact=True)
        self.retry_button = make_button("Retry", "tertiary", compact=True)
        self.view_button = make_button("View Patreon", "tertiary", compact=True)
        self.disconnect_button = make_button("Disconnect Patreon", "tertiary", compact=True)
        self.status = WrapLabel("")
        self.status.setObjectName("zoneText")
        self.footer = ZoneFooter(self.status)
        for button in (
            self.cancel_button, self.retry_button, self.disconnect_button, self.view_button,
            self.reconnect_button, self.link_button, self.support_button,
        ):
            self.footer.add_action(button)
        layout.addWidget(self.footer)

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

    def render(self) -> None:
        view = self.link.view() if self.link is not None else PatreonView(PatreonState.NOT_CONNECTED)
        state = view.state
        available = self.available()
        not_linked = state is PatreonState.NOT_CONNECTED

        word, tone = state_word(view, available=available)
        self.state_label.setText(word)
        self.state_label.setObjectName({"ok": "statusOk", "warn": "statusWarn"}.get(tone, "secondaryText"))
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)
        self._dot.set_status(tone)
        self._dot.setVisible(tone != "neutral")

        sentence = describe_view(view, available=available)
        note = link_failure_note(view.detail) if state in (PatreonState.NOT_CONNECTED, PatreonState.SERVICE_UNAVAILABLE) else ""
        self.status.setText(f"{sentence}\n{note}" if note else sentence)

        connected = state in (
            PatreonState.ACTIVE, PatreonState.NOT_ELIGIBLE, PatreonState.OFFLINE_GRACE, PatreonState.EXPIRED, PatreonState.RECONNECT_REQUIRED
        )
        supporter = state in (PatreonState.ACTIVE, PatreonState.OFFLINE_GRACE)

        self.support_button.setVisible(not_linked or state is PatreonState.SERVICE_UNAVAILABLE)
        self.view_button.setVisible(state is PatreonState.NOT_ELIGIBLE)
        self.link_button.setVisible(state in (PatreonState.NOT_CONNECTED, PatreonState.SERVICE_UNAVAILABLE) and available)
        self.link_button.setEnabled(available)
        self.cancel_button.setVisible(state is PatreonState.LINKING)
        self.reconnect_button.setVisible(state in (PatreonState.RECONNECT_REQUIRED, PatreonState.EXPIRED))
        self.retry_button.setVisible(state is PatreonState.EXPIRED)
        self.disconnect_button.setVisible(connected)

        # The switches are always shown; they are only usable while a supporter lease is valid, and until then
        # they are visibly locked (dashed track), with the reason said once, in the footer.
        for box, name in ((self.auto_download, "updates_auto_download"), (self.install_on_exit, "updates_install_on_exit")):
            with QSignalBlocker(box):
                box.setChecked(bool(getattr(self.settings, name, True)) and supporter)
            box.setEnabled(supporter)
            box.set_locked(not supporter)
            box.setToolTip("" if supporter else LOCKED_TIP)
        self._auto_row.set_disabled_look(not supporter)
        self._exit_row.set_disabled_look(not supporter)
        self.footer.reflow()
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
