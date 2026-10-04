"""Update channel selection and the "ahead" state (UI redesign: 0.7.0b1 must not read as "up to date" against 0.6.0).

Signed-manifest validation is untouched here; these tests only cover which release a channel is offered and how a
build newer than the newest published release is reported.
"""

from __future__ import annotations

import pytest

from exilelens.app.updates.channels import UpdateChannel
from exilelens.app.updates.constants import GITHUB_RELEASES_URL
from exilelens.app.updates.github import GitHubReleaseClient
from exilelens.app.updates.version import ExileLensVersion, Release


def _release(version: str, *, prerelease: bool | None = None) -> Release:
    parsed = ExileLensVersion.parse(version)
    assert parsed is not None
    pre = (not parsed.final) if prerelease is None else prerelease
    return Release(parsed, GITHUB_RELEASES_URL, f"v{version}", pre)


class _ListedClient(GitHubReleaseClient):
    def __init__(self, releases: list[Release]) -> None:
        super().__init__()
        self._listed = releases

    def list_releases(self, *, per_page: int = 30) -> list[Release]:
        return list(self._listed)


RELEASES = [_release("0.6.0"), _release("0.7.0b1"), _release("0.7.0b2"), _release("0.7.0"), _release("0.7.1b1")]


def test_stable_channel_never_offers_a_beta() -> None:
    newest = _ListedClient(RELEASES).best_newest_release_for_channel(UpdateChannel.STABLE)
    assert newest is not None and str(newest.version) == "0.7.0"


def test_stable_channel_with_only_betas_published_offers_nothing() -> None:
    client = _ListedClient([_release("0.7.0b1"), _release("0.7.0b2")])
    assert client.best_newest_release_for_channel(UpdateChannel.STABLE) is None


def test_beta_channel_is_offered_later_betas() -> None:
    client = _ListedClient([_release("0.6.0"), _release("0.7.0b1"), _release("0.7.0b2")])
    newest = client.best_newest_release_for_channel(UpdateChannel.BETA)
    assert newest is not None and str(newest.version) == "0.7.0b2"


def test_beta_channel_moves_on_to_the_final_release() -> None:
    client = _ListedClient([_release("0.7.0b1"), _release("0.7.0b2"), _release("0.7.0")])
    newest = client.best_newest_release_for_channel(UpdateChannel.BETA)
    assert newest is not None and str(newest.version) == "0.7.0"
    assert newest.version > ExileLensVersion.parse("0.7.0b2")


def test_list_order_does_not_matter() -> None:
    newest = _ListedClient(list(reversed(RELEASES))).best_newest_release_for_channel(UpdateChannel.BETA)
    assert newest is not None and str(newest.version) == "0.7.1b1"


@pytest.fixture
def service(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from exilelens.app.settings import AppSettings
    from exilelens.app.updates import service as svc

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(svc, "save_settings", lambda _s: None)
    monkeypatch.setattr(svc, "ensure_updater_bootstrapped", lambda: None)
    monkeypatch.setattr(svc, "is_packaged", lambda: True)
    monkeypatch.setattr(svc, "updater_active", lambda: False)
    instance = svc.UpdateService(AppSettings())
    yield instance
    instance.stop_scheduler()
    assert app is not None


def _states(service, monkeypatch, installed: str, release: Release) -> list[tuple[str, str]]:
    from exilelens.app.updates import service as svc

    monkeypatch.setattr(svc, "installed_version", lambda: ExileLensVersion.parse(installed))
    seen: list[tuple[str, str]] = []
    service.state_changed.connect(lambda state, version: seen.append((state, version)))
    service._finish_check_inner(release, True)
    return seen


def test_build_newer_than_the_newest_release_is_reported_as_ahead(service, monkeypatch) -> None:
    assert _states(service, monkeypatch, "0.7.0b1", _release("0.6.0")) == [("ahead", "0.6.0")]


def test_same_version_is_current_and_a_newer_release_is_available(service, monkeypatch) -> None:
    assert _states(service, monkeypatch, "0.6.0", _release("0.6.0")) == [("current", "0.6.0")]


def test_newer_release_is_available(service, monkeypatch) -> None:
    seen = _states(service, monkeypatch, "0.7.0b1", _release("0.7.0b2"))
    assert seen[0] == ("available", "0.7.0b2")


def test_service_uses_the_channel_aware_selector(service, monkeypatch) -> None:
    asked: list[UpdateChannel] = []

    class Client:
        def best_newest_release_for_channel(self, channel):
            asked.append(channel)
            return _release("0.7.0")

        def best_newest_release(self):  # pragma: no cover - must not be used
            raise AssertionError("unfiltered selector used")

    service.client = Client()
    service.set_channel(UpdateChannel.STABLE)
    release = service._newest_release_for_channel()
    assert asked == [UpdateChannel.STABLE] and str(release.version) == "0.7.0"
