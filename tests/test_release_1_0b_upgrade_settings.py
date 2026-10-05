"""1.0-B: a real 0.6.0 profile loads, round-trips and survives corruption on the current code. Engine-free, no network.

Preservation matrix (every key the 0.6.0 fixture stores, one class each; see PRESERVE_MATRIX):
  PRESERVE        kept as the user set it
  NORMALIZE       kept as a field but mapped to the current safe value on load
  DROP-DEPRECATED no longer read; disappears on the next save
  DEFAULT-NEW     not in 0.6.0; the current default applies (every privacy / market opt-in is OFF)
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from exilelens.app import settings as S
from exilelens.app.legacy_migration import migrate_character_build

pytestmark = pytest.mark.itemcheck

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "profiles" / "v0.6.0"

PRESERVE = "PRESERVE"
NORMALIZE = "NORMALIZE"
DROP = "DROP-DEPRECATED"
DEFAULT_NEW = "DEFAULT-NEW"

PRESERVE_MATRIX = {
    # classified from the 0.6.0 keys; anything else in the fixture fails test_every_fixture_key_is_classified
    "pob_path": PRESERVE, "build_path": PRESERVE, "context": PRESERVE, "overlay_enabled": PRESERVE,
    "overlay_position": PRESERVE, "overlay_position_mode": PRESERVE, "overlay_near_offset_px": PRESERVE,
    "overlay_auto_hide_seconds": PRESERVE, "debug": PRESERVE, "first_run_complete": PRESERVE,
    "onboarding_version_completed": PRESERVE, "selected_loadout": PRESERVE, "item_set_follow_loadout": PRESERVE,
    "selected_item_set_id": PRESERVE, "baseline_mode": PRESERVE, "value_profile": PRESERVE,
    "tree_heatmap_metric": PRESERVE, "tree_ranking_mode": PRESERVE, "tree_analysis_radius": PRESERVE,
    "tree_show_allocated": PRESERVE, "tree_show_frontier": PRESERVE, "tree_show_evaluated": PRESERVE,
    "tree_show_unevaluated": PRESERVE, "tree_show_notables": PRESERVE, "tree_show_keystones": PRESERVE,
    "tree_show_small": PRESERVE, "tree_overlay_enabled": PRESERVE, "tree_overlay_calibration": PRESERVE,
    "tree_overlay_mode": PRESERVE, "tree_overlay_debug": PRESERVE, "tree_overlay_opacity": PRESERVE,
    "tree_overlay_marker_size": PRESERVE, "tree_overlay_line_width": PRESERVE, "tracked_build_path": PRESERVE,
    "tracked_tree_set_id": PRESERVE, "dashboard_x": PRESERVE, "dashboard_y": PRESERVE, "dashboard_width": PRESERVE,
    "dashboard_height": PRESERVE, "dashboard_last_page": PRESERVE, "settings_dialog_x": PRESERVE,
    "settings_dialog_y": PRESERVE, "settings_dialog_width": PRESERVE, "settings_dialog_height": PRESERVE,
    "item_check_pro": PRESERVE, "market_assist": PRESERVE, "market_assist_overlay_x": PRESERVE,
    "market_assist_overlay_y": PRESERVE, "market_assist_overlay_width": PRESERVE,
    "market_assist_overlay_height": PRESERVE, "pinned_overlays": PRESERVE, "market_league": PRESERVE,
    "market_league_mode": PRESERVE, "market_league_cache": PRESERVE, "market_league_cache_at": PRESERVE,
    "strict_live": PRESERVE, "price_check_enabled": PRESERVE, "price_check_hotkey": PRESERVE,
    "price_check_refine_hotkey": PRESERVE, "price_check_capture_timeout_ms": PRESERVE,
    "price_check_release_wait_ms": PRESERVE, "price_check_diagnostic_mode": PRESERVE, "ui_scale": PRESERVE,
    "show_hotkey_hints": PRESERVE, "hotkey_hints_dismissed": PRESERVE, "hotkey_hints_success_count": PRESERVE,
    "update_last_check_at": PRESERVE, "update_latest_version": PRESERVE, "update_notified_version": PRESERVE,
    "update_last_error": PRESERVE, "diagnostic_verbose_until": PRESERVE,
    "schema_version": NORMALIZE,        # 23 -> 25 on the next save
    "update_channel": NORMALIZE,        # "beta" (old automatic default) -> "stable"
    "live_market_mode": NORMALIZE,      # "auto" is still stored but inert; market access is decided elsewhere
    "dedup_window_seconds": DROP,       # removed since 0.6.0
}
NEW_DEFAULTS = {  # DEFAULT-NEW: not in a 0.6.0 file
    "market_prices_enabled": False, "market_consent_version": 0, "send_usage_stats": False, "send_error_reports": False,
    "privacy_consent_version": 0, "privacy_card_resolved": False, "last_seen_release_notes_version": "",
    "updates_auto_download": True, "updates_install_on_exit": True,
}


@pytest.fixture(autouse=True)
def isolated_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(S, "_unbacked_unreadable_file", False)
    return tmp_path / "local"


def _data_dir() -> Path:
    return S.app_data_dir()


def _install_fixture() -> Path:
    target = _data_dir() / "settings.json"
    shutil.copyfile(FIXTURE / "settings.json", target)
    return target


def _write(raw: bytes) -> Path:
    path = S.settings_path()
    path.write_bytes(raw)
    return path


def _backups() -> list[Path]:
    return sorted(_data_dir().glob("settings.json.corrupt-*"))


# --- the real 0.6.0 fixture ---------------------------------------------------------------------------------------------


def test_fixture_is_a_real_060_profile_without_personal_data():
    stored = json.loads((FIXTURE / "settings.json").read_text(encoding="utf-8"))
    assert stored["schema_version"] == 23
    assert "dedup_window_seconds" in stored and stored["live_market_mode"] == "auto" and stored["update_channel"] == "beta"
    for added_later in NEW_DEFAULTS:
        assert added_later not in stored
    notes = (FIXTURE / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "b9ab35a46cfbce2af529bc08c44f9d78d3865230" in notes and "schema_version" in notes
    blob = "".join(p.read_text(encoding="utf-8") for p in FIXTURE.glob("*.json")).lower()
    assert "\\\\users\\\\player\\\\" in blob  # structure kept, identity scrubbed
    for secret in ("token", "patreon", "password", "secret"):
        assert secret not in blob


def test_every_fixture_key_is_classified():
    stored = json.loads((FIXTURE / "settings.json").read_text(encoding="utf-8"))
    assert set(stored) == set(PRESERVE_MATRIX)
    assert set(NEW_DEFAULTS) <= set(AppSettingsKeys())
    assert not set(NEW_DEFAULTS) & set(stored)


def AppSettingsKeys():
    return S.AppSettings().to_dict().keys()


def test_fixture_loads_with_current_code_and_preserves_user_state():
    _install_fixture()
    result = S.load_settings_result()
    assert result.loaded_from_disk and not result.load_error and result.recovery_backup is None
    s = result.settings
    assert s.pob_path.endswith("Path of Building Community (PoE2)") and s.build_path.endswith("Example Witch.xml")
    assert s.price_check_hotkey == "ctrl+shift+x"
    assert (s.overlay_position.corner, s.overlay_position.x, s.overlay_position.y) == ("top_left", 24, 96)
    assert s.overlay_position_mode == "fixed_corner" and s.overlay_near_offset_px == 52 and s.overlay_auto_hide_seconds == 12.0
    assert (s.dashboard_x, s.dashboard_y, s.dashboard_width, s.dashboard_height) == (140, 80, 1360, 900)
    assert s.dashboard_last_page == "settings"
    assert (s.settings_dialog_x, s.settings_dialog_y, s.settings_dialog_width, s.settings_dialog_height) == (300, 200, 600, 460)
    assert set(s.pinned_overlays) == {"slot-0", "slot-1"} and s.pinned_overlays["slot-1"]["y"] == 560
    assert (s.selected_loadout, s.selected_item_set_id, s.item_set_follow_loadout) == ("Mapping", "2", False)
    assert s.value_profile == "DEFENSIVE" and s.ui_scale == 1.2
    assert s.market_league == "Fate of the Vaal" and s.market_league_mode == "PINNED"
    assert s.first_run_complete and s.onboarding_version_completed == 1 and not S.onboarding_required(s)


def test_fixture_gets_the_current_safe_defaults_and_normalizations():
    _install_fixture()
    s = S.load_settings_result().settings
    for name, expected in NEW_DEFAULTS.items():
        assert getattr(s, name) == expected, name
    assert s.market_prices_enabled is False and s.market_consent_version == 0
    assert s.send_usage_stats is False and s.send_error_reports is False and s.privacy_consent_version == 0
    assert s.update_channel == "stable"
    # supporter update preferences: the current defaults; they grant nothing without a verified lease
    assert (s.updates_auto_download, s.updates_install_on_exit) == (True, True)
    assert not hasattr(s, "dedup_window_seconds")
    assert s.schema_version == 23  # in memory until the next save stamps the current schema


def test_legacy_live_market_mode_auto_is_inert():
    from exilelens.price_check import market_policy

    _install_fixture()
    s = S.load_settings_result().settings
    assert s.live_market_mode == "auto"
    access = market_policy.market_access_for_settings(s)
    assert access.state is market_policy.MarketAccessState.DISABLED_BY_USER and not access.network_permitted
    assert market_policy.LIVE_TRADE2_AUTHORIZED is False


def test_loading_the_fixture_does_not_touch_the_file():
    path = _install_fixture()
    before = path.read_bytes()
    S.load_settings_result()
    S.load_settings_result()
    assert path.read_bytes() == before
    assert not _backups() and not list(_data_dir().glob("*.tmp"))


# --- round trip ---------------------------------------------------------------------------------------------------------


def test_round_trip_writes_the_current_schema_and_is_idempotent():
    path = _install_fixture()
    first = S.load_settings_result().settings
    S.save_settings(first)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == S.CURRENT_SCHEMA_VERSION
    assert set(saved) == set(AppSettingsKeys())
    assert "dedup_window_seconds" not in saved
    assert saved["update_channel"] == "stable"
    assert saved["send_usage_stats"] is False and saved["send_error_reports"] is False
    assert saved["market_prices_enabled"] is False and saved["market_consent_version"] == 0
    original = json.loads((FIXTURE / "settings.json").read_text(encoding="utf-8"))
    for key, kind in PRESERVE_MATRIX.items():
        if kind == PRESERVE:
            assert saved[key] == original[key], key  # no path or geometry changed
    second = S.load_settings_result()
    assert not second.load_error
    assert second.settings.to_dict() == saved
    S.save_settings(second.settings)
    assert json.loads(path.read_text(encoding="utf-8")) == saved
    assert not _backups() and not list(_data_dir().glob("*.tmp"))


def test_second_load_save_cycle_is_byte_stable():
    path = _install_fixture()
    S.save_settings(S.load_settings_result().settings)
    after_first = path.read_bytes()
    S.save_settings(S.load_settings_result().settings)
    assert path.read_bytes() == after_first


# --- field-level hardening ----------------------------------------------------------------------------------------------

DEFAULTS = S.AppSettings().to_dict()


@pytest.mark.parametrize("value", [None, [], [1, 2], "x", 7, True, 3.5])
def test_overlay_position_of_any_type_never_crashes(value):
    s = S.AppSettings.from_dict({"overlay_position": value, "build_path": "C:/b.xml"})
    assert s.build_path == "C:/b.xml"
    assert s.overlay_position == S.OverlayPosition()


@pytest.mark.parametrize("bad", [[1], "str", 5, None, True])
def test_malformed_nested_dicts_become_empty_and_keep_the_rest(bad):
    s = S.AppSettings.from_dict({
        "pinned_overlays": bad, "item_check_pro": bad, "market_assist": bad, "tree_overlay_calibration": bad,
        "price_check_hotkey": "ctrl+shift+x",
    })
    assert s.pinned_overlays == {} and s.item_check_pro == {} and s.market_assist == {} and s.tree_overlay_calibration == {}
    assert s.price_check_hotkey == "ctrl+shift+x"


@pytest.mark.parametrize("bad", [{"a": 1}, "Standard", 4, None, [1, None, {}, "", "  ", "Standard"]])
def test_malformed_market_league_cache(bad):
    cache = S.AppSettings.from_dict({"market_league_cache": bad}).market_league_cache
    assert cache == (["Standard"] if isinstance(bad, list) else [])


@pytest.mark.parametrize("bad", ["wide", "", None, [], {}, True, float("nan"), float("inf"), -5, 0, "1e999"])
def test_malformed_numeric_geometry_falls_back_per_field(bad):
    s = S.AppSettings.from_dict({
        "dashboard_width": bad, "dashboard_height": bad, "dashboard_x": bad, "dashboard_y": bad,
        "settings_dialog_width": bad, "market_assist_overlay_height": bad, "overlay_near_offset_px": bad,
        "overlay_auto_hide_seconds": bad, "ui_scale": bad, "dashboard_last_page": "settings",
    })
    assert s.dashboard_width == 1280 and s.dashboard_height == 860
    if bad not in (-5, 0):  # negative and zero are valid coordinates on a multi-monitor desktop
        assert s.dashboard_x is None and s.dashboard_y is None
    assert s.settings_dialog_width == 560 and s.market_assist_overlay_height == 420
    assert s.overlay_near_offset_px == (0 if bad == 0 else 40) and s.overlay_auto_hide_seconds == 0.0
    assert s.ui_scale in (0.8, 1.0, 1.2, 1.4, 1.6)
    assert s.dashboard_last_page == "settings"


def test_numeric_strings_and_integral_floats_are_accepted():
    s = S.AppSettings.from_dict({"dashboard_width": "1400", "dashboard_height": 900.0, "dashboard_x": "-20"})
    assert (s.dashboard_width, s.dashboard_height, s.dashboard_x) == (1400, 900, -20)


@pytest.mark.parametrize("bad", ["false", "true", "False", "0", "1", 0, 1, [], {}, None, "no"])
def test_persisted_booleans_accept_only_json_booleans(bad):
    keys = ["overlay_enabled", "debug", "first_run_complete", "item_set_follow_loadout", "tree_show_allocated", "tree_overlay_enabled",
            "strict_live", "price_check_enabled", "show_hotkey_hints", "hotkey_hints_dismissed", "privacy_card_resolved"]
    s = S.AppSettings.from_dict({k: bad for k in keys})
    for key in keys:
        assert getattr(s, key) == DEFAULTS[key], key  # never bool("false") -> True
    flags = S.AppSettings.from_dict({"send_usage_stats": bad, "send_error_reports": bad, "market_prices_enabled": bad})
    assert flags.send_usage_stats is False and flags.send_error_reports is False and flags.market_prices_enabled is False


def test_real_booleans_are_kept():
    s = S.AppSettings.from_dict({"overlay_enabled": False, "debug": True, "send_usage_stats": True, "market_prices_enabled": True})
    assert s.overlay_enabled is False and s.debug is True and s.send_usage_stats is True and s.market_prices_enabled is True


@pytest.mark.parametrize("field,bad,expected", [
    ("overlay_position_mode", "sideways", "near_item"), ("overlay_position_mode", 7, "near_item"),
    ("value_profile", "ZZZ", "BALANCED"), ("value_profile", ["MAPPING"], "BALANCED"),
    ("tree_overlay_mode", "NOPE", "BUILD_PATH"), ("tree_overlay_mode", {}, "BUILD_PATH"),
    ("market_league_mode", "weird", "AUTO"), ("baseline_mode", "???", "POB_BUILD_GEAR"),
    ("context", 12, "MAP"), ("context", "", "MAP"), ("price_check_hotkey", ["x"], "shift+c"),
    ("price_check_hotkey", "a", "shift+c"), ("pob_path", {"p": 1}, S.DEFAULT_POB_PATH), ("build_path", 5, ""),
])
def test_unusable_enum_and_string_values_get_the_field_default(field, bad, expected):
    assert getattr(S.AppSettings.from_dict({field: bad}), field) == expected


def test_valid_enum_values_are_preserved():
    s = S.AppSettings.from_dict({"overlay_position_mode": "fixed_corner", "value_profile": "bossing", "tree_overlay_mode": "NEXT_POINTS",
                                 "market_league_mode": "PINNED"})
    assert (s.overlay_position_mode, s.value_profile, s.tree_overlay_mode, s.market_league_mode) == (
        "fixed_corner", "BOSSING", "NEXT_POINTS", "PINNED")


@pytest.mark.parametrize("top", [[], "text", 5, None, True, [{"pob_path": "x"}]])
def test_non_object_top_level_gives_defaults(top):
    assert S.AppSettings.from_dict(top) == S.AppSettings()


def test_schema_version_garbage_does_not_crash():
    for bad in ("v9", None, [], {}, 1.5, True):
        assert S.AppSettings.from_dict({"schema_version": bad, "build_path": "C:/b.xml"}).build_path == "C:/b.xml"


def test_partial_recovery_keeps_valid_fields_and_defaults_only_the_bad_one():
    s = S.AppSettings.from_dict({
        "build_path": "C:/Builds/Witch.xml", "price_check_hotkey": "ctrl+shift+x", "overlay_position": "corrupt",
        "pinned_overlays": {"slot-0": {"x": 1}},
    })
    assert s.build_path == "C:/Builds/Witch.xml"
    assert s.price_check_hotkey == "ctrl+shift+x"
    assert s.pinned_overlays == {"slot-0": {"x": 1}}
    assert s.overlay_position == S.OverlayPosition()  # only the bad field fell back


def test_one_bad_field_in_a_real_file_keeps_everything_else_and_is_not_a_whole_file_reset(isolated_profile):
    path = _install_fixture()
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["overlay_position"] = ["not", "a", "dict"]
    stored["dashboard_width"] = "huge"
    path.write_text(json.dumps(stored), encoding="utf-8")
    result = S.load_settings_result()
    assert not result.load_error and result.recovery_backup is None and S.recovery_notice_text(result) is None
    assert result.settings.build_path.endswith("Example Witch.xml") and result.settings.price_check_hotkey == "ctrl+shift+x"
    assert result.settings.dashboard_width == 1280 and result.settings.dashboard_height == 900
    assert not _backups()


def test_future_schema_loads_known_fields_ignores_unknown_and_never_enables_opt_ins():
    stored = json.loads((FIXTURE / "settings.json").read_text(encoding="utf-8"))
    stored.update({
        "schema_version": S.CURRENT_SCHEMA_VERSION + 7, "brand_new_future_flag": True, "future_dict": {"a": 1},
        "send_usage_stats": "yes-please", "send_error_reports": 1, "telemetry_v2": True, "market_prices_enabled": "on",
    })
    path = _write(json.dumps(stored).encode("utf-8"))
    before = path.read_bytes()
    result = S.load_settings_result()
    s = result.settings
    assert not result.load_error and not _backups()
    assert s.schema_version == S.CURRENT_SCHEMA_VERSION  # clamped in memory; nothing forward-migrated
    assert s.build_path.endswith("Example Witch.xml") and s.price_check_hotkey == "ctrl+shift+x"
    assert s.send_usage_stats is False and s.send_error_reports is False and s.market_prices_enabled is False
    assert path.read_bytes() == before  # loading writes nothing
    S.save_settings(s)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == S.CURRENT_SCHEMA_VERSION
    assert "brand_new_future_flag" not in saved and "future_dict" not in saved and "telemetry_v2" not in saved


# --- whole-file corruption ----------------------------------------------------------------------------------------------

CORRUPT_FILES = {
    "malformed_json": b'{"pob_path": "C:/x", ',
    "empty": b"",
    "whitespace": b"   \r\n  ",
    "top_level_list": b"[1, 2, 3]",
    "top_level_string": b'"settings"',
    "top_level_number": b"42",
    "top_level_null": b"null",
    "bom_then_garbage": b"\xef\xbb\xbfnot json",
    "binary": b"\xff\xfe\x00\x01\x02garbage\x80",
    "truncated": (FIXTURE / "settings.json").read_bytes()[:200],
}


@pytest.mark.parametrize("name", sorted(CORRUPT_FILES))
def test_whole_file_corruption_reaches_a_usable_state_and_keeps_the_original(name):
    raw = CORRUPT_FILES[name]
    path = _write(raw)
    result = S.load_settings_result()
    assert result.load_error and result.loaded_from_disk
    assert result.settings == S.AppSettings()
    assert result.recovery_backup is not None and result.recovery_backup.read_bytes() == raw
    assert path.read_bytes() == raw  # the original is untouched until a normal save
    S.save_settings(result.settings)
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == S.CURRENT_SCHEMA_VERSION
    assert result.recovery_backup.read_bytes() == raw  # a later save never overwrites the backup
    assert not S.load_settings_result().load_error


def test_utf8_bom_with_valid_json_is_not_corruption():
    raw = b"\xef\xbb\xbf" + (FIXTURE / "settings.json").read_bytes()
    _write(raw)
    result = S.load_settings_result()
    assert not result.load_error and result.settings.build_path.endswith("Example Witch.xml") and not _backups()


def test_backup_exists_before_any_startup_save_can_overwrite_the_original():
    raw = b"{ this is not json"
    path = _write(raw)
    xml = _data_dir() / "legacy-build.xml"
    xml.write_text("<PathOfBuilding2/>", encoding="utf-8")
    (_data_dir() / "active_character.json").write_text(json.dumps({"build_path": str(xml)}), encoding="utf-8")
    result = S.load_settings_result()  # main.py order: load first ...
    assert result.recovery_backup is not None and result.recovery_backup.read_bytes() == raw
    assert path.read_bytes() == raw
    assert migrate_character_build(result.settings)  # ... then migrate_character_build, which saves
    assert json.loads(path.read_text(encoding="utf-8"))["build_path"] == str(xml.resolve())
    assert result.recovery_backup.read_bytes() == raw


def test_backups_never_overwrite_each_other(monkeypatch):
    monkeypatch.setattr(time, "strftime", lambda fmt, *a: "20260101-000000")
    seen = []
    for payload in (b"first {", b"second {", b"third {"):
        _write(payload)
        result = S.load_settings_result()
        seen.append(result.recovery_backup)
    assert len({str(p) for p in seen}) == 3
    assert [p.read_bytes() for p in seen] == [b"first {", b"second {", b"third {"]


def test_backup_retention_is_bounded_and_keeps_the_newest():
    for index in range(S._BACKUPS_KEPT + 3):
        _write(f"bad-{index} {{".encode())
        newest = S.load_settings_result().recovery_backup
        time.sleep(0.01)
    kept = _backups()
    assert len(kept) <= S._BACKUPS_KEPT and newest in kept


def test_when_the_backup_cannot_be_written_the_original_is_never_overwritten(monkeypatch):
    raw = b"{ broken"
    path = _write(raw)
    real = S._write_recovery_backup
    monkeypatch.setattr(S, "_write_recovery_backup", lambda *a, **k: None)
    result = S.load_settings_result()
    assert result.load_error and result.recovery_backup is None
    S.save_settings(result.settings)  # refused: not pretending recovery completed
    assert path.read_bytes() == raw
    assert "could not be backed up" in S.recovery_notice_text(result)
    monkeypatch.setattr(S, "_write_recovery_backup", real)  # the disk recovers: the retry makes the backup, then saves
    S.save_settings(result.settings)
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == S.CURRENT_SCHEMA_VERSION
    assert [p.read_bytes() for p in _backups()] == [raw]


def test_unreadable_file_that_cannot_be_read_is_not_pretended_recovered(monkeypatch):
    path = _write(b"{}")
    original_read = Path.read_bytes

    def boom(self):
        if self.name == "settings.json":
            raise PermissionError("locked")
        return original_read(self)

    monkeypatch.setattr(Path, "read_bytes", boom)
    result = S.load_settings_result()
    assert result.load_error and result.recovery_backup is None
    S.save_settings(result.settings)
    monkeypatch.setattr(Path, "read_bytes", original_read)
    assert path.read_bytes() == b"{}"


# --- recovery notice ----------------------------------------------------------------------------------------------------


def test_recovery_notice_only_for_a_whole_file_reset_and_is_quiet():
    _write(b"{ not json")
    reset = S.load_settings_result()
    text = S.recovery_notice_text(reset)
    assert text and "default settings" in text and "backup" in text.lower() or "copy" in text.lower()
    assert "{" not in text and "Traceback" not in text and "JSON" not in text and str(_data_dir()) not in text
    assert S.recovery_notice_text(S.SettingsLoadResult(S.AppSettings(), loaded_from_disk=False)) is None
    _install_fixture()
    assert S.recovery_notice_text(S.load_settings_result()) is None  # normal 0.6.0 -> current migration: no notice


def test_recovery_notice_appears_once_not_on_the_next_launch():
    _write(b"[]")
    first = S.load_settings_result()
    assert S.recovery_notice_text(first)
    S.save_settings(first.settings)  # what main.py does once the backup exists
    second = S.load_settings_result()
    assert S.recovery_notice_text(second) is None and not second.load_error
    assert len(_backups()) == 1


def test_main_shows_the_notice_once_through_the_tray():
    pytest.importorskip("PySide6")
    from exilelens.app.main import ExileLensApp

    shown = []
    fake = type("Fake", (), {})()
    fake._settings_recovery_notice = "Your ExileLens settings file could not be read."
    fake._tray_visible = lambda: True
    fake.tray = type("Tray", (), {"showMessage": lambda self, *a: shown.append(a)})()
    ExileLensApp._show_settings_recovery_notice(fake)
    ExileLensApp._show_settings_recovery_notice(fake)
    assert len(shown) == 1 and "could not be read" in shown[0][1]
    quiet = type("Fake", (), {})()
    quiet._settings_recovery_notice = None
    quiet._tray_visible = lambda: True
    quiet.tray = fake.tray
    ExileLensApp._show_settings_recovery_notice(quiet)
    assert len(shown) == 1


# --- atomic save --------------------------------------------------------------------------------------------------------


def test_save_replaces_the_file_cleanly_and_leaves_no_temp():
    path = _install_fixture()
    s = S.load_settings_result().settings
    s.build_path = "C:/New/Build.xml"
    S.save_settings(s)
    assert json.loads(path.read_text(encoding="utf-8"))["build_path"] == "C:/New/Build.xml"
    assert not list(_data_dir().glob("*.tmp"))


def test_interrupted_temp_write_does_not_destroy_the_previous_valid_file(monkeypatch):
    path = _install_fixture()
    before = path.read_bytes()
    s = S.load_settings_result().settings
    s.build_path = "C:/Never/Saved.xml"

    def die(_fd):
        raise OSError("disk full")

    monkeypatch.setattr(S.os, "fsync", die)
    with pytest.raises(OSError):
        S.save_settings(s)
    assert path.read_bytes() == before
    assert not list(_data_dir().glob("*.tmp"))


def test_failed_replace_keeps_the_previous_file(monkeypatch):
    path = _install_fixture()
    before = path.read_bytes()
    s = S.load_settings_result().settings

    def refuse(self, target):
        raise PermissionError("antivirus holds settings.json")

    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(PermissionError):
        S.save_settings(s)
    assert path.read_bytes() == before
    assert not list(_data_dir().glob("*.tmp"))


# --- legacy settings root -----------------------------------------------------------------------------------------------


def _legacy(root: Path) -> Path:
    legacy = root / S.LEGACY_APP_DATA_DIRECTORY
    (legacy / "logs").mkdir(parents=True)
    (legacy / "build-cache").mkdir()
    (legacy / "settings.json").write_bytes((FIXTURE / "settings.json").read_bytes())
    (legacy / "item_history.json").write_bytes((FIXTURE / "item_history.json").read_bytes())
    (legacy / "active_character.json").write_text("{}", encoding="utf-8")
    (legacy / "build-cache" / "entry.bin").write_bytes(b"cache")
    (legacy / "logs" / "poe2value.log").write_text("log", encoding="utf-8")
    (legacy / "instance.json").write_text("{}", encoding="utf-8")
    (legacy / "settings.json.tmp").write_text("x", encoding="utf-8")
    return legacy


def test_legacy_root_is_copied_once_when_the_new_root_is_absent(isolated_profile):
    legacy = _legacy(isolated_profile)
    new_dir = S.app_data_dir()
    assert new_dir == isolated_profile / S.APP_DATA_DIRECTORY
    for name in ("settings.json", "item_history.json", "active_character.json"):
        assert (new_dir / name).read_bytes() == (legacy / name).read_bytes()
    assert (new_dir / "build-cache" / "entry.bin").read_bytes() == b"cache"
    for transient in ("logs", "instance.json", "settings.json.tmp"):
        assert not (new_dir / transient).exists()
    assert legacy.is_dir() and (legacy / "logs" / "poe2value.log").is_file()  # never deleted
    (new_dir / "settings.json").write_text('{"build_path": "C:/edited.xml"}', encoding="utf-8")
    S.app_data_dir()
    assert json.loads((new_dir / "settings.json").read_text(encoding="utf-8")) == {"build_path": "C:/edited.xml"}  # idempotent


def test_canonical_root_wins_when_both_exist(isolated_profile):
    legacy = _legacy(isolated_profile)
    canonical = isolated_profile / S.APP_DATA_DIRECTORY
    canonical.mkdir()
    (canonical / "settings.json").write_text('{"build_path": "C:/canonical.xml"}', encoding="utf-8")
    assert S.load_settings_result().settings.build_path == "C:/canonical.xml"
    assert not (canonical / "item_history.json").exists()
    assert (legacy / "settings.json").read_bytes() == (FIXTURE / "settings.json").read_bytes()


def test_normal_writes_never_return_to_the_legacy_root(isolated_profile):
    legacy = _legacy(isolated_profile)
    before = {p.relative_to(legacy): p.read_bytes() for p in legacy.rglob("*") if p.is_file()}
    s = S.load_settings_result().settings
    s.build_path = "C:/after.xml"
    S.save_settings(s)
    S.backup_settings_file("bak")
    after = {p.relative_to(legacy): p.read_bytes() for p in legacy.rglob("*") if p.is_file()}
    assert after == before
    assert json.loads((isolated_profile / S.APP_DATA_DIRECTORY / "settings.json").read_text(encoding="utf-8"))["build_path"] == "C:/after.xml"
