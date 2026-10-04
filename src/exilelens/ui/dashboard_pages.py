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
    QPlainTextEdit,
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
from exilelens.ui.components import Disclosure, SegmentedControl, StatusValue, make_button
from exilelens.ui.dashboard_widgets import (
    CardRow,
    ChevronComboBox,
    ColumnPage,
    FlowLayout,
    Hairline,
    HealthGridRow,
    KeycapDisplay,
    MonoPathLabel,
    SettingsRow,
    SettingsSection,
    SetupCard,
    ThemedSwitch,
    WrapLabel,
    ZoneFooter,
    set_button_tier,
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
    """One scrolling page, in the shipped section order. Settings apply immediately.

    Top to bottom: the Path of Building setup card, Hotkey, Updates (the free manual flow, then the Seamless
    updates supporter zone), Item evaluation, Overlay, Privacy, and the page foot (Reset, with a pointer to
    Diagnostics). There is no Advanced section: the folder and build pickers live on the card, logs and reports
    live on Diagnostics.
    """

    def __init__(
        self,
        settings: AppSettings,
        controller: EvaluationController,
        update_service=None,
        parent: QWidget | None = None,
        *,
        navigate=None,
    ) -> None:
        super().__init__("Settings", sticky_header=True, object_name="settingsPage", parent=parent)
        self.settings = settings
        self.controller = controller
        self.update_service = update_service
        self._navigate = navigate
        self._scroll_area = self.scroll
        self.scroll.setObjectName("settingsScrollArea")

        # Built first: later sections reference the widgets these create.
        self._build_shared_controls()
        for section in (
            self._build_pob_section(),
            self._build_hotkey_section(),
            self._build_updates_section(),
            self._build_evaluation_section(),
            self._build_overlay_section(),
            self._build_privacy_section(),
            self._build_reset_section(),
        ):
            self.column.addWidget(section)
        self.finish()

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

    def focus_supporter(self) -> None:
        """Reveal the Seamless updates supporter zone and put keyboard focus on its first action (the rail's
        "Support ExileLens"). Nothing external opens here."""
        self._reveal_supporter_zone()
        # The page may only just have been shown, so measure again once the layout has settled.
        QTimer.singleShot(0, self._reveal_supporter_zone)

    def _reveal_supporter_zone(self) -> None:
        zone = self._patreon_panel
        body = self.scroll.widget()
        top = zone.mapTo(body, zone.rect().topLeft()).y()
        bar = self.scroll.verticalScrollBar()
        bar.setValue(max(0, min(bar.maximum(), top - 96)))   # the zone with its Updates heading just above it
        for button in (
            zone.link_button, zone.reconnect_button, zone.support_button, zone.view_button, zone.cancel_button,
            zone.retry_button, zone.disconnect_button,
        ):
            if button.isVisibleTo(zone) and button.isEnabled():
                button.setFocus(Qt.FocusReason.TabFocusReason)
                return
        zone.setFocus(Qt.FocusReason.OtherFocusReason)

    # --- construction -----------------------------------------------------------

    def _build_shared_controls(self) -> None:
        """Create every control up front, so sections only arrange them."""
        settings = self.settings

        # The two paths are shown, never edited here: Detect / Change folder / Change build pick them.
        self._pob_path = str(settings.pob_path or "")
        self._build_path = str(settings.build_path or self.controller.build_info.path or "")

        for label_attr in ("_pob_status", "_loaded_status"):
            label = WrapLabel()
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
        """The setup card: Installation and Build, each with its own path and actions. The state shown comes from
        the same health model as the rail and Diagnostics; there is no second, independent status."""
        card = SetupCard("Path of Building")
        self._pob_card = card

        # --- Installation -----------------------------------------------------------------------------
        self._pob_state = StatusValue("", "neutral")
        self._pob_path_label = MonoPathLabel(self._pob_path, selectable=True)
        self._pob_path_label.setAccessibleName("Path of Building folder")
        self._detect_pob_btn = make_button("Detect", "tertiary", compact=True, tooltip="Look for Path of Building automatically")
        self._detect_pob_btn.clicked.connect(self._auto_detect_pob)
        self._change_pob_btn = make_button("Change folder", "secondary", compact=True)
        self._change_pob_btn.clicked.connect(self._browse_pob)
        # Surfaces only while the integration is actually down.
        self._reconnect_btn = make_button("Reconnect", "primary", compact=True)
        self._reconnect_btn.clicked.connect(self._reconnect_pob)
        self._reconnect_btn.setVisible(False)

        self._install_row = CardRow("Installation")
        for widget in (self._pob_state, self._pob_path_label, self._pob_status):
            self._install_row.add_value(widget)
        for button in (self._detect_pob_btn, self._change_pob_btn, self._reconnect_btn):
            self._install_row.add_action(button)
        card.add_row(self._install_row)

        # --- Build ------------------------------------------------------------------------------------
        self._build_name = QLabel("")
        self._build_name.setObjectName("healthValue")
        self._build_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._build_age = QLabel("")
        self._build_age.setObjectName("helperText")
        self._build_state = StatusValue("", "neutral")
        self._build_path_label = MonoPathLabel(self._build_path, selectable=True)
        self._build_path_label.setAccessibleName("Build file")
        self._reload_btn = make_button("Reload", "tertiary", compact=True, tooltip="Reload the active build from disk without restarting ExileLens.")
        self._reload_btn.clicked.connect(self._reload_build)
        self._change_build_btn = make_button("Change build", "secondary", compact=True)
        self._change_build_btn.clicked.connect(self._browse_build)

        self._build_row = CardRow("Build")
        for widget in (self._build_name, self._build_age, self._build_state, self._build_path_label, self._loaded_status):
            self._build_row.add_value(widget)
        for button in (self._reload_btn, self._change_build_btn):
            self._build_row.add_action(button)
        card.add_row(self._build_row)
        return card

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
        """Free, manual updates first (never tinted), then the one supporter zone, then the free-features line."""
        from exilelens.ui.patreon_panel import FREE_LINE, PatreonPanel

        section = SettingsSection("Updates", with_group=False)
        self._updates_section = section
        if self.update_service is None:
            note = QLabel("Update checks are unavailable in this view.")
            note.setObjectName("helperText")
            section.add_panel(note)
        else:
            from exilelens.ui.updates_panel import UpdatesPanel

            self._updates_panel = UpdatesPanel(self.settings, self.update_service)
            section.add_panel(self._updates_panel)
        self._patreon_panel = PatreonPanel(self.settings)
        section.add_below(self._patreon_panel, 12)
        free = QLabel(FREE_LINE)
        free.setObjectName("helperText")
        free.setWordWrap(True)
        free.setContentsMargins(0, 8, 0, 0)
        section.add_panel(free)
        return section

    def _build_privacy_section(self):
        from exilelens.ui.privacy_panel import PrivacyPanel

        section = SettingsSection("Privacy", with_group=False)
        self._privacy_panel = PrivacyPanel(self.settings)
        section.add_panel(self._privacy_panel)
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
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        note = QLabel(
            "Restores defaults and forgets your PoB folder, build and preferences. "
            "A backup is kept. Your builds and game files are not touched."
        )
        note.setObjectName("bodyText")
        note.setWordWrap(True)
        note.setMaximumWidth(560)
        texts.addWidget(note)
        # Logs, the event history and support reports are on Diagnostics, not here. One wrapping label with an
        # inline link, so it never forces the page wider at large text sizes.
        pointer = QLabel(
            f'<style>a {{ color: {theme.TEXT}; }}</style>'
            'Logs, event history and support reports are in <a href="diagnostics">Diagnostics</a>.'
        )
        pointer.setObjectName("helperText")
        pointer.setTextFormat(Qt.TextFormat.RichText)
        pointer.setWordWrap(True)
        pointer.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        pointer.setOpenExternalLinks(False)
        pointer.setAccessibleName("Logs, event history and support reports are in Diagnostics")
        pointer.linkActivated.connect(lambda _href: self._open_diagnostics())
        self._diagnostics_pointer = pointer
        texts.addWidget(pointer)
        self._reset_btn = make_button("Reset configuration", "destructive", compact=True)
        self._reset_btn.clicked.connect(self._reset_configuration)
        row.addLayout(texts, 1)
        row.addWidget(self._reset_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        column.addLayout(row)
        return host

    def _open_diagnostics(self) -> None:
        if self._navigate is not None:
            self._navigate("diagnostics")

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
        from exilelens.app.setup_status import check_build_file, check_pob_folder, describe_build_state

        # The displayed paths follow the runtime, not a copy made at start-up: the build can be changed from
        # Overview or Diagnostics too.
        self._set_pob_path(str(self.settings.pob_path or ""))
        self._set_build_path(str(self.settings.build_path or ""))
        pob = check_pob_folder(self._pob_path)
        loaded = describe_build_state(self.controller.build_info)
        self._pob_folder_detail = "" if pob.ok else (pob.detail or pob.label)
        # One detail line for the Build row, shown only when something is wrong. It carries the build state's own
        # explanation, a reload warning, and whether the configured file is still on disk.
        lines = [] if loaded.ok else [loaded.detail or loaded.label]
        warning = getattr(self.controller, "reload_warning", "")
        if isinstance(warning, str) and warning:
            lines.append(warning)
        if self._build_path:
            file_check = check_build_file(self._build_path)
            if not file_check.ok:
                lines.append(file_check.detail or file_check.label)
        self._build_detail_lines = lines
        self._loaded_status.setText("\n".join(lines))
        self._loaded_status.setStyleSheet(f"color: {theme.WARN};" if lines else "")
        from exilelens.platform.windows.elevation import evaluate_elevation_status

        elevation = evaluate_elevation_status()
        self._hotkey_elevation_status.setText(elevation.detail if elevation.mismatch else "")
        self._hotkey_elevation_status.setVisible(bool(elevation.mismatch))
        self._hotkey_elevation_status.setStyleSheet(f"color: {theme.WARN};" if elevation.mismatch else "")

        self._apply_health_presentation()

    @staticmethod
    def _card_status(health) -> tuple[str, str]:
        """Header word for the setup card: Path of Building and the build only (the hotkey is not part of it)."""
        pob, build = health.pob, health.build
        if pob.value == "Not found":
            return "Setup needed", "warn"
        if pob.value.startswith("Connecting"):
            return "Connecting…", "neutral"
        if pob.status in ("warn", "error"):
            return "Not connected", "error"
        if build.value == "Not selected":
            return "Setup needed", "warn"
        if build.status == "error":
            return "Needs attention", "error"
        if "loading" in build.value or "refreshing" in build.value:
            return "Loading…", "neutral"
        if build.status == "warn":
            return "Needs attention", "warn"
        return "Ready", "ok"

    def _apply_health_presentation(self) -> None:
        """Healthy configuration is quiet; only the affected row is lifted and gets the page's primary action."""
        from exilelens.app.setup_status import check_build_file
        from exilelens.ui.health import derive_health

        health = derive_health(self.controller, self.settings)
        pob, build = health.pob, health.build
        word, tone = self._card_status(health)
        self._pob_card.set_status(word, tone)

        # --- Installation ---
        self._pob_state.set_value(pob.value, pob.status)
        pob_problem = pob.status in ("warn", "error")
        not_found = pob.value == "Not found"
        self._pob_path_label.setVisible(bool(self._pob_path))
        # The one explanation: the health model's own detail (say, "The Path of Building worker stopped."), or the
        # folder check when the folder itself is the problem.
        detail = pob.detail or self._pob_folder_detail
        self._pob_status.setText(detail)
        self._pob_status.setStyleSheet(f"color: {theme.WARN};" if self._pob_folder_detail else "")
        self._pob_status.setVisible(pob_problem and bool(detail))
        self._install_row.set_problem(pob_problem)
        reconnect = pob_problem and not not_found
        self._reconnect_btn.setVisible(reconnect)
        set_button_tier(self._reconnect_btn, "primary")
        set_button_tier(self._change_pob_btn, "primary" if not_found else ("tertiary" if reconnect else "secondary"))

        # --- Build: the name and age come from the one health value ("Name · loaded 3 min ago") ---
        no_build = build.value == "Not selected" or not self._build_path
        file_bad = bool(self._build_path) and not check_build_file(self._build_path).ok
        build_problem = (build.status in ("warn", "error") or file_bad) and not pob_problem
        if build.status == "ok":
            name, _sep, age = build.value.partition(" · ")
            self._build_name.setText(name)
            self._build_age.setText(age[:1].upper() + age[1:] if age else "")
            self._build_age.setVisible(bool(age))
            self._build_name.setVisible(True)
            self._build_state.setVisible(False)
        else:
            self._build_state.set_value(build.value, build.status)
            self._build_state.setVisible(True)
            self._build_name.setVisible(False)
            self._build_age.setVisible(False)
        self._build_path_label.setVisible(bool(self._build_path))
        self._loaded_status.setVisible(bool(self._build_detail_lines))
        self._build_row.set_problem(build_problem)
        primary_build = not pob_problem and not not_found and (no_build or build.status == "error")
        self._change_build_btn.setText("Choose build" if no_build else "Change build")
        set_button_tier(self._change_build_btn, "primary" if primary_build else "secondary")
        self._reload_btn.setVisible(bool(self._build_path))
        set_button_tier(
            self._reload_btn,
            "primary" if (build.status == "warn" and not pob_problem and not primary_build) else "tertiary",
        )

    def _reconnect_pob(self) -> None:
        """Re-validate the configured folder and restart the Path of Building worker with it."""
        from exilelens.app.setup_status import check_pob_folder

        candidate = self._pob_path.strip()
        check = check_pob_folder(candidate)
        if not check.ok:
            self.refresh_setup_status()
            QMessageBox.warning(self, "Path of Building", check.text())
            return
        self.settings.pob_path = candidate
        save_settings(self.settings)
        self.refresh_setup_status()
        self.controller.restart_engine()
        self.refresh_setup_status()

    def _set_pob_path(self, path: str) -> None:
        self._pob_path = path
        if self._pob_path_label.full_text() != path:
            self._pob_path_label.set_full_text(path)

    def _set_build_path(self, path: str) -> None:
        self._build_path = path
        if self._build_path_label.full_text() != path:
            self._build_path_label.set_full_text(path)

    def _browse_build(self) -> None:
        from exilelens.ui.setup_dialog import pick_build_file

        path = pick_build_file(self._build_path)
        if path:
            self._load_build_from_path(path)

    def _load_build_from_path(self, path: str) -> None:
        """Validate the picked build file, then load it (or save it, while Path of Building is not running)."""
        from pathlib import Path

        from exilelens.app.setup_status import check_build_file

        path = path.strip()
        check = check_build_file(path)
        if not check.ok:
            QMessageBox.warning(self, "Build file", check.text())
            return
        if self.controller.engine_status() != "ready":
            self.settings.build_path = path
            save_settings(self.settings)
            self.refresh_setup_status()
            self._loaded_status.setText("Saved. It loads as soon as Path of Building is running.")
            self._loaded_status.setVisible(True)
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
        self._set_pob_path(self.settings.pob_path)
        self._set_build_path("")
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
        live = "Live prices off" if str(self.settings.live_market_mode or "auto") == "disabled" else "Live prices on"
        saved = str(self.settings.market_league or "").strip()
        if not saved:
            return f"{live} · league not resolved yet"
        mode = str(self.settings.market_league_mode or "AUTO").upper()
        return f"{live} · {saved} ({'pinned' if mode == 'PINNED' else 'auto-detected'})"

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
        path = self._pob_path.strip()
        if path == self.settings.pob_path:
            return
        from exilelens.app.setup_status import check_pob_folder

        check = check_pob_folder(path)
        if not check.ok:
            self._set_pob_path(self.settings.pob_path)
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
        self._set_pob_path(path)
        if path != self.settings.pob_path:
            self._reconnect_pob()

    def _browse_pob(self) -> None:
        from exilelens.ui.setup_dialog import pick_pob_directory

        path = pick_pob_directory(self._pob_path)
        if path:
            self._set_pob_path(path)
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
    """A utility, not a dashboard.

    Top to bottom: the Application health card (the one raised neutral card, with an aggregate status), the Report a
    problem help zone (honey; the Support ID travels with the report), and Advanced diagnostics, collapsed, with one
    viewer that switches between the event history and the technical report.
    """

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
    REPORT_INTRO = (
        "Copy the diagnostics or export a support package, then attach it to a GitHub issue. "
        "Nothing is sent automatically."
    )
    SUPPORT_ID_HINT = "Include it in the issue to match events."
    ADVANCED_PREVIEW = "Logs, event history, technical report"

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

        self.column.addWidget(self._build_health_card())
        self.column.addWidget(self._build_report_zone())
        self.column.addWidget(self._build_advanced())
        self.finish()
        self.column.setSpacing(24)

        self._advanced.toggled.connect(self._on_advanced_toggled)
        self.refresh()

    # --- construction -----------------------------------------------------------

    def _build_health_card(self) -> QWidget:
        card = SetupCard("Application health")
        self._health_card = card
        self._verdict = card.lead
        self._health_rows: dict[str, HealthGridRow] = {}
        for key in self.HEALTH_KEYS:
            row = HealthGridRow(self._LABELS[key], h_pad=SetupCard.PAD)
            self._health_rows[key] = row
            card.add_row(row)
        # The optional elevation row only exists when the product reports something about it.
        self._elevation_row = HealthGridRow("Hotkey access", h_pad=SetupCard.PAD)
        self._elevation_row.setVisible(False)
        card.add_row(self._elevation_row)
        # Footer: the recovery hint and the structured error summary, only when there is something to say.
        footer = QWidget()
        footer_column = QVBoxLayout(footer)
        footer_column.setContentsMargins(SetupCard.PAD, 10, SetupCard.PAD, 11)
        footer_column.setSpacing(6)
        self._support_hint = WrapLabel("")
        self._support_hint.setObjectName("helperText")
        self._structured_error_hint = WrapLabel("")
        self._structured_error_hint.setObjectName("helperText")
        for hint in (self._support_hint, self._structured_error_hint):
            hint.setVisible(False)
            footer_column.addWidget(hint)
        self._health_footer = card.add_footer(footer)
        self._health_footer.setVisible(False)
        return card

    def _build_report_zone(self) -> QWidget:
        zone = QFrame()
        zone.setObjectName("helpZone")
        zone.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        zone.setAccessibleName("Report a problem")
        self._help_zone = zone
        column = QVBoxLayout(zone)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        head = QWidget()
        head_row = QHBoxLayout(head)
        head_row.setContentsMargins(16, 13, 16, 0)
        head_row.setSpacing(10)
        mark = QLabel()
        mark.setFixedSize(20, 20)
        mark.setPixmap(outline_icon("lifebuoy", theme.HELP, 20).pixmap(20, 20))
        mark.setAccessibleName("")
        title = QLabel("Report a problem")
        title.setObjectName("zoneTitle")
        head_row.addWidget(mark, 0, Qt.AlignmentFlag.AlignVCenter)
        head_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        head_row.addStretch(1)
        column.addWidget(head)

        body = QWidget()
        body_column = QVBoxLayout(body)
        body_column.setContentsMargins(46, 4, 16, 14)   # aligned to the title, past the icon
        body_column.setSpacing(0)
        intro = WrapLabel(self.REPORT_INTRO)
        intro.setObjectName("helperText")
        body_column.addWidget(intro)
        body_column.addSpacing(10)
        self._repro_notes = QTextEdit()
        self._repro_notes.setPlaceholderText("Optional: what were you doing when it happened?")
        self._repro_notes.setFixedHeight(76)
        self._repro_notes.setAccessibleName("What were you doing when the problem happened?")
        body_column.addWidget(self._repro_notes)
        body_column.addSpacing(12)
        self._copy_btn = make_button("Copy diagnostics", "secondary", compact=True)
        self._copy_btn.setIcon(outline_icon("copy", theme.TEXT, 16))
        self._copy_btn.setToolTip("Copies a privacy-safe diagnostic summary for GitHub issues.")
        self._copy_btn.clicked.connect(self._copy)
        self._export_bundle_btn = make_button("Export support package…", "secondary", compact=True)
        self._export_bundle_btn.setToolTip("Save a reviewed ZIP bundle for support (logs and diagnostics).")
        self._export_bundle_btn.clicked.connect(self._export_support_bundle)
        # The GitHub mark, not a generic external-link icon: it says where this goes.
        self._report_issue_btn = make_button("Open a GitHub issue", "tertiary", compact=True, icon="github")
        self._report_issue_btn.setToolTip("Open the ExileLens issue tracker on GitHub.")
        self._report_issue_btn.clicked.connect(self._open_github_issues)
        actions = FlowLayout(spacing=8)  # wraps at larger Windows text sizes instead of widening the page
        actions.addWidget(self._copy_btn)
        actions.addWidget(self._export_bundle_btn)
        actions.addTrailingWidget(self._report_issue_btn)   # right-aligned: the only control that leaves the app
        body_column.addLayout(actions)
        self._report_status = WrapLabel("")
        self._report_status.setObjectName("helperText")
        self._report_status.setContentsMargins(0, 8, 0, 0)
        self._report_status.setVisible(False)
        body_column.addWidget(self._report_status)
        column.addWidget(body)

        # Footer: the Support ID with Copy, and what it is for.
        id_row = QWidget()
        id_layout = QHBoxLayout(id_row)
        id_layout.setContentsMargins(0, 0, 0, 0)
        id_layout.setSpacing(10)
        id_label = QLabel("Support ID")
        id_label.setObjectName("zoneFooterText")
        self._support_id = QLabel("")
        self._support_id.setObjectName("supportId")
        self._support_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._support_id.setAccessibleName("Support ID")
        self._copy_id_btn = make_button("Copy", "tertiary", compact=True)
        self._copy_id_btn.setAccessibleName("Copy Support ID")
        self._copy_id_btn.clicked.connect(self._copy_support_id)
        for widget in (id_label, self._support_id, self._copy_id_btn):
            id_layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        id_layout.addStretch(1)
        hint = QLabel(self.SUPPORT_ID_HINT)   # one line; the footer drops it under the ID when the zone is narrow
        hint.setObjectName("zoneFooterText")
        self._support_id_footer = ZoneFooter(id_row, margins=(46, 8, 16, 9))
        self._support_id_footer.add_action(hint)
        column.addWidget(self._support_id_footer)
        return zone

    def _build_advanced(self) -> QWidget:
        self._advanced = Disclosure("Advanced diagnostics", preview=self.ADVANCED_PREVIEW)
        # Tools row: most-used first, the clearing action apart at the right.
        self._logs_btn = make_button("Open logs folder", "secondary", compact=True)
        self._logs_btn.setIcon(outline_icon("folder", theme.TEXT, 16))
        self._logs_btn.setToolTip("Opens the ExileLens log folder in your file manager.")
        self._logs_btn.clicked.connect(self._open_logs)
        self._verbose_btn = make_button("Enable verbose diagnostics for 15 min", "tertiary", compact=True)
        self._verbose_btn.setToolTip("Records extra diagnostic detail locally for the next 15 minutes.")
        self._verbose_btn.clicked.connect(self._enable_verbose_diagnostics)
        self._clear_history_btn = make_button("Clear diagnostic history", "tertiary", compact=True)
        self._clear_history_btn.setToolTip("Removes stored diagnostic events from this installation.")
        self._clear_history_btn.clicked.connect(self._clear_diagnostic_history)
        tools = FlowLayout(spacing=8)
        tools.addWidget(self._logs_btn)
        tools.addWidget(self._verbose_btn)
        tools.addTrailingWidget(self._clear_history_btn)
        self._advanced.add_layout(tools)

        # One viewer, two modes. Copy always copies what is shown.
        self._viewer_mode = SegmentedControl([("events", "Event history"), ("report", "Technical report")])
        self._viewer_mode.set_current_value("events")
        self._viewer_mode.changed.connect(self._set_viewer_mode)
        for button in self._viewer_mode.buttons():
            button.setAccessibleName(button.text())
        self._viewer_copy_btn = make_button("Copy", "tertiary", compact=True)
        self._viewer_copy_btn.setIcon(outline_icon("copy", theme.TEXT_BODY, 16))
        self._viewer_copy_btn.setAccessibleName("Copy what is shown")
        self._viewer_copy_btn.clicked.connect(self._copy_viewer)
        mode_row = FlowLayout(spacing=8)   # Copy wraps under the switch when narrow
        mode_row.setContentsMargins(0, 8, 0, 0)
        mode_row.addWidget(self._viewer_mode)
        mode_row.addTrailingWidget(self._viewer_copy_btn)
        self._advanced.add_layout(mode_row)
        self._viewer = QPlainTextEdit()
        self._viewer.setObjectName("diagnosticViewer")
        self._viewer.setReadOnly(True)
        self._viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._viewer.setMinimumHeight(168)
        self._viewer.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._viewer.setAccessibleName("Diagnostic viewer")
        self._advanced.add_widget(self._viewer)
        self._viewer_caption = WrapLabel("")
        self._viewer_caption.setObjectName("helperText")
        self._advanced.add_widget(self._viewer_caption)
        self._event_text = ""
        self._report_text = ""
        self._events_caption = ""
        self._report_caption = ""
        return self._advanced

    def _on_advanced_toggled(self, expanded: bool) -> None:
        return None

    def expand_advanced(self) -> None:
        self._advanced.set_expanded(True)

    # --- viewer -----------------------------------------------------------------

    def _set_viewer_mode(self, mode: str) -> None:
        self._viewer_mode.set_current_value(mode)
        events = mode == "events"
        self._viewer.setPlainText(self._event_text if events else self._report_text)
        self._viewer_caption.setText(self._events_caption if events else self._report_caption)

    def viewer_mode(self) -> str:
        return self._viewer_mode.current_value()

    def _copy_viewer(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._viewer.toPlainText())
        self._viewer_copy_btn.setText("Copied")
        QTimer.singleShot(2000, lambda: self._viewer_copy_btn.setText("Copy"))

    @staticmethod
    def format_events(events: list[dict]) -> str:
        """One readable line per event: time, category, name, then every detail as ``key=value`` (nothing dropped)."""
        import json
        import time

        lines = []
        for event in events:
            stamp = time.strftime("%H:%M:%S", time.localtime(float(event.get("ts") or 0)))
            head = f"{stamp}  {str(event.get('category', '')):<12} {event.get('name', '')}"
            detail = event.get("detail") or {}
            parts = []
            for key, value in detail.items():
                shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
                parts.append(f"{key}={shown}")
            lines.append(f"{head}  {' '.join(parts)}".rstrip())
        return "\n".join(lines) if lines else "No events recorded this session."

    # --- health rows ------------------------------------------------------------

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

    # --- report actions ---------------------------------------------------------

    def _copy(self) -> None:
        from exilelens.ui.recovery_actions import copy_diagnostics

        self.refresh()
        copy_diagnostics(self.controller, self.settings, update_service=self.update_service)
        self._copy_btn.setText("Diagnostics copied")
        QTimer.singleShot(2500, lambda: self._copy_btn.setText("Copy diagnostics"))

    def _copy_support_id(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._support_id.text())
        self._copy_id_btn.setText("Copied")
        QTimer.singleShot(2000, lambda: self._copy_id_btn.setText("Copy"))

    def _set_report_status(self, text: str) -> None:
        self._report_status.setText(text)
        self._report_status.setVisible(bool(text))

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
            self._set_report_status(str(exc))
            return
        self._set_report_status(f"Support package saved to {destination.name}")
        self.refresh()

    def _clear_diagnostic_history(self) -> None:
        from exilelens.diagnostics import clear_event_history

        clear_event_history()
        self._set_report_status("Diagnostic event history cleared.")
        self.refresh()

    def _enable_verbose_diagnostics(self) -> None:
        from exilelens.app.settings import save_settings
        from exilelens.diagnostics import enable_verbose_mode, verbose_mode_active

        enable_verbose_mode(self.settings)
        save_settings(self.settings)
        self._set_report_status(
            "Verbose diagnostics enabled for 15 minutes." if verbose_mode_active(self.settings) else ""
        )
        self.refresh()

    def _open_logs(self) -> None:
        from exilelens.ui.recovery_actions import open_logs_folder

        open_logs_folder()

    def _open_github_issues(self) -> None:
        from exilelens.ui.recovery_actions import open_github_issues

        open_github_issues()

    # --- refresh ----------------------------------------------------------------

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
        needing = len(degraded) + (1 if self._elevation_row.isVisibleTo(self) else 0)
        # The header word is the aggregate; the card itself never changes colour.
        if needing:
            self._health_card.set_status(f"{needing} need attention" if needing > 1 else "1 needs attention", "warn")
        else:
            self._health_card.set_status("All good", "ok")
        self._health_card.set_lead(self._verdict_text(status) if degraded else self.INTRO)
        if degraded:
            actions = [item.action for item in degraded if item.action]
            recovery = actions[0] if actions else "the relevant recovery action"
            self._support_hint.setText(f"Try {recovery} first. Still stuck? Report it below.")
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
        self._health_footer.setVisible(not self._support_hint.isHidden() or not self._structured_error_hint.isHidden())

        from exilelens.diagnostics import build_extended_summary, event_buffer, verbose_mode_active

        report = build_global_diagnostics(self.controller)
        build_info = f"ExileLens {report.version}  |  build {report.build}  |  {report.mode}"
        extended = build_extended_summary(self.controller, self.settings, update_service=self.update_service)
        self._support_id.setText(str(extended.get("support_session_id", "")))
        verbose = "on" if verbose_mode_active(self.settings) else "off"
        events = event_buffer().export_records(include_verbose=verbose_mode_active(self.settings), limit=80)
        self._event_text = self.format_events(events)
        self._report_text = report.render()
        self._events_caption = f"Privacy filtered · verbose {verbose} · {len(events)} events recorded"
        self._report_caption = f"{build_info}. Allowlisted technical report for deep troubleshooting."
        self._set_viewer_mode(self._viewer_mode.current_value() or "events")
