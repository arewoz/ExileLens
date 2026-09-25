from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSignalBlocker, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from exilelens.app.controller import EvaluationController
from exilelens.app.settings import AppSettings, save_settings
from exilelens.ui.overlay import OverlayWindow
from exilelens.ui.styles import apply_scroll_area_theme


class HotkeyCaptureDialog(QDialog):
    """Capture one keyboard chord without installing another global hook."""

    def __init__(self, refine_hotkey: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.refine_hotkey = refine_hotkey
        self.binding = ""
        self.setWindowTitle("Change Item Check hotkey")
        self._label = QLabel("Press the new shortcut…")
        self._label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self._label)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.isAutoRepeat():
            return
        key = int(event.key())
        if key in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            token = chr(key).lower()
        elif Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
            token = f"f{key - int(Qt.Key.Key_F1) + 1}"
        else:
            self._label.setText("Use a letter, digit, or F1–F24 key with a modifier.")
            return
        mods = event.modifiers()
        parts = []
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("shift")
        if mods & Qt.KeyboardModifier.MetaModifier:
            parts.append("win")
        from exilelens.platform.windows.hotkey_binding import validate_hotkey

        canonical, error = validate_hotkey("+".join([*parts, token]), refine_hotkey=self.refine_hotkey)
        if error:
            self._label.setText(error)
            return
        self.binding = canonical
        self.accept()


class SettingsPage(QWidget):
    def __init__(
        self,
        settings: AppSettings,
        controller: EvaluationController,
        update_service=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self.settings = settings
        self.controller = controller
        self.update_service = update_service

        from exilelens.ui import theme
        from exilelens.ui.components import Section

        title = QLabel("Settings")
        title.setObjectName("pageTitle")

        # Built first: later sections reference the widgets these create.
        self._build_shared_controls()

        content = QWidget()
        content.setObjectName("settingsScrollContent")
        content.setMinimumWidth(440)
        content.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(theme.SECTION_GAP)
        for section in (
            self._build_pob_section(),
            self._build_evaluation_section(),
            self._build_overlay_section(),
            self._build_hotkey_section(),
            self._build_updates_section(),
            self._build_advanced_section(),
            self._build_reset_section(),
        ):
            content_layout.addWidget(section)
        content_layout.addStretch(1)

        self._scroll_area = QScrollArea()
        self._scroll_area.setObjectName("settingsScrollArea")
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setWidget(content)
        apply_scroll_area_theme(self._scroll_area, viewport_object_name="settingsScrollViewport")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_LG)
        layout.addWidget(title)
        layout.addWidget(self._scroll_area, 1)

        controller.value_profile_changed.connect(self._on_profile_changed_externally)
        controller.build_changed.connect(lambda _info: self.refresh_setup_status())
        controller.baseline_state_changed.connect(lambda _state: self.refresh_setup_status())
        controller.engine_ready.connect(self.refresh_setup_status)
        controller.engine_failed.connect(lambda _msg: self.refresh_setup_status())
        self.refresh_setup_status()

    # --- construction -----------------------------------------------------------

    def _build_shared_controls(self) -> None:
        """Create every control up front, so sections only arrange them.

        The two path line edits are real, editable controls kept under Advanced.
        The primary surface shows a value and a Change button instead, but pasting
        a path directly stays possible and the widgets stay live.
        """
        settings = self.settings

        self._pob_edit = QLineEdit(settings.pob_path)
        self._pob_edit.editingFinished.connect(self._persist_pob_path)
        self._build_edit = QLineEdit(settings.build_path or self.controller.build_info.path)

        for label_attr in ("_pob_status", "_build_file_status", "_engine_status", "_loaded_status"):
            label = QLabel()
            label.setWordWrap(True)
            label.setObjectName("helperText")
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            setattr(self, label_attr, label)

        self._context = QComboBox()
        self._context.addItem("Map", "MAP")
        self._context.addItem("Boss", "BOSS")
        index = self._context.findData(settings.context)
        self._context.setCurrentIndex(max(index, 0))
        self._context.currentIndexChanged.connect(self._on_context_changed)

        from exilelens.ui.profile_catalog import PROFILE_CARDS

        self._profile_combo = QComboBox()
        for card in PROFILE_CARDS:
            self._profile_combo.addItem(card.title, card.profile.value)
        profile_index = self._profile_combo.findData(str(settings.value_profile or "BALANCED"))
        self._profile_combo.setCurrentIndex(max(profile_index, 0))
        self._profile_combo.currentIndexChanged.connect(self._on_profile_combo_changed)

        self._ui_scale = QComboBox()
        for percent, value in (("80%", 0.8), ("100%", 1.0), ("120%", 1.2), ("140%", 1.4), ("160%", 1.6)):
            self._ui_scale.addItem(percent, value)
        current_scale = float(getattr(settings, "ui_scale", 1.0) or 1.0)
        scale_index = self._ui_scale.findData(current_scale)
        self._ui_scale.setCurrentIndex(max(scale_index, 0) if scale_index >= 0 else 1)
        self._ui_scale.currentIndexChanged.connect(self._on_ui_scale_changed)

        self._auto_hide = QLineEdit(str(settings.overlay_auto_hide_seconds))
        self._auto_hide.editingFinished.connect(self._persist_numeric_settings)
        self._auto_hide.setMaximumWidth(90)

        self._dedup = QLineEdit(str(settings.dedup_window_seconds))
        self._dedup.editingFinished.connect(self._persist_numeric_settings)
        self._dedup.setMaximumWidth(90)

        from exilelens.ui.components import ThemedCheckBox

        self._show_hints = ThemedCheckBox("Show hotkey hints")
        self._show_hints.setChecked(bool(getattr(settings, "show_hotkey_hints", True)))
        self._show_hints.toggled.connect(self._on_show_hints_changed)

        self._ignore_socketed_mods = ThemedCheckBox("Ignore socketed Runes")
        self._ignore_socketed_mods.setToolTip(
            "Compare items without the effects of socketed Runes. Runes are ignored on"
            " both the equipped item and the item being checked."
        )
        self._ignore_socketed_mods.setChecked(
            bool(self.controller.item_check_settings().ignore_socketed_mods)
        )
        self._ignore_socketed_mods.toggled.connect(self._on_ignore_socketed_mods_changed)

        from exilelens.platform.windows.hotkey_binding import HotkeyBinding

        self._hotkey_label = QLabel(HotkeyBinding.parse(settings.price_check_hotkey).display)
        self._hotkey_label.setObjectName("cardTitle")
        self._hotkey_test_status = QLabel("")
        self._hotkey_test_status.setObjectName("helperText")
        self._hotkey_elevation_status = QLabel("")
        self._hotkey_elevation_status.setWordWrap(True)
        self._hotkey_elevation_status.setObjectName("helperText")
        self._hotkey_elevation_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.controller.price_check_hotkey.hotkey_tested.connect(self._hotkey_test_succeeded)

        self._live_market_label = QLabel(
            "Enabled" if str(settings.live_market_mode or "auto") != "disabled" else "Disabled"
        )
        self._live_market_label.setObjectName("secondaryText")

        self._build_league_controls()

    def _build_league_controls(self) -> None:
        from exilelens.price_check.league_catalog import LeagueCatalog
        from exilelens.price_check.league_resolver import MODE_PINNED

        self._league_catalog = LeagueCatalog.from_settings(self.settings)
        self._league_combo = QComboBox()
        self._league_combo.addItem("Auto-detect", "")
        for name in self._league_catalog.selectable_leagues():
            self._league_combo.addItem(name, name)
        saved = str(self.settings.market_league or "").strip()
        pinned = str(self.settings.market_league_mode or "").upper() == MODE_PINNED
        if pinned and saved:
            index = self._league_combo.findData(saved)
            if index < 0:
                self._league_combo.addItem(f"{saved} (not currently available)", saved)
                index = self._league_combo.count() - 1
            self._league_combo.setCurrentIndex(index)
        self._league_combo.currentIndexChanged.connect(self._apply_league_choice)
        self._league_status = QLabel(self._league_status_text())
        self._league_status.setObjectName("helperText")
        self._league_status.setWordWrap(True)
        self._league_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def _build_pob_section(self):
        from exilelens.ui.components import HealthRow, Section, button_row, make_button

        section = Section("Path of Building")
        # Named rows: "Connected" on its own does not say what is connected.
        self._pob_state = HealthRow("Path of Building")
        self._build_state = HealthRow("Build")
        section.add_widget(self._pob_state)
        section.add_widget(self._pob_status)
        section.add_widget(self._build_state)
        section.add_widget(self._loaded_status)

        self._change_pob_btn = make_button("Change PoB location", "secondary")
        self._change_pob_btn.clicked.connect(self._browse_pob)
        self._change_build_btn = make_button("Change build", "secondary")
        self._change_build_btn.clicked.connect(self._browse_build)
        # Surfaces only while the integration is actually down.
        self._reconnect_btn = make_button("Reconnect", "primary")
        self._reconnect_btn.clicked.connect(self._apply_pob_path)
        self._reconnect_btn.setVisible(False)
        section.add_layout(
            button_row([self._reconnect_btn, self._change_pob_btn, self._change_build_btn])
        )
        return section

    def _build_evaluation_section(self):
        from exilelens.ui.components import Section, SettingRow, button_row, make_button

        section = Section("Item evaluation")
        section.add_widget(SettingRow("Profile", self._profile_combo))
        section.add_widget(
            SettingRow(
                "Context",
                self._context,
                "How ExileLens evaluates the item in the current activity. Reloads the build.",
            )
        )
        # Selector, action and resolved state read as one unit: the action sits on
        # the same line as the control it refreshes, the state directly beneath.
        self._refresh_leagues_btn = make_button("Refresh", "tertiary")
        self._refresh_leagues_btn.clicked.connect(self._refresh_leagues)
        league_row = SettingRow("Market league", self._league_combo)
        league_row.add_trailing(self._refresh_leagues_btn)
        league_row.set_helper_widget(self._league_status)
        section.add_widget(league_row)
        section.add_widget(self._ignore_socketed_mods)
        return section

    def _build_overlay_section(self):
        from exilelens.ui.components import Section, SettingRow

        section = Section("Overlay")
        section.add_widget(SettingRow("UI scale", self._ui_scale))
        section.add_widget(SettingRow("Auto hide (seconds)", self._auto_hide))
        section.add_widget(self._show_hints)
        return section

    def _build_hotkey_section(self):
        from exilelens.ui import theme
        from exilelens.ui.components import Section, make_button

        section = Section("Hotkey")
        self._change_hotkey_btn = make_button("Change", "secondary")
        self._change_hotkey_btn.setObjectName("changeItemCheckHotkey")
        self._change_hotkey_btn.clicked.connect(self._change_hotkey)
        self._test_hotkey_btn = make_button("Test", "tertiary")
        self._test_hotkey_btn.setObjectName("testItemCheckHotkey")
        self._test_hotkey_btn.clicked.connect(self._test_hotkey)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_MD)
        caption = QLabel("Item check")
        caption.setObjectName("fieldLabel")
        row.addWidget(caption)
        row.addWidget(self._hotkey_label)
        row.addWidget(self._change_hotkey_btn)
        row.addWidget(self._test_hotkey_btn)
        row.addWidget(self._hotkey_test_status, 1)
        section.add_layout(row)
        section.add_widget(self._hotkey_elevation_status)
        return section

    def _build_updates_section(self):
        from exilelens.ui.components import Section

        section = Section("Updates")
        if self.update_service is None:
            note = QLabel("Update checks are unavailable in this view.")
            note.setObjectName("helperText")
            section.add_widget(note)
            return section
        from exilelens.ui.updates_panel import UpdatesPanel

        self._updates_panel = UpdatesPanel(self.settings, self.update_service)
        section.add_widget(self._updates_panel)
        return section

    def _build_advanced_section(self):
        from exilelens.ui.components import Disclosure, Section, SettingRow, button_row, make_button

        section = Section("Advanced")
        self._advanced = Disclosure("Troubleshooting & diagnostics")

        pob_row = QHBoxLayout()
        pob_row.setContentsMargins(0, 0, 0, 0)
        pob_row.addWidget(self._pob_edit, 1)
        pob_browse = make_button("Browse", "tertiary")
        pob_browse.clicked.connect(self._browse_pob)
        pob_apply = make_button("Apply", "secondary", tooltip="Reconnect using this folder")
        pob_apply.clicked.connect(self._apply_pob_path)
        pob_row.addWidget(pob_browse)
        pob_row.addWidget(pob_apply)
        self._advanced.add_widget(QLabel("Path of Building folder"))
        self._advanced.add_layout(pob_row)

        build_row = QHBoxLayout()
        build_row.setContentsMargins(0, 0, 0, 0)
        build_row.addWidget(self._build_edit, 1)
        build_browse = make_button("Browse", "tertiary")
        build_browse.clicked.connect(self._browse_build)
        build_load = make_button("Load", "secondary")
        build_load.clicked.connect(self._load_build_from_edit)
        build_row.addWidget(build_browse)
        build_row.addWidget(build_load)
        self._advanced.add_widget(QLabel("Build file"))
        self._advanced.add_layout(build_row)
        self._advanced.add_widget(self._build_file_status)

        self._advanced.add_widget(SettingRow("Dedup window (seconds)", self._dedup))
        self._advanced.add_widget(SettingRow("Live market", self._live_market_label))

        reload_btn = make_button("Reload build", "secondary")
        reload_btn.setToolTip("Reload the active build from disk without restarting ExileLens.")
        reload_btn.clicked.connect(self._reload_build)
        self._advanced.add_layout(button_row([reload_btn]))

        section.add_widget(self._advanced)
        return section

    def _build_reset_section(self):
        from exilelens.ui.components import Section, button_row, make_button

        section = Section("Reset configuration")
        note = QLabel(
            "Restores ExileLens defaults and forgets your PoB folder, build and "
            "preferences. A backup is kept. Path of Building, your builds and game "
            "files are not touched."
        )
        note.setObjectName("helperText")
        note.setWordWrap(True)
        section.add_widget(note)
        self._reset_btn = make_button("Reset configuration", "destructive")
        self._reset_btn.clicked.connect(self._reset_configuration)
        section.add_layout(button_row([self._reset_btn]))
        return section

    # --- setup / recovery -------------------------------------------------------

    def _on_profile_combo_changed(self) -> None:
        value = str(self._profile_combo.currentData() or "BALANCED")
        if value != str(self.settings.value_profile or ""):
            self.controller.select_value_profile(value)

    def _on_profile_changed_externally(self, profile: str) -> None:
        index = self._profile_combo.findData(profile)
        if index >= 0 and index != self._profile_combo.currentIndex():
            with QSignalBlocker(self._profile_combo):
                self._profile_combo.setCurrentIndex(index)

    def refresh_setup_status(self) -> None:
        from exilelens.app.setup_status import (
            check_build_file,
            check_pob_folder,
            describe_build_state,
            describe_engine,
        )

        pob = check_pob_folder(self._pob_edit.text())
        build_file = check_build_file(self._build_edit.text())
        engine = describe_engine(self.controller.engine_status())
        loaded = describe_build_state(self.controller.build_info)
        for label, check in (
            (self._pob_status, pob),
            (self._build_file_status, build_file),
            (self._engine_status, engine),
            (self._loaded_status, loaded),
        ):
            # The row beside this already names the state ("* Not found"), so the
            # detail line carries only the explanation, not "NOT FOUND -- " again.
            label.setText(check.detail or check.label)
            label.setProperty("setupOk", check.ok)
            label.setStyleSheet("" if check.ok else "color: #e0a040;")
        import time

        loaded_text = loaded.detail or loaded.label
        loaded_at = getattr(self.controller, "build_loaded_at", None)
        if loaded.ok and isinstance(loaded_at, (int, float)):
            loaded_text += f" · loaded {time.strftime('%H:%M:%S', time.localtime(loaded_at))}"
        warning = getattr(self.controller, "reload_warning", "")
        if isinstance(warning, str) and warning:
            loaded_text += f"\n{warning}"
            self._loaded_status.setStyleSheet("color: #e0a040;")
        self._loaded_status.setText(loaded_text)
        from exilelens.platform.windows.elevation import evaluate_elevation_status

        elevation = evaluate_elevation_status()
        self._hotkey_elevation_status.setText(elevation.detail if elevation.mismatch else "")
        self._hotkey_elevation_status.setVisible(bool(elevation.mismatch))
        self._hotkey_elevation_status.setStyleSheet("color: #e0a040;" if elevation.mismatch else "")

        self._apply_health_presentation()

    def _apply_health_presentation(self) -> None:
        """Healthy configuration is quiet; problems get the detail and the action."""
        from exilelens.app.setup_status import check_build_file
        from exilelens.ui.health import derive_health

        health = derive_health(self.controller, self.settings)

        self._pob_state.set_value(health.pob.value, health.pob.status)
        # Detail lines only earn their space when something is wrong.
        self._pob_status.setVisible(health.pob.status != "ok")
        self._reconnect_btn.setVisible(
            health.pob.status in ("warn", "error") and health.pob.value != "Not found"
        )

        build = health.build
        self._build_state.set_value(build.value, build.status)
        show_build_detail = build.status != "ok" or bool(
            getattr(self.controller, "reload_warning", "")
        )
        self._loaded_status.setVisible(show_build_detail)
        # "FOUND" next to a healthy build file is noise; the check only earns space
        # when it has a problem to report.
        self._build_file_status.setVisible(not check_build_file(self._build_edit.text()).ok)

    def _apply_pob_path(self) -> None:
        candidate = self._pob_edit.text().strip()
        from exilelens.app.setup_status import check_pob_folder

        check = check_pob_folder(candidate)
        if not check.ok:
            self._pob_edit.setText(self.settings.pob_path)
            self.refresh_setup_status()
            QMessageBox.warning(self, "Path of Building", check.text())
            return

        self.settings.pob_path = candidate
        save_settings(self.settings)
        self.refresh_setup_status()
        self.controller.restart_engine()
        self.refresh_setup_status()

    def _browse_build(self) -> None:
        from exilelens.ui.setup_dialog import pick_build_file

        path = pick_build_file(self._build_edit.text())
        if path:
            self._build_edit.setText(path)
            self._load_build_from_edit()

    def _load_build_from_edit(self) -> None:
        from pathlib import Path

        from exilelens.app.setup_status import check_build_file

        path = self._build_edit.text().strip()
        check = check_build_file(path)
        self.refresh_setup_status()
        if not check.ok:
            QMessageBox.warning(self, "Build file", check.text())
            return
        if self.controller.engine_status() != "ready":
            self.settings.build_path = path
            save_settings(self.settings)
            self._build_file_status.setText("FOUND — saved; it loads as soon as Path of Building is running.")
            return
        self.controller.change_build(path)
        if self.controller.build_info.path != str(Path(path).resolve()) or not self.controller.build_info.is_ready:
            reason = self.controller.last_build_error or "unknown error"
            QMessageBox.warning(self, "Build file", f"Couldn't load this build:\n{reason}")
        self.refresh_setup_status()

    def _reload_build(self) -> None:
        self.controller.reload_evaluation_build()
        self.refresh_setup_status()

    def _reset_configuration(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reset configuration",
            "Reset ExileLens settings to their defaults?\n\n"
            "This forgets the PoB folder, the selected build and your preferences. "
            "A backup of the current settings file is kept.\n\n"
            "Path of Building, your builds and game files are not touched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.perform_reset()

    def perform_reset(self) -> None:
        from exilelens.app.build_cache import BuildCache
        from exilelens.app.settings import reset_settings

        backup = reset_settings(self.settings)
        BuildCache().clear_active()
        self._pob_edit.setText(self.settings.pob_path)
        self._build_edit.setText("")
        self.refresh_setup_status()
        self.controller.restart_engine()
        QMessageBox.information(
            self,
            "Reset configuration",
            "Settings were reset."
            + (f"\n\nBackup: {backup}" if backup else "")
            + "\n\nChoose your Path of Building folder and build file above.",
        )

    def _league_status_text(self) -> str:
        saved = str(self.settings.market_league or "").strip()
        if not saved:
            return "Not resolved yet"
        mode = str(self.settings.market_league_mode or "AUTO").upper()
        return f"{saved} ({'pinned' if mode == 'PINNED' else 'auto-detected'})"

    def _refresh_leagues(self) -> None:
        from exilelens.price_check.league_catalog import LOOKUP_OK

        result = self._league_catalog.refresh(force=True)
        if result.status == LOOKUP_OK:
            self._league_catalog.write_to_settings(self.settings)
            selected = self._league_combo.currentData()
            self._league_combo.blockSignals(True)
            self._league_combo.clear()
            self._league_combo.addItem("Auto-detect", "")
            for name in self._league_catalog.selectable_leagues():
                self._league_combo.addItem(name, name)
            index = self._league_combo.findData(selected)
            self._league_combo.setCurrentIndex(max(index, 0))
            self._league_combo.blockSignals(False)
            self._league_status.setText(self._league_status_text())
            save_settings(self.settings)
            return
        QMessageBox.information(
            self,
            "Market",
            "Could not refresh the league list right now "
            f"({result.status.replace('_', ' ').lower()}). The saved list is still in use.",
        )

    def _persist_pob_path(self) -> None:
        path = self._pob_edit.text().strip()
        if path == self.settings.pob_path:
            return
        from exilelens.app.setup_status import check_pob_folder

        check = check_pob_folder(path)
        if not check.ok:
            self._pob_edit.setText(self.settings.pob_path)
            self.refresh_setup_status()
            return
        self.settings.pob_path = path
        save_settings(self.settings)
        self.refresh_setup_status()

    def _browse_pob(self) -> None:
        from exilelens.ui.setup_dialog import pick_pob_directory

        path = pick_pob_directory(self._pob_edit.text())
        if path:
            self._pob_edit.setText(path)
            self._persist_pob_path()
            self.refresh_setup_status()

    def _on_context_changed(self) -> None:
        context = str(self._context.currentData() or "MAP")
        self.settings.context = context
        save_settings(self.settings)
        self.controller.set_context(context)

    def _on_ui_scale_changed(self) -> None:
        self.settings.ui_scale = float(self._ui_scale.currentData() or 1.0)
        save_settings(self.settings)
        from PySide6.QtWidgets import QApplication

        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, OverlayWindow):
                widget.apply_ui_scale(float(self.settings.ui_scale or 1.0))

    def _on_show_hints_changed(self, enabled: bool) -> None:
        self.settings.show_hotkey_hints = bool(enabled)
        if enabled:
            self.settings.hotkey_hints_dismissed = False
        save_settings(self.settings)

    def _on_ignore_socketed_mods_changed(self, enabled: bool) -> None:
        self.controller.update_item_check_settings(ignore_socketed_mods=bool(enabled))
        save_settings(self.settings)

    def _change_hotkey(self) -> None:
        dialog = HotkeyCaptureDialog(self.settings.price_check_refine_hotkey, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.binding:
            return
        self.settings.price_check_hotkey = dialog.binding
        save_settings(self.settings)
        self.controller.price_check_hotkey.reconfigure(dialog.binding)
        from exilelens.platform.windows.hotkey_binding import HotkeyBinding

        self._hotkey_label.setText(HotkeyBinding.parse(dialog.binding).display)
        self._hotkey_test_status.setText("Saved")

    def _test_hotkey(self) -> None:
        from exilelens.platform.windows.hotkey_binding import HotkeyBinding

        display = HotkeyBinding.parse(self.settings.price_check_hotkey).display
        self._hotkey_test_status.setText(f"Waiting for {display}…")
        self.controller.price_check_hotkey.set_test_mode(True)
        QTimer.singleShot(10000, self._stop_hotkey_test)

    def _stop_hotkey_test(self) -> None:
        self.controller.price_check_hotkey.set_test_mode(False)
        if self._hotkey_test_status.text().startswith("Waiting"):
            self._hotkey_test_status.setText("Test timed out")

    def _hotkey_test_succeeded(self) -> None:
        self.controller.price_check_hotkey.set_test_mode(False)
        from exilelens.platform.windows.hotkey_binding import HotkeyBinding

        display = HotkeyBinding.parse(self.settings.price_check_hotkey).display
        self._hotkey_test_status.setText(f"✓ {display} detected")

    def _persist_numeric_settings(self) -> None:
        try:
            self.settings.overlay_auto_hide_seconds = float(self._auto_hide.text())
            self.settings.dedup_window_seconds = float(self._dedup.text())
        except ValueError:
            return
        save_settings(self.settings)

    def _apply_league_choice(self) -> None:
        from exilelens.price_check.league_resolver import MODE_AUTO, MODE_PINNED

        chosen = str(self._league_combo.currentData() or "").strip()
        if chosen:
            self.settings.market_league = chosen
            self.settings.market_league_mode = MODE_PINNED
        else:
            self.settings.market_league_mode = MODE_AUTO
        self._league_catalog.write_to_settings(self.settings)
        self._league_status.setText(self._league_status_text())
        save_settings(self.settings)


class DiagnosticsPage(QWidget):
    """Player-facing health summary and support actions."""

    #: Health rows, in the order they are shown.
    HEALTH_KEYS = ("app", "pob", "build", "hotkey", "market")

    def __init__(self, controller: EvaluationController, settings: AppSettings, update_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("diagnosticsPage")
        self.controller = controller
        self.settings = settings
        self.update_service = update_service

        from exilelens.ui import theme
        from exilelens.ui.components import Disclosure, HealthRow, Section, button_row, make_button
        from exilelens.ui.ui_icons import apply_button_icon

        ui_scale = float(getattr(settings, "ui_scale", 1.0) or 1.0)

        title = QLabel("Diagnostics")
        title.setObjectName("pageTitle")

        health = Section("Application health")
        health_intro = QLabel(
            "A quick view of whether ExileLens is ready to use. Details appear when something needs attention."
        )
        health_intro.setObjectName("helperText")
        health_intro.setWordWrap(True)
        health.add_widget(health_intro)
        self._health_rows: dict[str, HealthRow] = {}
        for key, label in (
            ("app", "ExileLens"),
            ("pob", "Path of Building"),
            ("build", "Build"),
            ("hotkey", "Item check hotkey"),
            ("market", "Market"),
        ):
            row = HealthRow(label)
            self._health_rows[key] = row
            health.add_widget(row)
        self._support_hint = QLabel("")
        self._support_hint.setObjectName("helperText")
        self._support_hint.setWordWrap(True)
        self._support_hint.setVisible(False)
        health.add_widget(self._support_hint)

        report = Section("Report a problem")
        report_intro = QLabel(
            "Copy diagnostics or export a support package, then open a GitHub issue if you need help. "
            "Nothing is sent automatically."
        )
        report_intro.setObjectName("helperText")
        report_intro.setWordWrap(True)
        report.add_widget(report_intro)
        self._repro_notes = QTextEdit()
        self._repro_notes.setPlaceholderText("Optional: what were you doing when the problem happened?")
        self._repro_notes.setMaximumHeight(72)
        report.add_widget(self._repro_notes)
        self._copy_btn = make_button("Copy diagnostics", "primary")
        self._copy_btn.setToolTip("Copies a privacy-safe diagnostic summary for GitHub issues.")
        self._copy_btn.clicked.connect(self._copy)
        self._export_bundle_btn = make_button("Export support package", "secondary")
        self._export_bundle_btn.setToolTip("Save a reviewed ZIP bundle for support (logs and diagnostics).")
        self._export_bundle_btn.clicked.connect(self._export_support_bundle)
        self._report_issue_btn = make_button("Report an issue", "tertiary")
        self._report_issue_btn.setToolTip("Open the ExileLens issue tracker on GitHub.")
        self._report_issue_btn.clicked.connect(self._open_github_issues)
        apply_button_icon(self._report_issue_btn, "github", ui_scale=ui_scale)
        report.add_layout(button_row([self._copy_btn, self._export_bundle_btn, self._report_issue_btn]))
        self._report_status = QLabel("")
        self._report_status.setObjectName("helperText")
        self._report_status.setWordWrap(True)
        report.add_widget(self._report_status)

        self._advanced = Disclosure("Advanced diagnostics")
        self._session_label = QLabel("")
        self._session_label.setObjectName("helperText")
        self._session_label.setWordWrap(True)
        session_help = QLabel("Support session ID helps match your report to in-app events.")
        session_help.setObjectName("helperText")
        session_help.setWordWrap(True)
        self._advanced.add_widget(session_help)
        self._advanced.add_widget(self._session_label)

        event_help = QLabel("Recent in-app diagnostic events (privacy filtered).")
        event_help.setObjectName("helperText")
        event_help.setWordWrap(True)
        self._advanced.add_widget(event_help)
        self._event_history_text = QTextEdit()
        self._event_history_text.setReadOnly(True)
        self._event_history_text.setMinimumHeight(140)
        self._advanced.add_widget(self._event_history_text)

        self._verbose_btn = make_button("Enable verbose diagnostics (15 min)", "tertiary")
        self._verbose_btn.setToolTip("Records extra diagnostic detail locally for the next 15 minutes.")
        self._verbose_btn.clicked.connect(self._enable_verbose_diagnostics)
        self._clear_history_btn = make_button("Clear diagnostic history", "tertiary")
        self._clear_history_btn.setToolTip("Removes stored diagnostic events from this installation.")
        self._clear_history_btn.clicked.connect(self._clear_diagnostic_history)
        self._logs_btn = make_button("Open logs", "secondary")
        self._logs_btn.setToolTip("Opens the ExileLens log folder in your file manager.")
        self._logs_btn.clicked.connect(self._open_logs)
        self._advanced.add_layout(button_row([self._verbose_btn, self._clear_history_btn, self._logs_btn]))

        raw_help = QLabel("Raw technical dump for deep troubleshooting (same data as Copy diagnostics, verbose).")
        raw_help.setObjectName("helperText")
        raw_help.setWordWrap(True)
        self._advanced.add_widget(raw_help)
        self._build_info = QLabel()
        self._build_info.setWordWrap(True)
        self._build_info.setObjectName("diagnosticsBuildInfo")
        self._build_info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._text.setMinimumHeight(220)
        self._text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._refresh_btn = make_button("Refresh", "tertiary")
        self._refresh_btn.clicked.connect(self.refresh)
        self._advanced.add_widget(self._build_info)
        self._advanced.add_widget(self._text)
        self._advanced.add_layout(button_row([self._refresh_btn]))

        content = QWidget()
        content.setObjectName("diagnosticsScrollContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(theme.SECTION_GAP)
        content_layout.addWidget(health)
        content_layout.addWidget(report)
        content_layout.addWidget(self._advanced)
        content_layout.addStretch(1)
        self._content_layout = content_layout

        self._scroll_area = QScrollArea()
        self._scroll_area.setObjectName("diagnosticsScrollArea")
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setWidget(content)
        apply_scroll_area_theme(self._scroll_area, viewport_object_name="diagnosticsScrollViewport")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_LG)
        layout.addWidget(title)
        layout.addWidget(self._scroll_area, 1)

        self._advanced.toggled.connect(self._on_advanced_toggled)
        self.refresh()

    def _on_advanced_toggled(self, expanded: bool) -> None:
        self._content_layout.setStretchFactor(self._advanced, 1 if expanded else 0)

    def health_summary(self) -> dict[str, tuple[str, str]]:
        """Test/debug helper: ``key -> (value, status)`` as currently rendered."""
        return {key: (row.value(), row.status()) for key, row in self._health_rows.items()}

    def _copy(self) -> None:
        from exilelens.ui.recovery_actions import copy_diagnostics

        self.refresh()
        copy_diagnostics(self.controller, self.settings, update_service=self.update_service)
        self._copy_btn.setText("Diagnostics copied")
        QTimer.singleShot(2500, lambda: self._copy_btn.setText("Copy diagnostics"))

    def _export_support_bundle(self) -> None:
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        from exilelens.diagnostics.bundle import SupportBundleError, write_support_bundle
        from exilelens.ui.support_bundle_dialog import SupportBundleReviewDialog

        dialog = SupportBundleReviewDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Export Support Bundle",
            "ExileLens-support-bundle.zip",
            "ZIP archives (*.zip)",
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".zip")
        try:
            write_support_bundle(
                destination,
                self.controller,
                self.settings,
                update_service=self.update_service,
                reproduction_notes=self._repro_notes.toPlainText(),
            )
        except SupportBundleError as exc:
            self._report_status.setText(str(exc))
            return
        self._report_status.setText(f"Support package saved to {destination.name}")
        self.refresh()

    def _clear_diagnostic_history(self) -> None:
        from exilelens.diagnostics import clear_event_history

        clear_event_history()
        self._report_status.setText("Diagnostic event history cleared.")
        self.refresh()

    def _enable_verbose_diagnostics(self) -> None:
        from exilelens.app.settings import save_settings
        from exilelens.diagnostics import enable_verbose_mode, verbose_mode_active

        enable_verbose_mode(self.settings)
        save_settings(self.settings)
        self._report_status.setText(
            "Verbose diagnostics enabled for 15 minutes." if verbose_mode_active(self.settings) else ""
        )
        self.refresh()

    def _open_logs(self) -> None:
        from exilelens.ui.recovery_actions import open_logs_folder

        open_logs_folder()

    def _open_github_issues(self) -> None:
        from exilelens.ui.recovery_actions import open_github_issues

        open_github_issues()

    def refresh(self) -> None:
        from exilelens.app.diagnostics import build_global_diagnostics
        from exilelens.ui.health import derive_health

        health = derive_health(self.controller, self.settings)
        for key in self.HEALTH_KEYS:
            item = getattr(health, key)
            # The value stays short; the explanation goes on its own wrapped line
            # so a long path can never set the width of the page.
            detail = item.detail if item.status in ("warn", "error") else ""
            self._health_rows[key].set_value(item.value, item.status, detail)

        degraded = [getattr(health, key) for key in self.HEALTH_KEYS if getattr(health, key).status in ("warn", "error")]
        if degraded:
            actions = [item.action for item in degraded if item.action]
            recovery = actions[0] if actions else "the relevant recovery action"
            self._support_hint.setText(f"Try {recovery} first. If the problem continues, see below.")
            self._support_hint.setVisible(True)
        else:
            self._support_hint.setVisible(False)

        from exilelens.diagnostics import build_extended_summary, event_buffer, verbose_mode_active
        import json

        report = build_global_diagnostics(self.controller)
        build_info = f"ExileLens {report.version}  |  build {report.build}  |  {report.mode}"
        self._build_info.setText(build_info)
        self._build_info.setToolTip(build_info)
        self._text.setPlainText(report.render())
        extended = build_extended_summary(self.controller, self.settings, update_service=self.update_service)
        session = extended.get("support_session_id", "")
        verbose = "on" if verbose_mode_active(self.settings) else "off"
        event_count = len(event_buffer().snapshot(include_verbose=verbose_mode_active(self.settings)))
        self._session_label.setText(f"Session ID: {session} · verbose {verbose} · {event_count} events recorded")
        events = event_buffer().export_records(
            include_verbose=verbose_mode_active(self.settings),
            limit=80,
        )
        self._event_history_text.setPlainText(json.dumps(events, indent=2))
