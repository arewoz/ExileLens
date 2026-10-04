"""Settings › Updates: the free manual update flow.

The current update state and its manual actions are always usable by everyone, never tinted, and stay visually
primary whenever an update is available. One explanatory sentence appears only when it changes what the player
should understand (the pre-release case). Seamless updates, a Patreon supporter feature, live in their own zone
(``patreon_panel.PatreonPanel``) directly beneath this panel.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from exilelens.app.settings import AppSettings
from exilelens.ui.components import make_button
from exilelens.ui.dashboard_widgets import Notice, SettingsGroup, SettingsRow, WrapLabel

PRERELEASE_NOTE = "Beta channel · Later betas and the final release are offered automatically."

class UpdatesPanel(QWidget):
    """Wires one :class:`~exilelens.app.updates.service.UpdateService` into Settings."""

    def __init__(self, settings: AppSettings, update_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.update_service = update_service
        self._check_state = "unchecked"
        self._check_version = ""
        self._download_state = ""

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
        self._extra = WrapLabel("")
        self._extra.setObjectName("helperText")
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
                text = f"Pre-release · Latest stable {version}"
                extra = PRERELEASE_NOTE
            else:
                text = f"Newer than the latest release ({version})"
        else:
            text = {
                "unchecked": "Not checked yet.",
                "checking": "Checking…",
                "current": "Up to date.",
                "failed": "Couldn't reach GitHub. Try again later.",
                "unavailable": "Self-update works only in the installed (packaged) build.",
                "verification_failed": f"Release {version} could not be verified safely and won't be installed.",
            }.get(state, "")
        if state == "available":
            self._status.setText(f"Update available: {version}")
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

    def _sync_extras(self) -> None:
        widgets = (self._progress, self._bar, self._extra, self._last_result)
        self._extras_host.setVisible(any(not widget.isHidden() for widget in widgets))
        # Wrapped labels toggled after the first layout pass need their height-for-width re-asked.
        for widget in widgets:
            widget.updateGeometry()
        self._extras.invalidate()
        self._extras_host.updateGeometry()
        self.updateGeometry()

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
                    "Downloaded and verified. Installs when ExileLens closes, or restart now."
                )
            else:
                self._progress.setText("Downloaded and verified. Restart to install.")
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

    def focus_here(self) -> None:
        """Scroll target for the rail's "Update available" link."""
        self.setFocus(Qt.FocusReason.OtherFocusReason)
