"""Persistent, advisory cache of the last successfully loaded PoB builds.

The PoB worker remains the source of truth for calculations.  This cache gives
the application a stable build identity and display snapshot across restarts,
and ensures a failed refresh never replaces the last usable state.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from exilelens.app.build_revision import BuildFileRevision, read_build_revision
from exilelens.app.settings import app_data_dir
from exilelens.build_sources import BuildSourceKind, BuildSourceRef

log = logging.getLogger(__name__)

BUILD_CACHE_SCHEMA_VERSION = 1
BUILD_CACHE_DIRNAME = "build-cache"
MAX_CACHE_ENTRIES = 8


@dataclass(frozen=True)
class BuildCacheKey:
    value: str

    @classmethod
    def for_build_file(cls, path: str | Path) -> "BuildCacheKey":
        resolved = os.path.normcase(str(Path(path).resolve()))
        return cls(f"build_file:{resolved}")

    @classmethod
    def for_source(cls, ref: BuildSourceRef) -> "BuildCacheKey":
        if ref.kind == BuildSourceKind.LOCAL_POB:
            return cls(f"build_file:{ref.identity}")
        return cls(f"api_character:{ref.identity}")

    @property
    def filename(self) -> str:
        digest = hashlib.sha1(self.value.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
        return f"{digest}.json"

    def __str__(self) -> str:
        return self.value


@dataclass
class BuildCacheEntry:
    key: str
    build_path: str
    source_kind: str = BuildSourceKind.LOCAL_POB.value
    source_identity: str = ""
    source_revision: str = ""
    display_name: str = ""
    context: str = "MAP"
    loadout: str = ""
    item_set_id: str = ""
    item_set_name: str = ""
    tree_set_name: str = ""
    fingerprint: str = ""
    tree_fingerprint: str = ""
    equipment_fingerprint: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    build_revision: dict[str, int] = field(default_factory=dict)
    pob_head: str = ""
    loaded_at: float = 0.0
    last_refresh_attempt_at: float = 0.0
    last_refresh_error: dict[str, str] | None = None
    schema_version: int = BUILD_CACHE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "key": self.key,
            "buildPath": self.build_path,
            "sourceKind": self.source_kind,
            "sourceIdentity": self.source_identity,
            "sourceRevision": self.source_revision,
            "displayName": self.display_name,
            "context": self.context,
            "loadout": self.loadout,
            "itemSetId": self.item_set_id,
            "itemSetName": self.item_set_name,
            "treeSetName": self.tree_set_name,
            "fingerprint": self.fingerprint,
            "treeFingerprint": self.tree_fingerprint,
            "equipmentFingerprint": self.equipment_fingerprint,
            "metrics": self.metrics,
            "buildRevision": self.build_revision,
            "pobHead": self.pob_head,
            "freshness": {
                "loadedAt": self.loaded_at,
                "lastRefreshAttemptAt": self.last_refresh_attempt_at,
                "lastRefreshError": self.last_refresh_error,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BuildCacheEntry | None":
        if not isinstance(data, dict) or data.get("schemaVersion") != BUILD_CACHE_SCHEMA_VERSION:
            return None
        key = str(data.get("key") or "")
        path = str(data.get("buildPath") or "")
        kind = str(data.get("sourceKind") or BuildSourceKind.LOCAL_POB.value)
        identity = str(data.get("sourceIdentity") or (key.removeprefix("build_file:") if key.startswith("build_file:") else ""))
        if not key or kind not in {item.value for item in BuildSourceKind} or not identity:
            return None
        if kind == BuildSourceKind.LOCAL_POB and (not key.startswith("build_file:") or not path):
            return None
        if kind == BuildSourceKind.API_CHARACTER and key != f"api_character:{identity}":
            return None
        freshness = data.get("freshness") if isinstance(data.get("freshness"), dict) else {}
        revision = data.get("buildRevision") if isinstance(data.get("buildRevision"), dict) else {}
        error = freshness.get("lastRefreshError")
        return cls(
            key=key,
            build_path=path,
            source_kind=kind,
            source_identity=identity,
            source_revision=str(data.get("sourceRevision") or ""),
            display_name=str(data.get("displayName") or ""),
            context=str(data.get("context") or "MAP"),
            loadout=str(data.get("loadout") or ""),
            item_set_id=str(data.get("itemSetId") or ""),
            item_set_name=str(data.get("itemSetName") or ""),
            tree_set_name=str(data.get("treeSetName") or ""),
            fingerprint=str(data.get("fingerprint") or ""),
            tree_fingerprint=str(data.get("treeFingerprint") or ""),
            equipment_fingerprint=str(data.get("equipmentFingerprint") or ""),
            metrics=dict(data.get("metrics") or {}),
            build_revision=(
                {"mtimeNs": int(revision.get("mtimeNs") or 0), "size": int(revision.get("size") or 0)}
                if kind == BuildSourceKind.LOCAL_POB.value else {}
            ),
            pob_head=str(data.get("pobHead") or ""),
            loaded_at=float(freshness.get("loadedAt") or 0.0),
            last_refresh_attempt_at=float(freshness.get("lastRefreshAttemptAt") or 0.0),
            last_refresh_error=(
                {"code": str(error.get("code") or ""), "message": str(error.get("message") or "")}
                if isinstance(error, dict)
                else None
            ),
        )


@dataclass(frozen=True)
class ActiveBuildStatus:
    display_name: str = ""
    build_path: str = ""
    loaded_at: float = 0.0
    freshness: str = "UNKNOWN"
    last_error: str = ""
    engine_state: str = "NO_BUILD"

    def last_loaded_text(self, now: float | None = None) -> str:
        if self.loaded_at <= 0:
            return "never"
        delta = max(0.0, (time.time() if now is None else now) - self.loaded_at)
        if delta < 60:
            return "just now"
        if delta < 3600:
            return f"{int(delta // 60)} min ago"
        if delta < 86400:
            return f"{int(delta // 3600)} h ago"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.loaded_at))


class BuildCache:
    def __init__(self, root: Path | None = None, *, max_entries: int = MAX_CACHE_ENTRIES) -> None:
        self.root = Path(root) if root is not None else app_data_dir() / BUILD_CACHE_DIRNAME
        self.index_path = self.root / "index.json"
        self.max_entries = max(1, int(max_entries))

    def load_active(self) -> BuildCacheEntry | None:
        index = self._read_index()
        key = str(index.get("activeKey") or "")
        return self.get(key) if key else None

    def get(self, key: str | BuildCacheKey) -> BuildCacheEntry | None:
        value = str(key)
        index = self._read_index()
        meta = (index.get("entries") or {}).get(value)
        if not isinstance(meta, dict):
            return None
        filename = str(meta.get("file") or "")
        if not filename or Path(filename).name != filename:
            return None
        try:
            data = json.loads((self.root / filename).read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return None
        entry = BuildCacheEntry.from_dict(data)
        return entry if entry is not None and entry.key == value else None

    def upsert(self, entry: BuildCacheEntry, *, set_active: bool = True) -> None:
        if entry.schema_version != BUILD_CACHE_SCHEMA_VERSION:
            return
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            key = BuildCacheKey(entry.key)
            self._atomic_json(self.root / key.filename, entry.to_dict())
            index = self._read_index()
            entries = dict(index.get("entries") or {})
            entries[entry.key] = {
                "file": key.filename,
                "displayName": entry.display_name,
                "loadedAt": entry.loaded_at,
            }
            active = entry.key if set_active else str(index.get("activeKey") or "")
            entries = self._prune(entries, preserve=active)
            self._atomic_json(
                self.index_path,
                {"schemaVersion": BUILD_CACHE_SCHEMA_VERSION, "activeKey": active, "entries": entries},
            )
        except (OSError, TypeError, ValueError):
            log.exception("could not persist build cache")

    def set_active(self, key: str | BuildCacheKey) -> None:
        value = str(key)
        index = self._read_index()
        if value not in (index.get("entries") or {}):
            return
        index["activeKey"] = value
        try:
            self._atomic_json(self.index_path, index)
        except (OSError, TypeError, ValueError):
            log.exception("could not update active build cache entry")

    def clear_active(self) -> None:
        """Forget the active build so startup cannot resurrect a path the user reset."""
        index = self._read_index()
        if not index.get("activeKey"):
            return
        index["activeKey"] = ""
        try:
            self._atomic_json(self.index_path, index)
        except (OSError, TypeError, ValueError):
            log.exception("could not clear active build cache entry")

    def record_refresh_error(self, key: str | BuildCacheKey, code: str, message: str) -> None:
        entry = self.get(key)
        if entry is None:
            return
        entry.last_refresh_attempt_at = time.time()
        entry.last_refresh_error = {"code": str(code), "message": str(message)}
        self.upsert(entry, set_active=False)

    def _read_index(self) -> dict[str, Any]:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return {"schemaVersion": BUILD_CACHE_SCHEMA_VERSION, "activeKey": "", "entries": {}}
        if not isinstance(data, dict) or data.get("schemaVersion") != BUILD_CACHE_SCHEMA_VERSION:
            return {"schemaVersion": BUILD_CACHE_SCHEMA_VERSION, "activeKey": "", "entries": {}}
        if not isinstance(data.get("entries"), dict):
            data["entries"] = {}
        return data

    def _prune(self, entries: dict[str, Any], *, preserve: str) -> dict[str, Any]:
        ordered = sorted(
            entries.items(), key=lambda item: float((item[1] or {}).get("loadedAt") or 0.0), reverse=True
        )
        keep = dict(ordered[: self.max_entries])
        if preserve and preserve in entries and preserve not in keep:
            keep[preserve] = entries[preserve]
            oldest = min((k for k in keep if k != preserve), key=lambda k: float(keep[k].get("loadedAt") or 0), default="")
            if len(keep) > self.max_entries and oldest:
                keep.pop(oldest, None)
        for key, meta in entries.items():
            if key in keep or not isinstance(meta, dict):
                continue
            filename = str(meta.get("file") or "")
            if filename and Path(filename).name == filename:
                try:
                    (self.root / filename).unlink(missing_ok=True)
                except OSError:
                    log.warning("could not prune build cache entry %s", filename)
        return keep

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)


def revision_dict(revision: BuildFileRevision | None) -> dict[str, int]:
    if revision is None:
        return {"mtimeNs": 0, "size": 0}
    return {"mtimeNs": revision.mtime_ns, "size": revision.size}


def freshness_for(entry: BuildCacheEntry, *, now: float | None = None) -> str:
    if entry.last_refresh_error:
        return "REFRESH_FAILED"
    if entry.source_kind != BuildSourceKind.LOCAL_POB.value:
        return "UNKNOWN"
    current = read_build_revision(entry.build_path)
    cached = entry.build_revision
    if current is None or not cached:
        return "UNKNOWN"
    if current.mtime_ns != int(cached.get("mtimeNs") or 0) or current.size != int(cached.get("size") or 0):
        return "CHANGED_ON_DISK"
    return "FRESH"


def status_from_entry(entry: BuildCacheEntry | None, *, engine_state: str = "NO_BUILD") -> ActiveBuildStatus:
    if entry is None:
        return ActiveBuildStatus(engine_state=engine_state)
    error = entry.last_refresh_error or {}
    return ActiveBuildStatus(
        display_name=entry.display_name,
        build_path=entry.build_path,
        loaded_at=entry.loaded_at,
        freshness=freshness_for(entry),
        last_error=str(error.get("message") or ""),
        engine_state=engine_state,
    )
