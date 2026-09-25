from __future__ import annotations

from enum import Enum

from exilelens.app.updates.version import ExileLensVersion, Release


class UpdateChannel(str, Enum):
    STABLE = "stable"
    BETA = "beta"

    @classmethod
    def parse(cls, raw: object) -> "UpdateChannel":
        value = str(raw or "").strip().lower()
        if value == cls.STABLE.value:
            return cls.STABLE
        return cls.BETA


def release_matches_channel(release: Release, channel: UpdateChannel) -> bool:
    if channel is UpdateChannel.BETA:
        return True
    return release.version.final and not release.prerelease
