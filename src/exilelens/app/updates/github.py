from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

from exilelens.app.updates.channels import UpdateChannel, release_matches_channel
from exilelens.app.updates.constants import GITHUB_RELEASES_API, NETWORK_TIMEOUT_SECONDS
from exilelens.app.updates.version import ExileLensVersion, Release, parse_release_payload


class GitHubReleaseClient:
    def __init__(self, opener: Callable = urllib.request.urlopen) -> None:
        self._opener = opener

    def list_releases(self, *, per_page: int = 30) -> list[Release]:
        url = f"{GITHUB_RELEASES_API}?per_page={int(per_page)}"
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "ExileLens-update-check"},
            method="GET",
        )
        try:
            with self._opener(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
                raw = response.read(2 * 1024 * 1024)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            raise RuntimeError("request_failed") from None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("invalid_response") from None
        if not isinstance(payload, list):
            return []
        releases: list[Release] = []
        for row in payload:
            parsed = parse_release_payload(row)
            if parsed is not None:
                releases.append(parsed)
        return releases

    def latest_release(self) -> Release | None:
        releases = self.list_releases(per_page=1)
        return releases[0] if releases else None

    def best_release_for_channel(self, channel: UpdateChannel) -> Release | None:
        candidates = [row for row in self.list_releases() if release_matches_channel(row, channel)]
        if not candidates:
            return None
        return max(candidates, key=lambda row: row.version)

    def fetch_json(self, url: str, *, max_bytes: int = 512 * 1024) -> object:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "ExileLens-update-check"},
            method="GET",
        )
        try:
            with self._opener(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
                raw = response.read(max_bytes)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            raise RuntimeError("request_failed") from None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("invalid_response") from None


def installed_version() -> ExileLensVersion | None:
    from exilelens._version import __version__

    return ExileLensVersion.parse(__version__)
