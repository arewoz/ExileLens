from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

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
        now = float(self.clock())
        previous = float(getattr(self.settings, "update_last_check_at", 0.0) or 0.0)
        if previous > 0 and now - previous < CHECK_COOLDOWN_SECONDS:
            self._emit_known_state()
            return False
        self.settings.update_last_check_at = now
        save_settings(self.settings)
        return self._start_check(manual=False)

    def check_now(self) -> bool:
        if not is_packaged():
            self.state_changed.emit("unavailable", "")
            return False
        ensure_updater_bootstrapped()
        return self._start_check(manual=True)

    def cancel_download(self) -> None:
        self.downloader.cancel()

    def start_download(self) -> bool:
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
                release = self.client.best_release_for_channel(self.channel())
                result: Release | RuntimeError | None = release
                if release is not None and release.manifest_asset_url:
                    try:
                        envelope = self.client.fetch_json(release.manifest_asset_url)
                        manifest = verify_signed_envelope(envelope)
                    except (ManifestError, RuntimeError) as exc:
                        logger.warning("update_manifest_unavailable tag=%s error=%s", release.tag, exc)
                        manifest = None
                    else:
                        result = (release, manifest)
            except Exception:
                result = RuntimeError("request_failed")
            self._check_finished.emit(result, manual)

        threading.Thread(target=run, name="exilelens-update-check", daemon=True).start()
        return True

    def _finish_check(self, result: object, manual: bool) -> None:
        self._check_in_flight = False
        self._verified_manifest = None
        if isinstance(result, RuntimeError):
            self.state_changed.emit("failed", "")
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
