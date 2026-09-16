"""One-time migration from the removed character-sync identity to build-file-only."""

from __future__ import annotations

import json
from pathlib import Path

from poe2value.app.settings import AppSettings, app_data_dir, save_settings


def migrate_character_build(settings: AppSettings) -> bool:
    legacy = app_data_dir() / "active_character.json"
    if not legacy.is_file():
        return False
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    candidate = Path(str(data.get("build_path") or ""))
    current_ok = bool(settings.build_path) and Path(settings.build_path).is_file()
    if not current_ok and candidate.is_file() and candidate.suffix.lower() == ".xml":
        settings.build_path = str(candidate.resolve())
        save_settings(settings)
    migrated = legacy.with_suffix(".json.migrated")
    try:
        legacy.replace(migrated)
    except OSError:
        return False
    return True
