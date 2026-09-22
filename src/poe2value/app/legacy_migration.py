"""One-time migration from the removed character-sync identity to build-file-only."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from poe2value.app.settings import AppSettings, app_data_dir, save_settings

logger = logging.getLogger(__name__)


def migrate_character_build(settings: AppSettings) -> bool:
    legacy = app_data_dir() / "active_character.json"
    if not legacy.is_file():
        return False
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("legacy_migration_parse_failed path=%s error=%s", legacy, exc)
        data = {}
    if not isinstance(data, dict):
        data = {}
    candidate = Path(str(data.get("build_path") or ""))
    current_ok = bool(settings.build_path) and Path(settings.build_path).is_file()
    applied = False
    if not current_ok and candidate.is_file() and candidate.suffix.lower() == ".xml":
        settings.build_path = str(candidate.resolve())
        save_settings(settings)
        applied = True
    migrated = legacy.with_suffix(".json.migrated")
    try:
        legacy.replace(migrated)
    except OSError as exc:
        logger.warning("legacy_migration_archive_failed path=%s error=%s", legacy, exc)
        return False
    logger.info("legacy_migration_complete build_applied=%s build_path=%s", applied, settings.build_path)
    return True
