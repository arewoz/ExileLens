from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from exilelens._version import __version__, is_packaged
from exilelens.app.settings import save_settings
from exilelens.app.updates.archive import extract_zip_to_staging, validate_zip_archive
from exilelens.app.updates.bootstrap import (
    ensure_updater_bootstrapped,
    launch_updater,
    updater_active,
    updater_matches_bundled,
)
from exilelens.app.updates.channels import UpdateChannel
from exilelens.app.updates.constants import (
    AUTO_DOWNLOAD_DISK_FACTOR,
    CHECK_COOLDOWN_SECONDS,
    GITHUB_RELEASES_URL,
    SUPPORTER_CHECK_COOLDOWN_SECONDS,
)
from exilelens.app.updates.download import DownloadError, DownloadManager
from exilelens.app.updates.github import GitHubReleaseClient, installed_version
from exilelens.app.updates.manifest import (
    ManifestError,
    VerifiedUpdateManifest,
    bind_manifest_to_release,
    verify_signed_envelope,
)
from exilelens.app.updates.outcome import UpdateOutcomeNotice, cleanup_after_launch, consume_update_result
from exilelens.app.updates.paths import (
    backup_dir,
    clear_staging,
    download_cache_dir,
    install_root,
    staging_dir,
    updates_data_dir,
    write_update_job,
)
from exilelens.app.updates.ready import ReadyUpdate, discard_ready_record, load_ready_update, write_ready_record
from exilelens.app.updates.version import ExileLensVersion, Release
from exilelens.updater.job import JOB_SCHEMA
from exilelens.updater.result import UpdateResult

# Cleanup of recovery material waits until this launch has been up for a while (healthy start).
POST_LAUNCH_CLEANUP_DELAY_MS = 30_000

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpdateAvailability:
    remote: Release
    installed: ExileLensVersion
    manifest: VerifiedUpdateManifest | None = None


@dataclass(frozen=True)
class NewestReleaseVerificationFailed:
    release: Release
    reason: str


class UpdateService(QObject):
    """Background update checks and user-initiated secure downloads."""

    state_changed = Signal(str, str)
    update_available = Signal(str, str)
    download_progress = Signal(int, int)
    download_state_changed = Signal(str)
    action_error = Signal(str)
    # One-time UpdateOutcomeNotice describing the previous external-updater run (consumed on launch).
    install_outcome = Signal(object)
    #: A supporter's automatic download finished and verified (argument: version).
    auto_update_ready = Signal(str)

    _check_finished = Signal(object, bool)
    _download_finished = Signal(object)
    _ready_restored = Signal(object)
    _prestage_finished = Signal(object)

    def __init__(
        self,
        settings,
        client: GitHubReleaseClient | None = None,
        downloader: DownloadManager | None = None,
        clock=time.time,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.client = client or GitHubReleaseClient()
        self.downloader = downloader or DownloadManager()
        self.clock = clock
        self._check_in_flight = False
        self._availability: UpdateAvailability | None = None
        self._verified_manifest: VerifiedUpdateManifest | None = None
        self._verified_envelope: dict | None = None
        self._ready: ReadyUpdate | None = None
        self._session_started = False
        self.last_install_result: UpdateResult | None = None
        self.last_install_notice: UpdateOutcomeNotice | None = None
        self._download_when_verified = False
        # Entitlement is only ever a yes/no gate on automating THIS existing, signature-verified flow.
        # It cannot supply a URL, version, file name, hash or manifest: there is no parameter for them.
        self._automation_gate: Callable[[], bool] = lambda: False
        self.last_download_mode = "manual"
        self._auto_download_attempted: set[str] = set()
        self._download_state = ""
        self._prestaged: str | None = None
        self._prestage_in_flight = False
        self._verification_failed = False  # newest release failed signed-manifest verification this session
        # TRUST-01D: one single-shot timer that wakes locally when the 24h cooldown elapses. It never polls;
        # the network request itself is still gated by `start_automatic`.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.start_automatic)
        self._check_finished.connect(self._finish_check)
        self._download_finished.connect(self._finish_download)
        self._ready_restored.connect(self._on_ready_restored)
        self._prestage_finished.connect(self._on_prestage_finished)
        self.download_state_changed.connect(self._remember_download_state)

    # -- supporter automation (gate only) ----------------------------------------------------
    def set_automation_gate(self, gate: Callable[[], bool]) -> None:
        self._automation_gate = gate

    def _supporter(self) -> bool:
        try:
            return self._automation_gate() is True  # only a real boolean True; nothing else is ever interpreted
        except Exception:  # noqa: BLE001 - a broken gate means free behaviour
            return False

    def automation_permitted(self, manifest: VerifiedUpdateManifest | None = None) -> bool:
        manifest = manifest or self._verified_manifest
        return manifest is not None and manifest.seamless_eligible and self._supporter()

    def auto_download_enabled(self, manifest: VerifiedUpdateManifest | None = None) -> bool:
        return self.automation_permitted(manifest) and bool(getattr(self.settings, "updates_auto_download", True))

    def install_on_exit_enabled(self, manifest: VerifiedUpdateManifest | None = None) -> bool:
        return self.automation_permitted(manifest) and bool(getattr(self.settings, "updates_install_on_exit", True))

    def _cooldown_seconds(self) -> int:
        return SUPPORTER_CHECK_COOLDOWN_SECONDS if self._supporter() else CHECK_COOLDOWN_SECONDS

    def _remember_download_state(self, state: str) -> None:
        self._download_state = state

    @property
    def installed_version_text(self) -> str:
        return __version__

    def channel(self) -> UpdateChannel:
        return UpdateChannel.parse(getattr(self.settings, "update_channel", UpdateChannel.STABLE.value))

    def set_channel(self, channel: UpdateChannel) -> None:
        self.settings.update_channel = channel.value
        save_settings(self.settings)

    def begin_session(self) -> None:
        """Once per launch (packaged): surface the last updater result, restore a verified ready update,
        and schedule cleanup of recovery material after a healthy start.

        Called explicitly by application startup (never implicitly by checks), because it reads and cleans
        the real app-data update directory.
        """
        if self._session_started or not is_packaged():
            return
        self._session_started = True
        installed = installed_version()
        try:
            result, notice = consume_update_result(installed)
        except OSError:
            logger.exception("update_result_consume_failed")
            result, notice = None, None
        self.last_install_result = result
        self.last_install_notice = notice
        if result is not None:
            logger.info("update_previous_result outcome=%s to=%s", result.outcome.value, result.to_version)
        if notice is not None:
            self.install_outcome.emit(notice)

        def restore() -> None:
            try:
                ready = load_ready_update(installed)
            except Exception:  # noqa: BLE001 - a broken record must never break startup
                logger.exception("update_ready_restore_failed")
                ready = None
            self._ready_restored.emit(ready)

        threading.Thread(target=restore, name="exilelens-update-ready-restore", daemon=True).start()
        updates, root = updates_data_dir(), install_root()
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.setSingleShot(True)
        self._cleanup_timer.timeout.connect(lambda: self._start_post_launch_cleanup(updates, root))
        self._cleanup_timer.start(POST_LAUNCH_CLEANUP_DELAY_MS)

    def _start_post_launch_cleanup(self, updates, root) -> None:
        installed = installed_version()
        consumed = self.last_install_result
        keep = self._verified_manifest.artifact.filename if self._verified_manifest is not None else None
        running = updater_active()

        def run() -> None:
            try:
                cleanup_after_launch(
                    installed=installed,
                    consumed=consumed,
                    keep_archive=keep,
                    updater_running=running,
                    updates_dir=updates,
                    install_dir=root,
                )
            except Exception:  # noqa: BLE001
                logger.exception("update_post_launch_cleanup_failed")

        threading.Thread(target=run, name="exilelens-update-cleanup", daemon=True).start()

    def start_automatic(self) -> bool:
        if not is_packaged():
            self.state_changed.emit("unavailable", "")
            return False
        ensure_updater_bootstrapped()
        if self._check_in_flight:
            # A check is already running: neither touch the cooldown timestamp nor re-emit stale state.
            return False
        now = float(self.clock())
        previous = float(getattr(self.settings, "update_last_check_at", 0.0) or 0.0)
        if previous > 0 and now - previous < self._cooldown_seconds():
            self._emit_known_state()
            self._schedule_next_automatic()
            return False
        self.settings.update_last_check_at = now
        save_settings(self.settings)
        started = self._start_check(manual=False)
        self._schedule_next_automatic()
        return started

    def next_automatic_delay_ms(self) -> int:
        """Milliseconds until the next automatic check becomes eligible (last check + cooldown)."""
        now = float(self.clock())
        previous = float(getattr(self.settings, "update_last_check_at", 0.0) or 0.0)
        due = (previous + self._cooldown_seconds()) if previous > 0 else now
        # +1s tolerance so the wake-up lands just after the cooldown; never faster than every 60s.
        return int(max(60.0, due - now + 1.0) * 1000)

    def _schedule_next_automatic(self) -> None:
        self._timer.start(min(self.next_automatic_delay_ms(), 2**31 - 1))

    def stop_scheduler(self) -> None:
        self._timer.stop()
        cleanup_timer = getattr(self, "_cleanup_timer", None)
        if cleanup_timer is not None:
            cleanup_timer.stop()

    def release_url(self) -> str:
        """Official GitHub release page of the verified newest release, or "" when unknown or not GitHub."""
        url = str(self._availability.remote.url or "") if self._availability is not None else ""
        return url if url.startswith("https://github.com/") else ""

    def check_now(self) -> bool:
        if not is_packaged():
            self.state_changed.emit("unavailable", "")
            return False
        ensure_updater_bootstrapped()
        return self._start_check(manual=True)

    def cancel_download(self) -> None:
        self.downloader.cancel()

    def _pending_remote_is_newer(self) -> bool:
        remote = ExileLensVersion.parse(getattr(self.settings, "update_latest_version", ""))
        installed = installed_version()
        return remote is not None and installed is not None and remote > installed

    def start_download(self, *, mode: str = "manual") -> bool:
        self.last_download_mode = mode if mode in ("manual", "auto") else "manual"
        if (
            (self._availability is None or self._verified_manifest is None)
            and is_packaged()
            and not self._verification_failed
            and self._pending_remote_is_newer()
        ):
            # A pending update remembered from an earlier session has no verified manifest yet: the user's click
            # verifies it first (a user-initiated check), then the download starts.
            self._download_when_verified = True
            self.download_state_changed.emit("downloading")
            self._start_check(manual=True)
            return True
        if self._availability is None:
            self.action_error.emit("No update is available to download.")
            return False
        manifest = self._verified_manifest
        if manifest is None:
            self.action_error.emit("Signed update metadata is not available yet.")
            return False
        destination = download_cache_dir() / manifest.artifact.filename
        self.download_state_changed.emit("downloading")
        return self.downloader.start_background(
            url=manifest.artifact.url,
            destination=destination,
            expected_size=manifest.artifact.size,
            expected_sha256=manifest.artifact.sha256,
            on_progress=lambda done, total: self.download_progress.emit(done, total),
            on_finished=self._download_finished.emit,
        )

    def begin_restart_and_update(self, *, parent_pid: int, restart_after_update: bool = True) -> bool:
        """Stage the verified package and hand off to the external updater (job contract v2).

        ``restart_after_update=False`` is updater infrastructure only (future install-on-exit); no
        production path requests it yet. It is refused unless the app-data updater is byte-identical to
        the bundled v2 updater, because a legacy updater would ignore the flag and always relaunch.
        """
        manifest = self._verified_manifest
        if manifest is None:
            self.action_error.emit("Update is not verified.")
            return False
        if self._prestage_in_flight:
            self.action_error.emit("The update is still being prepared; try again in a moment.")
            return False
        if updater_active():
            self.action_error.emit("An update is already being installed.")
            return False
        if not restart_after_update and not updater_matches_bundled():
            self.action_error.emit("The external updater is out of date; restart ExileLens and try again.")
            return False
        archive_path = download_cache_dir() / manifest.artifact.filename
        if not archive_path.is_file():
            self.action_error.emit("Downloaded update package is missing.")
            return False
        try:
            staged_root = staging_dir() / "ExileLens"
            if self._prestaged != manifest.artifact.filename or not staged_root.is_dir():
                validate_zip_archive(archive_path)
                clear_staging()
                staged_root = extract_zip_to_staging(archive_path, staging_dir())
            # The updater re-verifies the prepared tree against the package and the signed hash either way.
        except Exception:
            logger.exception("update_prepare_failed")
            self.action_error.emit("Downloaded update package failed safety checks.")
            return False
        root = install_root()
        job_path = write_update_job(
            {
                "schema": JOB_SCHEMA,
                "job_id": uuid.uuid4().hex,
                "from_version": __version__,
                "to_version": manifest.version,
                "restart_after_update": bool(restart_after_update),
                "install_root": str(root),
                "staged_root": str(staged_root),
                "backup_root": str(backup_dir()),
                "exe_path": str(root / "ExileLens.exe"),
                "zip_path": str(archive_path),
                "zip_sha256": manifest.artifact.sha256,
                "zip_size": manifest.artifact.size,
                # Legacy keys: a not-yet-refreshed schema-1 updater can still run this restart job.
                "pid": int(parent_pid),
                "version": manifest.version,
            }
        )
        try:
            launch_updater(job_path)
        except Exception:
            logger.exception("update_launch_failed")
            self.action_error.emit("Could not start the external updater.")
            return False
        self._prestaged = None
        self.download_state_changed.emit("installing")
        return True

    # -- supporter: automatic download, pre-staging, install on exit ---------------------------
    def _maybe_auto_download(self) -> None:
        manifest, availability = self._verified_manifest, self._availability
        if manifest is None or availability is None or not availability.remote.version > availability.installed:
            return
        if not self.auto_download_enabled(manifest):
            return
        if self._ready is not None and self._ready.manifest == manifest:
            self._maybe_prestage()
            return
        if manifest.version in self._auto_download_attempted or self.downloader.is_active():
            return
        if not self._enough_disk(manifest):
            logger.info("update_auto_download_skipped reason=disk_space")
            return
        self._auto_download_attempted.add(manifest.version)
        self.start_download(mode="auto")

    def _enough_disk(self, manifest: VerifiedUpdateManifest) -> bool:
        probe = download_cache_dir()
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        try:
            return shutil.disk_usage(probe).free >= AUTO_DOWNLOAD_DISK_FACTOR * manifest.artifact.size
        except OSError:
            return False

    def _maybe_prestage(self) -> None:
        """Extract the verified package in the background so an install on exit is instant and bounded."""
        manifest = self._verified_manifest
        if manifest is None or self._prestage_in_flight or self._prestaged == manifest.artifact.filename:
            return
        if not self.install_on_exit_enabled(manifest):
            return
        archive = download_cache_dir() / manifest.artifact.filename
        if not archive.is_file():
            return
        filename = manifest.artifact.filename
        self._prestage_in_flight = True

        def run() -> None:
            try:
                validate_zip_archive(archive)
                clear_staging()
                extract_zip_to_staging(archive, staging_dir())
                ok = True
            except Exception:  # noqa: BLE001
                logger.exception("update_prestage_failed")
                ok = False
            self._prestage_finished.emit((filename, ok))

        threading.Thread(target=run, name="exilelens-update-prestage", daemon=True).start()

    def _on_prestage_finished(self, payload: object) -> None:
        filename, ok = payload  # type: ignore[misc]
        self._prestage_in_flight = False
        self._prestaged = filename if ok else None

    def install_on_exit_ready(self) -> bool:
        """Everything needed for an unattended install at clean exit is verified and prepared."""
        manifest = self._verified_manifest
        installed = installed_version()
        return bool(
            manifest is not None
            and installed is not None
            and self._download_state == "ready"
            and ExileLensVersion.parse(manifest.version) is not None
            and ExileLensVersion.parse(manifest.version) > installed
            and self.install_on_exit_enabled(manifest)
            and self._prestaged == manifest.artifact.filename
            and not self._prestage_in_flight
            and not updater_active()
            and updater_matches_bundled()
        )

    def begin_install_on_exit(self, *, parent_pid: int) -> bool:
        """Hand the prepared update to the updater WITHOUT relaunching. Never extracts or downloads: if
        anything is not already verified and prepared it does nothing and the update stays pending."""
        if not self.install_on_exit_ready():
            return False
        return self.begin_restart_and_update(parent_pid=parent_pid, restart_after_update=False)

    def _newest_release_for_channel(self) -> Release | None:
        """Newest release offered to this install's update channel (stable users never see betas).

        Falls back to the unfiltered newest release for clients that predate channel
        filtering (test doubles); the real GitHub client always filters.
        """
        selector = getattr(self.client, "best_newest_release_for_channel", None)
        if callable(selector):
            return selector(self.channel())
        return self.client.best_newest_release()

    def _start_check(self, *, manual: bool) -> bool:
        if self._check_in_flight:
            return False
        self._check_in_flight = True
        self.state_changed.emit("checking", "")

        def run() -> None:
            try:
                release = self._newest_release_for_channel()
                if release is None:
                    result: object = None
                else:
                    installed = installed_version()
                    if installed is not None and release.version <= installed:
                        # Already on the newest listed release — no manifest fetch required.
                        result = release
                    elif not release.manifest_asset_url:
                        result = NewestReleaseVerificationFailed(release, "missing_signed_manifest")
                    else:
                        try:
                            envelope = self.client.fetch_json(release.manifest_asset_url)
                            manifest = verify_signed_envelope(envelope)
                            # The release listing is unsigned: bind every decision to the signed fields.
                            bind_manifest_to_release(
                                manifest,
                                tag=release.tag,
                                version=release.version,
                                installed=installed,
                                release_zip_name=release.zip_asset_name,
                            )
                        except (ManifestError, RuntimeError) as exc:
                            logger.warning("update_manifest_unavailable tag=%s error=%s", release.tag, exc)
                            result = NewestReleaseVerificationFailed(release, "manifest_verification_failed")
                        else:
                            result = (release, manifest, envelope)
            except Exception:
                result = RuntimeError("request_failed")
            self._check_finished.emit(result, manual)

        threading.Thread(target=run, name="exilelens-update-check", daemon=True).start()
        return True

    def _finish_check(self, result: object, manual: bool) -> None:
        self._finish_check_inner(result, manual)
        if self._download_when_verified:
            self._download_when_verified = False
            if self._availability is not None and self._verified_manifest is not None and (
                self._availability.remote.version > self._availability.installed
            ):
                self.start_download()
            else:
                self.download_state_changed.emit("")
                self.action_error.emit("The update could not be verified right now. Try again later.")

    def _finish_check_inner(self, result: object, manual: bool) -> None:
        self._check_in_flight = False
        self._verification_failed = isinstance(result, NewestReleaseVerificationFailed)
        self._verified_manifest = None
        if isinstance(result, RuntimeError):
            self.state_changed.emit("failed", "")
            return
        if isinstance(result, NewestReleaseVerificationFailed):
            remote = str(result.release.version)
            self.settings.update_latest_version = remote
            self._availability = None
            self.cancel_download()
            self._drop_ready()
            self.download_state_changed.emit("")
            save_settings(self.settings)
            self.state_changed.emit("verification_failed", remote)
            if manual:
                self.action_error.emit(
                    f"Release {remote} is available but could not be verified safely. "
                    "ExileLens will not install an older release automatically."
                )
            return
        manifest: VerifiedUpdateManifest | None = None
        release: Release | None
        if isinstance(result, tuple):
            release, manifest, envelope = result
            self._verified_manifest = manifest
            self._verified_envelope = envelope
        else:
            release = result  # type: ignore[assignment]
        if release is None:
            self.state_changed.emit("failed", "")
            return
        remote = str(release.version)
        self.settings.update_latest_version = remote
        installed = installed_version()
        if installed is None:
            self.state_changed.emit("failed", "")
            return
        self._availability = UpdateAvailability(remote=release, installed=installed, manifest=manifest)
        if release.version > installed:
            self.state_changed.emit("available", remote)
            if self.settings.update_notified_version != remote:
                self.settings.update_notified_version = remote
                self.update_available.emit(remote, str(installed))
        elif release.version < installed:
            # This build is newer than anything released to its channel (an unpublished
            # candidate or a development build). Not "up to date", and not an error.
            self.state_changed.emit("ahead", remote)
        else:
            self.state_changed.emit("current", remote)
        save_settings(self.settings)
        ready = self._ready
        if ready is not None:
            if manifest is not None and ready.manifest == manifest:
                self.download_state_changed.emit("ready")
            else:
                # Superseded by a newer verified release, or already installed.
                self._drop_ready()
                self.download_state_changed.emit("")
        self._maybe_auto_download()

    def _drop_ready(self) -> None:
        if self._ready is None:
            return
        self._ready = None
        self._prestaged = None
        try:
            discard_ready_record(delete_archive=True)
        except OSError:
            logger.exception("update_ready_discard_failed")

    def _on_ready_restored(self, ready: object) -> None:
        if not isinstance(ready, ReadyUpdate):
            return
        if self._check_in_flight:
            self._ready = ready  # the in-flight check decides whether it is still current
            return
        current = self._availability
        if current is not None and current.remote.version != ready.version:
            self._ready = ready
            self._drop_ready()
            return
        installed = installed_version()
        if installed is None or not ready.version > installed:
            self._ready = ready
            self._drop_ready()
            return
        self._ready = ready
        self._verified_manifest = ready.manifest
        self._verified_envelope = ready.envelope
        release = Release(ready.version, GITHUB_RELEASES_URL, ready.manifest.tag, not ready.version.final)
        self._availability = UpdateAvailability(remote=release, installed=installed, manifest=ready.manifest)
        remote = str(ready.version)
        self.settings.update_latest_version = remote
        save_settings(self.settings)
        self.state_changed.emit("available", remote)
        self.download_state_changed.emit("ready")
        logger.info("update_ready_restored version=%s", remote)
        self._maybe_prestage()

    def _finish_download(self, result: object) -> None:
        if isinstance(result, DownloadError):
            self.settings.update_last_error = str(result)
            save_settings(self.settings)
            self.download_state_changed.emit("error")
            self.action_error.emit(
                {
                    "cancelled": "Download cancelled.",
                    "hash_mismatch": "Download failed verification.",
                    "size_mismatch": "Download size did not match the signed manifest.",
                }.get(str(result), "Download failed.")
            )
            return
        self.settings.update_last_error = ""
        save_settings(self.settings)
        manifest, envelope = self._verified_manifest, self._verified_envelope
        if manifest is not None and envelope is not None:
            try:
                write_ready_record(envelope, manifest)
            except OSError:
                logger.exception("update_ready_record_write_failed")
        self.download_state_changed.emit("ready")
        if self.last_download_mode == "auto" and manifest is not None:
            self.auto_update_ready.emit(manifest.version)
        self._maybe_prestage()

    def _emit_known_state(self) -> None:
        remote = ExileLensVersion.parse(getattr(self.settings, "update_latest_version", ""))
        installed = installed_version()
        if remote is not None and installed is not None:
            state = "available" if remote > installed else ("ahead" if remote < installed else "current")
            self.state_changed.emit(state, str(remote))
        else:
            self.state_changed.emit("unchecked", "")


UpdateCheckService = UpdateService
