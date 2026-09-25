"""Shared Settings UI for secure application updates."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from exilelens.app.settings import AppSettings
from exilelens.ui.components import button_row, make_button
from exilelens.ui.ui_icons import apply_button_icon


class UpdatesPanel(QWidget):
    """Wires one :class:`~exilelens.app.updates.service.UpdateService` into Settings."""

    def __init__(self, settings: AppSettings, update_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.update_service = update_service

        ui_scale = float(getattr(settings, "ui_scale", 1.0) or 1.0)

        self._installed = QLabel("")
        self._installed.setObjectName("fieldLabel")
        self._latest = QLabel("")
        self._latest.setObjectName("helperText")
        self._latest.setWordWrap(True)
        self._status = QLabel("")
        self._status.setObjectName("helperText")
        self._status.setWordWrap(True)

        self._check_btn = make_button("Check for updates", "secondary")
        self._check_btn.clicked.connect(self.update_service.check_now)
        self._download_btn = make_button("Download && Install", "primary")
        self._download_btn.clicked.connect(self._start_download)
        self._download_btn.setVisible(False)
        apply_button_icon(self._download_btn, "download", ui_scale=ui_scale)
        self._restart_btn = make_button("Restart && Update", "primary")
        self._restart_btn.clicked.connect(self._restart_and_update)
        self._restart_btn.setVisible(False)
        self._cancel_btn = make_button("Cancel download", "secondary")
        self._cancel_btn.clicked.connect(self.update_service.cancel_download)
        self._cancel_btn.setVisible(False)
        self._progress = QLabel("")
        self._progress.setObjectName("helperText")
        self._progress.setVisible(False)
        self._open_releases_btn = make_button("Open GitHub Releases", "secondary")
        self._open_releases_btn.clicked.connect(self._open_github_releases)
        self._open_releases_btn.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._installed)
        layout.addWidget(self._latest)
        layout.addWidget(self._status)
        layout.addLayout(
            button_row(
                [
                    self._check_btn,
                    self._download_btn,
                    self._restart_btn,
                    self._cancel_btn,
                    self._open_releases_btn,
                ]
            )
        )
        layout.addWidget(self._progress)

        self.update_service.state_changed.connect(self._on_update_state)
        self.update_service.download_progress.connect(self._on_download_progress)
        self.update_service.download_state_changed.connect(self._on_download_state)
        self.update_service.action_error.connect(self._on_action_error)
        self._refresh_installed_line()
        self._on_update_state("unchecked", "")

    def _refresh_installed_line(self) -> None:
        self._installed.setText(f"Installed version: {self.update_service.installed_version_text}")

    def _refresh_latest_line(self, version: str) -> None:
        known = str(version or getattr(self.settings, "update_latest_version", "") or "").strip()
        if known:
            self._latest.setText(f"Latest available: {known}")
        else:
            self._latest.setText("Latest available: not checked yet")

    def _on_update_state(self, state: str, version: str) -> None:
        self._refresh_latest_line(version)
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
            text = f"Update available: {version}. Download installs the signed package after verification."
        self._status.setText(text)
        self._open_releases_btn.setVisible(state in ("available", "verification_failed"))
        self._download_btn.setVisible(state == "available")
        self._check_btn.setEnabled(state != "checking")

    def _start_download(self) -> None:
        if not self.update_service.start_download():
            return
        self._cancel_btn.setVisible(True)
        self._progress.setVisible(True)

    def _restart_and_update(self) -> None:
        from exilelens.ui.update_actions import restart_and_update

        restart_and_update(self.update_service)

    def _on_download_progress(self, done: int, total: int) -> None:
        if total:
            percent = int((done / total) * 100)
            self._progress.setText(f"Downloading update… {percent}%")
        else:
            self._progress.setText("Downloading update…")
        self._progress.setVisible(True)

    def _on_download_state(self, state: str) -> None:
        if state == "downloading":
            self._download_btn.setEnabled(False)
            self._cancel_btn.setVisible(True)
            self._restart_btn.setVisible(False)
        elif state == "ready":
            self._download_btn.setEnabled(True)
            self._cancel_btn.setVisible(False)
            self._progress.setText("Update downloaded and verified. Restart to install.")
            self._restart_btn.setVisible(True)
        elif state == "installing":
            self._progress.setText("Installing update…")
            self._restart_btn.setVisible(False)
        elif state == "error":
            self._download_btn.setEnabled(True)
            self._cancel_btn.setVisible(False)
            self._restart_btn.setVisible(False)

    def _on_action_error(self, message: str) -> None:
        if message:
            self._progress.setText(message)
            self._progress.setVisible(True)

    def _open_github_releases(self) -> None:
        from exilelens.ui.recovery_actions import open_github_releases

        open_github_releases()
