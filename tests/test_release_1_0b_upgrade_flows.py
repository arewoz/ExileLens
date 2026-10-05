"""1.0-B: what a 0.6.0 profile sees on the current code beyond settings: item history, What's New, and zero network. Engine-free."""

from __future__ import annotations

import json
import shutil
import socket
import urllib.request
import webbrowser
from pathlib import Path

import pytest

from exilelens.app import settings as S
from exilelens.app.updates.version import ExileLensVersion
from exilelens.items.persistent_history import PersistentItemHistory
from exilelens.whats_new import content, trigger

pytestmark = pytest.mark.itemcheck

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "profiles" / "v0.6.0"
V = ExileLensVersion.parse
PRICE_ERA_KEYS = ("power_per_currency", "ppc", "value_class", "value_per_currency", "price", "currency_value")


class NetworkAttempt(AssertionError):
    pass


@pytest.fixture(autouse=True)
def isolated_profile_and_no_network(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(S, "_unbacked_unreadable_file", False)
    attempts: list[str] = []

    def forbid(label):
        def inner(*args, **kwargs):
            attempts.append(label)
            raise NetworkAttempt(label)
        return inner

    monkeypatch.setattr(socket.socket, "connect", forbid("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", forbid("socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", forbid("create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", forbid("getaddrinfo"))
    monkeypatch.setattr(urllib.request, "urlopen", forbid("urlopen"))
    monkeypatch.setattr(webbrowser, "open", forbid("webbrowser.open"))
    monkeypatch.setattr(webbrowser, "open_new_tab", forbid("webbrowser.open_new_tab"))
    return attempts


def _dir() -> Path:
    return S.app_data_dir()


def _release(version, previous, highlight="gamma"):
    return {
        "version": version, "released": "2026-10-04", "previous": previous,
        "highlights": [{"id": highlight, "title": "A change", "text": "One plain sentence about the change.",
                        "introduced": version, "priority": 1, "link": None}],
        "minor": [], "limitations": [], "action": None,
    }


# An injected catalog: the live whats_new.json is not touched and has no 1.0.0 entry.
CATALOG_1_0 = content.parse_document({"schema": 1, "releases": [_release("1.0.0", "0.6.0")]})
INSTALLED = V("1.0.0")


def _profile(last_seen: str | None) -> S.AppSettings:
    stored = json.loads((FIXTURE / "settings.json").read_text(encoding="utf-8"))
    if last_seen is not None:
        stored["last_seen_release_notes_version"] = last_seen
    S.settings_path().write_text(json.dumps(stored), encoding="utf-8")
    return S.load_settings_result().settings


# --- item history -------------------------------------------------------------------------------------------------------


def test_060_history_entry_loads_and_exposes_what_the_ui_reads():
    shutil.copyfile(FIXTURE / "item_history.json", _dir() / "item_history.json")
    history = PersistentItemHistory()
    (entry,) = history.entries()
    assert entry["item_name"] == "Example Rare Helmet" and entry["verdict"] == "UPGRADE" and entry["best_slot"] == "Helmet"
    assert entry["status"] == "CURRENT" and entry["stale"] is False and entry["seen_count"] == 1
    assert entry["content_hash"] and entry["baseline_identity"].endswith("|MAP|1")
    assert not any(key in entry for key in PRICE_ERA_KEYS)
    assert history.last() is entry


def test_loading_history_never_rewrites_the_file():
    path = _dir() / "item_history.json"
    shutil.copyfile(FIXTURE / "item_history.json", path)
    before = path.read_bytes()
    PersistentItemHistory()
    PersistentItemHistory()
    assert path.read_bytes() == before


def test_060_history_has_no_price_era_fields_to_show():
    blob = (FIXTURE / "item_history.json").read_text(encoding="utf-8").lower()
    for key in PRICE_ERA_KEYS:
        assert key not in blob  # 0.6.0 persisted only summary fields: there is nothing for a PPC/value-class renderer to read


def test_older_payloads_carrying_price_fields_load_and_the_fields_stay_unread(tmp_path):
    path = _dir() / "item_history.json"
    payload = {
        "limit": 50, "seen": {"h|id": 2},
        "entries": [{
            "id": "old-1", "status": "HISTORICAL", "baseline_identity": "id", "content_hash": "h", "item_name": "Old Ring",
            "verdict": "SIDEGRADE", "best_slot": "Ring", "seen_count": 2, "stale": True,
            "power_per_currency": 12.5, "value_class": "GREAT_VALUE", "price": {"amount": 4, "currency": "divine"},
            "result": {"price_check": {"power_per_currency": 3.1}, "value_class": "EXCELLENT"},
        }],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_bytes()
    history = PersistentItemHistory()
    (entry,) = history.entries()
    assert entry["item_name"] == "Old Ring" and entry["verdict"] == "SIDEGRADE" and entry["best_slot"] == "Ring"
    assert path.read_bytes() == before  # loading did not rewrite it
    # Nothing in the current history code reads those keys, and recording again drops them from the stored form.
    history.record({"raw_input": {"content_hash": "new"}, "pob_parse": {"display_name": "New"}}, identity="id")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert all("power_per_currency" not in row and "value_class" not in row and "price" not in row for row in stored["entries"])
    assert [row["item_name"] for row in stored["entries"]] == ["Old Ring", "New"]


@pytest.mark.parametrize("raw", ["[]", "null", '"x"', "5", "{", "", '{"entries": {"a": 1}}', '{"entries": [1, "x", null, {"id": "ok"}]}',
                                 '{"limit": "many", "seen": [1], "entries": []}'])
def test_malformed_history_never_crashes_the_app(raw):
    (_dir() / "item_history.json").write_text(raw, encoding="utf-8")
    history = PersistentItemHistory()
    assert all(isinstance(entry, dict) for entry in history.entries())
    assert history.limit > 0


# --- What's New on upgrade ----------------------------------------------------------------------------------------------


def test_live_catalog_still_has_no_1_0_notes():
    live = content.packaged_catalog()
    assert live is not None and live.get(INSTALLED) is None  # the 1.0.0 What's New stays a draft until 1.0-E


def test_a_060_profile_without_a_stored_version_sees_the_notes_once():
    settings = _profile(None)
    assert settings.last_seen_release_notes_version == ""
    summary = trigger.evaluate(settings, INSTALLED, CATALOG_1_0)
    assert summary is not None and summary.kind == "release"


def test_after_dismissal_the_notes_do_not_come_back():
    settings = _profile(None)
    assert trigger.mark_seen(settings, INSTALLED, S.save_settings)
    assert trigger.evaluate(settings, INSTALLED, CATALOG_1_0) is None
    reloaded = S.load_settings_result().settings  # next launch
    assert reloaded.last_seen_release_notes_version == "1.0.0"
    assert trigger.evaluate(reloaded, INSTALLED, CATALOG_1_0) is None


def test_fresh_1_0_install_records_the_version_and_shows_no_upgrade_notes():
    settings = S.load_settings_result()  # no settings.json
    assert not settings.loaded_from_disk
    assert trigger.record_fresh_install(settings.settings, INSTALLED, loaded_from_disk=False)
    assert settings.settings.last_seen_release_notes_version == "1.0.0"
    assert trigger.evaluate(settings.settings, INSTALLED, CATALOG_1_0) is None


def test_a_profile_reset_after_corruption_is_treated_as_fresh_not_as_an_upgrade():
    S.settings_path().write_bytes(b"{ broken")
    result = S.load_settings_result()
    assert result.load_error
    assert trigger.record_fresh_install(result.settings, INSTALLED, loaded_from_disk=True, load_error=True)
    assert trigger.evaluate(result.settings, INSTALLED, CATALOG_1_0) is None


def test_internal_0_7_0b1_profile_is_deterministic():
    """Documented for the owner: a 0.7.0b1 profile that last dismissed 0.7.0b1, upgrading to 1.0.0 against a catalog whose 1.0.0
    entry says previous = 0.6.0. 0.6.0 <= 0.7.0b1, so the chain is just 1.0.0: the notes are shown once as "Updated from 0.7.0b1"
    with the 1.0.0 highlights. No special 0.7.0b1 path exists; whether that wording is right for internal testers is an owner call."""
    settings = _profile("0.7.0b1")
    first = trigger.evaluate(settings, INSTALLED, CATALOG_1_0)
    again = trigger.evaluate(settings, INSTALLED, CATALOG_1_0)
    assert first is not None and first == again
    assert first.kind == "release" and "Updated from 0.7.0b1" in first.meta and first.note == "" and first.highlights
    assert trigger.mark_seen(settings, INSTALLED, S.save_settings)
    assert trigger.evaluate(settings, INSTALLED, CATALOG_1_0) is None


# --- zero network -------------------------------------------------------------------------------------------------------


def test_the_network_guard_really_blocks(isolated_profile_and_no_network):
    with pytest.raises(NetworkAttempt):
        urllib.request.urlopen("https://example.invalid/")
    with pytest.raises(NetworkAttempt):
        socket.create_connection(("127.0.0.1", 9))
    with pytest.raises(NetworkAttempt):
        webbrowser.open("https://example.invalid/")
    isolated_profile_and_no_network.clear()


def test_migration_and_recovery_paths_make_no_network_request(isolated_profile_and_no_network):
    from exilelens.app.updates.channels import UpdateChannel
    from exilelens.price_check import market_policy

    # 0.6.0 settings + legacy "beta" channel + live_market_mode "auto"
    shutil.copyfile(FIXTURE / "settings.json", _dir() / "settings.json")
    shutil.copyfile(FIXTURE / "item_history.json", _dir() / "item_history.json")
    loaded = S.load_settings_result().settings
    assert loaded.update_channel == "stable" and UpdateChannel.parse(loaded.update_channel) is UpdateChannel.STABLE
    assert market_policy.market_access_for_settings(loaded).network_permitted is False
    S.save_settings(loaded)
    PersistentItemHistory()
    trigger.evaluate(loaded, INSTALLED, CATALOG_1_0)
    # whole-file recovery
    S.settings_path().write_bytes(b"{ not json")
    reset = S.load_settings_result()
    S.recovery_notice_text(reset)
    S.save_settings(reset.settings)
    S.reset_settings(reset.settings)
    assert isolated_profile_and_no_network == []
