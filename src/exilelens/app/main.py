from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

WORKER_ARG = "--exilelens-worker"
LEGACY_WORKER_ARG = "--poe2value-worker"
UPDATER_ARG = "--exilelens-updater"
_WORKER_ARGS = {WORKER_ARG, LEGACY_WORKER_ARG}


def _maybe_run_worker_subprocess() -> None:
    if _WORKER_ARGS.intersection(sys.argv):
        from exilelens.worker import run_worker_entrypoint

        raise SystemExit(run_worker_entrypoint())


def _maybe_run_updater_subprocess() -> None:
    if UPDATER_ARG in sys.argv:
        from exilelens.updater.__main__ import main as updater_main

        index = sys.argv.index(UPDATER_ARG)
        job_args = sys.argv[index + 1 :]
        raise SystemExit(updater_main(job_args or None))


_maybe_run_worker_subprocess()
_maybe_run_updater_subprocess()

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from exilelens.app.build_state import BuildState
from exilelens.app.controller import EvaluationController
from exilelens._version import __version__
from exilelens.branding import APP_NAME, app_icon, apply_windows_app_id
from exilelens.price_check.capture_diagnostics import CapturePhase as PriceCheckCapturePhase, log_capture_phase
from exilelens.app.instance_ipc import (
    COMMAND_ACTIVATE,
    COMMAND_QUIT,
    QUIT_ARG,
    InstanceServer,
    allow_foreground_activation,
    clear_instance_record,
    find_running_instances,
    read_instance_record,
    send_command,
    terminate_instance,
    write_instance_record,
)
from exilelens.app.logging_setup import configure_logging, install_crash_handlers, log_price_check_startup_mode
from exilelens.app.modules.registry import FeatureModule, is_enabled
from exilelens.app.build_cache import BuildCache
from exilelens.app.legacy_migration import migrate_character_build
from exilelens.app.settings import AppSettings, load_settings_result, onboarding_required, save_settings
from exilelens.app.single_instance import InstanceLock, acquire_single_instance_lock
from exilelens.platform.windows.clipboard import ClipboardEvent, ClipboardWatcher
from exilelens.tree.calibration_session import CapturePhase
from exilelens.tree.overlay_frame import OverlayAppearance
from exilelens.tree.overlay_mode import OverlayMode
from exilelens.ui.dashboard_window import DashboardWindow
from exilelens.ui.market_assistant_overlay import MarketAssistantOverlay
from exilelens.ui.overlay import OverlayWindow
from exilelens.ui.onboarding_dialog import OnboardingDialog
from exilelens.ui.tray import TrayManager
from exilelens.ui.tree_overlay import LiveTreeOverlayWindow, frame_from_model, stack_item_above_tree
from exilelens.ui.tree_overlay_capture import CalibrationCaptureOverlay
from exilelens.ui.tree_overlay_finetune import OverlayFineTuneDialog

logger = logging.getLogger(__name__)

_EXIT_WATCHDOG_S = 20.0


class ExileLensApp:
    def __init__(self) -> None:
        # Configure the durable failure path before settings load or migration can
        # fail. Neither operation requires a QApplication.
        self.log_path = configure_logging()
        install_crash_handlers()
        load_result = load_settings_result()
        self.settings = load_result.settings
        self._settings_load_error = load_result.load_error
        migrate_character_build(self.settings)
        if self._settings_load_error:
            from exilelens.app.settings import backup_settings_file

            backup = backup_settings_file("corrupt")
            logger.warning("settings_load_failed defaults_in_use backup=%s", backup)
        log_price_check_startup_mode(self.settings)
        self._restore_trade_penalties()
        self._shutdown_done = False
        self.controller: EvaluationController | None = None
        self.overlay: OverlayWindow | None = None
        self.market_assist_overlay: MarketAssistantOverlay | None = None
        self.tree_overlay: LiveTreeOverlayWindow | None = None
        self.capture_overlay: CalibrationCaptureOverlay | None = None
        self.dashboard: DashboardWindow | None = None
        self._coach_hidden_for_capture = False
        self._anchors_only = False
        self._league_prompt_open = False
        self.clipboard: ClipboardWatcher | None = None
        self.tray: TrayManager | None = None
        self._instance_lock: InstanceLock | None = None
        self._instance_server: InstanceServer | None = None
        self._primary_instance = False
        self._tray_retry_timer: QTimer | None = None
        self._tray_retries_left = 0
        self._setup_dialog: OnboardingDialog | None = None
        self._refine_dialog = None
    def run(self) -> int:
        apply_windows_app_id()
        app = QApplication(sys.argv)
        app.setProperty("exilelens_app_shell", self)
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName(APP_NAME)
        app.setApplicationDisplayName(APP_NAME)
        app.setApplicationVersion(__version__)
        icon = app_icon()
        if icon is not None:
            app.setWindowIcon(icon)
        app.aboutToQuit.connect(self._on_about_to_quit)
        logger.info("app_start version=%s pid=%s exe=%s", __version__, os.getpid(), sys.executable)

        # A second copy would compete for the same global Item Check hotkey. It hands
        # activation to the running copy instead of starting.
        self._instance_lock = acquire_single_instance_lock()
        if not self._instance_lock.acquired:
            logger.info("second instance detected: %s", self._instance_lock.reason)
            outcome = self._handle_second_instance()
            if outcome is not None:
                return outcome
        elif QUIT_ARG in sys.argv:
            logger.info("quit requested but no instance is running")
            return 0
        self._start_instance_server()

        from exilelens.security_audit import overlay_disabled

        if overlay_disabled():
            self.settings.overlay_enabled = False
        self._compose_primary_ui()
        from exilelens.diagnostics.wiring import (
            attach_controller_diagnostics,
            attach_update_diagnostics,
            record_application_initialized,
        )

        assert self.controller is not None and self.dashboard is not None
        attach_controller_diagnostics(self.controller)
        attach_update_diagnostics(self.dashboard.update_service)
        record_application_initialized()
        if is_enabled(FeatureModule.MARKET_ASSISTANT):
            self.market_assist_overlay = MarketAssistantOverlay(self.settings)
        if is_enabled(FeatureModule.LIVE_TREE_OVERLAY):
            self.tree_overlay = LiveTreeOverlayWindow()
            self.capture_overlay = CalibrationCaptureOverlay()
            self.capture_overlay.clicked_client.connect(self._on_capture_click)
            self.capture_overlay.cancelled.connect(self._on_capture_cancelled)
        self.clipboard = ClipboardWatcher()

        self._show_tray()

        assert self.controller is not None
        self.controller.price_check_hotkey.bind(controller=self.controller)
        self._set_item_check_active(True)
        self._wire_signals()
        self.controller.engine_ready.connect(self._on_engine_ready)
        self.controller.engine_failed.connect(self._on_engine_failed)

        assert self.clipboard is not None
        self.clipboard.clipboard_event.connect(self._on_clipboard_event)

        # Update discovery is best-effort and starts only after the tray and UI
        # exist. Source runs are rejected by the service without a request.
        QTimer.singleShot(0, self.dashboard.update_service.start_automatic)

        # Everything that can block (worker boot, build load, network) runs once the
        # event loop is live, so the tray and second-launch activation always respond.
        # The dialog observes this normal startup pipeline. It does not probe PoB or
        # load a build itself, keeping startup to one worker and one build load.
        if onboarding_required(self.settings):
            QTimer.singleShot(0, self._show_onboarding)
        QTimer.singleShot(0, self._start_engine)
        return app.exec()

    def _compose_primary_ui(self, *, quit_callback=None) -> None:
        """Build the production Item Check UI without starting external inputs or PoB."""
        self.controller = EvaluationController(self.settings)
        self.overlay = OverlayWindow(self.settings)
        self.dashboard = DashboardWindow(self.settings, self.controller)

        self.overlay.set_placement_callback(self.controller.record_overlay_placement)
        self.overlay.set_pin_handlers(
            on_pin=self.controller.pin_from_overlay,
            can_pin=self.controller.can_pin_more,
        )
        self.overlay.set_retry_handler(self.controller.retry_last_item_check)
        self.controller.pin_compare_changed.connect(self._on_pin_compare_changed)
        if quit_callback is None:
            app = QApplication.instance()
            quit_callback = app.quit if app is not None else None
        self.tray = TrayManager(
            self.settings,
            self.controller,
            self.overlay,
            self.dashboard,
            on_setup=lambda: self._show_onboarding(manual=True),
            on_quit=quit_callback,
        )
        self.controller.item_dismiss.bind(overlay=self.overlay, controller=self.controller)

    # --- lifecycle / recovery -------------------------------------------------------

    def _start_instance_server(self) -> None:
        self._primary_instance = True
        server = InstanceServer()
        server.activate_requested.connect(self._on_activate_requested)
        server.quit_requested.connect(self._on_quit_requested)
        server.start()
        self._instance_server = server
        write_instance_record()

    def _handle_second_instance(self) -> int | None:
        """Return an exit code, or None when this launch took over as the instance."""
        if QUIT_ARG in sys.argv:
            return 0 if send_command(COMMAND_QUIT) else 1
        allow_foreground_activation()
        if send_command(COMMAND_ACTIVATE):
            logger.info("second_instance activated the running instance")
            return 0

        record = read_instance_record()
        pids = [record.pid] if record is not None else find_running_instances()
        expected_exe = record.exe if record is not None else sys.executable
        logger.warning("second_instance running_instance_unresponsive record=%s pids=%s", record, pids)
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            APP_NAME,
            f"{APP_NAME} is already running but is not responding.\n\n"
            "You can end the running copy and start a fresh one. "
            "Your settings and Path of Building builds are not changed.",
        )
        end_button = box.addButton("End it and restart", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not end_button:
            logger.info("second_instance user kept the unresponsive instance")
            return 0

        failures = []
        for pid in pids:
            ok, detail = terminate_instance(pid, expected_exe)
            if not ok:
                failures.append(detail)
        lock = acquire_single_instance_lock()
        if not lock.acquired:
            detail = "; ".join(failures) or "the running copy did not exit"
            logger.error("second_instance takeover_failed detail=%s", detail)
            QMessageBox.critical(
                None,
                APP_NAME,
                f"{APP_NAME} could not end the running copy ({detail}).\n\n"
                "Signing out of Windows or restarting the PC will clear it.",
            )
            return 1
        logger.info("second_instance took over after ending the unresponsive instance")
        self._instance_lock = lock
        return None

    def _show_tray(self) -> None:
        assert self.tray is not None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
            self.tray.show_startup_notification()
            logger.info("tray_ready visible=%s", self.tray.isVisible())
            return
        # Explorer can still be starting (autostart, fresh login). Retry silently so a
        # briefly unavailable tray never flashes the full dashboard; surface it only
        # after retries are exhausted.
        logger.warning("tray_unavailable at startup; retrying without surfacing dashboard")
        self._tray_retries_left = 30
        timer = QTimer()
        timer.setInterval(2000)
        timer.timeout.connect(self._retry_tray)
        timer.start()
        self._tray_retry_timer = timer

    def _retry_tray(self) -> None:
        self._tray_retries_left -= 1
        if QSystemTrayIcon.isSystemTrayAvailable() and self.tray is not None:
            if self._tray_retry_timer is not None:
                self._tray_retry_timer.stop()
            self.tray.show()
            if self.dashboard is not None:
                self.dashboard.exit_on_close = False
            logger.info("tray_ready after_retry visible=%s", self.tray.isVisible())
            return
        if self._tray_retries_left <= 0 and self._tray_retry_timer is not None:
            self._tray_retry_timer.stop()
            logger.error("tray_unavailable permanently; surfacing dashboard as last resort")
            if self.dashboard is not None:
                self.dashboard.exit_on_close = True
                self._surface_dashboard("build")

    def _tray_visible(self) -> bool:
        return self.tray is not None and self.tray.isVisible()

    def _start_engine(self) -> None:
        if self.controller is None:
            return
        self._refresh_league_catalog_at_startup()
        self.controller.start_engine_async()

    def _on_engine_ready(self) -> None:
        if self.controller is None:
            return
        build_path = self._resolve_startup_build_path()
        if build_path:
            if self.settings.build_path != build_path:
                self.settings.build_path = build_path
                save_settings(self.settings)
            self.controller.load_build(build_path, context=self.settings.context)
        # The first-run dialog observes the same controller. Returning users get the
        # compact recovery page instead of a welcome-flow replay.
        info = self.controller.build_info
        if info.state == BuildState.READY:
            return
        if not self.settings.onboarding_version_completed:
            return
        if info.path and info.error_message:
            self._open_recovery_ui(f"Couldn't load your PoB build: {info.error_message}")
        else:
            self._open_recovery_ui("No PoB build is loaded. Choose your build file in Settings.")

    def _on_engine_failed(self, message: str) -> None:
        if not self.settings.onboarding_version_completed:
            return
        self._open_recovery_ui(f"{message}\n\nCheck the Path of Building installation in Settings.")

    def _show_onboarding(self, manual: bool = False) -> None:
        """Show one reusable setup window without restarting application services."""
        if self.controller is None:
            return
        if self._setup_dialog is not None:
            self._setup_dialog.showNormal()
            self._setup_dialog.raise_()
            self._setup_dialog.activateWindow()
            return
        dialog = OnboardingDialog(
            self.settings,
            self.controller,
            on_diagnostics=lambda: self._surface_dashboard("diagnostics"),
            parent=self.dashboard,
        )
        dialog.finished.connect(lambda _result: setattr(self, "_setup_dialog", None))
        self._setup_dialog = dialog
        logger.info("setup_dialog_shown manual=%s", manual)
        dialog.show()

    def _open_recovery_ui(self, message: str) -> None:
        """Startup could not finish on its own: show Settings with the reason."""
        logger.warning("recovery_ui_opened reason=%s", message.replace("\n", " "))
        self._surface_dashboard("settings")
        if self._tray_visible():
            self.tray.showMessage(APP_NAME, message, QSystemTrayIcon.MessageIcon.Warning, 8000)

    def _surface_dashboard(self, page: str) -> None:
        if self.dashboard is None:
            return
        self.dashboard.navigate(page)
        if self.dashboard.isMinimized():
            self.dashboard.showNormal()
        self.dashboard.show_dashboard()
        logger.info("dashboard_surfaced page=%s", page)

    def _on_activate_requested(self) -> None:
        dialog = getattr(self, "_setup_dialog", None)
        if dialog is not None:
            dialog.showNormal()
            dialog.raise_()
            dialog.activateWindow()
            logger.info("dashboard_surfaced page=first_run_setup")
            return
        if self.dashboard is None or self.controller is None:
            logger.info("activation received before the window exists")
            return
        ready = self.controller.build_info.state == BuildState.READY and not self.controller.engine_error
        self._surface_dashboard("build" if ready else "settings")

    def _on_quit_requested(self) -> None:
        logger.info("ipc_quit_dispatch_to_application")
        dialog = getattr(self, "_setup_dialog", None)
        if dialog is not None:
            # A modal exec() loop does not end on app.quit(); close it explicitly.
            dialog.reject()
        app = QApplication.instance()
        if app is not None:
            # This handler runs nested inside QLocalSocket's own readyRead delivery
            # (InstanceServer -> quit_requested), on Windows backed by an overlapped
            # (asynchronous) named pipe. Tearing the server down here -- destroying
            # the very socket whose in-flight read is still being delivered to us --
            # crashed with a native "Fatal Python error: Aborted" on every IPC quit,
            # reproduced from source and confirmed unrelated to any other subsystem
            # (worker thread, hooks, engine, clipboard, tray all ruled out
            # individually). Requeuing with QTimer.singleShot(0, ...) was not enough:
            # Qt can still run a zero-delay timer before the pipe's async I/O has
            # actually settled. A short real delay lets that settle before teardown
            # runs, the same wait-for-native-resource pattern already used elsewhere
            # in shutdown (thread.join/proc.wait timeouts). Tray Exit needs no such
            # delay: it calls plain app.quit(), which only triggers aboutToQuit after
            # the triggering QAction's own call stack has fully unwound.
            QTimer.singleShot(150, self._finish_ipc_quit)

    def _finish_ipc_quit(self) -> None:
        self.shutdown()
        app = QApplication.instance()
        if app is not None:
            app.exit(0)

    @staticmethod
    def _trade_policy_path():
        from exilelens.app.settings import app_data_dir

        return app_data_dir() / "trade2_policy.json"

    def _restore_trade_penalties(self) -> None:
        """Re-arm occupancy and any server penalty from the last run or another process."""
        from exilelens.price_check.rate_policy import shared_policy_registry

        try:
            registry = shared_policy_registry()
            path = self._trade_policy_path()
            registry.load_penalties(path)
            registry.enable_persist(path)
        except Exception:  # noqa: BLE001 - never block startup on this
            logger.exception("could not restore trade2 policy")

    def _persist_trade_penalties(self) -> None:
        from exilelens.price_check.rate_policy import shared_policy_registry

        try:
            shared_policy_registry().save_penalties(self._trade_policy_path())
        except Exception:  # noqa: BLE001
            logger.exception("could not persist trade2 penalties")

    def _refresh_league_catalog_at_startup(self) -> None:
        """Warm the league cache once per launch; never fatal, never blocking a search."""
        if not self.controller:
            return
        try:
            result = self.controller.refresh_league_catalog()
        except Exception:
            logger.exception("league catalog refresh failed at startup")
            return
        logger.info(
            "price_check_league_catalog startup status=%s leagues=%d from_cache=%s",
            result.status,
            len(result.leagues),
            result.from_cache,
        )

    def _set_item_check_active(self, active: bool) -> None:
        if self.clipboard is not None:
            self.clipboard.set_enabled(active)
        dismiss = self.controller.item_dismiss if self.controller else None
        if dismiss is None:
            return
        if active:
            dismiss.start()
        else:
            dismiss.stop()
            if self.overlay:
                self.overlay.dismiss()
        if active and self.controller:
            if not self.controller.price_check_hotkey.start():
                logger.error(
                    "price_check_hotkey_register_failed hotkey=%s registered=%s module=ITEM_CHECK",
                    self.controller.price_check_hotkey.hook.hotkey,
                    self.controller.price_check_hotkey.hook_registered,
                )
        elif self.controller:
            self.controller.price_check_hotkey.stop()

    def _resolve_startup_build_path(self) -> str | None:
        build_path = str(self.settings.build_path or "").strip()
        if build_path and Path(build_path).is_file():
            return build_path
        controller = getattr(self, "controller", None)
        cache = controller._build_cache if controller is not None else BuildCache()
        cached = cache.load_active()
        if cached is not None:
            cached_path = str(cached.build_path or "").strip()
            if cached_path and Path(cached_path).is_file():
                return cached_path
        return None

    def _wire_signals(self) -> None:
        assert self.controller is not None
        assert self.overlay is not None
        self.controller.evaluation_started.connect(self._on_eval_started)
        self.controller.analyzing.connect(self.overlay.show_analyzing)
        self.controller.evaluation_warming.connect(self.overlay.show_warming)
        self.controller.evaluation_timeout.connect(self.overlay.show_timeout)
        self.controller.evaluation_finished.connect(self._on_eval_finished)
        self.controller.evaluation_error.connect(self.overlay.show_error)
        self.controller.evaluation_titled_error.connect(self.overlay.show_titled_error)
        self.controller.presentation_invalidated.connect(self._on_presentation_invalidated)
        self.controller.last_result_rescored.connect(self._on_result_rescored)
        self.controller.upgrade_path_updated.connect(self._on_upgrade_path_updated)
        self.controller.tree_overlay_show_requested.connect(self._on_tree_overlay_show)
        self.controller.tree_overlay_calibrate_requested.connect(self._on_tree_overlay_calibrate)
        self.controller.tree_overlay_invalidated.connect(self._refresh_tree_overlay)
        self.controller.tree_overlay_mode_requested.connect(self._on_tree_overlay_mode)
        self.controller.tree_overlay_realign_requested.connect(self._on_quick_realign)
        self.controller.tree_overlay_scale_requested.connect(self._on_recalibrate_scale)
        self.controller.tree_overlay_test_pattern_requested.connect(self._on_test_pattern)
        self.controller.tree_overlay_debug_requested.connect(self._on_overlay_debug)
        self.controller.tree_overlay_capture_requested.connect(self._on_capture_phase)
        self.controller.tree_overlay_fine_tune_requested.connect(self._open_fine_tune)
        self.controller.tree_overlay_looks_good_requested.connect(self._on_looks_good)
        self.controller.tree_overlay_reset_calibration_requested.connect(self._on_reset_calibration)
        self.controller.tree_overlay_anchors_only_requested.connect(self._on_anchors_only)
        self.controller.analysis_finished.connect(lambda _payload: self._refresh_tree_overlay())
        self.controller.baseline_state_changed.connect(lambda _state: self._refresh_tree_overlay())
        self.controller.item_dismiss.dismissed.connect(lambda: None)
        self.controller.market_capture_updated.connect(self._on_market_capture_updated)
        self.controller.market_capture_session_changed.connect(self._on_market_capture_session_changed)
        self.controller.market_capture_new_best.connect(self._on_market_capture_new_best)
        self.controller.price_check_hotkey.capture_requested.connect(self._on_price_check_hotkey)
        self.controller.price_check_hotkey.poe_inactive.connect(self._on_price_check_poe_inactive)
        self.controller.price_check_hotkey.capture_blocked.connect(self._on_price_check_blocked)
        self.controller.price_check_captured.connect(self._on_price_check_captured)
        self.controller.price_check_started.connect(self._on_price_check_started)
        self.controller.price_check_finished.connect(self._on_price_check_finished)
        self.controller.refine_last_price_requested.connect(self._on_refine_last_price)
        self.controller.refine_price_hotkey.refine_requested.connect(self._on_refine_last_price)
        self.controller.league_selection_required.connect(self._on_league_selection_required)
        if self.controller:
            if not self.controller.price_check_hotkey.start():
                logger.error(
                    "price_check_hotkey_register_failed hotkey=%s registered=%s",
                    self.controller.price_check_hotkey.hook.hotkey,
                    self.controller.price_check_hotkey.hook_registered,
                )
            if self.settings.price_check_enabled:
                self.controller.refine_price_hotkey.start()

    def _on_clipboard_event(self, event: ClipboardEvent) -> None:
        if not self.controller:
            return
        # CS-001: never log clipboard content (or a slice of it). The clipboard
        # listener sees every clipboard change on the machine, from any
        # application, not only PoE2 - length/sequence metadata is the most
        # this log line may ever carry.
        logger.info(
            "clipboard_event seq=%s len=%s",
            event.sequence,
            len(event.text or ""),
        )
        if self.controller.route_price_check_clipboard(
            text=event.text,
            sequence=event.sequence,
            anchor_screen_px=event.copy_anchor_screen_px,
        ):
            return
        if self.controller.should_suppress_gameplay_for_price_capture(event.sequence):
            return
        captured, capture_message = self.controller.try_market_capture_clipboard(
            event.text,
            content_hash=event.content_hash,
            clipboard_sequence=event.sequence,
        )
        if captured and self.controller.market_assist_suppress_popup():
            return
        self.controller.try_external_clipboard_item_check(
            event.text,
            sequence=event.sequence,
            content_hash=event.content_hash,
            copy_anchor_screen_px=event.copy_anchor_screen_px,
            cursor_position=event.cursor_position,
            copy_timestamp=event.received_at,
        )

    def _on_price_check_hotkey(self, request_id: int, anchor: object) -> None:
        if not self.controller:
            return
        physical_anchor = anchor if isinstance(anchor, tuple) else None
        if physical_anchor is None:
            from exilelens.platform.windows.cursor import get_cursor_pos_physical

            physical_anchor = get_cursor_pos_physical() or (0, 0)
        capture_id = self.controller.begin_price_check_capture(physical_anchor, request_id=int(request_id))
        if capture_id is None:
            self.controller._on_price_check_capture_failed(
                int(request_id),
                "Path of Exile 2 must be active.",
            )

    def _on_price_check_poe_inactive(self, request_id: int) -> None:
        if not self.controller:
            return
        self.controller._on_price_check_capture_failed(int(request_id), "Path of Exile 2 must be active.")

    def _on_price_check_blocked(self, request_id: int, message: str) -> None:
        if not self.controller:
            return
        text = str(message or "Could not read hovered item.")
        self.controller._on_price_check_capture_failed(int(request_id), text)

    def _on_league_selection_required(
        self,
        request_id: int,
        leagues: object,
        failure_code: str,
        stale_league: str,
    ) -> None:
        """Ask for the league once, then let the controller resume the parked request."""
        if self._league_prompt_open:
            return
        if not self.controller:
            return
        from exilelens.ui.league_dialog import prompt_for_league

        options = list(leagues or [])
        if not options:
            # The cached list is empty; try once to fetch it so the picker is useful.
            try:
                options = list(self.controller.refresh_league_catalog(force=True).leagues)
            except Exception:
                logger.exception("league catalog refresh failed while opening the picker")
                options = []
            options = options or list(self.controller.league_catalog.selectable_leagues())

        self._league_prompt_open = True
        try:
            chosen = prompt_for_league(
                options,
                current=self.settings.market_league,
                failure_code=str(failure_code or ""),
                stale_league=str(stale_league or ""),
                parent=self.dashboard,
            )
        finally:
            self._league_prompt_open = False

        if not chosen:
            logger.info("league selection cancelled request_id=%s", request_id)
            return
        self.controller.apply_league_selection(chosen, pinned=True)

    def _price_check_panel(self):
        """The MARKET-03 panel, built on first use.

        Lazy so a headless or price-check-disabled run never constructs a widget, and so
        the panel outlives any single capture -- a pinned panel is expected to.
        """
        if getattr(self, "_interactive_price_panel", None) is None:
            from exilelens.ui.interactive_price_check_panel import InteractivePriceCheckPanel

            panel = InteractivePriceCheckPanel()
            panel.refresh_requested.connect(self._on_price_panel_refresh)
            self._interactive_price_panel = panel
        return self._interactive_price_panel

    def _on_price_check_captured(self, request_id: int, payload: dict) -> None:
        """Acknowledge the capture before the market is asked.

        This is the product-level answer to "Shift+C did nothing": the panel is on screen
        with the item's name and base while the search is still pending or queued.
        """
        if not self.settings.price_check_enabled:
            return
        panel = self._price_check_panel()
        generation = int(payload.get("generation") or 0)
        panel.adopt_generation(generation)
        anchor = payload.get("anchor")
        panel.open_for_capture(
            generation,
            item_name=str(payload.get("item_name") or "Item"),
            base_line=str(payload.get("base_line") or ""),
        )
        if isinstance(anchor, tuple):
            panel.place_near(anchor)
        log_capture_phase(
            PriceCheckCapturePhase.OVERLAY_SHOW_CALLED,
            capture_id=request_id,
            surface="price_check_panel",
            generation=generation,
        )

    def _on_price_panel_refresh(self, edits: dict) -> None:
        if self.controller is None:
            return
        self.controller.submit_panel_refresh(edits)

    def _on_price_check_started(self, request_id: int) -> None:
        # The interactive panel owns the loading state now, and it is opened from the
        # capture signal. The passive analyzing tooltip would race it onto the screen.
        if self.settings.price_check_enabled:
            return
        if self.overlay and self.settings.overlay_enabled:
            anchor = self.controller.copy_anchor_for_request(request_id) if self.controller else None
            if anchor is not None:
                self.overlay.set_anchor_cursor(request_id, None, physical_anchor=anchor)
            self.overlay.show_price_check_analyzing(request_id)

    def _on_price_check_finished(self, request_id: int, payload: dict) -> None:
        # MARKET-03: the result belongs to the panel that is already on screen. Falling
        # through to the passive tooltip would show the same answer twice, on two
        # surfaces, one of which the user cannot edit.
        meta = (payload or {}).get("request_meta") or {}
        if self.settings.price_check_enabled:
            panel = self._price_check_panel()
            generation = int(meta.get("generation") or 0)
            model = (payload or {}).get("panel_model")
            if model is not None:
                applied = panel.apply_model(generation, model)
                log_capture_phase(
                    PriceCheckCapturePhase.OVERLAY_VISIBLE_AFTER_SHOW,
                    capture_id=request_id,
                    surface="price_check_panel",
                    generation=generation,
                    applied=bool(applied),
                )
                return
            presentation = (payload or {}).get("presentation") or {}
            if presentation:
                panel.apply_presentation_fallback(generation, presentation)
                log_capture_phase(
                    PriceCheckCapturePhase.OVERLAY_VISIBLE_AFTER_SHOW,
                    capture_id=request_id,
                    surface="price_check_panel",
                    generation=generation,
                    applied=True,
                    fallback=True,
                )
                return
            return
        if not self.overlay or not self.settings.overlay_enabled:
            log_capture_phase(
                PriceCheckCapturePhase.OVERLAY_SUPPRESSED,
                capture_id=request_id,
                overlay_present=self.overlay is not None,
                overlay_enabled=bool(self.settings.overlay_enabled),
            )
            return
        presentation = payload.get("presentation") or {}
        log_capture_phase(PriceCheckCapturePhase.OVERLAY_SHOW_CALLED, capture_id=request_id)
        try:
            self.overlay.show_price_check(request_id, presentation)
        except Exception:
            logger.exception("price_check_overlay_show_failed request_id=%s", request_id)
            raise
        log_capture_phase(
            PriceCheckCapturePhase.OVERLAY_VISIBLE_AFTER_SHOW,
            capture_id=request_id,
            visible=bool(self.overlay.isVisible()),
            geometry=[
                self.overlay.geometry().x(),
                self.overlay.geometry().y(),
                self.overlay.geometry().width(),
                self.overlay.geometry().height(),
            ],
            window_opacity=float(self.overlay.windowOpacity()),
        )

    def _on_refine_last_price(self) -> None:
        """Compatibility alias: show and pin the panel rather than a second surface.

        The old Refine dialog stays reachable through _open_legacy_refine_dialog until
        MARKET-03 parity is proven, but it is not on the normal path any more.
        """
        if not self.controller or not self.controller.has_last_price_check():
            return
        if self.settings.price_check_enabled:
            panel = self._price_check_panel()
            panel.show_panel()
            if not panel.pinned:
                panel._toggle_pin()
            return
        self._open_legacy_refine_dialog()

    def _open_legacy_refine_dialog(self) -> None:
        if not self.controller or not self.controller.has_last_price_check():
            return
        from exilelens.ui.refine_price_dialog import RefinePriceDialog

        hypothesis = self.controller.last_price_check_hypothesis()
        if hypothesis is None:
            return
        if self._refine_dialog is None:
            self._refine_dialog = RefinePriceDialog(
                None,
                on_refresh=self.controller.submit_refined_price_check,
            )
        self._refine_dialog.load_hypothesis(
            hypothesis,
            self.controller.last_price_check_presentation(),
        )
        self._refine_dialog.show()
        self._refine_dialog.raise_()
        self._refine_dialog.activateWindow()

    def _on_eval_started(self, request_id: int) -> None:
        if self.settings.overlay_enabled and self.overlay and self.controller:
            # An ExileLens-owned Item Check started. This arms the overlay for this
            # request's paints without showing anything.
            self.overlay.authorize_show(int(request_id))
            self.overlay.set_presentation_generation(self.controller.presentation_generation)
            anchor = self.controller.copy_anchor_for_request(request_id)
            if anchor is not None:
                self.overlay.set_anchor_cursor(request_id, None, physical_anchor=anchor)

    def _on_eval_finished(self, request_id: int, result: dict) -> None:
        if not self.settings.overlay_enabled or not self.overlay or not self.controller:
            return
        meta = result.setdefault("request_meta", {})
        anchor_meta = meta.get("copy_anchor_screen_px")
        if anchor_meta and isinstance(anchor_meta, dict):
            ax = anchor_meta.get("x")
            ay = anchor_meta.get("y")
            if ax is not None and ay is not None:
                self.overlay.set_anchor_cursor(request_id, None, physical_anchor=(int(ax), int(ay)))
        result_gen = meta.get("presentation_generation")
        latest_request_id = self.controller.latest_request_id
        if (
            result_gen is not None
            and result_gen != self.controller.presentation_generation
            and request_id != latest_request_id
        ):
            return
        meta["build_name"] = self.controller.build_info.name if self.controller else ""
        if self.controller.active_loadout:
            meta["loadout_name"] = self.controller.active_loadout
        if result_gen is not None:
            self.overlay.set_presentation_generation(int(result_gen))
        self.overlay.show_result(request_id, result)

    def _on_result_rescored(self, result: dict) -> None:
        if not self.settings.overlay_enabled or not self.overlay:
            return
        self.overlay.show_last_result(result)

    def _on_upgrade_path_updated(self, request_id: int, result: dict) -> None:
        if not self.settings.overlay_enabled or not self.overlay or not self.controller:
            return
        meta = result.get("request_meta") or {}
        if meta.get("presentation_generation") != self.controller.presentation_generation:
            return
        self.overlay.update_result_in_place(request_id, result)
        if self.controller:
            self.controller.refresh_pinned_results(result)

    def _on_presentation_invalidated(self) -> None:
        if self.overlay:
            from exilelens.ui.overlay_visibility import OverlayHideReason

            self.overlay.set_presentation_generation(self.controller.presentation_generation)
            self.overlay.dismiss(reason=OverlayHideReason.PRESENTATION_INVALIDATED)

    def _on_tree_overlay_show(self, visible: bool) -> None:
        if visible and self.controller and not is_enabled(FeatureModule.LIVE_TREE_OVERLAY):
            return
        self.settings.tree_overlay_enabled = bool(visible)
        if self.tree_overlay:
            self.tree_overlay.set_overlay_visible(bool(visible))
        self._refresh_tree_overlay()

    def _on_test_pattern(self) -> None:
        if not self.tree_overlay:
            return
        enabled = not self.tree_overlay._test_pattern
        self.tree_overlay.set_test_pattern(enabled)
        if enabled:
            stack_item_above_tree(tree=self.tree_overlay, item=self.overlay)

    def _on_tree_overlay_mode(self, mode: str) -> None:
        self.settings.tree_overlay_mode = str(mode)
        save_settings(self.settings)
        self._refresh_tree_overlay()

    def _on_overlay_debug(self, enabled: bool) -> None:
        self.settings.tree_overlay_debug = bool(enabled)
        save_settings(self.settings)
        if self.tree_overlay:
            self.tree_overlay.set_debug(bool(enabled))
        self._refresh_tree_overlay()

    def _on_capture_phase(self, which: str) -> None:
        if not self.controller:
            return
        mapping = {
            "A": CapturePhase.CAPTURE_A,
            "B": CapturePhase.CAPTURE_B,
            "REALIGN": CapturePhase.REALIGN,
            "SCALE": CapturePhase.RECALIBRATE_SCALE_A,
            "VERIFY": CapturePhase.VERIFY_C,
        }
        phase = mapping.get(str(which).upper())
        if phase is None:
            return
        err = self.controller.calibration_session.begin_capture(phase)
        if err:
            return
        self._begin_capture()

    def _on_looks_good(self) -> None:
        if not self.controller:
            return
        self.controller.calibration_session.looks_good = True
        payload = self.controller.calibration_session.to_calibration_payload()
        if payload:
            self.settings.tree_overlay_calibration = payload
            save_settings(self.settings)
            self.controller.bump_calibration_generation()
        self.settings.tree_overlay_enabled = True
        self.settings.tree_overlay_mode = OverlayMode.BUILD_PATH.value
        self._refresh_tree_overlay()

    def _on_reset_calibration(self) -> None:
        if not self.controller:
            return
        self.controller.calibration_session.reset()
        self.settings.tree_overlay_calibration = {}
        save_settings(self.settings)
        self.controller.bump_calibration_generation()
        self._refresh_tree_overlay()

    def _on_anchors_only(self, enabled: bool) -> None:
        self._anchors_only = bool(enabled)
        self._refresh_tree_overlay()

    def _on_tree_overlay_calibrate(self) -> None:
        if self.dashboard is not None:
            self.dashboard.navigate("tree")
            self.dashboard.show_dashboard()
            ws = self.dashboard.tree_workspace()
            if ws is not None:
                ws._advanced.setChecked(True)

    def _on_quick_realign(self) -> None:
        if not self.controller:
            return
        err = self.controller.calibration_session.begin_capture(CapturePhase.REALIGN)
        if err:
            return
        self._begin_capture()

    def _on_recalibrate_scale(self) -> None:
        if not self.controller:
            return
        err = self.controller.calibration_session.begin_capture(CapturePhase.RECALIBRATE_SCALE_A)
        if err:
            return
        self._begin_capture()

    def begin_overlay_capture(self) -> None:
        self._begin_capture()

    def _begin_capture(self) -> None:
        if not self.controller or not self.capture_overlay:
            return
        session = self.controller.calibration_session
        if self.dashboard is not None and self.dashboard.isVisible():
            self.dashboard.hide()
            self._coach_hidden_for_capture = True
        rect = self.tree_overlay.client_logical_rect() if self.tree_overlay else None
        if rect:
            session.client_logical = rect
            self.capture_overlay.bind_client_rect(rect)
        self.capture_overlay.set_prompt(session.capture_prompt())
        self.capture_overlay.show()
        self.capture_overlay.raise_()
        self.capture_overlay.activateWindow()

    def _restore_after_capture(self) -> None:
        if self.capture_overlay:
            self.capture_overlay.hide()
            self.capture_overlay.releaseKeyboard()
        if self._coach_hidden_for_capture and self.dashboard is not None:
            self.dashboard.navigate("tree")
            self.dashboard.show_dashboard()
        self._coach_hidden_for_capture = False
        self._refresh_tree_overlay()

    def _on_capture_click(self, x: float, y: float) -> None:
        if not self.controller:
            return
        session = self.controller.calibration_session
        err = session.record_client_click(x, y)
        if session.phase is CapturePhase.IDLE:
            self._restore_after_capture()
            if session.transform is not None:
                self.settings.tree_overlay_enabled = True
                self.settings.tree_overlay_mode = OverlayMode.BUILD_PATH.value
                payload = session.to_calibration_payload()
                if payload:
                    self.settings.tree_overlay_calibration = payload
                    save_settings(self.settings)
                    self.controller.bump_calibration_generation()
            self._refresh_tree_overlay()
            if self.dashboard is not None:
                workspace = self.dashboard.tree_workspace()
                if workspace is not None:
                    workspace.refresh_calibration_panel()
        elif session.phase is CapturePhase.RECALIBRATE_SCALE_B and self.capture_overlay:
            self.capture_overlay.set_prompt(session.capture_prompt())
        if err:
            self._restore_after_capture()

    def _on_capture_cancelled(self) -> None:
        if self.controller:
            self.controller.calibration_session.cancel_capture()
        self._restore_after_capture()

    def _open_fine_tune(self) -> None:
        if not self.controller:
            return
        dlg = OverlayFineTuneDialog(self.controller.calibration_session, self._refresh_tree_overlay)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.controller.calibration_session.looks_good = True
            payload = self.controller.calibration_session.to_calibration_payload()
            if payload:
                self.settings.tree_overlay_calibration = payload
                save_settings(self.settings)
                self.controller.bump_calibration_generation()
            self._refresh_tree_overlay()

    def _refresh_tree_overlay(self) -> None:
        if not self.controller or not self.tree_overlay:
            return
        if not is_enabled(FeatureModule.LIVE_TREE_OVERLAY):
            self.tree_overlay.clear_markers()
            self.tree_overlay.set_overlay_visible(False)
            return
        session = self.controller.calibration_session
        tracked = self.controller.tracked_snapshot()
        session.mark_layout(tracked)
        appearance = OverlayAppearance(
            opacity=float(self.settings.tree_overlay_opacity),
            marker_size=float(self.settings.tree_overlay_marker_size),
            line_width=float(self.settings.tree_overlay_line_width),
        )
        self.tree_overlay.set_appearance(appearance)
        self.tree_overlay.set_debug(bool(self.settings.tree_overlay_debug))
        if self.controller.build_info.state.value != "READY":
            if self.tree_overlay._test_pattern:
                self.tree_overlay.set_overlay_visible(True)
                return
            self.tree_overlay.clear_markers()
            return
        x0, y0, x1, y1 = self.tree_overlay.client_logical_rect()
        viewport = (0.0, 0.0, float(x1 - x0), float(y1 - y0))
        try:
            mode = OverlayMode(self.settings.tree_overlay_mode)
        except ValueError:
            mode = OverlayMode.BUILD_PATH
        if self._anchors_only:
            mode = OverlayMode.CALIBRATION_ANCHORS
        preview = session.ui_status().value == "PREVIEW"
        frame = frame_from_model(
            self.controller.tree_view_model,
            baseline_generation=self.controller.baseline_generation,
            calibration=self.settings.tree_overlay_calibration,
            viewport=viewport,
            mode=mode,
            transform=session.transform,
            anchors=(
                session.anchor_a.node_id if session.anchor_a else None,
                session.anchor_b.node_id if session.anchor_b else None,
            ),
            preview=preview,
            debug={"window": (x1 - x0, y1 - y0, x0, y0)},
            tracked_snapshot=self.controller.tracked_snapshot(),
            tracked_generation=self.controller.tracked_tree_generation,
        )
        self.controller.tree_overlay_diagnostics = {
            "coverage": frame.coverage,
            "misalignment": frame.misalignment,
            "status": frame.status_line,
            "calibration": session.ui_status().value,
            "hwnd": self.tree_overlay.hwnd_diagnostic(),
        }
        self.tree_overlay.set_frame(frame)
        if self.settings.tree_overlay_enabled or self.tree_overlay._test_pattern:
            self.tree_overlay.set_overlay_visible(True)
            stack_item_above_tree(tree=self.tree_overlay, item=self.overlay)

    def _on_market_capture_updated(self, payload: dict) -> None:
        if not self.market_assist_overlay or not self.controller:
            return
        runtime = self.controller.market_assist_runtime_settings()
        if not runtime.overlay_enabled:
            return
        self.market_assist_overlay.show_session(payload)

    def _on_market_capture_session_changed(self, payload: dict) -> None:
        if not self.market_assist_overlay:
            return
        if payload.get("active"):
            self._on_market_capture_updated(payload)
        else:
            self.market_assist_overlay.hide_session()
            if self.market_assist_overlay:
                self.market_assist_overlay.remember_geometry_to_settings()

    def _on_market_capture_new_best(self) -> None:
        if self.market_assist_overlay:
            self.market_assist_overlay.flash_new_best()

    def request_restart_for_update(self, *, parent_pid: int) -> None:
        dashboard = getattr(self, "dashboard", None)
        if dashboard is None:
            return
        if not dashboard.update_service.begin_restart_and_update(parent_pid=parent_pid):
            return

        def finish() -> None:
            self.shutdown()
            app = QApplication.instance()
            if app is not None:
                app.quit()

        QTimer.singleShot(150, finish)

    def shutdown(self) -> None:
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True
        if not getattr(self, "_primary_instance", False):
            # A second launch that handed activation over owns nothing to tear down and
            # must not write the running instance's settings.
            instance_lock = getattr(self, "_instance_lock", None)
            if instance_lock is not None:
                instance_lock.release()
                self._instance_lock = None
            return
        logger.info("shutdown_begin")
        from exilelens.diagnostics.wiring import record_application_shutdown

        record_application_shutdown()
        self._persist_trade_penalties()
        # 1-4: stop taking input (hotkeys, capture, mouse dismiss hook, clipboard).
        if self.controller:
            self._shutdown_step("price_check_capture", self.controller.price_check_capture.shutdown)
            self._shutdown_step("price_check_hotkey", self.controller.price_check_hotkey.stop)
            self._shutdown_step("refine_price_hotkey", self.controller.refine_price_hotkey.stop)
            self._shutdown_step("item_dismiss", self.controller.item_dismiss.stop)
        if self.clipboard:
            self._shutdown_step("clipboard", lambda: self.clipboard.set_enabled(False))
        # Persist layout. A settings file that failed to load is never overwritten: it
        # stays on disk for inspection and Reset Configuration.
        if not getattr(self, "_settings_load_error", False):
            if getattr(self, "dashboard", None):
                self.dashboard.remember_geometry(self.settings, prefix="dashboard")
            if self.overlay:
                self.overlay.remember_position()
            if self.controller and self.controller.build_info.path:
                self.settings.build_path = self.controller.build_info.path
            self._shutdown_step("save_settings", lambda: save_settings(self.settings))
        # 5-6: workers, PoB subprocesses, pinned/overlay windows.
        if self.controller:
            self._shutdown_step("controller", self.controller.shutdown)
        for window in (self.overlay, getattr(self, "market_assist_overlay", None), getattr(self, "tree_overlay", None)):
            if window is not None:
                self._shutdown_step("overlay_hide", window.hide)
        # 7-9: tray, IPC, and finally the single-instance lock.
        if getattr(self, "_tray_retry_timer", None) is not None:
            self._tray_retry_timer.stop()
        if getattr(self, "tray", None) is not None:
            self._shutdown_step("tray", self.tray.hide)
        server = getattr(self, "_instance_server", None)
        if server is not None:
            self._shutdown_step("instance_server", server.close)
            self._instance_server = None
        clear_instance_record()
        instance_lock = getattr(self, "_instance_lock", None)
        if instance_lock is not None:
            instance_lock.release()
            self._instance_lock = None
        logger.info("shutdown_complete")

    @staticmethod
    def _shutdown_step(name: str, action) -> None:  # noqa: ANN001
        """One teardown step; a failure is logged and never skips the remaining steps."""
        try:
            action()
        except Exception:  # noqa: BLE001
            logger.exception("shutdown_step_failed step=%s", name)

    def _on_about_to_quit(self) -> None:
        # Last resort: if teardown or interpreter exit hangs (a stuck native hook or
        # thread), end the process rather than leave an invisible zombie holding the
        # single-instance lock. Daemon timer, so a normal exit never waits on it.
        import threading

        def _force_exit() -> None:
            logger.critical("exit_watchdog fired: shutdown did not finish in %ss; forcing exit", _EXIT_WATCHDOG_S)
            logging.shutdown()
            os._exit(0)

        timer = threading.Timer(_EXIT_WATCHDOG_S, _force_exit)
        timer.daemon = True
        timer.start()
        self.shutdown()

    def _on_pin_compare_changed(self) -> None:
        return


def main() -> int:
    app = ExileLensApp()
    try:
        return app.run()
    finally:
        app.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
