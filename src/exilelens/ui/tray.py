from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from exilelens.branding import APP_NAME
from exilelens.app.build_state import BuildInfo, BuildState
from exilelens.app.controller import EvaluationController
from exilelens.app.modules.registry import FeatureModule, is_enabled
from exilelens.app.settings import AppSettings, save_settings
from exilelens.ui.dashboard_window import DashboardWindow
from exilelens.ui.tray_icon import create_tray_icon
from exilelens.ui.ui_icons import apply_action_icon
from exilelens.ui.update_actions import restart_and_update, tray_update_action_label


class TrayManager(QSystemTrayIcon):
    def __init__(
        self,
        settings: AppSettings,
        controller: EvaluationController,
        overlay,
        dashboard: DashboardWindow,
        on_setup=None,
        on_quit=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.controller = controller
        self.overlay = overlay
        self.dashboard = dashboard
        self._on_setup = on_setup
        self._on_quit = on_quit

        self.setToolTip(f"{APP_NAME} {self.dashboard.update_service.installed_version_text}")
        self.setIcon(create_tray_icon())
        self.activated.connect(self._on_activated)

        self._update_action: QAction | None = None
        self._check_updates_action: QAction | None = None
        self._profile_actions: dict[str, QAction] = {}
        self._context_actions: dict[str, QAction] = {}
        self._loadout_actions: dict[str, QAction] = {}
        self._item_set_actions: dict[str, QAction] = {}
        self._overlay_mode_actions: dict[str, QAction] = {}
        self._tree_overlay_action: QAction | None = None
        self._loadout_menu: QMenu | None = None
        self._item_set_menu: QMenu | None = None
        self._build_action: QAction | None = None
        self._tree_action: QAction | None = None
        self._overlay_menu: QMenu | None = None
        self._update_check_state = "unchecked"
        self._update_remote_version = ""
        self._update_download_state = ""

        self.rebuild_menu()
        dashboard.update_service.update_available.connect(self._show_update_available)
        dashboard.update_service.state_changed.connect(self._on_update_state)
        dashboard.update_service.download_state_changed.connect(self._on_download_state)
        dashboard.update_service.download_progress.connect(self._on_download_progress)
        controller.build_changed.connect(self._on_build_changed)
        controller.loadouts_changed.connect(self._on_loadouts_changed)
        controller.state_message.connect(self._show_message)
        controller.value_profile_changed.connect(self._on_value_profile_changed)
        controller.active_build_status_changed.connect(lambda _s: self._update_build_action())

    def rebuild_menu(self) -> None:
        menu = QMenu()
        title = QAction(f"{APP_NAME} {self.dashboard.update_service.installed_version_text}", self)
        title.setEnabled(False)
        menu.addAction(title)
        menu.addSeparator()

        # Application: open, current build, reload -- must work whatever state the
        # build or engine is in. Settings/Setup/Diagnostics live on the Dashboard
        # only; the tray does not duplicate a second Settings/Support screen.
        open_dash = QAction("Open ExileLens", self)
        open_dash.triggered.connect(self._open_dashboard)
        menu.addAction(open_dash)

        self._build_action = QAction(self._build_label(), self)
        self._build_action.triggered.connect(self._open_build_page)
        menu.addAction(self._build_action)

        reload_build = QAction("Reload Build", self)
        reload_build.triggered.connect(self._reload_build)
        menu.addAction(reload_build)

        # Quick gameplay controls. Optional/parked by default, so the separator
        # around this section is only added when it actually has something in it --
        # otherwise a default build shows two adjacent separators with nothing
        # between them.
        gameplay_controls_start = len(menu.actions())
        if is_enabled(FeatureModule.MARKET):
            market_action = QAction("Market Search", self)
            market_action.triggered.connect(self._open_market)
            menu.addAction(market_action)

        if is_enabled(FeatureModule.MARKET_ASSISTANT):
            assist_menu = menu.addMenu("Market Assistant")
            open_assist = QAction("Open Market Assistant", self)
            open_assist.triggered.connect(self._open_market_assistant)
            assist_menu.addAction(open_assist)
            if self.controller.market_capture_active:
                stop_assist = QAction("Stop Capture", self)
                stop_assist.triggered.connect(self._stop_market_capture)
                assist_menu.addAction(stop_assist)
            if self.controller.last_result:
                pin_last = QAction("Pin Last Checked Item", self)
                pin_last.triggered.connect(self._pin_last_item)
                assist_menu.addAction(pin_last)
        elif is_enabled(FeatureModule.ITEM_CHECK) and self.controller.last_result:
            pin_action = QAction("Pin Last Checked Item", self)
            pin_action.triggered.connect(self._pin_last_item)
            menu.addAction(pin_action)

        if is_enabled(FeatureModule.TREE_TOOLS):
            self._tree_action = QAction("Tree", self)
            self._tree_action.triggered.connect(self._open_tree)
            menu.addAction(self._tree_action)

        if len(menu.actions()) > gameplay_controls_start:
            menu.addSeparator()

        self._loadout_menu = menu.addMenu("Loadout")
        self._item_set_menu = menu.addMenu("Gear Set")

        profile_menu = menu.addMenu("Profile")
        self._profile_actions.clear()
        for name in ("BALANCED", "MAPPING", "BOSSING", "DEFENSIVE"):
            action = QAction(name.title(), self)
            action.setCheckable(True)
            action.setChecked(self.settings.value_profile == name)
            action.triggered.connect(lambda checked=False, profile=name: self._set_profile(profile))
            profile_menu.addAction(action)
            self._profile_actions[name] = action

        context_menu = menu.addMenu("Context")
        map_action = QAction("MAP", self)
        map_action.setCheckable(True)
        map_action.setChecked(self.settings.context == "MAP")
        map_action.triggered.connect(lambda: self._set_context("MAP"))
        context_menu.addAction(map_action)
        boss_action = QAction("BOSS", self)
        boss_action.setCheckable(True)
        boss_action.setChecked(self.settings.context == "BOSS")
        boss_action.triggered.connect(lambda: self._set_context("BOSS"))
        context_menu.addAction(boss_action)
        self._context_actions = {"MAP": map_action, "BOSS": boss_action}

        if is_enabled(FeatureModule.LIVE_TREE_OVERLAY):
            menu.addSeparator()
            self._overlay_menu = menu.addMenu("Live Tree Overlay [Experimental]")
            self._tree_overlay_action = QAction("Show Tree Overlay", self)
            self._tree_overlay_action.setCheckable(True)
            self._tree_overlay_action.setChecked(self.settings.tree_overlay_enabled)
            self._tree_overlay_action.triggered.connect(self._toggle_tree_overlay)
            self._overlay_menu.addAction(self._tree_overlay_action)
            hide_tree = QAction("Hide Tree Overlay", self)
            hide_tree.triggered.connect(lambda: self._toggle_tree_overlay(False))
            self._overlay_menu.addAction(hide_tree)
            self._overlay_mode_actions.clear()
            mode_menu = self._overlay_menu.addMenu("Mode")
            for key, title in (("BUILD_PATH", "Build Path"), ("NEXT_POINTS", "Next Points"), ("VALUE_HEATMAP", "Value Heatmap")):
                action = QAction(title, self)
                action.setCheckable(True)
                action.setChecked(self.settings.tree_overlay_mode == key)
                action.triggered.connect(lambda checked=False, mode=key: self._set_overlay_mode(mode))
                mode_menu.addAction(action)
                self._overlay_mode_actions[key] = action
            calibrate = QAction("Calibrate…", self)
            calibrate.triggered.connect(self._calibrate_tree_overlay)
            self._overlay_menu.addAction(calibrate)
            realign = QAction("Quick Re-align…", self)
            realign.triggered.connect(lambda: self.controller.tree_overlay_realign_requested.emit())
            self._overlay_menu.addAction(realign)
            test_pat = QAction("Show Overlay Test Pattern", self)
            test_pat.triggered.connect(lambda: self.controller.tree_overlay_test_pattern_requested.emit())
            self._overlay_menu.addAction(test_pat)

        menu.addSeparator()
        self._check_updates_action = QAction("Check for Updates", self)
        self._check_updates_action.triggered.connect(self.dashboard.update_service.check_now)
        menu.addAction(self._check_updates_action)
        self._update_action = QAction("Download Update", self)
        self._update_action.triggered.connect(self._on_update_action)
        self._update_action.setVisible(False)
        ui_scale = float(getattr(self.settings, "ui_scale", 1.0) or 1.0)
        apply_action_icon(self._update_action, "download", ui_scale=ui_scale)
        menu.addAction(self._update_action)

        support_menu = menu.addMenu("Help && Support")
        discord_action = QAction("Discord / Community", self)
        discord_action.triggered.connect(self._open_discord)
        apply_action_icon(discord_action, "discord", ui_scale=ui_scale)
        support_menu.addAction(discord_action)

        report_issue_action = QAction("Report an Issue", self)
        report_issue_action.triggered.connect(self._open_github_issues)
        apply_action_icon(report_issue_action, "github", ui_scale=ui_scale)
        support_menu.addAction(report_issue_action)

        logs_action = QAction("Open Logs Folder", self)
        logs_action.triggered.connect(self._open_logs_folder)
        support_menu.addAction(logs_action)

        menu.addSeparator()
        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)
        self._rebuild_loadout_menus()

    def top_level_action_labels(self) -> list[str]:
        labels = []
        for action in self.contextMenu().actions():
            if action.isSeparator():
                continue
            if action.menu():
                labels.append(action.text())
            else:
                labels.append(action.text())
        return labels

    def _build_label(self) -> str:
        status = self.controller.active_build_status()
        name = status.display_name or self.controller.build_info.name
        if not name:
            path = status.build_path or self.controller.build_info.path
            name = Path(path).stem if path else "No build"
        return f"Build: {name}"

    def _update_build_action(self) -> None:
        if self._build_action is not None:
            self._build_action.setText(self._build_label())
            path = self.controller.active_build_status().build_path or self.controller.build_info.path or ""
            self._build_action.setToolTip(path or "No build loaded")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Single click as well as double click: testers read an unresponsive single
        # click as "the tray icon does not work".
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._open_dashboard()

    def _open_logs_folder(self) -> None:
        from exilelens.ui.recovery_actions import open_logs_folder

        open_logs_folder()

    def _open_discord(self) -> None:
        from exilelens.ui.recovery_actions import open_discord_invite

        open_discord_invite()

    def _open_github_issues(self) -> None:
        from exilelens.ui.recovery_actions import open_github_issues

        open_github_issues()

    def show_attention(self, title: str, message: str) -> None:
        """Tooltip + balloon for states the user has to act on (build/engine errors)."""
        self.setToolTip(f"{APP_NAME}\n{title}")
        self.showMessage(APP_NAME, message, QSystemTrayIcon.MessageIcon.Warning, 8000)

    def _open_dashboard(self) -> None:
        self.dashboard.show_dashboard()

    def _open_build_page(self) -> None:
        self.dashboard.navigate("build")
        self.dashboard.show_dashboard()

    def _open_market(self) -> None:
        self.dashboard.navigate("market")
        self.dashboard.show_dashboard()

    def _open_market_assistant(self) -> None:
        self.dashboard.navigate("market")
        self.dashboard._market.navigate("assistant")
        self.dashboard.show_dashboard()

    def _stop_market_capture(self) -> None:
        self.controller.stop_market_capture_session(finalize=True)

    def _pin_last_item(self) -> None:
        self.controller.pin_last_result()

    def _refine_last_price(self) -> None:
        self.controller.request_refine_last_price_check()

    def _open_tree(self) -> None:
        self.dashboard.navigate("tree")
        self.dashboard.show_dashboard()

    def _open_settings(self) -> None:
        self.dashboard.navigate("settings")
        self.dashboard.show_dashboard()

    def _open_setup(self) -> None:
        if self._on_setup is not None:
            self._on_setup()

    def _open_diagnostics(self) -> None:
        self.dashboard.navigate("diagnostics")
        self.dashboard.show_dashboard()

    def _on_build_changed(self, info: BuildInfo) -> None:
        if info.state in (BuildState.FAILED, BuildState.ERROR):
            self.setToolTip(f"{APP_NAME}\nBuild error — open Settings")
        else:
            self._sync_update_presentation()
        self._update_build_action()

    def _on_loadouts_changed(self, _payload: dict) -> None:
        self._rebuild_loadout_menus()

    def _rebuild_loadout_menus(self) -> None:
        if self._loadout_menu is None or self._item_set_menu is None:
            return
        self._loadout_menu.clear()
        self._item_set_menu.clear()
        self._loadout_actions.clear()
        self._item_set_actions.clear()

        loadouts = self.controller.loadouts
        if not loadouts:
            placeholder = QAction("(single loadout)", self)
            placeholder.setEnabled(False)
            self._loadout_menu.addAction(placeholder)
        else:
            for entry in loadouts:
                name = str(entry.get("name") or "Default")
                action = QAction(name, self)
                action.setCheckable(True)
                action.setChecked(name == self.controller.active_loadout)
                action.triggered.connect(lambda checked=False, n=name: self._set_loadout(n))
                self._loadout_menu.addAction(action)
                self._loadout_actions[name] = action

        follow = QAction("Follow Loadout", self)
        follow.setCheckable(True)
        follow.setChecked(self.settings.item_set_follow_loadout)
        follow.triggered.connect(self._toggle_follow_loadout)
        self._item_set_menu.addAction(follow)
        self._item_set_menu.addSeparator()

        item_sets = self.controller.item_sets
        if len(item_sets) <= 1:
            single = QAction("(single gear set)", self)
            single.setEnabled(False)
            self._item_set_menu.addAction(single)
        else:
            for entry in item_sets:
                set_id = str(entry.get("id"))
                title = str(entry.get("title") or entry.get("name") or f"Item Set {set_id}")
                action = QAction(title, self)
                action.setCheckable(True)
                enabled = not self.settings.item_set_follow_loadout
                action.setEnabled(enabled)
                action.setChecked(set_id == self.controller.active_item_set_id)
                action.triggered.connect(lambda checked=False, sid=set_id: self._set_item_set(sid))
                self._item_set_menu.addAction(action)
                self._item_set_actions[set_id] = action

    def _set_loadout(self, name: str) -> None:
        self.settings.selected_loadout = name
        save_settings(self.settings)
        self.controller.set_active_loadout(name)
        self._rebuild_loadout_menus()

    def _set_item_set(self, item_set_id: str) -> None:
        self.settings.item_set_follow_loadout = False
        save_settings(self.settings)
        self.controller.set_active_item_set(item_set_id, follow_loadout=False)
        self._rebuild_loadout_menus()

    def _toggle_follow_loadout(self, enabled: bool) -> None:
        self.settings.item_set_follow_loadout = enabled
        if enabled:
            self.settings.selected_item_set_id = ""
            if self.controller.active_loadout:
                self.controller.set_active_loadout(self.controller.active_loadout)
        save_settings(self.settings)
        self._rebuild_loadout_menus()

    def _reload_build(self) -> None:
        self.controller.reload_evaluation_build()

    def _set_context(self, context: str) -> None:
        for key, action in self._context_actions.items():
            action.setChecked(key == context)
        self.settings.context = context
        save_settings(self.settings)
        self.controller.set_context(context)

    def _set_profile(self, profile: str) -> None:
        rescored = self.controller.select_value_profile(profile)
        if rescored:
            self.overlay.show_last_result(rescored)

    def _on_value_profile_changed(self, profile: str) -> None:
        for key, action in self._profile_actions.items():
            action.setChecked(key == profile)

    def _toggle_tree_overlay(self, enabled: bool) -> None:
        self.settings.tree_overlay_enabled = bool(enabled)
        if self._tree_overlay_action is not None:
            self._tree_overlay_action.setChecked(bool(enabled))
        save_settings(self.settings)
        self.controller.tree_overlay_show_requested.emit(bool(enabled))

    def _set_overlay_mode(self, mode: str) -> None:
        self.settings.tree_overlay_mode = mode
        save_settings(self.settings)
        for key, action in self._overlay_mode_actions.items():
            action.setChecked(key == mode)
        self.controller.set_tree_overlay_mode(mode)

    def _calibrate_tree_overlay(self) -> None:
        self.dashboard.navigate("tree")
        self.dashboard.show_dashboard()
        self.controller.tree_overlay_calibrate_requested.emit()

    def show_startup_notification(self) -> None:
        self.showMessage(
            APP_NAME,
            "Running in system tray — Open ExileLens from the menu",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

    def _show_message(self, message: str) -> None:
        self.showMessage(APP_NAME, message, QSystemTrayIcon.MessageIcon.Information, 3000)

    def _show_update_available(self, remote: str, installed: str) -> None:
        self._update_remote_version = remote
        self._sync_update_presentation()
        self.showMessage(
            APP_NAME,
            f"ExileLens {remote} is available\nYou're using {installed}",
            QSystemTrayIcon.MessageIcon.Information,
            8000,
        )

    def _on_update_state(self, state: str, version: str) -> None:
        self._update_check_state = state
        self._update_remote_version = version
        if state in ("current", "unchecked", "unavailable"):
            self._update_download_state = ""
        self._sync_update_presentation()

    def _on_download_state(self, state: str) -> None:
        self._update_download_state = state
        self._sync_update_presentation()

    def _on_download_progress(self, _done: int, _total: int) -> None:
        # Tray action label stays stable while downloading; dashboard shows percent.
        self._sync_update_presentation()

    def _on_update_action(self) -> None:
        if self._update_download_state == "ready":
            restart_and_update(self.dashboard.update_service)
            return
        if self._update_check_state == "available":
            self.dashboard.update_service.start_download()
            return
        self.dashboard.navigate("diagnostics")
        self.dashboard.show_dashboard()

    def _installed_version_tooltip(self) -> str:
        return self.dashboard.update_service.installed_version_text

    def _sync_update_presentation(self) -> None:
        if self.controller.build_info.state in (BuildState.FAILED, BuildState.ERROR):
            self.setToolTip(f"{APP_NAME}\nBuild error — open Settings")
            return
        installed = self._installed_version_tooltip()
        label, visible, enabled = tray_update_action_label(
            self._update_check_state,
            self._update_download_state,
            self._update_remote_version,
        )
        if self._update_action is not None:
            self._update_action.setText(label)
            self._update_action.setVisible(visible)
            self._update_action.setEnabled(enabled)
        if self._update_download_state == "ready":
            tooltip = f"{APP_NAME} {installed} — update ready to install"
        elif self._update_download_state == "downloading":
            tooltip = f"{APP_NAME} {installed} — downloading update"
        elif self._update_check_state == "available" and self._update_remote_version:
            tooltip = f"{APP_NAME} {installed} — update {self._update_remote_version} available"
        elif self._update_check_state == "failed":
            tooltip = f"{APP_NAME} {installed} — update check failed"
        else:
            tooltip = f"{APP_NAME} {installed}"
        if self.controller.build_info.state == BuildState.READY:
            name = self.controller.build_info.name or Path(self.controller.build_info.path).name
            self.setToolTip(f"{tooltip}\nBuild: {name}\nProfile: {self.settings.value_profile}")
        else:
            self.setToolTip(tooltip)
        if self.contextMenu() is not None:
            for action in self.contextMenu().actions():
                if not action.isSeparator() and action.text().startswith(APP_NAME):
                    action.setText(f"{APP_NAME} {installed}")

    def _quit(self) -> None:
        self.dashboard._remember_geometry()
        self.overlay.remember_position()
        save_settings(self.settings)
        if self._on_quit is not None:
            self._on_quit()
            return
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app:
            app.quit()
