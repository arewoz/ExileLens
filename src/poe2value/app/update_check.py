"""Small, privacy-preserving GitHub Releases update availability checker."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, Signal

from poe2value._version import __version__, is_packaged
from poe2value.app.settings import save_settings

GITHUB_LATEST_RELEASE_API = "https://api.github.com/repos/arewoz/ExileLens/releases/latest"
GITHUB_RELEASES_URL = "https://github.com/arewoz/ExileLens/releases"
GITHUB_ISSUES_URL = "https://github.com/arewoz/ExileLens/issues"
CHECK_COOLDOWN_SECONDS = 24 * 60 * 60
TIMEOUT_SECONDS = 3


@dataclass(frozen=True, order=True)
class ExileLensVersion:
    major: int
    minor: int
    patch: int
    final: bool
    beta: int

    @classmethod
    def parse(cls, value: object) -> "ExileLensVersion | None":
        import re

        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:b(\d+))?", str(value or "").strip())
        if match is None:
            return None
        major, minor, patch, beta = match.groups()
        # ``final`` sorts after every beta of the same release.
        return cls(int(major), int(minor), int(patch), beta is None, int(beta or 0))

    def __str__(self) -> str:
        suffix = "" if self.final else f"b{self.beta}"
        return f"{self.major}.{self.minor}.{self.patch}{suffix}"


@dataclass(frozen=True)
class Release:
    version: ExileLensVersion
    url: str


def parse_latest_release(payload: object) -> Release | None:
    """Validate GitHub's one authoritative, normal latest release response."""
    if not isinstance(payload, dict):
        return None
    if bool(payload.get("draft")) or bool(payload.get("prerelease")):
        return None
    tag = str(payload.get("tag_name") or "").strip()
    version = ExileLensVersion.parse(tag[1:] if tag.startswith("v") else tag)
    if version is None:
        return None
    # The browser destination is fixed locally. Do not trust arbitrary API URLs.
    return Release(version, GITHUB_RELEASES_URL)


class GitHubReleaseClient:
    def __init__(self, opener: Callable = urllib.request.urlopen) -> None:
        self._opener = opener

    def latest_release(self) -> Release | None:
        request = urllib.request.Request(
            GITHUB_LATEST_RELEASE_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "ExileLens-update-check"},
            method="GET",
        )
        try:
            with self._opener(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read(512 * 1024)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            raise RuntimeError("request_failed") from None
        try:
            return parse_latest_release(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("invalid_response") from None


class UpdateCheckService(QObject):
    """One-shot background checks; never part of item evaluation or startup critical path."""

    state_changed = Signal(str, str)  # state, bounded version
    update_available = Signal(str, str)  # remote, installed
    _finished = Signal(object, bool)

    def __init__(self, settings, client: GitHubReleaseClient | None = None, clock=time.time) -> None:
        super().__init__()
        self.settings = settings
        self.client = client or GitHubReleaseClient()
        self.clock = clock
        self._in_flight = False
        self._finished.connect(self._finish)

    def start_automatic(self) -> bool:
        if not is_packaged():
            self.state_changed.emit("unavailable", "")
            return False
        now = float(self.clock())
        previous = float(getattr(self.settings, "update_last_check_at", 0.0) or 0.0)
        if previous > 0 and now - previous < CHECK_COOLDOWN_SECONDS:
            self._emit_known_state()
            return False
        self.settings.update_last_check_at = now
        save_settings(self.settings)
        return self._start(manual=False)

    def check_now(self) -> bool:
        if not is_packaged():
            self.state_changed.emit("unavailable", "")
            return False
        return self._start(manual=True)

    def _start(self, *, manual: bool) -> bool:
        if self._in_flight:
            return False
        self._in_flight = True
        self.state_changed.emit("checking", "")

        def run() -> None:
            try:
                result: Release | RuntimeError | None = self.client.latest_release()
            except Exception:  # noqa: BLE001 - an update check must stay non-fatal
                result = RuntimeError("request_failed")
            self._finished.emit(result, manual)

        threading.Thread(target=run, name="exilelens-update-check", daemon=True).start()
        return True

    def _finish(self, result: Release | RuntimeError | None, manual: bool) -> None:
        self._in_flight = False
        if isinstance(result, RuntimeError):
            self.state_changed.emit("failed", "")
            return
        if result is None:
            self.state_changed.emit("failed", "")
            return
        remote = str(result.version)
        self.settings.update_latest_version = remote
        installed = ExileLensVersion.parse(__version__)
        if installed is None:
            self.state_changed.emit("failed", "")
            return
        if result.version > installed:
            self.state_changed.emit("available", remote)
            if self.settings.update_notified_version != remote:
                self.settings.update_notified_version = remote
                self.update_available.emit(remote, str(installed))
        else:
            self.state_changed.emit("current", remote)
        save_settings(self.settings)

    def _emit_known_state(self) -> None:
        remote = ExileLensVersion.parse(getattr(self.settings, "update_latest_version", ""))
        installed = ExileLensVersion.parse(__version__)
        if remote is not None and installed is not None:
            self.state_changed.emit("available" if remote > installed else "current", str(remote))
        else:
            self.state_changed.emit("unchecked", "")
