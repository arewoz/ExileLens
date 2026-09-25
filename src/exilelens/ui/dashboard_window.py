from __future__ import annotations

from PySide6.QtGui import QCloseEvent
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from exilelens.branding import window_title
from exilelens.app.controller import EvaluationController
from exilelens.app.settings import AppSettings, save_settings
from exilelens.app.update_check import UpdateService
from exilelens.app.modules.registry import FeatureModule, is_enabled
from exilelens.ui import theme
from exilelens.ui.app_header import AppHeader
from exilelens.ui.overview_page import OverviewPage
from exilelens.ui.dashboard_pages import DiagnosticsPage, SettingsPage
from exilelens.ui.market_hub_page import MarketHubPage
from exilelens.ui.gear_optimizer_page import GearOptimizerPage
from exilelens.ui.components import make_button
from exilelens.ui.styles import DASHBOARD_STYLESHEET, apply_exile_lens_chrome
from exilelens.ui.ui_icons import apply_button_icon
from exilelens.ui.update_actions import footer_update_summary, restart_and_update
from exilelens.ui.tree_window import TreeWorkspace
from exilelens.ui.managed_window import ManagedToolWindow, recover_window_geometry
from exilelens.ui.window_policy import WindowInteractionPolicy, apply_native_extended_style

#: Canonical navigation, in sidebar order.
PAGE_IDS = (
    "overview",
    "settings",
    "diagnostics",
)

#: Page ids that existed before UIUX-01. ``settings.dashboard_last_page`` holds
#: "build" on every existing install, and the tray still navigates by the old names.
PAGE_ALIASES = {
    "build": "overview",
    "items": "overview",
}


class DashboardWindow(ManagedToolWindow):
    """Canonical primary application window."""

    _instance: DashboardWindow | None = None

    #: UIUX-01: the dashboard is the one managed window the user may resize.
    resizable = True

    @staticmethod
    def _resolve_window_size(settings: AppSettings) -> QSize:
        """Pick the opening size, migrating the pre-UIUX-01 default.

        Every existing install has 1280x860 persisted, because that was the old
        default and geometry is written back on every hide. Honouring it would mean
        nobody -- including the people reviewing this redesign -- ever sees the
        compact layout. So the old default (and an unset value) maps to the new
        default, while any other size is the user's own choice and is kept.

        One-shot and self-clearing: after the first deliberate resize the stored
        size is no longer the legacy default and is honoured forever after.
        """
        width = int(getattr(settings, "dashboard_width", 0) or 0)
        height = int(getattr(settings, "dashboard_height", 0) or 0)
        if (width, height) == theme.LEGACY_DEFAULT_WINDOW_SIZE or not (width and height):
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
        self.setWindowTitle(window_title())
        self.setStyleSheet(DASHBOARD_STYLESHEET)
        apply_exile_lens_chrome(self)
        target = self._resolve_window_size(settings)
        self.restore_geometry(
            x=settings.dashboard_x,
            y=settings.dashboard_y,
            width=target.width(),
            height=target.height(),
        )

        self._header = AppHeader(controller, settings, navigate=self.navigate)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: dict[str, QPushButton] = {}
        nav = QVBoxLayout()
        nav.setContentsMargins(0, 8, 0, 8)
        nav.setSpacing(0)
        for page_id, label in (
            ("overview", "Overview"),
            ("market", "Market"),
            ("tree", "Tree"),
            ("gear_optimizer", "Gear Optimizer"),
        ):
            btn = QPushButton(label)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setMinimumHeight(theme.NAV_ITEM_HEIGHT)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, pid=page_id: self.navigate(pid))
            self._nav_group.addButton(btn)
            self._nav_buttons[page_id] = btn
            nav.addWidget(btn)
        # Secondary items sit directly under Overview: one coherent navigation
        # group, separated by a small gap rather than pushed to the window bottom
        # where they read as unrelated.
        nav.addSpacing(theme.SPACE_SM)
        for page_id, label in (("settings", "Settings"), ("diagnostics", "Diagnostics")):
            btn = QPushButton(label)
            btn.setObjectName("navButtonSecondary")
            btn.setCheckable(True)
            btn.setMinimumHeight(theme.NAV_ITEM_HEIGHT)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, pid=page_id: self.navigate(pid))
            self._nav_group.addButton(btn)
            self._nav_buttons[page_id] = btn
            nav.addWidget(btn)
        nav.addStretch(1)
        # Community links sit below the stretch, pinned to the bottom of the rail
        # and visually separated from page navigation -- discoverable without
        # making the sidebar read as a support portal.
        ui_scale = float(getattr(settings, "ui_scale", 1.0) or 1.0)
        for index, (label, tooltip, handler, icon_name) in enumerate((
            (
                "Support ExileLens",
                "Support the continued development of free, open-source ExileLens on Patreon.",
                self._open_patreon,
                "patreon",
            ),
            (
                "Discord",
                "Join the ExileLens Discord for questions, feedback and community help.",
                self._open_discord,
                "discord",
            ),
            (
                "Report an Issue",
                "Open the ExileLens issue tracker on GitHub to report a bug.",
                self._open_github_issues,
                "github",
            ),
        )):
            if index == 1:
                nav.addSpacing(theme.SPACE_SM)
            link = QPushButton(label)
            link.setObjectName("navButtonSecondary")
            link.setMinimumHeight(theme.NAV_ITEM_HEIGHT)
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.setToolTip(tooltip)
            apply_button_icon(link, icon_name, ui_scale=ui_scale)
            link.clicked.connect(handler)
            nav.addWidget(link)

        nav_rail = QWidget()
        nav_rail.setObjectName("navRail")
        nav_rail.setFixedWidth(theme.SIDEBAR_WIDTH)
        nav_rail.setLayout(nav)

        self._stack = QStackedWidget()
        self._pages: dict[str, QWidget] = {}
        self._overview = OverviewPage(controller, settings, navigate=self.navigate)
        self._market = MarketHubPage(controller, settings) if is_enabled(FeatureModule.MARKET) else None
        self._tree = TreeWorkspace(controller, embed_mode=True) if is_enabled(FeatureModule.TREE_TOOLS) else None
        self._gear = GearOptimizerPage(controller) if is_enabled(FeatureModule.GEAR_OPTIMIZER) else None
        self._settings_page = SettingsPage(settings, controller)
        self._diagnostics = DiagnosticsPage(controller, settings, self.update_service)
        for page_id, widget in (
            ("overview", self._overview),
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

        content_pane = QWidget()
        content_pane.setObjectName("contentPane")
        content = QVBoxLayout(content_pane)
        content.setContentsMargins(
            theme.PAGE_GUTTER, theme.SPACE_MD, theme.PAGE_GUTTER, theme.SPACE_MD
        )
        content.setSpacing(0)
        content.addWidget(self._stack, 1)

        # The old status footer repeated "PoB <state> / Generation N / <item set>",
        # which is internal detail that now lives in Diagnostics. Only progress is
        # left, and it stays hidden unless something is actually running.
        self._progress_row = QWidget()
        self._progress_row.setObjectName("progressStrip")
        progress_l = QHBoxLayout(self._progress_row)
        progress_l.setContentsMargins(theme.SPACE_MD, theme.SPACE_SM, theme.SPACE_MD, theme.SPACE_SM)
        self._progress_label = QLabel("")
        self._progress_label.setObjectName("secondaryText")
        progress_l.addWidget(self._progress_label, 1)
        self._progress_row.setVisible(False)
        content.addWidget(self._progress_row)

        self._status_footer = QWidget()
        self._status_footer.setObjectName("dashboardStatusFooter")
        footer_l = QHBoxLayout(self._status_footer)
        footer_l.setContentsMargins(theme.SPACE_MD, theme.SPACE_SM, theme.SPACE_MD, theme.SPACE_SM)
        footer_l.setSpacing(theme.SPACE_SM)
        self._update_check_state = "unchecked"
        self._update_remote_version = ""
        self._update_download_state = ""
        self._update_progress_percent: int | None = None
        self._update_indicator = QLabel("")
        self._update_indicator.setObjectName("updateStatusText")
        self._footer_download_btn = make_button("Download && Install", "primary")
        apply_button_icon(self._footer_download_btn, "download", ui_scale=ui_scale)
        self._footer_download_btn.clicked.connect(self._footer_update_action)
        self._footer_download_btn.setVisible(False)
        self._version_label = QLabel("")
        self._version_label.setObjectName("secondaryText")
        self._version_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        footer_l.addStretch(1)
        footer_l.addWidget(self._update_indicator, 0)
        footer_l.addWidget(self._footer_download_btn, 0)
        footer_l.addWidget(self._version_label, 0)
        content.addWidget(self._status_footer)
        self.update_service.state_changed.connect(self._on_update_state_footer)
        self.update_service.download_state_changed.connect(self._on_update_download_state_footer)
        self.update_service.download_progress.connect(self._on_update_download_progress_footer)
        self.update_service.action_error.connect(self._on_update_action_error_footer)
        self._refresh_version_footer()

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(nav_rail)
        body.addWidget(content_pane, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._header)
        root.addLayout(body, 1)

        if hasattr(controller, "progress_hub"):
            controller.progress_hub.progress_updated.connect(self._on_progress)
            controller.progress_hub.progress_cleared.connect(lambda _op_id: self._refresh_progress())
        self.navigate(settings.dashboard_last_page or "overview")
        self._apply_module_nav()
        self.resize(target)
        # Tray-first startup: never create a visible native window until the user
        # explicitly opens ExileLens (or recovery surfaces Settings).
        self.hide()
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

    @classmethod
    def instance(cls) -> DashboardWindow | None:
        return cls._instance

    def navigate(self, page_id: str) -> None:
        page_id = PAGE_ALIASES.get(page_id, page_id)
        if page_id not in self._pages:
            page_id = PAGE_IDS[0]
        self._stack.setCurrentWidget(self._pages[page_id])
        btn = self._nav_buttons.get(page_id)
        if btn is not None:
            btn.setChecked(True)
        self.settings.dashboard_last_page = page_id
        if page_id == "tree" and self._tree is not None:
            self._tree.on_page_shown()
        if page_id == "diagnostics":
            self._diagnostics.refresh()
        if page_id == "overview":
            self._overview.refresh()
        if page_id == "market" and self._market is not None:
            self._market.refresh()

    @property
    def _build(self) -> QWidget:
        """Back-compat alias for the pre-UIUX-01 attribute name."""
        return self._overview

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
            "market": is_enabled(FeatureModule.MARKET) or is_enabled(FeatureModule.MARKET_ASSISTANT),
            "tree": is_enabled(FeatureModule.TREE_TOOLS),
            "gear_optimizer": is_enabled(FeatureModule.GEAR_OPTIMIZER),
            "settings": True,
            "diagnostics": True,
        }
        for page_id, btn in self._nav_buttons.items():
            btn.setVisible(visible.get(page_id, True))
        current = PAGE_ALIASES.get(
            self.settings.dashboard_last_page or PAGE_IDS[0], self.settings.dashboard_last_page
        )
        if not visible.get(current, True):
            self.navigate(PAGE_IDS[0])

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

    def _on_update_state_footer(self, state: str, version: str) -> None:
        self._update_check_state = state
        self._update_remote_version = version
        if state in ("current", "unchecked", "unavailable"):
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

    def _footer_update_action(self) -> None:
        if self._update_download_state == "ready":
            restart_and_update(self.update_service)
            return
        if self._update_check_state == "available":
            self.update_service.start_download()

    def _refresh_version_footer(self) -> None:
        from exilelens._version import __version__

        self._version_label.setText(f"ExileLens {__version__}")
        summary = footer_update_summary(
            self._update_check_state,
            self._update_download_state,
            self._update_remote_version,
            self._update_progress_percent,
        )
        show_strip = bool(summary) or self._update_download_state in ("downloading", "ready", "installing", "error")
        self._update_indicator.setText(summary)
        self._update_indicator.setVisible(show_strip)
        if self._update_download_state == "ready":
            self._footer_download_btn.setText("Restart && Update")
            self._footer_download_btn.setEnabled(True)
            self._footer_download_btn.setVisible(True)
        elif self._update_download_state == "downloading":
            self._footer_download_btn.setText("Downloading…")
            self._footer_download_btn.setEnabled(False)
            self._footer_download_btn.setVisible(True)
        elif self._update_download_state == "installing":
            self._footer_download_btn.setVisible(False)
        elif self._update_check_state == "available":
            self._footer_download_btn.setText("Download && Install")
            self._footer_download_btn.setEnabled(True)
            self._footer_download_btn.setVisible(True)
        else:
            self._footer_download_btn.setVisible(False)

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
                app.quit()

    # UIUX-01: the dashboard is user-resizable (``resizable = True``), so the size
    # lock that ManagedToolWindow applies on move/resize is deliberately not
    # overridden here any more. Moving still never changes size, because nothing
    # resizes the window on a move.

    def _remember_geometry(self) -> None:
        self.remember_geometry(self.settings, prefix="dashboard")
        save_settings(self.settings)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_native_extended_style(self, WindowInteractionPolicy.INTERACTIVE_APP_WINDOW)
        self._header.refresh()
        recover_window_geometry(self, cap_size=True)
