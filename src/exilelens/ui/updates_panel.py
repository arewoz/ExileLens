"""Settings › Updates: the free manual update flow, then the seamless-automatic-updates group.

Order, top to bottom:

1. the current update state and its manual actions (always usable by everyone);
2. one explanatory sentence only when it changes what the player should understand
   (the pre-release case);
3. **Seamless automatic updates**, always visible: what it is, and the two real switches.
   Without a supporter lease the switches are shown disabled, so the benefit is obvious
   without a card, a lock or a badge.

The manual update controls stay visually primary whenever an update is available.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from exilelens.app.settings import AppSettings
from exilelens.ui.components import make_button, make_link_button
from exilelens.ui.dashboard_widgets import Notice, SettingsGroup, SettingsRow

SEAMLESS_TITLE = "Seamless automatic updates"
SEAMLESS_FULL = (
    "Manual updates are always free. Patreon supporters get signed updates downloaded automatically "
    "and installed when ExileLens closes."
)
SEAMLESS_QUIET = "Patreon supporters can have future updates handled automatically."
SEAMLESS_ACTIVE = (
    "Signed updates are downloaded automatically and installed when ExileLens closes. "
    "ExileLens never restarts by itself."
)
SEAMLESS_NOT_ELIGIBLE = "Your current membership doesn't include seamless updates."
PRERELEASE_NOTE = (
    "You are on the pre-release channel. ExileLens will offer later betas, and the final stable "
    "release when it is published."
)

#: Update-check states during which the manual flow is "in progress" and the Patreon row stays quiet.
_BUSY_STATES = {"available", "verification_failed"}


class UpdatesPanel(QWidget):
    """Wires one :class:`~exilelens.app.updates.service.UpdateService` into Settings."""

    def __init__(self, settings: AppSettings, update_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.update_service = update_service
        self._check_state = "unchecked"
        self._check_version = ""
        self._download_state = ""
        self._seamless_state = "not_connected"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- manual update row ----------------------------------------------------------------------
        self._installed = QLabel("")  # kept for tests/back-compat; the row label carries the same text
        self._installed.setObjectName("fieldLabel")
        self._latest = QLabel("")
        self._latest.setObjectName("helperText")
        self._status = QLabel("")
        self._status.setObjectName("helperText")
        self._status.setWordWrap(True)

        self._check_btn = make_button("Check for updates", "secondary", compact=True)
        self._check_btn.clicked.connect(self.update_service.check_now)
        self._download_btn = make_button("Download && install", "primary", compact=True, icon="download")
        self._download_btn.clicked.connect(self._start_download)
        self._restart_btn = make_button("Restart && update", "primary", compact=True)
        self._restart_btn.clicked.connect(self._restart_and_update)
        self._cancel_btn = make_button("Cancel download", "secondary", compact=True)
        self._cancel_btn.clicked.connect(self.update_service.cancel_download)
        self._open_releases_btn = make_button("Open GitHub Releases", "tertiary", compact=True)
        self._open_releases_btn.clicked.connect(self._open_github_releases)
        for button in (self._download_btn, self._restart_btn, self._cancel_btn, self._open_releases_btn):
            button.setVisible(False)

        self._group = SettingsGroup()
        self._row = SettingsRow("", "")
        self._row.label.setObjectName("fieldLabel")
        self._row.label.setVisible(True)
        self._row.helper.setVisible(False)
        self._row._left.addWidget(self._status)
        for button in (self._open_releases_btn, self._cancel_btn, self._check_btn, self._download_btn, self._restart_btn):
            self._row.add_control(button)
        self._group.add_row(self._row)
        layout.addWidget(self._group)

        self._progress = QLabel("")
        self._progress.setObjectName("helperText")
        self._progress.setWordWrap(True)
        self._progress.setVisible(False)
        self._bar = QProgressBar()
        self._bar.setObjectName("thinProgress")
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(False)
        self._bar.setVisible(False)
        self._extra = QLabel("")
        self._extra.setObjectName("bodyText")
        self._extra.setWordWrap(True)
        self._extra.setVisible(False)
        self._extra.setMaximumWidth(620)
        self._last_result = Notice("", "plain")
        self._last_result.setVisible(False)
        # Spacing between visible items only: hidden widgets do not take space in a box layout.
        self._extras = QVBoxLayout()
        self._extras.setContentsMargins(0, 0, 0, 0)
        self._extras.setSpacing(10)
        self._extras_host = QWidget()
        self._extras_host.setLayout(self._extras)
        for widget in (self._progress, self._bar, self._extra, self._last_result):
            self._extras.addWidget(widget)
        self._extras_host.setContentsMargins(0, 10, 0, 0)
        self._extras_host.setVisible(False)
        layout.addWidget(self._extras_host)
        self._recovery_needed = False

        # --- seamless automatic updates ----------------------------------------------------------
        self._seamless_host = QWidget()
        seamless_layout = QVBoxLayout(self._seamless_host)
        seamless_layout.setContentsMargins(0, 14, 0, 0)
        seamless_layout.setSpacing(0)
        self._seamless_group = SettingsGroup()
        self._seamless_row = SettingsRow(SEAMLESS_TITLE, SEAMLESS_FULL)
        self._learn_link = make_link_button("Learn about supporter updates")
        self._learn_link.clicked.connect(self._open_patreon_page)
        self._seamless_row.add_control(self._learn_link)
        self._seamless_group.add_row(self._seamless_row)
        seamless_layout.addWidget(self._seamless_group)
        layout.addWidget(self._seamless_host)

        self.update_service.state_changed.connect(self._on_update_state)
        self.update_service.download_progress.connect(self._on_download_progress)
        self.update_service.download_state_changed.connect(self._on_download_state)
        self.update_service.action_error.connect(self._on_action_error)
        install_outcome = getattr(self.update_service, "install_outcome", None)
        if install_outcome is not None:
            install_outcome.connect(self._on_install_outcome)
        self._refresh_installed_line()
        self._on_update_state("unchecked", "")
        previous = getattr(self.update_service, "last_install_notice", None)
        if previous is not None:
            self._on_install_outcome(previous)

    # --- seamless group (switches come from the Patreon panel) ---------------------------------------

    def attach_seamless_controls(self, patreon_panel) -> None:
        """Place the two supporter switches under the seamless row and follow the Patreon state."""
        host = patreon_panel.detach_seamless_controls()
        layout = self._seamless_host.layout()
        layout.addWidget(host)
        self._seamless_controls = host
        patreon_panel.view_rendered.connect(self._on_patreon_view)
        self._on_patreon_view(patreon_panel.current_state())

    def _on_patreon_view(self, state_value) -> None:
        from exilelens.cloud.patreon import PatreonState

        try:
            state = PatreonState(state_value)
        except ValueError:
            state = PatreonState.NOT_CONNECTED
        self._seamless_state = state.value
        self._refresh_seamless_row()

    def _refresh_seamless_row(self) -> None:
        from exilelens.cloud.patreon import PatreonState

        state = self._seamless_state
        if state in (PatreonState.ACTIVE.value, PatreonState.OFFLINE_GRACE.value):
            text, link = SEAMLESS_ACTIVE, False
        elif state == PatreonState.NOT_ELIGIBLE.value:
            text, link = SEAMLESS_NOT_ELIGIBLE, False
        else:
            quiet = self._check_state in _BUSY_STATES or self._download_state in {"downloading", "ready", "installing", "error"}
            text, link = (SEAMLESS_QUIET if quiet else SEAMLESS_FULL), True
        self._seamless_row.set_helper(text)
        self._learn_link.setVisible(link)

    def seamless_helper_text(self) -> str:
        return self._seamless_row.helper.text()

    # --- manual flow -------------------------------------------------------------------------------------

    def _refresh_installed_line(self) -> None:
        installed = self.update_service.installed_version_text
        self._installed.setText(f"Installed version: {installed}")
        self._row.label.setText(f"ExileLens {installed}")

    def _refresh_latest_line(self, version: str) -> None:
        known = str(version or getattr(self.settings, "update_latest_version", "") or "").strip()
        self._latest.setText(f"Latest available: {known}" if known else "Latest available: not checked yet")

    def _installed_is_prerelease(self) -> bool:
        from exilelens.app.updates.version import ExileLensVersion

        parsed = ExileLensVersion.parse(self.update_service.installed_version_text)
        return parsed is not None and not parsed.final

    def _on_update_state(self, state: str, version: str) -> None:
        self._check_state = state
        self._check_version = version
        self._refresh_latest_line(version)
        self._refresh_installed_line()
        installed = self.update_service.installed_version_text
        label = f"ExileLens {installed}"
        extra = ""
        if state == "ahead":
            if self._installed_is_prerelease():
                text = f"Pre-release · latest public release is {version}"
                extra = PRERELEASE_NOTE
            else:
                text = f"Newer than the latest public release ({version})"
        else:
            text = {
                "unchecked": "Check for updates to see whether a newer ExileLens release is available.",
                "checking": "Checking for updates…",
                "current": "You are on the latest verified release.",
                "failed": "Could not reach GitHub to check for updates. Try again later.",
                "unavailable": (
                    "Automatic updates are available only in a packaged ExileLens installation "
                    "(the downloaded installer build). Source and development runs do not self-update."
                ),
                "verification_failed": (
                    f"Release {version} is listed on GitHub but could not be verified safely. "
                    "ExileLens will not install an older release automatically."
                ),
            }.get(state, "")
        if state == "available":
            label = f"Update available: {version}"
            text = "Download installs the signed package after verification."
            self._status.setText(f"Update available: {version}. Download installs the signed package after verification.")
        else:
            self._status.setText(text)
        self._row.label.setText(label)
        # The row helper is the status sentence; for "available" it carries the full shipped sentence.
        self._status.setVisible(bool(self._status.text()))
        self._extra.setText(extra)
        self._extra.setVisible(bool(extra))
        self._open_releases_btn.setVisible(state in ("available", "verification_failed") or self._recovery_needed)
        self._download_btn.setVisible(state == "available" and self._download_state not in {"downloading", "installing"})
        self._check_btn.setVisible(state != "available" or self._download_state == "")
        self._check_btn.setEnabled(state != "checking")
        if state == "available":
            self._check_btn.setVisible(False)
        self._sync_extras()
        self._refresh_seamless_row()

    def _sync_extras(self) -> None:
        widgets = (self._progress, self._bar, self._extra, self._last_result)
        self._extras_host.setVisible(any(not widget.isHidden() for widget in widgets))

    def _start_download(self) -> None:
        if not self.update_service.start_download():
            return
        self._cancel_btn.setVisible(True)
        self._progress.setVisible(True)
        self._sync_extras()

    def _restart_and_update(self) -> None:
        # Always an explicit click: ExileLens never restarts itself.
        from exilelens.ui.update_actions import restart_and_update

        restart_and_update(self.update_service)

    def _on_download_progress(self, done: int, total: int) -> None:
        if total:
            percent = int((done / total) * 100)
            self._progress.setText(f"Downloading update… {percent}%")
            self._bar.setValue(percent)
            self._bar.setVisible(True)
        else:
            self._progress.setText("Downloading update…")
        self._progress.setVisible(True)
        self._sync_extras()

    def _on_download_state(self, state: str) -> None:
        self._download_state = state
        if state == "downloading":
            self._download_btn.setVisible(False)
            self._cancel_btn.setVisible(True)
            self._restart_btn.setVisible(False)
            self._check_btn.setVisible(False)
        elif state == "ready":
            self._download_btn.setVisible(False)
            self._cancel_btn.setVisible(False)
            self._bar.setVisible(False)
            on_exit = getattr(self.update_service, "install_on_exit_enabled", None)
            if callable(on_exit) and on_exit():
                self._progress.setText(
                    "Update downloaded and verified. It installs when ExileLens closes — or restart now."
                )
            else:
                self._progress.setText("Update downloaded and verified. Restart to install.")
            self._progress.setVisible(True)
            self._restart_btn.setVisible(True)
        elif state == "installing":
            self._progress.setText("Installing update…")
            self._restart_btn.setVisible(False)
        elif state == "error":
            self._download_btn.setVisible(self._check_state == "available")
            self._cancel_btn.setVisible(False)
            self._restart_btn.setVisible(False)
            self._bar.setVisible(False)
        else:
            self._cancel_btn.setVisible(False)
            self._bar.setVisible(False)
        self._sync_extras()
        self._refresh_seamless_row()

    def _on_action_error(self, message: str) -> None:
        if message:
            self._progress.setText(message)
            self._progress.setVisible(True)
            self._sync_extras()

    def _on_install_outcome(self, notice) -> None:
        message = str(getattr(notice, "message", "") or "")
        kind = getattr(notice, "kind", "")
        self._last_result.set_text(message)
        self._last_result.setProperty("tone", "error" if kind == "failed" else "plain")
        self._last_result.style().unpolish(self._last_result)
        self._last_result.style().polish(self._last_result)
        self._last_result.setVisible(bool(message))
        self._recovery_needed = kind == "failed"
        if self._recovery_needed:
            self._open_releases_btn.setVisible(True)
        self._sync_extras()

    def _open_github_releases(self) -> None:
        from exilelens.ui.recovery_actions import open_github_releases

        open_github_releases()

    def _open_patreon_page(self) -> None:
        from exilelens.ui.recovery_actions import open_patreon

        open_patreon()

    def focus_here(self) -> None:
        """Scroll target for the rail's "Update available" link."""
        self.setFocus(Qt.FocusReason.OtherFocusReason)
