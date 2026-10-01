from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from exilelens._version import __version__, is_packaged
from exilelens.app.settings import save_settings
from exilelens.app.updates.archive import extract_zip_to_staging, validate_zip_archive
from exilelens.app.updates.bootstrap import ensure_updater_bootstrapped, launch_updater
from exilelens.app.updates.channels import UpdateChannel
from exilelens.app.updates.constants import CHECK_COOLDOWN_SECONDS
from exilelens.app.updates.download import DownloadError, DownloadManager
from exilelens.app.updates.github import GitHubReleaseClient, installed_version
from exilelens.app.updates.manifest import ManifestError, VerifiedUpdateManifest, verify_signed_envelope
from exilelens.app.updates.paths import (
    backup_dir,
    clear_staging,
    download_cache_dir,
    install_root,
    staging_dir,
    write_update_job,
)
from exilelens.app.updates.version import ExileLensVersion, Release

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

    _check_finished = Signal(object, bool)
    _download_finished = Signal(object)

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
        self._download_when_verified = False
        self._verification_failed = False  # newest release failed signed-manifest verification this session
        # TRUST-01D: one single-shot timer that wakes locally when the 24h cooldown elapses. It never polls;
        # the network request itself is still gated by `start_automatic`.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.start_automatic)
        self._check_finished.connect(self._finish_check)
        self._download_finished.connect(self._finish_download)

    @property
    def installed_version_text(self) -> str:
        return __version__

    def channel(self) -> UpdateChannel:
        return UpdateChannel.parse(getattr(self.settings, "update_channel", UpdateChannel.BETA.value))

    def set_channel(self, channel: UpdateChannel) -> None:
        self.settings.update_channel = channel.value
        save_settings(self.settings)

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
        if previous > 0 and now - previous < CHECK_COOLDOWN_SECONDS:
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
        due = (previous + CHECK_COOLDOWN_SECONDS) if previous > 0 else now
        # +1s tolerance so the wake-up lands just after the cooldown; never faster than every 60s.
        return int(max(60.0, due - now + 1.0) * 1000)

    def _schedule_next_automatic(self) -> None:
        self._timer.start(min(self.next_automatic_delay_ms(), 2**31 - 1))

    def stop_scheduler(self) -> None:
        self._timer.stop()

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

    def start_download(self) -> bool:
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

    def begin_restart_and_update(self, *, parent_pid: int) -> bool:
        manifest = self._verified_manifest
        if manifest is None:
            self.action_error.emit("Update is not verified.")
            return False
        archive_path = download_cache_dir() / manifest.artifact.filename
        if not archive_path.is_file():
            self.action_error.emit("Downloaded update package is missing.")
            return False
        try:
            validate_zip_archive(archive_path)
            clear_staging()
            staged_root = extract_zip_to_staging(archive_path, staging_dir())
        except Exception:
            logger.exception("update_prepare_failed")
            self.action_error.emit("Downloaded update package failed safety checks.")
            return False
        job_path = write_update_job(
            {
                "schema": 1,
                "version": manifest.version,
                "pid": int(parent_pid),
                "install_root": str(install_root()),
                "staged_root": str(staged_root),
                "backup_root": str(backup_dir()),
                "exe_path": str(install_root() / "ExileLens.exe"),
            }
        )
        try:
            launch_updater(job_path)
        except Exception:
            logger.exception("update_launch_failed")
            self.action_error.emit("Could not start the external updater.")
            return False
        self.download_state_changed.emit("installing")
        return True

    def _start_check(self, *, manual: bool) -> bool:
        if self._check_in_flight:
            return False
        self._check_in_flight = True
        self.state_changed.emit("checking", "")

        def run() -> None:
            try:
                release = self.client.best_newest_release()
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
                        except (ManifestError, RuntimeError) as exc:
                            logger.warning("update_manifest_unavailable tag=%s error=%s", release.tag, exc)
                            result = NewestReleaseVerificationFailed(release, "manifest_verification_failed")
                        else:
                            result = (release, manifest)
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
            release, manifest = result
            self._verified_manifest = manifest
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
        else:
            self.state_changed.emit("current", remote)
        save_settings(self.settings)

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
        self.download_state_changed.emit("ready")

    def _emit_known_state(self) -> None:
        remote = ExileLensVersion.parse(getattr(self.settings, "update_latest_version", ""))
        installed = installed_version()
        if remote is not None and installed is not None:
            self.state_changed.emit("available" if remote > installed else "current", str(remote))
        else:
            self.state_changed.emit("unchecked", "")


UpdateCheckService = UpdateService
