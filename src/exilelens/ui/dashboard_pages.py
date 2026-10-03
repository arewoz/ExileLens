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
from exilelens.ui import theme
from exilelens.ui.components import Disclosure, StatusValue, make_button
from exilelens.ui.dashboard_widgets import (
    ChevronComboBox,
    FlowLayout,
    ColumnPage,
    Hairline,
    HealthGridRow,
    KeycapDisplay,
    MonoPathLabel,
    SettingsGroup,
    SettingsRow,
    SettingsSection,
    ThemedSwitch,
)
from exilelens.ui.overlay import OverlayWindow
from exilelens.ui.ui_icons import outline_icon
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


class SettingsPage(ColumnPage):
    """One scrolling page of flat rows, in the shipped section order. Settings apply immediately."""

    def __init__(
        self,
        settings: AppSettings,
        controller: EvaluationController,
        update_service=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Settings", sticky_header=True, object_name="settingsPage", parent=parent)
        self.settings = settings
        self.controller = controller
        self.update_service = update_service
        self._scroll_area = self.scroll
        self.scroll.setObjectName("settingsScrollArea")

        # Built first: later sections reference the widgets these create.
        self._build_shared_controls()
        self._updates_section = self._build_updates_section()
        # Updates and Support ExileLens are one related block (supporter convenience under the update
        # controls): tighter spacing between the two than between ordinary sections, no card.
        supporter_block = QWidget()
        block = QVBoxLayout(supporter_block)
        block.setContentsMargins(0, 0, 0, 0)
        block.setSpacing(20)
        block.addWidget(self._updates_section)
        block.addWidget(self._build_patreon_section())
        for section in (
            self._build_pob_section(),
            self._build_hotkey_section(),
            supporter_block,
            self._build_evaluation_section(),
            self._build_overlay_section(),
            self._build_privacy_section(),
            self._build_advanced_section(),
            self._build_reset_section(),
        ):
            self.column.addWidget(section)
        self.finish()
        updates_panel = getattr(self, "_updates_panel", None)
        if updates_panel is not None:
            updates_panel.attach_seamless_controls(self._patreon_panel)

        controller.value_profile_changed.connect(self._on_profile_changed_externally)
        controller.build_changed.connect(lambda _info: self.refresh_setup_status())
        controller.baseline_state_changed.connect(lambda _state: self.refresh_setup_status())
        controller.engine_ready.connect(self.refresh_setup_status)
        controller.engine_failed.connect(lambda _msg: self.refresh_setup_status())
        self.refresh_setup_status()

    # --- page API ---------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-sync the live panels when the page is opened."""
        self.refresh_setup_status()
        privacy = getattr(self, "_privacy_panel", None)
        if privacy is not None:
            privacy.refresh()
        patreon = getattr(self, "_patreon_panel", None)
        if patreon is not None:
            patreon.render()

    def focus_updates(self) -> None:
        """Scroll the Updates section to the top (the rail's "Update available" link)."""
        self.scroll.ensureWidgetVisible(self._updates_section, 0, 12)
        self.scroll.verticalScrollBar().setValue(self._updates_section.y())

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

        self._context = ChevronComboBox()
        self._context.addItem("Map", "MAP")
        self._context.addItem("Boss", "BOSS")
        index = self._context.findData(settings.context)
        self._context.setCurrentIndex(max(index, 0))
        self._context.currentIndexChanged.connect(self._on_context_changed)

        from exilelens.ui.profile_catalog import PROFILE_CARDS

        self._profile_combo = ChevronComboBox()
        for card in PROFILE_CARDS:
            self._profile_combo.addItem(card.title, card.profile.value)
        profile_index = self._profile_combo.findData(str(settings.value_profile or "BALANCED"))
        self._profile_combo.setCurrentIndex(max(profile_index, 0))
        self._profile_combo.currentIndexChanged.connect(self._on_profile_combo_changed)

        self._ui_scale = ChevronComboBox()
        for percent, value in (("80%", 0.8), ("100%", 1.0), ("120%", 1.2), ("140%", 1.4), ("160%", 1.6)):
            self._ui_scale.addItem(percent, value)
        current_scale = float(getattr(settings, "ui_scale", 1.0) or 1.0)
        scale_index = self._ui_scale.findData(current_scale)
        self._ui_scale.setCurrentIndex(max(scale_index, 0) if scale_index >= 0 else 1)
        self._ui_scale.currentIndexChanged.connect(self._on_ui_scale_changed)

        self._auto_hide = QLineEdit(str(settings.overlay_auto_hide_seconds))
        self._auto_hide.editingFinished.connect(self._persist_numeric_settings)
        self._auto_hide.setFixedWidth(theme.SETTINGS_SELECT_WIDTH)
        self._auto_hide.setAccessibleName("Auto hide (seconds)")

        self._dedup = QLineEdit(str(settings.dedup_window_seconds))
        self._dedup.editingFinished.connect(self._persist_numeric_settings)
        self._dedup.setFixedWidth(theme.SETTINGS_SELECT_WIDTH)
        self._dedup.setAccessibleName("Dedup window (seconds)")

        self._show_hints = ThemedSwitch("Show hotkey hints")
        self._show_hints.setChecked(bool(getattr(settings, "show_hotkey_hints", True)))
        self._show_hints.toggled.connect(self._on_show_hints_changed)

        self._ignore_socketed_mods = ThemedSwitch("Ignore socketed Runes")
        self._ignore_socketed_mods.setToolTip(
            "Compare items without the effects of socketed Runes. Runes are ignored on"
            " both the equipped item and the item being checked."
        )
        self._ignore_socketed_mods.setChecked(
            bool(self.controller.item_check_settings().ignore_socketed_mods)
        )
        self._ignore_socketed_mods.toggled.connect(self._on_ignore_socketed_mods_changed)

        from exilelens.platform.windows.hotkey_binding import HotkeyBinding

        self._hotkey_label = KeycapDisplay(HotkeyBinding.parse(settings.price_check_hotkey).display)
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
        self._league_combo = ChevronComboBox()
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
        section = SettingsSection("Path of Building")
        # Named rows: "Connected" on its own does not say what is connected.
        self._pob_state = StatusValue("", "neutral")
        self._pob_state.set_word_wrap(False)
        self._build_state = StatusValue("", "neutral")
        self._build_state.set_word_wrap(False)
        self._pob_path_label = MonoPathLabel(self._pob_edit.text())
        self._build_path_label = MonoPathLabel(self._build_edit.text())
        self._pob_edit.textChanged.connect(self._pob_path_label.set_full_text)
        self._build_edit.textChanged.connect(self._build_path_label.set_full_text)

        self._change_pob_btn = make_button("Change location", "secondary", compact=True)
        self._change_pob_btn.clicked.connect(self._browse_pob)
        self._detect_pob_btn = make_button("Detect", "tertiary", compact=True, tooltip="Look for Path of Building automatically")
        self._detect_pob_btn.clicked.connect(self._auto_detect_pob)
        self._change_build_btn = make_button("Change build", "secondary", compact=True)
        self._change_build_btn.clicked.connect(self._browse_build)
        # Surfaces only while the integration is actually down.
        self._reconnect_btn = make_button("Reconnect", "primary", compact=True)
        self._reconnect_btn.clicked.connect(self._apply_pob_path)
        self._reconnect_btn.setVisible(False)

        install = SettingsRow("Installation")
        install.add_left(self._pob_state)
        install.add_left(self._pob_path_label)
        install.add_left(self._pob_status)
        for button in (self._reconnect_btn, self._detect_pob_btn, self._change_pob_btn):
            install.add_control(button)
        section.add_row(install)

        build = SettingsRow("Build")
        build.add_left(self._build_state)
        build.add_left(self._build_path_label)
        build.add_left(self._loaded_status)
        build.add_control(self._change_build_btn)
        section.add_row(build)
        return section

    def _build_evaluation_section(self):
        section = SettingsSection("Item evaluation")
        row = SettingsRow("Profile")
        row.add_control(self._profile_combo)
        section.add_row(row)
        row = SettingsRow("Context", "Evaluation context. Reloads the build.")
        row.add_control(self._context)
        section.add_row(row)
        # Selector, action and resolved state read as one unit: the action sits on
        # the same line as the control it refreshes, the state directly beneath.
        self._refresh_leagues_btn = make_button("Refresh", "tertiary", compact=True)
        self._refresh_leagues_btn.clicked.connect(self._refresh_leagues)
        row = SettingsRow("Market league")
        row.add_left(self._league_status)
        row.add_control(self._league_combo)
        row.add_control(self._refresh_leagues_btn)
        section.add_row(row)
        row = SettingsRow("Ignore socketed Runes")
        row.add_control(self._ignore_socketed_mods)
        section.add_row(row)
        return section

    def _build_overlay_section(self):
        section = SettingsSection("Overlay")
        row = SettingsRow("UI scale")
        row.add_control(self._ui_scale)
        section.add_row(row)
        row = SettingsRow("Auto hide (seconds)")
        row.add_control(self._auto_hide)
        section.add_row(row)
        row = SettingsRow("Show hotkey hints")
        row.add_control(self._show_hints)
        section.add_row(row)
        return section

    def _build_hotkey_section(self):
        section = SettingsSection("Hotkey")
        self._change_hotkey_btn = make_button("Change", "secondary", compact=True)
        self._change_hotkey_btn.setObjectName("changeItemCheckHotkey")
        self._change_hotkey_btn.clicked.connect(self._change_hotkey)
        self._test_hotkey_btn = make_button("Test", "tertiary", compact=True)
        self._test_hotkey_btn.setObjectName("testItemCheckHotkey")
        self._test_hotkey_btn.clicked.connect(self._test_hotkey)
        row = SettingsRow("Item check", "While hovering an item.")
        row.add_left(self._hotkey_test_status)
        row.add_left(self._hotkey_elevation_status)
        row.add_control(self._hotkey_label)
        row.add_control(self._change_hotkey_btn)
        row.add_control(self._test_hotkey_btn)
        section.add_row(row)
        return section

    def _build_updates_section(self):
        section = SettingsSection("Updates", with_group=False)
        if self.update_service is None:
            note = QLabel("Update checks are unavailable in this view.")
            note.setObjectName("helperText")
            section.add_panel(note)
            return section
        from exilelens.ui.updates_panel import UpdatesPanel

        self._updates_panel = UpdatesPanel(self.settings, self.update_service)
        section.add_panel(self._updates_panel)
        return section

    def _build_privacy_section(self):
        from exilelens.ui.privacy_panel import PrivacyPanel

        section = SettingsSection("Privacy", with_group=False)
        self._privacy_panel = PrivacyPanel(self.settings)
        section.add_panel(self._privacy_panel)
        return section

    def _build_patreon_section(self):
        from exilelens.ui.patreon_panel import PatreonPanel

        section = SettingsSection("Support ExileLens", with_group=False)
        self._patreon_panel = PatreonPanel(self.settings)
        section.set_heading_icon("patreon")  # the exact shipped mark, native colour, once
        section.add_panel(self._patreon_panel)
        return section

    def _build_advanced_section(self):
        section = SettingsSection("Advanced", with_group=False)
        self._advanced = Disclosure("Troubleshooting & diagnostics")
        group = SettingsGroup()

        row = SettingsRow("Path of Building folder")
        row.add_left(self._pob_edit)
        pob_browse = make_button("Browse", "tertiary", compact=True)
        pob_browse.clicked.connect(self._browse_pob)
        pob_detect = make_button("Auto-detect", "tertiary", compact=True, tooltip="Look for Path of Building automatically")
        pob_detect.clicked.connect(self._auto_detect_pob)
        pob_apply = make_button("Apply", "secondary", compact=True, tooltip="Reconnect using this folder")
        pob_apply.clicked.connect(self._apply_pob_path)
        for button in (pob_browse, pob_detect, pob_apply):
            row.add_control(button)
        group.add_row(row)

        row = SettingsRow("Build file")
        row.add_left(self._build_edit)
        row.add_left(self._build_file_status)
        build_browse = make_button("Browse", "tertiary", compact=True)
        build_browse.clicked.connect(self._browse_build)
        build_load = make_button("Load", "secondary", compact=True)
        build_load.clicked.connect(self._load_build_from_edit)
        row.add_control(build_browse)
        row.add_control(build_load)
        group.add_row(row)

        row = SettingsRow("Dedup window (seconds)")
        row.add_control(self._dedup)
        group.add_row(row)
        row = SettingsRow("Live market")
        row.add_control(self._live_market_label)
        group.add_row(row)
        reload_btn = make_button("Reload build", "secondary", compact=True)
        reload_btn.setToolTip("Reload the active build from disk without restarting ExileLens.")
        reload_btn.clicked.connect(self._reload_build)
        row = SettingsRow("Reload build")
        row.add_control(reload_btn)
        group.add_row(row)

        self._advanced.add_widget(group)
        section.add_panel(self._advanced)
        return section

    def _build_reset_section(self):
        host = QWidget()
        host.setObjectName("resetSection")
        column = QVBoxLayout(host)
        column.setContentsMargins(0, 8, 0, 0)  # the column's 28px section gap plus this keeps Reset clearly apart
        column.setSpacing(18)
        column.addWidget(Hairline())
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(24)
        note = QLabel(
            "Restores defaults and forgets your PoB folder, build and preferences. "
            "A backup is kept. Your builds and game files are not touched."
        )
        note.setObjectName("bodyText")
        note.setWordWrap(True)
        note.setMaximumWidth(560)
        self._reset_btn = make_button("Reset configuration", "destructive", compact=True)
        self._reset_btn.clicked.connect(self._reset_configuration)
        row.addWidget(note, 1)
        row.addWidget(self._reset_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        column.addLayout(row)
        return host

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
        # Reset returns both consent switches to OFF: stop collecting and delete queues/IDs right away.
        from exilelens.cloud import hooks as cloud_hooks

        if cloud_hooks.get() is not None:
            cloud_hooks.get().apply_consent()
        privacy_panel = getattr(self, "_privacy_panel", None)
        if privacy_panel is not None:
            privacy_panel.refresh()
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

    def _auto_detect_pob(self) -> None:
        """Rerun bounded local discovery: one result is applied, several are offered, none keeps the current path."""
        from exilelens.ui.pob_detect import detect_pob_path

        path = detect_pob_path(self)
        if path is None:
            return
        self._pob_edit.setText(path)
        if path != self.settings.pob_path:
            self._apply_pob_path()

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


class DiagnosticsPage(ColumnPage):
    """A utility, not a dashboard: five health rows, a report block, and collapsed advanced tools."""

    #: Health rows, in the order they are shown.
    HEALTH_KEYS = ("app", "pob", "build", "hotkey", "market")
    _LABELS = {
        "app": "ExileLens",
        "pob": "Path of Building",
        "build": "Build",
        "hotkey": "Item check hotkey",
        "market": "Market",
    }
    INTRO = ""

    def __init__(
        self,
        controller: EvaluationController,
        settings: AppSettings,
        update_service,
        parent: QWidget | None = None,
        *,
        navigate=None,
    ) -> None:
        super().__init__("Diagnostics", sticky_header=True, object_name="diagnosticsPage", parent=parent)
        self.controller = controller
        self.settings = settings
        self.update_service = update_service
        self._navigate = navigate
        self._scroll_area = self.scroll
        self.scroll.setObjectName("diagnosticsScrollArea")

        # --- header action ---------------------------------------------------------------------
        self._refresh_btn = make_button("Refresh", "tertiary", compact=True, icon="")
        self._refresh_btn.setIcon(outline_icon("refresh", theme.TEXT_BODY, 16))
        self._refresh_btn.clicked.connect(self.refresh)
        self.header.actions.addWidget(self._refresh_btn)

        # --- application health ---------------------------------------------------------------------
        health = QWidget()
        health_layout = QVBoxLayout(health)
        health_layout.setContentsMargins(0, 0, 0, 0)
        health_layout.setSpacing(0)
        heading = QLabel("Application health")
        heading.setObjectName("sectionHeading")
        self._verdict = QLabel(self.INTRO)
        self._verdict.setObjectName("helperText")
        self._verdict.setWordWrap(True)
        self._verdict.setVisible(bool(self.INTRO))
        health_layout.addWidget(heading)
        health_layout.addWidget(self._verdict)
        health_layout.addSpacing(8)
        self._rows_group = SettingsGroup()
        self._health_rows: dict[str, HealthGridRow] = {}
        for key in self.HEALTH_KEYS:
            row = HealthGridRow(self._LABELS[key])
            self._health_rows[key] = row
            self._rows_group.add_row(row)
        # The optional elevation row only exists when the product reports something about it.
        self._elevation_row = HealthGridRow("Hotkey access")
        self._elevation_row.setVisible(False)
        self._rows_group.add_row(self._elevation_row)
        health_layout.addWidget(self._rows_group)
        self._support_hint = QLabel("")
        self._support_hint.setObjectName("helperText")
        self._support_hint.setWordWrap(True)
        self._support_hint.setVisible(False)
        self._support_hint.setContentsMargins(0, 8, 0, 0)
        health_layout.addWidget(self._support_hint)
        self._structured_error_hint = QLabel("")
        self._structured_error_hint.setObjectName("helperText")
        self._structured_error_hint.setWordWrap(True)
        self._structured_error_hint.setVisible(False)
        self._structured_error_hint.setContentsMargins(0, 8, 0, 0)
        health_layout.addWidget(self._structured_error_hint)
        self.column.addWidget(health)

        # --- report a problem --------------------------------------------------------------------------
        report = QWidget()
        report_layout = QVBoxLayout(report)
        report_layout.setContentsMargins(0, 0, 0, 0)
        report_layout.setSpacing(0)
        report_heading = QLabel("Report a problem")
        report_heading.setObjectName("sectionHeading")
        report_intro = QLabel(
            "Copy diagnostics or export a support package for a GitHub issue. Nothing is sent automatically."
        )
        report_intro.setObjectName("helperText")
        report_intro.setWordWrap(True)
        report_layout.addWidget(report_heading)
        report_layout.addWidget(report_intro)
        report_layout.addSpacing(10)
        self._repro_notes = QTextEdit()
        self._repro_notes.setPlaceholderText("Optional: what were you doing when the problem happened?")
        self._repro_notes.setFixedHeight(76)
        self._repro_notes.setAccessibleName("What were you doing when the problem happened?")
        report_layout.addWidget(self._repro_notes)
        report_layout.addSpacing(12)
        self._copy_btn = make_button("Copy diagnostics", "secondary")
        self._copy_btn.setToolTip("Copies a privacy-safe diagnostic summary for GitHub issues.")
        self._copy_btn.clicked.connect(self._copy)
        self._export_bundle_btn = make_button("Export support package", "secondary")
        self._export_bundle_btn.setToolTip("Save a reviewed ZIP bundle for support (logs and diagnostics).")
        self._export_bundle_btn.clicked.connect(self._export_support_bundle)
        # The GitHub mark, not a generic external-link icon: it says where this goes.
        self._report_issue_btn = make_button("Report an issue", "tertiary", icon="github")
        self._report_issue_btn.setToolTip("Open the ExileLens issue tracker on GitHub.")
        self._report_issue_btn.clicked.connect(self._open_github_issues)
        actions = FlowLayout(spacing=10)  # wraps at larger Windows text sizes instead of widening the page
        for button in (self._copy_btn, self._export_bundle_btn, self._report_issue_btn):
            actions.addWidget(button)
        report_layout.addLayout(actions)
        self._report_status = QLabel("")
        self._report_status.setObjectName("helperText")
        self._report_status.setWordWrap(True)
        self._report_status.setContentsMargins(0, 8, 0, 0)
        report_layout.addWidget(self._report_status)
        self.column.addWidget(report)

        # --- advanced diagnostics (collapsed) -------------------------------------------------------------
        self._advanced = Disclosure("Advanced diagnostics")
        self._session_label = QLabel("")
        self._session_label.setObjectName("helperText")
        self._session_label.setWordWrap(True)
        session_help = QLabel("Support session ID helps match your report to in-app events.")
        session_help.setObjectName("helperText")
        session_help.setWordWrap(True)
        self._advanced.add_widget(session_help)
        self._advanced.add_widget(self._session_label)

        self._event_history = Disclosure("Diagnostic event history")
        event_help = QLabel("Recent in-app diagnostic events (privacy filtered).")
        event_help.setObjectName("helperText")
        event_help.setWordWrap(True)
        self._event_history.add_widget(event_help)
        self._event_history_text = QTextEdit()
        self._event_history_text.setReadOnly(True)
        self._event_history_text.setMinimumHeight(120)
        self._event_history_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._event_history.add_widget(self._event_history_text)
        self._advanced.add_widget(self._event_history)

        self._verbose_btn = make_button("Enable verbose diagnostics (15 min)", "tertiary", compact=True)
        self._verbose_btn.setToolTip("Records extra diagnostic detail locally for the next 15 minutes.")
        self._verbose_btn.clicked.connect(self._enable_verbose_diagnostics)
        self._clear_history_btn = make_button("Clear diagnostic history", "tertiary", compact=True)
        self._clear_history_btn.setToolTip("Removes stored diagnostic events from this installation.")
        self._clear_history_btn.clicked.connect(self._clear_diagnostic_history)
        self._logs_btn = make_button("Open logs", "secondary", compact=True)
        self._logs_btn.setToolTip("Opens the ExileLens log folder in your file manager.")
        self._logs_btn.clicked.connect(self._open_logs)
        tool_row = QHBoxLayout()
        tool_row.setContentsMargins(0, 0, 0, 0)
        tool_row.setSpacing(8)
        for button in (self._verbose_btn, self._clear_history_btn, self._logs_btn):
            tool_row.addWidget(button)
        tool_row.addStretch(1)
        self._advanced.add_layout(tool_row)

        self._technical_report = Disclosure("Technical report")
        raw_help = QLabel("Raw technical dump for deep troubleshooting (allowlisted global report).")
        raw_help.setObjectName("helperText")
        raw_help.setWordWrap(True)
        self._technical_report.add_widget(raw_help)
        self._build_info = QLabel()
        self._build_info.setWordWrap(True)
        self._build_info.setObjectName("diagnosticsBuildInfo")
        self._build_info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._text.setMinimumHeight(180)
        self._text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._technical_report.add_widget(self._build_info)
        self._technical_report.add_widget(self._text)
        self._advanced.add_widget(self._technical_report)
        self.column.addWidget(self._advanced)
        self.finish()
        self.column.setSpacing(30)

        self._advanced.toggled.connect(self._on_advanced_toggled)
        self._technical_report.toggled.connect(self._on_technical_report_toggled)
        self.refresh()

    def _on_advanced_toggled(self, expanded: bool) -> None:
        return None

    def _on_technical_report_toggled(self, expanded: bool) -> None:
        return None

    def expand_advanced(self) -> None:
        self._advanced.set_expanded(True)

    def _verdict_text(self, status) -> str:
        """One line of consequence under the heading when something is wrong."""
        from exilelens.ui import status_model

        key = status.key
        if key in (status_model.DISCONNECTED, status_model.CONNECTING):
            return "Item checks are paused until Path of Building reconnects."
        if key == status_model.SETUP:
            return "ExileLens needs a little setup before it can evaluate items."
        return "Something needs attention."

    def _row_action(self, key: str, item, *, primary: bool):
        """The fix button for a problem row, using only actions the product already supports."""
        if item.status not in ("warn", "error"):
            return None
        label = {
            "Reconnect": "Reconnect",
            "Locate Path of Building": "Locate Path of Building",
            "Choose build": "Choose build",
            "Choose another build": "Choose another build",
            "Refresh": "Refresh",
        }.get(item.action)
        if key == "hotkey":
            label = "Open settings"  # no concrete cause or one-click fix is known; Settings is where the hotkey lives
        if not label:
            return None
        button = make_button(label, "primary" if primary else "secondary", compact=True)
        button.clicked.connect(lambda _c=False, name=label: self._run_row_action(name))
        return button

    def _run_row_action(self, label: str) -> None:
        if label == "Reconnect":
            self.controller.restart_engine()
        elif label in ("Choose build", "Choose another build"):
            from exilelens.ui.setup_dialog import pick_build_file

            path = pick_build_file(self.settings.build_path)
            if path:
                self.controller.change_build(path)
        elif label == "Refresh":
            self.controller.reload_evaluation_build()
        elif label in ("Locate Path of Building", "Open settings") and self._navigate is not None:
            self._navigate("settings")
        self.refresh()

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
            from exilelens.error_catalog.integration import record_generic_failure

            record_generic_failure(
                self.controller.error_context,
                str(exc),
                el_code="EL-DIAG-001",
                subsystem="diagnostics",
                stage="export_bundle",
            )
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
        from exilelens.ui import status_model

        status = status_model.derive_status(self.controller, self.settings)
        health = status.health
        self._last_status = status
        first_problem_done = False
        for key in self.HEALTH_KEYS:
            item = getattr(health, key)
            problem = item.status in ("warn", "error")
            # The value stays short; the explanation goes on its own wrapped line
            # so a long path can never set the width of the page.
            detail = item.detail if problem else ""
            action = self._row_action(key, item, primary=problem and not first_problem_done)
            if action is not None and problem:
                first_problem_done = True
            self._health_rows[key].set_item(item.value, item.status, detail, action)
        elevation = health.elevation
        self._elevation_row.setVisible(elevation is not None and elevation.status in ("warn", "error"))
        if elevation is not None and self._elevation_row.isVisibleTo(self):
            self._elevation_row.set_item(elevation.value, elevation.status, elevation.detail)

        degraded = [getattr(health, key) for key in self.HEALTH_KEYS if getattr(health, key).status in ("warn", "error")]
        self._verdict.setText(self._verdict_text(status) if degraded else self.INTRO)
        self._verdict.setVisible(bool(self._verdict.text()))
        if degraded:
            actions = [item.action for item in degraded if item.action]
            recovery = actions[0] if actions else "the relevant recovery action"
            self._support_hint.setText(f"Try {recovery} first. If the problem continues, see below.")
            self._support_hint.setVisible(True)
        else:
            self._support_hint.setVisible(False)

        from exilelens.error_catalog.formatting import diagnostics_error_summary

        store = getattr(self.controller, "error_context", None)
        error_summary = diagnostics_error_summary(store.last_error if store is not None else None)
        limitation = store.last_limitation if store is not None else None
        if limitation is not None:
            extra = f"Last evaluation note ({limitation.code}): {limitation.user_guidance}"
            error_summary = f"{error_summary}\n{extra}".strip() if error_summary else extra
        self._structured_error_hint.setText(error_summary)
        self._structured_error_hint.setVisible(bool(error_summary))

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
