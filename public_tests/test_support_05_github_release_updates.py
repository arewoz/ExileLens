"""Offline focused coverage for GitHub Release update availability."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from poe2value.app import update_check
from poe2value.app.settings import AppSettings
from poe2value.ui import recovery_actions


def test_canonical_version_ordering() -> None:
    parse = update_check.ExileLensVersion.parse
    assert parse("0.2.0b1") < parse("0.2.0b2")
    assert parse("0.2.0b9") < parse("0.2.0b10")
    assert parse("0.2.0b10") < parse("0.2.0") < parse("0.2.1b2")
    assert parse("0.2.0") == parse("0.2.0")
    assert parse("v0.2.0") is None
    assert parse("0.2") is None


@pytest.mark.parametrize("tag", ["v0.2.0b3", "0.2.0b3"])
def test_latest_release_accepts_canonical_tag_with_optional_v(tag: str) -> None:
    release = update_check.parse_latest_release({"tag_name": tag, "draft": False, "prerelease": False})
    assert release is not None
    assert str(release.version) == "0.2.0b3"
    assert release.url == update_check.GITHUB_RELEASES_URL


@pytest.mark.parametrize(
    "payload",
    [
        {"tag_name": "not-an-exilelens-version", "draft": False, "prerelease": False},
        {"tag_name": "v0.2.0b3", "draft": True, "prerelease": False},
        {"tag_name": "v0.2.0b3", "draft": False, "prerelease": True},
        [],
    ],
)
def test_latest_release_rejects_unusable_response(payload: object) -> None:
    assert update_check.parse_latest_release(payload) is None


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, _size: int) -> bytes:
        return self.body


def test_client_uses_fixed_public_get_request_only() -> None:
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return _Response(json.dumps({"tag_name": "v0.2.0b3", "draft": False, "prerelease": False}).encode())

    result = update_check.GitHubReleaseClient(opener).latest_release()
    assert str(result.version) == "0.2.0b3"
    request, timeout = calls[0]
    assert request.full_url == update_check.GITHUB_LATEST_RELEASE_API
    assert request.get_method() == "GET"
    assert timeout == update_check.TIMEOUT_SECONDS
    assert "sentinel" not in request.full_url + str(request.header_items()).lower()


@pytest.mark.parametrize(
    "body",
    [
        b"{",
        json.dumps({"tag_name": "bad-tag", "draft": False, "prerelease": False}).encode(),
        b"[]",
    ],
)
def test_client_bad_or_empty_response_is_not_an_update(body: bytes) -> None:
    client = update_check.GitHubReleaseClient(lambda *_args, **_kwargs: _Response(body))
    if body == b"{":
        with pytest.raises(RuntimeError):
            client.latest_release()
    else:
        assert client.latest_release() is None


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError(),
        urllib.error.URLError("offline"),
        urllib.error.HTTPError(update_check.GITHUB_LATEST_RELEASE_API, 404, "Not Found", {}, None),
    ],
)
def test_client_transport_errors_are_bounded(error: Exception) -> None:
    def opener(*_args, **_kwargs):
        raise error

    with pytest.raises(RuntimeError, match="request_failed"):
        update_check.GitHubReleaseClient(opener).latest_release()


def test_service_binds_unexpected_client_failures_to_a_safe_state(monkeypatch) -> None:
    class BrokenClient:
        def latest_release(self):
            raise ValueError("private sentinel must not escape")

    service = update_check.UpdateCheckService(AppSettings(), BrokenClient())
    monkeypatch.setattr(update_check, "is_packaged", lambda: True)
    monkeypatch.setattr(update_check, "save_settings", lambda _settings: None)
    states = []
    service.state_changed.connect(lambda state, value: states.append((state, value)))
    service._in_flight = True
    service._finish(RuntimeError("request_failed"), manual=True)

    assert states == [("failed", "")]


def test_automatic_cooldown_and_manual_bypass(monkeypatch) -> None:
    settings = AppSettings()
    client = update_check.GitHubReleaseClient()
    service = update_check.UpdateCheckService(settings, client, clock=lambda: 1000.0)
    calls = []
    monkeypatch.setattr(update_check, "is_packaged", lambda: True)
    monkeypatch.setattr(update_check, "save_settings", lambda _settings: None)
    monkeypatch.setattr(service, "_start", lambda *, manual: calls.append(manual) or True)

    assert service.start_automatic()
    assert not service.start_automatic()
    assert service.check_now()
    assert calls == [False, True]


def test_notification_is_once_per_newer_version(monkeypatch) -> None:
    settings = AppSettings()
    service = update_check.UpdateCheckService(settings)
    monkeypatch.setattr(update_check, "save_settings", lambda _settings: None)
    notifications = []
    service.update_available.connect(lambda remote, installed: notifications.append((remote, installed)))
    newer = update_check.Release(update_check.ExileLensVersion.parse("0.2.1b3"), update_check.GITHUB_RELEASES_URL)
    later = update_check.Release(update_check.ExileLensVersion.parse("0.2.1b4"), update_check.GITHUB_RELEASES_URL)

    service._finish(newer, manual=False)
    service._finish(newer, manual=False)
    service._finish(later, manual=False)

    assert notifications == [("0.2.1b3", "0.2.1b2"), ("0.2.1b4", "0.2.1b2")]


def test_source_builds_never_start_a_request(monkeypatch) -> None:
    service = update_check.UpdateCheckService(AppSettings())
    monkeypatch.setattr(update_check, "is_packaged", lambda: False)
    monkeypatch.setattr(service, "_start", lambda *, manual: pytest.fail("must not request"))
    assert not service.start_automatic()
    assert not service.check_now()


def test_open_releases_uses_only_the_official_destination(monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(recovery_actions.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))

    recovery_actions.open_github_releases()

    assert opened == [update_check.GITHUB_RELEASES_URL]


def test_release_workflow_publishes_normal_releases() -> None:
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "--prerelease" not in workflow
    assert "--draft" not in workflow
    assert "--latest=false" not in workflow
    assert "--latest" in workflow
