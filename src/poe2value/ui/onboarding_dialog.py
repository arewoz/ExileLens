"""Small first-run setup surface backed by :mod:`poe2value.app.readiness`."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from poe2value.app.readiness import AppReadiness, derive_readiness
from poe2value.app.settings import AppSettings, complete_onboarding, save_settings
from poe2value.branding import window_title


class OnboardingDialog(QDialog):
    """A non-modal, reactive setup dialog. It never owns runtime initialization."""

    def __init__(
        self,
        settings: AppSettings,
        controller,
        *,
        on_diagnostics: Callable[[], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.controller = controller
        self._on_diagnostics = on_diagnostics
        self.setWindowTitle(window_title("Setup"))
        self.setMinimumWidth(460)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        layout = QVBoxLayout(self)
        self._progress = QLabel("1  Welcome    2  PoB2    3  Build")
        layout.addWidget(self._progress)
        welcome = QLabel("Welcome to ExileLens\n\nExileLens compares the item you hover in Path of Exile 2 against your current build. It uses Path of Building Community for PoE2.\n\nYour Item Check hotkey is " + self._hotkey_label() + ".")
        welcome.setWordWrap(True)
        layout.addWidget(welcome)
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._status)

        actions = QHBoxLayout()
        self._pob_button = QPushButton("Choose PoB2…")
        self._pob_button.clicked.connect(self._choose_pob)
        actions.addWidget(self._pob_button)
        self._retry_button = QPushButton("Retry")
        self._retry_button.clicked.connect(self._retry)
        actions.addWidget(self._retry_button)
        self._build_button = QPushButton("Choose build XML…")
        self._build_button.clicked.connect(self._choose_build)
        actions.addWidget(self._build_button)
        layout.addLayout(actions)

        footer = QHBoxLayout()
        self._diagnostics = QPushButton("Diagnostics")
        self._diagnostics.clicked.connect(self._open_diagnostics)
        footer.addWidget(self._diagnostics)
        footer.addStretch(1)
        self._skip = QPushButton("Skip for now")
        self._skip.clicked.connect(self._skip_onboarding)
        footer.addWidget(self._skip)
        self._finish = QPushButton("Start using ExileLens")
        self._finish.clicked.connect(self._finish_onboarding)
        footer.addWidget(self._finish)
        layout.addLayout(footer)

        controller.build_changed.connect(lambda _info: self.refresh())
        controller.engine_ready.connect(self.refresh)
        controller.engine_failed.connect(lambda _message: self.refresh())
        self.refresh()

    def _hotkey_label(self) -> str:
        return str(getattr(self.settings, "price_check_hotkey", "shift+c") or "shift+c").replace("+", "+").upper()

    def refresh(self) -> None:
        status = derive_readiness(self.settings, self.controller)
        pob_text = self._pob_identity_text()
        self._status.setText(f"PoB2: {pob_text}\n\n{status.title}\n{status.detail}".strip())
        self._finish.setEnabled(status.ready)
        self._build_button.setEnabled(status.state not in {AppReadiness.INITIALIZING, AppReadiness.POB_NOT_FOUND})
        self._diagnostics.setVisible(status.support_action_available)
        if status.ready:
            self._progress.setText("1  Welcome    2  PoB2 ✓    3  Build ✓ — READY")
        elif status.state is AppReadiness.POB_NOT_FOUND:
            self._progress.setText("1  Welcome    2  PoB2 needs setup    3  Build")
        else:
            self._progress.setText("1  Welcome    2  PoB2 ✓    3  Build")

    def _pob_identity_text(self) -> str:
        """Show bounded runtime identity, never the user's full local path."""
        from poe2value.app.setup_status import check_pob_folder
        check = check_pob_folder(self.settings.pob_path)
        if not check.ok:
            return check.text()
        try:
            from poe2value.config import detect_pob_identity
            identity = detect_pob_identity(self.settings.pob_path)
            if identity.version != "unknown":
                return f"detected · v{identity.version}"
        except Exception:  # informational metadata cannot block readiness
            pass
        return "detected"

    def _choose_pob(self) -> None:
        from poe2value.ui.setup_dialog import pick_pob_directory
        path = pick_pob_directory(self.settings.pob_path)
        if not path:
            return
        self.settings.pob_path = path
        save_settings(self.settings)
        self.controller.restart_engine()
        self.refresh()

    def _retry(self) -> None:
        if self.controller.engine_status() == "ready":
            self.controller.reload_evaluation_build()
        else:
            self.controller.restart_engine()
        self.refresh()

    def _choose_build(self) -> None:
        from poe2value.ui.setup_dialog import pick_build_file
        path = pick_build_file(self.settings.build_path)
        if not path:
            return
        self.settings.build_path = str(Path(path))
        save_settings(self.settings)
        if self.controller.engine_status() == "ready":
            self.controller.load_build(self.settings.build_path, context=self.settings.context)
        self.refresh()

    def _open_diagnostics(self) -> None:
        if self._on_diagnostics is not None:
            self._on_diagnostics()

    def _finish_onboarding(self) -> None:
        if derive_readiness(self.settings, self.controller).ready:
            complete_onboarding(self.settings)
            self.accept()

    def _skip_onboarding(self) -> None:
        complete_onboarding(self.settings)
        self.reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        # Closing is a deliberate dismissal, not a claim that the app is ready.
        if not self.settings.onboarding_completed:
            complete_onboarding(self.settings)
        super().closeEvent(event)
