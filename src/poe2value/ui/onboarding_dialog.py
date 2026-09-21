"""Reactive dashboard-style setup surface backed by canonical readiness."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout

from poe2value.app.readiness import AppReadiness, derive_readiness
from poe2value.app.settings import AppSettings, complete_onboarding, onboarding_required, save_settings
from poe2value.branding import app_icon, window_title
from poe2value.ui import theme
from poe2value.ui.components import StatusValue, make_button
from poe2value.ui.styles import DASHBOARD_STYLESHEET


class OnboardingDialog(QDialog):
    """One setup dashboard; it observes the normal controller and starts nothing."""

    def __init__(self, settings: AppSettings, controller, *, on_diagnostics: Callable[[], None] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.settings, self.controller, self._on_diagnostics = settings, controller, on_diagnostics
        self.setWindowTitle(window_title("Setup")); self.setMinimumSize(560, 520); self.resize(620, 560)
        self.setModal(False); self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        if (icon := app_icon()) is not None: self.setWindowIcon(icon)
        self.setStyleSheet(DASHBOARD_STYLESHEET + """
QDialog { background:#17181b; color:#e3e1dc; font-family:'Segoe UI'; }
QWidget#onboardingCard { background:rgba(255,255,255,10); border:1px solid rgba(255,255,255,18); border-radius:8px; }
QLabel#onboardingTitle { font-size:22px; font-weight:700; color:#f5f3ee; }
QLabel#onboardingSubtitle,QLabel#onboardingDetail { font-size:12px; color:#8b8a85; }
QLabel#onboardingCardTitle { font-size:14px; font-weight:700; color:#f5f3ee; }
""")
        root = QVBoxLayout(self); root.setContentsMargins(24, 24, 24, 24); root.setSpacing(theme.SPACE_LG)
        header = QHBoxLayout(); header.setSpacing(theme.SPACE_SM)
        if (icon := app_icon()) is not None:
            logo = QLabel(); logo.setPixmap(icon.pixmap(30, 30)); header.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        heading = QVBoxLayout(); heading.setSpacing(2)
        title = QLabel("ExileLens Setup"); title.setObjectName("onboardingTitle"); heading.addWidget(title)
        self._subtitle = QLabel("Get ExileLens ready for item checks"); self._subtitle.setObjectName("onboardingSubtitle"); heading.addWidget(self._subtitle)
        header.addLayout(heading, 1)
        self._overall = StatusValue("Checking setup…", "neutral"); header.addWidget(self._overall, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)
        self._pob_card, self._pob_status, self._pob_detail, self._pob_action = self._card("Path of Building 2", "Configure")
        self._build_card, self._build_status, self._build_detail, self._build_action = self._card("Current Build", "Choose build")
        self._item_card, self._item_status, self._item_detail, _ = self._card("Item Check", "")
        root.addWidget(self._pob_card); root.addWidget(self._build_card); root.addWidget(self._item_card)
        self._pob_action.clicked.connect(self._choose_pob); self._build_action.clicked.connect(self._choose_build)
        footer = QHBoxLayout(); self._diagnostics = make_button("Diagnostics", "tertiary"); self._diagnostics.clicked.connect(self._open_diagnostics)
        footer.addWidget(self._diagnostics); footer.addStretch(1)
        self._skip = make_button("Skip for now", "tertiary"); self._skip.clicked.connect(self._skip_onboarding); footer.addWidget(self._skip)
        self._finish = make_button("Start using ExileLens", "primary"); self._finish.clicked.connect(self._finish_onboarding); footer.addWidget(self._finish); root.addLayout(footer)
        controller.build_changed.connect(lambda _info: self.refresh()); controller.engine_ready.connect(self.refresh); controller.engine_failed.connect(lambda _msg: self.refresh()); self.refresh()

    def _card(self, title: str, action: str):
        card = QFrame(); card.setObjectName("onboardingCard"); row = QHBoxLayout(card); row.setContentsMargins(16, 12, 12, 12)
        text = QVBoxLayout(); text.setSpacing(4); heading = QLabel(title); heading.setObjectName("onboardingCardTitle"); text.addWidget(heading)
        status = StatusValue("Checking…", "neutral"); detail = QLabel(); detail.setObjectName("onboardingDetail"); detail.setWordWrap(True); text.addWidget(status); text.addWidget(detail); row.addLayout(text, 1)
        button = make_button(action, "secondary") if action else None
        if button: row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        return card, status, detail, button

    def _hotkey(self) -> str: return str(getattr(self.settings, "price_check_hotkey", "shift+c") or "shift+c").upper()
    def _pob_text(self) -> str:
        from poe2value.app.setup_status import check_pob_folder
        check = check_pob_folder(self.settings.pob_path)
        if not check.ok: return check.detail or check.label
        try:
            from poe2value.config import detect_pob_identity
            version = detect_pob_identity(self.settings.pob_path).version
            return f"Version {version}" if version != "unknown" else "Detected"
        except Exception: return "Detected"
    @staticmethod
    def _tone(state: AppReadiness) -> str:
        if state is AppReadiness.READY: return "ok"
        if state in {AppReadiness.POB_NOT_FOUND, AppReadiness.BUILD_ERROR, AppReadiness.RUNTIME_ERROR}: return "error"
        return "warn" if state in {AppReadiness.BUILD_REQUIRED, AppReadiness.BUILD_LOADING} else "neutral"

    def refresh(self) -> None:
        status = derive_readiness(self.settings, self.controller); tone = self._tone(status.state)
        self._overall.set_value("READY" if status.ready else ("Needs attention" if tone == "error" else "Setup required" if tone == "warn" else "Initializing"), tone)
        pob_bad = status.state is AppReadiness.POB_NOT_FOUND
        self._pob_status.set_value("Not found" if pob_bad else ("Needs attention" if status.state is AppReadiness.RUNTIME_ERROR else "Detected"), "error" if pob_bad or status.state is AppReadiness.RUNTIME_ERROR else "ok")
        self._pob_detail.setText(self._pob_text()); self._pob_action.setText("Configure" if pob_bad else "Change")
        build_text = "Ready" if status.ready else "Loading…" if status.state is AppReadiness.BUILD_LOADING else "Couldn’t be loaded" if status.state is AppReadiness.BUILD_ERROR else "Build required"
        self._build_status.set_value(build_text, "ok" if status.ready else tone)
        self._build_detail.setText(status.detail if status.state in {AppReadiness.BUILD_ERROR, AppReadiness.BUILD_LOADING} else (getattr(self.controller.build_info, "name", "") or "Choose the PoB build you play."))
        self._build_action.setText("Retry" if status.state is AppReadiness.BUILD_ERROR else ("Switch build" if getattr(self.controller.build_info, "name", "") else "Choose build"))
        self._build_action.setEnabled(status.state not in {AppReadiness.INITIALIZING, AppReadiness.POB_NOT_FOUND, AppReadiness.RUNTIME_ERROR})
        self._item_status.set_value("Ready" if status.ready else "Waiting for setup", "ok" if status.ready else "neutral")
        self._item_detail.setText(f"Hover an item in PoE2    [ {self._hotkey().replace('+', ' + ')} ]" if status.ready else "Item Check will be ready when Path of Building and a build are ready.")
        self._item_detail.setStyleSheet("font-weight:700; color:#f5f3ee;" if status.ready else "")
        self._finish.setEnabled(status.ready); self._skip.setVisible(not status.ready); self._diagnostics.setVisible(status.support_action_available)
        if status.ready:
            self._subtitle.setText("Ready for item checks")
            self._item_card.setStyleSheet("QWidget#onboardingCard { border: 1px solid rgba(203,184,146,110); background: rgba(203,184,146,18); }")
        else:
            self._subtitle.setText("Get ExileLens ready for item checks")
            self._item_card.setStyleSheet("")

    def _choose_pob(self) -> None:
        from poe2value.ui.setup_dialog import pick_pob_directory
        if path := pick_pob_directory(self.settings.pob_path): self.settings.pob_path = path; save_settings(self.settings); self.controller.restart_engine(); self.refresh()
    def _choose_build(self) -> None:
        if derive_readiness(self.settings, self.controller).state is AppReadiness.BUILD_ERROR: self.controller.reload_evaluation_build(); return
        from poe2value.ui.setup_dialog import pick_build_file
        if path := pick_build_file(self.settings.build_path):
            self.settings.build_path = str(Path(path)); save_settings(self.settings)
            if self.controller.engine_status() == "ready": self.controller.load_build(self.settings.build_path, context=self.settings.context)
            self.refresh()
    def _open_diagnostics(self) -> None:
        if self._on_diagnostics: self._on_diagnostics()
    def _finish_onboarding(self) -> None:
        if derive_readiness(self.settings, self.controller).ready: complete_onboarding(self.settings); self.accept()
    def _skip_onboarding(self) -> None: complete_onboarding(self.settings); self.reject()
    def closeEvent(self, event) -> None:  # noqa: N802
        if onboarding_required(self.settings): complete_onboarding(self.settings)
        super().closeEvent(event)
