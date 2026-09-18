from __future__ import annotations

import json

import pytest

from poe2value.app import settings as settings_module


pytestmark = pytest.mark.itemcheck


def _root(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)
    return tmp_path


def test_fresh_profile_uses_product_directory(monkeypatch, tmp_path):
    root = _root(monkeypatch, tmp_path)
    assert settings_module.app_data_dir() == root / "ExileLens"


def test_legacy_settings_migrate_once_without_transient_files(monkeypatch, tmp_path):
    root = _root(monkeypatch, tmp_path)
    legacy = root / "poe2-value-overlay"; legacy.mkdir()
    (legacy / "settings.json").write_text(json.dumps({"price_check_hotkey": "ctrl+shift+x", "onboarding_version_completed": 1, "value_profile": "BOSSING"}))
    (legacy / "poe2value.log").write_text("private log")
    new = settings_module.app_data_dir()
    assert (new / "settings.json").exists() and not (new / "poe2value.log").exists()
    loaded = settings_module.load_settings()
    assert loaded.price_check_hotkey == "ctrl+shift+x"
    assert loaded.onboarding_version_completed == 1 and loaded.value_profile == "BOSSING"
    assert (legacy / "settings.json").exists()


def test_canonical_directory_wins_and_migration_is_idempotent(monkeypatch, tmp_path):
    root = _root(monkeypatch, tmp_path)
    legacy = root / "poe2-value-overlay"; canonical = root / "ExileLens"; legacy.mkdir(); canonical.mkdir()
    (legacy / "settings.json").write_text(json.dumps({"price_check_hotkey": "ctrl+shift+x"}))
    (canonical / "settings.json").write_text(json.dumps({"price_check_hotkey": "alt+shift+x"}))
    assert settings_module.load_settings().price_check_hotkey == "alt+shift+x"
    assert settings_module.app_data_dir() == canonical
    assert settings_module.load_settings().price_check_hotkey == "alt+shift+x"
