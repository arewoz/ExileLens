"""Diagnose whether ExileLens would evaluate the build the user thinks is loaded."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from poe2value.app.build_cache import BuildCache, BuildCacheEntry, freshness_for
from poe2value.app.settings import AppSettings
from poe2value.build_source import read_build_source
from poe2value.errors import BuildNotFound, BuildParseFailed
from poe2value.ops.models import BuildSourceStatus


@dataclass
class BuildSourceAudit:
    status: BuildSourceStatus
    configured_path: str
    actual_loaded_path: str
    exists: bool
    mtime_ns: int | None
    size: int | None
    sha256_short: str
    cache_freshness: str
    match: bool
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": f"BUILD SOURCE: {self.status.value}",
            "status": self.status.value,
            "configured_pob_or_build_path": self.configured_path,
            "actual_loaded_build": self.actual_loaded_path,
            "file_exists": self.exists,
            "mtime_ns": self.mtime_ns,
            "size": self.size,
            "sha256_short": self.sha256_short,
            "cache_freshness": self.cache_freshness,
            "equipment_match": self.match,
            "notes": self.notes,
        }


def _settings_from_file(path: Path | None, overrides: dict[str, Any] | None) -> AppSettings:
    if path and path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if overrides:
            data.update(overrides)
        return AppSettings.from_dict(data)
    return AppSettings.from_dict(overrides or {})


def audit_build_source(
    *,
    build_path: str | Path | None = None,
    settings_path: str | Path | None = None,
    cache_root: str | Path | None = None,
    cache_entry: BuildCacheEntry | None = None,
) -> BuildSourceAudit:
    notes: list[str] = []
    settings = _settings_from_file(Path(settings_path) if settings_path else None, None)
    configured = str(build_path or settings.build_path or "").strip()
    loaded_path = configured
    freshness = "UNKNOWN"
    entry = cache_entry
    if entry is None and cache_root is not None:
        entry = BuildCache(Path(cache_root)).load_active()
    if entry is not None:
        loaded_path = entry.build_path or loaded_path
        freshness = freshness_for(entry)
        if entry.last_refresh_error:
            notes.append(f"last refresh error: {entry.last_refresh_error.get('message')}")

    if not configured and not loaded_path:
        return BuildSourceAudit(
            status=BuildSourceStatus.UNAVAILABLE,
            configured_path="",
            actual_loaded_path="",
            exists=False,
            mtime_ns=None,
            size=None,
            sha256_short="",
            cache_freshness=freshness,
            match=False,
            notes=["no build path configured"],
        )

    path = Path(loaded_path or configured)
    if not path.is_file():
        return BuildSourceAudit(
            status=BuildSourceStatus.UNAVAILABLE,
            configured_path=configured,
            actual_loaded_path=str(path),
            exists=False,
            mtime_ns=None,
            size=None,
            sha256_short="",
            cache_freshness=freshness,
            match=False,
            notes=["build file does not exist"],
        )

    try:
        source = read_build_source(path)
    except (BuildNotFound, BuildParseFailed) as exc:
        return BuildSourceAudit(
            status=BuildSourceStatus.UNAVAILABLE,
            configured_path=configured,
            actual_loaded_path=str(path),
            exists=True,
            mtime_ns=None,
            size=path.stat().st_size,
            sha256_short="",
            cache_freshness=freshness,
            match=False,
            notes=[str(exc)],
        )

    configured_resolved = str(Path(configured).resolve()) if configured else ""
    actual_resolved = str(Path(loaded_path).resolve()) if loaded_path else ""
    path_match = (not configured_resolved) or configured_resolved == actual_resolved
    revision_match = True
    if entry is not None:
        cached_mtime = int(entry.build_revision.get("mtimeNs") or 0)
        cached_size = int(entry.build_revision.get("size") or 0)
        if cached_mtime and (cached_mtime != source.mtime_ns or cached_size != source.size):
            revision_match = False
            notes.append("cache revision does not match bytes on disk")
        if freshness in {"CHANGED_ON_DISK", "REFRESH_FAILED"}:
            revision_match = False

    if not path_match:
        status = BuildSourceStatus.MISMATCH
        notes.append("configured path differs from cache/loaded path")
    elif not revision_match or freshness == "CHANGED_ON_DISK":
        status = BuildSourceStatus.STALE
    else:
        status = BuildSourceStatus.CURRENT

    return BuildSourceAudit(
        status=status,
        configured_path=configured_resolved or configured,
        actual_loaded_path=actual_resolved or str(path),
        exists=True,
        mtime_ns=source.mtime_ns,
        size=source.size,
        sha256_short=source.short_sha,
        cache_freshness=freshness,
        match=path_match and revision_match,
        notes=notes,
    )
