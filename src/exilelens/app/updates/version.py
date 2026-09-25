from __future__ import annotations

import re
from dataclasses import dataclass

from exilelens.app.updates.constants import GITHUB_RELEASES_URL


@dataclass(frozen=True, order=True)
class ExileLensVersion:
    major: int
    minor: int
    patch: int
    final: bool
    beta: int

    @classmethod
    def parse(cls, value: object) -> "ExileLensVersion | None":
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:b(\d+))?", str(value or "").strip())
        if match is None:
            return None
        major, minor, patch, beta = match.groups()
        return cls(int(major), int(minor), int(patch), beta is None, int(beta or 0))

    def __str__(self) -> str:
        suffix = "" if self.final else f"b{self.beta}"
        return f"{self.major}.{self.minor}.{self.patch}{suffix}"


@dataclass(frozen=True)
class Release:
    version: ExileLensVersion
    url: str
    tag: str
    prerelease: bool
    manifest_asset_url: str | None = None
    zip_asset_url: str | None = None
    zip_asset_name: str | None = None


def parse_release_payload(payload: object) -> Release | None:
    if not isinstance(payload, dict):
        return None
    if bool(payload.get("draft")):
        return None
    tag = str(payload.get("tag_name") or "").strip()
    version = ExileLensVersion.parse(tag[1:] if tag.startswith("v") else tag)
    if version is None:
        return None
    manifest_url: str | None = None
    zip_url: str | None = None
    zip_name: str | None = None
    for asset in payload.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if name.endswith(".update.json"):
            manifest_url = url or None
        elif name.endswith("-win64.zip"):
            zip_url = url or None
            zip_name = name or None
    return Release(
        version=version,
        url=GITHUB_RELEASES_URL,
        tag=tag,
        prerelease=bool(payload.get("prerelease")),
        manifest_asset_url=manifest_url,
        zip_asset_url=zip_url,
        zip_asset_name=zip_name,
    )
