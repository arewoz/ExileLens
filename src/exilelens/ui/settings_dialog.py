from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QCloseEvent, QMoveEvent, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from exilelens.branding import app_icon, window_title
from exilelens.app.settings import AppSettings, save_settings
from exilelens.config import PobConfig, detect_common_pob_installation, validate_pob_path
from exilelens.engine import Engine
from exilelens.ui.managed_window import clamp_window_to_screen, recover_window_geometry


class _GeometryLockedDialog(QDialog):
    """Root cause fix: moveEvent previously allowed implicit size growth on DPI clamp."""

    def __init__(self, settings: AppSettings, *, prefix: str = "settings_dialog", parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._prefix = prefix
        self._locked_size = QSize()
        # Top-level dialogs do not reliably inherit QApplication's icon on Windows.
        # Set the canonical icon explicitly so Setup never falls back to Qt's default.
        if (icon := app_icon()) is not None:
            self.setWindowIcon(icon)
        flags = self.windowFlags()
        flags |= Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint
        self.setWindowFlags(flags)


    def _center_on_primary_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        recover_window_geometry(self, cap_size=True)
        self.raise_()
        self.activateWindow()

    def restore_geometry(self) -> None:
        width = int(getattr(self._settings, f"{self._prefix}_width", 560) or 560)
        height = int(getattr(self._settings, f"{self._prefix}_height", 420) or 420)
        self.resize(max(width, self.minimumWidth()), max(height, self.minimumHeight()))
        self._locked_size = self.size()
        x = getattr(self._settings, f"{self._prefix}_x", None)
        y = getattr(self._settings, f"{self._prefix}_y", None)
        if x is not None and y is not None:
            self.move(int(x), int(y))
        else:
            self._center_on_primary_screen()
        clamp_window_to_screen(self)

    def persist_geometry(self) -> None:
        geo = self.geometry()
        setattr(self._settings, f"{self._prefix}_x", geo.x())
        setattr(self._settings, f"{self._prefix}_y", geo.y())
        setattr(self._settings, f"{self._prefix}_width", geo.width())
        setattr(self._settings, f"{self._prefix}_height", geo.height())

    def moveEvent(self, event: QMoveEvent) -> None:  # noqa: N802
        super().moveEvent(event)
        if self._locked_size.isValid() and self.size() != self._locked_size:
            self.resize(self._locked_size)
        clamp_window_to_screen(self)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not self._locked_size.isValid() or self._locked_size.isEmpty():
            self._locked_size = event.size()
        elif self.isVisible() and event.size() != self._locked_size:
            if event.spontaneous():
                self._locked_size = event.size()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.persist_geometry()
        super().closeEvent(event)


class SetupDialog(_GeometryLockedDialog):
    """First-run setup: PoB path + build file."""

    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(settings, prefix="settings_dialog", parent=parent)
        self.settings = settings
        self._verified_pob_path = ""
        self.setWindowTitle(window_title("Setup"))
        self.setMinimumSize(480, 360)
        self.restore_geometry()

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(QLabel("Configure your Path of Building Community (PoE2) installation and build file."))

        form = QFormLayout()
        detected = detect_common_pob_installation() if not settings.pob_path else None
        self._pob_edit = QLineEdit(settings.pob_path or (str(detected) if detected else ""))
        pob_row = QHBoxLayout()
        pob_row.addWidget(self._pob_edit)
        pob_browse = QPushButton("Browse…")
        pob_browse.clicked.connect(self._browse_pob)
        pob_test = QPushButton("Test")
        pob_test.clicked.connect(self._test_pob)
        pob_row.addWidget(pob_browse)
        pob_row.addWidget(pob_test)
        form.addRow("Path of Building installation:", pob_row)

        self._build_edit = QLineEdit(settings.build_path)
        build_row = QHBoxLayout()
        build_row.addWidget(self._build_edit)
        build_browse = QPushButton("Browse…")
        build_browse.clicked.connect(self._browse_build)
        build_test = QPushButton("Load")
        build_test.clicked.connect(self._test_build)
        build_row.addWidget(build_browse)
        build_row.addWidget(build_test)
        form.addRow("Build XML:", build_row)

        self._status = QLabel("")
        form.addRow("Status:", self._status)
        layout.addLayout(form)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)

        root = QVBoxLayout(self)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse_pob(self) -> None:
        from exilelens.ui.setup_dialog import pick_pob_directory

        path = pick_pob_directory(self._pob_edit.text())
        if path:
            self._pob_edit.setText(path)
            from exilelens.app.setup_status import check_pob_folder

            self._status.setText(check_pob_folder(path).text())

    def _browse_build(self) -> None:
        from exilelens.ui.setup_dialog import pick_build_file

        path = pick_build_file(self._build_edit.text())
        if path:
            self._build_edit.setText(path)

    def _test_pob(self) -> bool:
        try:
            config = PobConfig(pob_path=Path(self._pob_edit.text().strip()))
            info = validate_pob_path(config)
            with Engine(config, use_subprocess=True) as engine:
                engine.ping()
            self._verified_pob_path = str(config.pob_path.resolve())
            from exilelens.config import detect_pob_identity

            pob_identity = detect_pob_identity(config.pob_path)
            revision = info.get("head")
            revision_text = f"revision {revision[:8]}" if revision else f"{info['layout']} layout"
            if pob_identity.status == "verified":
                version_text = f"v{pob_identity.version}"
            else:
                version_text = "version unverified"
            self._status.setText(f"PoB engine ready — {version_text} — {revision_text}")
            return True
        except Exception as exc:
            self._verified_pob_path = ""
            self._status.setText(f"PoB error: {exc}")
            return False

    def _test_build(self) -> None:
        build_path = self._build_edit.text().strip()
        if not build_path:
            self._status.setText("Select a build file first.")
            return
        try:
            config = PobConfig(pob_path=Path(self._pob_edit.text()))
            validate_pob_path(config)
            with Engine(config, use_subprocess=True) as engine:
                result = engine.load_build(build_path)
                name = (result.get("build") or {}).get("name") or Path(build_path).stem
            self._verified_pob_path = str(config.pob_path.resolve())
            self._status.setText(f"Build loaded: {name}")
        except Exception as exc:
            self._status.setText(f"Build error: {exc}")

    def _accept(self) -> None:
        pob = self._pob_edit.text().strip()
        build = self._build_edit.text().strip()
        if not pob or not build:
            QMessageBox.warning(self, "Setup", "Both PoB path and build file are required.")
            return
        if self._verified_pob_path != str(Path(pob).resolve()) and not self._test_pob():
            QMessageBox.warning(
                self,
                "Setup",
                "Path of Building could not start. Choose the installation folder containing Launch.lua and lua51.dll.",
            )
            return
        from exilelens.app.setup_status import check_build_file

        build_check = check_build_file(build)
        if not build_check.ok:
            QMessageBox.warning(self, "Setup", build_check.detail)
            return
        self.settings.pob_path = pob
        self.settings.build_path = build
        # Legacy dialog remains available to integrations, but completion uses the
        # versioned onboarding marker rather than implying a merely configured path
        # is a ready runtime/build.
        from exilelens.app.settings import complete_onboarding
        complete_onboarding(self.settings)
        self.persist_geometry()
        self.accept()
