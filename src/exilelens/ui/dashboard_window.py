from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from exilelens.app.controller import EvaluationController
from exilelens.app.modules.registry import FeatureModule, is_enabled
from exilelens.app.settings import AppSettings, save_settings
from exilelens.app.update_check import UpdateService
from exilelens.branding import app_icon, window_title
from exilelens.platform.windows.dark_titlebar import apply_dark_title_bar
from exilelens.ui.fonts import register_bundled_fonts
from exilelens.ui import theme
from exilelens.ui.analysis_window import AnalysisWindow
from exilelens.ui.components import make_button
from exilelens.ui.dashboard_pages import DiagnosticsPage, SettingsPage
from exilelens.ui.gear_optimizer_page import GearOptimizerPage
from exilelens.ui.managed_window import ManagedToolWindow, recover_window_geometry
from exilelens.ui.market_hub_page import MarketHubPage
from exilelens.ui.overview_page import OverviewPage
from exilelens.ui.redesign_style import REDESIGN_STYLESHEET
from exilelens.ui.status_rail import StatusRail
from exilelens.ui.styles import DASHBOARD_STYLESHEET, apply_exile_lens_chrome
from exilelens.ui.tree_window import TreeWorkspace
from exilelens.ui.update_actions import restart_and_update, update_notice_view
from exilelens.ui.window_policy import WindowInteractionPolicy, apply_native_extended_style

#: Canonical navigation, in rail order. ``build_analysis`` is the Analyze Build page.
PAGE_IDS = (
    "overview",
    "build_analysis",
    "settings",
    "diagnostics",
)

#: Page ids that existed before the redesign. ``settings.dashboard_last_page`` holds
#: "build" on every existing install, and the tray still navigates by the old names.
PAGE_ALIASES = {
    "build": "overview",
    "items": "overview",
    "analyze": "build_analysis",
    "analysis": "build_analysis",
}

#: Ctrl+N shortcut -> page. Ctrl+, opens Settings (the Windows convention).
_PAGE_SHORTCUTS = (
    ("Ctrl+1", "overview"),
    ("Ctrl+2", "build_analysis"),
    ("Ctrl+3", "settings"),
    ("Ctrl+4", "diagnostics"),
    ("Ctrl+,", "settings"),
)


class DashboardWindow(ManagedToolWindow):
    """Canonical primary application window: Status Rail plus one page at a time."""

    _instance: DashboardWindow | None = None

    #: The dashboard is the one managed window the user may resize.
    resizable = True

    @staticmethod
    def _resolve_window_size(settings: AppSettings) -> QSize:
        """Pick the opening size, migrating the sizes the user never chose.

        Geometry is written back on every hide, so every existing install has one of the
        old *defaults* persisted (1280x860 from before UIUX-01, 980x640 from 0.7.0b1).
        Honouring them would mean nobody ever sees the new default, so those exact sizes
        (and an unset value) map to the new default. Any other size is the user's own
        choice and is kept. One-shot and self-clearing: after the first deliberate resize
        the stored size is honoured forever after.
        """
        width = int(getattr(settings, "dashboard_width", 0) or 0)
        height = int(getattr(settings, "dashboard_height", 0) or 0)
        unchosen = (theme.LEGACY_DEFAULT_WINDOW_SIZE, theme.PREVIOUS_DEFAULT_WINDOW_SIZE)
        if (width, height) in unchosen or not (width and height):
            width, height = theme.DEFAULT_WINDOW_SIZE
        min_w, min_h = theme.MINIMUM_WINDOW_SIZE
        return QSize(max(width, min_w), max(height, min_h))

    def __init__(
        self,
        settings: AppSettings,
        controller: EvaluationController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            policy=WindowInteractionPolicy.INTERACTIVE_APP_WINDOW,
            minimum_size=QSize(*theme.MINIMUM_WINDOW_SIZE),
            parent=parent,
        )
        DashboardWindow._instance = self
        self.settings = settings
        self.controller = controller
        self.update_service = UpdateService(settings)
        self.setObjectName("dashboardRoot")
        # Initial keyboard focus goes to the window itself, so no control shows a focus ring
        # until the user presses Tab.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setWindowTitle(window_title())
        icon = app_icon()
        if icon is not None:
            self.setWindowIcon(icon)
        # Legacy sheet first (the parked Market / Tree / Gear pages still use it), then the
        # redesign sheet, whose rules are scoped under #dashboardRoot and out-rank it.
        register_bundled_fonts()
        self.setStyleSheet(DASHBOARD_STYLESHEET + REDESIGN_STYLESHEET)
        apply_exile_lens_chrome(self)
        target = self._resolve_window_size(settings)
        self.restore_geometry(
            x=settings.dashboard_x,
            y=settings.dashboard_y,
            width=target.width(),
            height=target.height(),
        )

        # --- pages -------------------------------------------------------------------
        self._stack = QStackedWidget()
        self._pages: dict[str, QWidget] = {}
        self._overview = OverviewPage(controller, settings, navigate=self.navigate)
        self._analysis = (
            AnalysisWindow(controller, embedded=True, navigate=self.navigate)
            if is_enabled(FeatureModule.BUILD_ANALYSIS) else None
        )
        self._market = MarketHubPage(controller, settings) if is_enabled(FeatureModule.MARKET) else None
        self._tree = TreeWorkspace(controller, embed_mode=True) if is_enabled(FeatureModule.TREE_TOOLS) else None
        self._gear = GearOptimizerPage(controller) if is_enabled(FeatureModule.GEAR_OPTIMIZER) else None
        self._settings_page = SettingsPage(settings, controller, self.update_service)
        self._diagnostics = DiagnosticsPage(controller, settings, self.update_service, navigate=self.navigate)
        for page_id, widget in (
            ("overview", self._overview),
            ("build_analysis", self._analysis),
            ("market", self._market),
            ("tree", self._tree),
            ("gear_optimizer", self._gear),
            ("settings", self._settings_page),
            ("diagnostics", self._diagnostics),
        ):
            if widget is None:
                continue
            self._pages[page_id] = widget
            self._stack.addWidget(widget)

        # --- status rail ---------------------------------------------------------------
        from exilelens._version import __version__

        primary = [("overview", "Overview", "home"), ("build_analysis", "Analyze Build", "chart")]
        for page_id, label in (("market", "Market"), ("tree", "Tree"), ("gear_optimizer", "Gear Optimizer")):
            if page_id in self._pages:  # parked modules: only present when explicitly unparked
                primary.append((page_id, label, "chart"))
        secondary = [("settings", "Settings", "cog"), ("diagnostics", "Diagnostics", "pulse")]
        self._rail = StatusRail(
            controller,
            settings,
            [primary, secondary],
            open_patreon=self._open_patreon,
            open_discord=self._open_discord,
            open_issues=self._open_github_issues,
            version_text=f"ExileLens {__version__}",
        )
        self._rail.navigate_requested.connect(self.navigate)
        self._rail.update_action_requested.connect(self._rail_update_action)

        # --- content pane --------------------------------------------------------------
        content_pane = QWidget()
        content_pane.setObjectName("contentPane")
        content = QVBoxLayout(content_pane)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        content.addWidget(self._build_update_notice_host())
        content.addWidget(self._stack, 1)

        # Only progress is left of the old status footer, and it stays hidden unless
        # something is actually running.
        self._progress_row = QWidget()
        self._progress_row.setObjectName("progressStrip")
        progress_l = QHBoxLayout(self._progress_row)
        progress_l.setContentsMargins(theme.PAGE_GUTTER, theme.SPACE_SM, theme.PAGE_GUTTER, theme.SPACE_SM)
        self._progress_label = QLabel("")
        self._progress_label.setObjectName("secondaryText")
        progress_l.addWidget(self._progress_label, 1)
        self._progress_row.setVisible(False)
        content.addWidget(self._progress_row)

        self._update_check_state = "unchecked"
        self._update_remote_version = ""
        self._update_download_state = ""
        self._update_progress_percent: int | None = None
        self.update_service.state_changed.connect(self._on_update_state_footer)
        self.update_service.download_state_changed.connect(self._on_update_download_state_footer)
        self.update_service.download_progress.connect(self._on_update_download_progress_footer)
        self.update_service.action_error.connect(self._on_update_action_error_footer)
        self._refresh_version_footer()

        body = QHBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._rail)
        body.addWidget(content_pane, 1)

        if hasattr(controller, "progress_hub"):
            controller.progress_hub.progress_updated.connect(self._on_progress)
            controller.progress_hub.progress_cleared.connect(lambda _op_id: self._refresh_progress())
        self._install_shortcuts()
        self.navigate(settings.dashboard_last_page or "overview")
        self._apply_module_nav()
        self.resize(target)
        self._apply_responsive(target.width())
        # Tray-first startup: never create a visible native window until the user
        # explicitly opens ExileLens (or recovery surfaces Settings).
        self.hide()
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

    @classmethod
    def instance(cls) -> DashboardWindow | None:
        return cls._instance

    # --- navigation ---------------------------------------------------------------------

    def navigate(self, page_id: str) -> None:
        page_id = PAGE_ALIASES.get(page_id, page_id)
        if page_id not in self._pages:
            page_id = PAGE_IDS[0]
        self._stack.setCurrentWidget(self._pages[page_id])
        self._rail.set_current(page_id)
        self.settings.dashboard_last_page = page_id
        if page_id == "tree" and self._tree is not None:
            self._tree.on_page_shown()
        if page_id == "diagnostics":
            self._diagnostics.refresh()
        if page_id == "overview":
            self._overview.refresh()
        if page_id == "market" and self._market is not None:
            self._market.refresh()
        if page_id == "settings":
            refresh = getattr(self._settings_page, "refresh", None)
            if callable(refresh):
                refresh()
        self._rail.refresh()
        self._refresh_update_notice()

    def current_page_id(self) -> str:
        current = self._stack.currentWidget()
        for page_id, widget in self._pages.items():
            if widget is current:
                return page_id
        return PAGE_IDS[0]

    @property
    def _build(self) -> QWidget:
        """Back-compat alias for the pre-UIUX-01 attribute name."""
        return self._overview

    def _install_shortcuts(self) -> None:
        self._shortcuts: list[QShortcut] = []
        for sequence, page_id in _PAGE_SHORTCUTS:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(lambda pid=page_id: self.navigate(pid))
            self._shortcuts.append(shortcut)
        refresh = QShortcut(QKeySequence("F5"), self)
        refresh.setContext(Qt.ShortcutContext.WindowShortcut)
        refresh.activated.connect(self._refresh_build_shortcut)
        self._shortcuts.append(refresh)

    def _refresh_build_shortcut(self) -> None:
        """F5: reload the selected build from disk (the same action as the Refresh button)."""
        info = getattr(self.controller, "build_info", None)
        if info is not None and getattr(info, "path", ""):
            self.controller.reload_evaluation_build()

    def _open_discord(self) -> None:
        from exilelens.ui.recovery_actions import open_discord_invite

        open_discord_invite()

    def _open_patreon(self) -> None:
        from exilelens.ui.recovery_actions import open_patreon

        open_patreon()

    def _open_github_issues(self) -> None:
        from exilelens.ui.recovery_actions import open_github_issues

        open_github_issues()

    def tree_workspace(self) -> TreeWorkspace | None:
        return self._tree

    def show_dashboard(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, False)
        self.show()
        self.raise_()
        self.activateWindow()

    def _apply_module_nav(self) -> None:
        visible = {
            "overview": True,
            "build_analysis": is_enabled(FeatureModule.BUILD_ANALYSIS),
            "market": is_enabled(FeatureModule.MARKET) or is_enabled(FeatureModule.MARKET_ASSISTANT),
            "tree": is_enabled(FeatureModule.TREE_TOOLS),
            "gear_optimizer": is_enabled(FeatureModule.GEAR_OPTIMIZER),
            "settings": True,
            "diagnostics": True,
        }
        for page_id in self._rail.nav_buttons():
            self._rail.set_page_visible(page_id, visible.get(page_id, True))
        current = PAGE_ALIASES.get(
            self.settings.dashboard_last_page or PAGE_IDS[0], self.settings.dashboard_last_page
        )
        if not visible.get(current, True):
            self.navigate(PAGE_IDS[0])

    # --- responsive -----------------------------------------------------------------------

    def _apply_responsive(self, width: int) -> None:
        compact = width < theme.COMPACT_BREAKPOINT
        if compact != self._rail.is_compact():
            self._rail.set_compact(compact)
        for widget in self._pages.values():
            setter = getattr(widget, "set_compact", None)
            if callable(setter):
                setter(compact)
        gutter = theme.PAGE_GUTTER_COMPACT if compact else theme.PAGE_GUTTER
        self._notice_margins.setContentsMargins(gutter, 16, gutter, 0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_responsive(event.size().width())

    # --- progress ---------------------------------------------------------------------------

    def _on_progress(self, payload: dict) -> None:
        fraction = payload.get("fraction")
        completed = payload.get("completed")
        total = payload.get("total")
        title = payload.get("title") or "Working"
        phase = payload.get("phase") or ""
        if fraction is not None and total:
            text = f"{title}: {int(completed or 0)}/{int(total)}"
        elif payload.get("status") == "indeterminate":
            text = f"{title}: {phase or 'working…'}"
        else:
            text = title
        if phase and fraction is not None:
            text = f"{text} · {phase}"
        self._progress_label.setText(text)
        self._progress_row.setVisible(bool(text))

    def _refresh_progress(self) -> None:
        hub = getattr(self.controller, "progress_hub", None)
        if hub is None or not hub.has_active():
            self._progress_label.setText("")
            self._progress_row.setVisible(False)

    # --- update state ------------------------------------------------------------------------

    def _on_update_state_footer(self, state: str, version: str) -> None:
        self._update_check_state = state
        self._update_remote_version = version
        if state in ("current", "ahead", "unchecked", "unavailable", "verification_failed", "failed"):
            self._update_download_state = ""
            self._update_progress_percent = None
        self._refresh_version_footer()

    def _on_update_download_state_footer(self, state: str) -> None:
        self._update_download_state = state
        if state != "downloading":
            self._update_progress_percent = None
        self._refresh_version_footer()

    def _on_update_action_error_footer(self, message: str) -> None:
        if message:
            self._update_download_state = "error"
            self._refresh_version_footer()

    def _on_update_download_progress_footer(self, done: int, total: int) -> None:
        if total:
            self._update_progress_percent = int((done / total) * 100)
        else:
            self._update_progress_percent = None
        self._refresh_version_footer()

    def _build_update_notice_host(self) -> QWidget:
        """Slim in-app notice slot above the pages, aligned to the page gutter."""
        notice = self._build_update_notice()
        host = QWidget()
        host.setObjectName("updateNoticeHost")
        self._notice_margins = QHBoxLayout(host)
        self._notice_margins.setContentsMargins(theme.PAGE_GUTTER, 16, theme.PAGE_GUTTER, 0)
        self._notice_margins.setSpacing(0)
        notice.setMaximumWidth(theme.COLUMN_MAX_WIDTH)
        self._notice_margins.addWidget(notice, 1)
        self._notice_margins.addStretch(0)
        self._update_notice_host = host
        host.setVisible(False)
        return host

    def _build_update_notice(self) -> QWidget:
        """One non-modal in-dashboard notice for a pending, verified update (no new window, no focus grab)."""
        self._dismissed_update_versions: set[str] = set()  # session only; a new app session may remind again
        self._update_notice = QWidget()
        self._update_notice.setObjectName("updateNotice")
        self._update_notice.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(self._update_notice)
        row.setContentsMargins(theme.SPACE_MD, theme.SPACE_SM, theme.SPACE_MD, theme.SPACE_SM)
        row.setSpacing(theme.SPACE_SM)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self._update_notice_title = QLabel("")
        self._update_notice_title.setObjectName("cardTitle")
        self._update_notice_detail = QLabel("")
        self._update_notice_detail.setObjectName("secondaryText")
        texts.addWidget(self._update_notice_title)
        texts.addWidget(self._update_notice_detail)
        self._update_notice_action = make_button("Download && install", "primary", compact=True)
        self._update_notice_action.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._update_notice_action.clicked.connect(self._footer_update_action)
        self._update_notice_whats_new = make_button("What's new", "tertiary", compact=True)
        self._update_notice_whats_new.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._update_notice_whats_new.clicked.connect(self._open_release_page)
        self._update_notice_later = make_button("Later", "tertiary", compact=True)
        self._update_notice_later.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._update_notice_later.clicked.connect(self._dismiss_update_notice)
        row.addLayout(texts, 1)
        row.addWidget(self._update_notice_whats_new)
        row.addWidget(self._update_notice_action)
        row.addWidget(self._update_notice_later)
        self._update_notice.setVisible(False)
        return self._update_notice

    def _refresh_update_notice(self) -> None:
        from exilelens._version import __version__

        view = update_notice_view(
            self._update_check_state,
            self._update_download_state,
            self._update_remote_version,
            __version__,
            self._update_progress_percent,
            self._dismissed_update_versions,
        )
        host = getattr(self, "_update_notice_host", None)
        # The notice lives on Overview; elsewhere the rail link and Settings carry the state.
        on_overview = getattr(self, "_stack", None) is None or getattr(self, "_overview", None) is None or self._stack.currentWidget() is self._overview
        if view is None:
            self._update_notice.setVisible(False)
            if host is not None:
                host.setVisible(False)
            return
        self._update_notice_title.setText(view["title"])
        self._update_notice_detail.setText(view["detail"])
        self._update_notice_action.setText(view["action"].replace("Download update", "Download && install").replace("Restart & Update", "Restart && update"))
        self._update_notice_action.setEnabled(view["action_enabled"])
        self._update_notice_later.setVisible(view["later_visible"])
        release_url = getattr(self.update_service, "release_url", lambda: "")()
        self._update_notice_whats_new.setVisible(bool(release_url))
        self._update_notice.setVisible(True)
        if host is not None:
            host.setVisible(on_overview)

    def _dismiss_update_notice(self) -> None:
        if self._update_remote_version:
            self._dismissed_update_versions.add(self._update_remote_version)
        self._refresh_update_notice()

    def _open_release_page(self) -> None:
        url = self.update_service.release_url()
        if url:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl(url))

    def _footer_update_action(self) -> None:
        if self._update_download_state == "ready":
            restart_and_update(self.update_service)
            return
        if self._update_check_state == "available":
            self.update_service.start_download()

    def _rail_update_action(self) -> None:
        """The rail link never installs or restarts by itself: it opens Settings > Updates."""
        self.navigate("settings")
        focus = getattr(self._settings_page, "focus_updates", None)
        if callable(focus):
            focus()

    def _refresh_version_footer(self) -> None:
        """Push the current update state to the rail's version row and the Overview notice."""
        if self._update_download_state == "ready":
            text = "Restart to update"
        elif self._update_download_state == "downloading":
            text = (
                f"Downloading… {self._update_progress_percent}%"
                if self._update_progress_percent is not None else "Downloading…"
            )
        elif self._update_download_state == "installing":
            text = ""
        elif self._update_check_state == "available":
            text = "Update available"
        else:
            text = ""
        self._rail.set_update_state(text)
        self._refresh_update_notice()

    # --- lifecycle ------------------------------------------------------------------------------

    def on_hide(self) -> None:
        self._remember_geometry()

    #: Set while no tray icon exists: hiding the only window would strand the process.
    exit_on_close = False

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        super().closeEvent(event)
        if self.exit_on_close:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                shell = app.property("exilelens_app_shell")
                if shell is not None and hasattr(shell, "mark_user_exit"):
                    shell.mark_user_exit()  # closing the only window is an explicit user exit
                app.quit()

    # The dashboard is user-resizable (``resizable = True``), so the size lock that
    # ManagedToolWindow applies on move/resize is deliberately not overridden here.
    # Moving still never changes size, because nothing resizes the window on a move.

    def _remember_geometry(self) -> None:
        self.remember_geometry(self.settings, prefix="dashboard")
        save_settings(self.settings)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # Opening the dashboard asks for an automatic check; the service owns the 24h cooldown
        # (and the packaged-build gate), so repeated opens make no extra network request.
        self.update_service.start_automatic()
        apply_native_extended_style(self, WindowInteractionPolicy.INTERACTIVE_APP_WINDOW)
        apply_dark_title_bar(int(self.winId()))
        self._rail.refresh()
        recover_window_geometry(self, cap_size=True)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
