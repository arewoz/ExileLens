"""Patch / data drift detection for generated filters (FILTER-08D). Offline: no network, no required client access.

Tracked versions: pinned PoB2 commit and version, the generated base / modifier / skill datasets (by hash and by the commit each
carries), the passive-data generation PoB2 ships (a hint for the game version the data describes), the item-filter syntax source and
the generator schema. Optionally the installed client version as DIAGNOSTIC context.

States and the behaviour they trigger when a filter is generated:

  CURRENT                 datasets consistent and match the PoB2 commit this ExileLens build supports -> normal generation
  UNVERIFIED_NEWER_GAME   a detected client is newer than the data generation -> warn, WIDEN (no narrowing from old data)
  STALE_SNAPSHOT          datasets are intact but not the PoB2 commit ExileLens supports -> warn, WIDEN
  INCOMPATIBLE_DATA       datasets disagree with their manifest or each other -> BLOCK (native validity cannot be guaranteed)
  UNKNOWN                 no manifest -> warn, WIDEN

"Widen" means: no demotion, no weapon-class narrowing, no measured layer hides, verified bands applied everywhere.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from exilelens.filters import snapshot_tools as st

GENERATOR_SCHEMA = "FILTER-08D-1"          # bump when generated-rule semantics change
FILTER_SYNTAX_SOURCE = "GGG item-filter reference (PoE2), conditions/actions checked 2026-09-26 (filters/validation.py)"


class DataState(str, Enum):
    CURRENT = "CURRENT"
    UNVERIFIED_NEWER_GAME = "UNVERIFIED NEWER GAME"
    STALE_SNAPSHOT = "STALE SNAPSHOT"
    INCOMPATIBLE_DATA = "INCOMPATIBLE DATA"
    UNKNOWN = "UNKNOWN"


class DataIncompatible(RuntimeError):
    """Raised instead of generating a filter whose native validity cannot be guaranteed."""


@dataclass(frozen=True)
class DataStatus:
    state: DataState
    reasons: tuple[str, ...]
    versions: Mapping[str, Any] = field(default_factory=dict)
    client_version: str = ""

    @property
    def widen(self) -> bool:
        return self.state in (DataState.UNVERIFIED_NEWER_GAME, DataState.STALE_SNAPSHOT, DataState.UNKNOWN)

    @property
    def blocks(self) -> bool:
        return self.state == DataState.INCOMPATIBLE_DATA

    @property
    def headline(self) -> str:
        return f"Data: {self.state.value}" + (f" — {'; '.join(self.reasons)}" if self.reasons else "")


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])


def detect_client_version(explicit: str = "", install_dir: Path | None = None) -> str:
    """Best-effort installed PoE2 version: an explicit value, EXILELENS_POE2_VERSION, then the game executable's file version.

    Returns '' when it cannot be determined (the normal case): that is diagnostic, never a reason to block."""
    value = explicit or os.environ.get("EXILELENS_POE2_VERSION", "")
    if value or not install_dir:
        return value
    try:
        import ctypes
        from ctypes import wintypes
        for exe in ("PathOfExile.exe", "PathOfExile_x64.exe", "PathOfExileSteam.exe"):
            path = Path(install_dir) / exe
            if not path.exists():
                continue
            size = ctypes.windll.version.GetFileVersionInfoSizeW(str(path), None)
            if not size:
                continue
            buffer = ctypes.create_string_buffer(size)
            ctypes.windll.version.GetFileVersionInfoW(str(path), 0, size, buffer)
            info, length = ctypes.c_void_p(), wintypes.UINT()
            if ctypes.windll.version.VerQueryValueW(buffer, "\\", ctypes.byref(info), ctypes.byref(length)):
                class _Fixed(ctypes.Structure):
                    _fields_ = [("sig", wintypes.DWORD), ("sv", wintypes.DWORD), ("fvms", wintypes.DWORD), ("fvls", wintypes.DWORD)]
                fixed = ctypes.cast(info, ctypes.POINTER(_Fixed)).contents
                return f"{fixed.fvms >> 16}.{fixed.fvms & 0xFFFF}.{fixed.fvls >> 16}"
    except Exception:
        return ""
    return ""


def check(data_dir: Path = st.DATA_DIR, *, client_version: str = "", supported_pob_head: str | None = None) -> DataStatus:
    if supported_pob_head is None:
        from exilelens import SUPPORTED_POB_HEAD as supported_pob_head
    manifest_path = Path(data_dir) / st.MANIFEST
    versions: dict[str, Any] = {"generator_schema": GENERATOR_SCHEMA, "filter_syntax": FILTER_SYNTAX_SOURCE, "supported_pob_head": supported_pob_head}
    if not manifest_path.exists():
        return DataStatus(DataState.UNKNOWN, ("no data manifest",), versions, client_version)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DataStatus(DataState.INCOMPATIBLE_DATA, ("data manifest unreadable",), versions, client_version)
    versions.update({"pob_version": manifest.get("pob_version"), "pob_commit": manifest.get("pob_commit"),
                     "game_version_hint": manifest.get("game_version_hint"), "manifest_schema": manifest.get("schema_version")})
    problems: list[str] = []
    commits = set()
    for name, recorded in (manifest.get("files") or {}).items():
        path = Path(data_dir) / name
        if not path.exists():
            problems.append(f"{name} missing")
            continue
        if st.sha256_file(path) != recorded.get("sha256"):
            problems.append(f"{name} differs from its manifest hash")
            continue
        try:
            commits.add(json.loads(path.read_text(encoding="utf-8")).get("pob_commit"))
        except ValueError:
            problems.append(f"{name} unreadable")
    if manifest.get("schema_version") != st.SCHEMA_VERSION:
        problems.append(f"manifest schema {manifest.get('schema_version')} != {st.SCHEMA_VERSION}")
    if len(commits) > 1 or (commits and manifest.get("pob_commit") not in commits):
        problems.append("datasets disagree on the PoB2 commit")
    if problems:
        return DataStatus(DataState.INCOMPATIBLE_DATA, tuple(problems), versions, client_version)
    client = client_version or detect_client_version()
    versions["client_version"] = client or "not detected"
    hint = manifest.get("game_version_hint") or ""
    if client and hint and _version_tuple(client)[:2] > _version_tuple(hint)[:2]:
        return DataStatus(DataState.UNVERIFIED_NEWER_GAME,
                          (f"client {client} is newer than the data generation {hint}",), versions, client)
    if manifest.get("pob_commit") != supported_pob_head:
        return DataStatus(DataState.STALE_SNAPSHOT,
                          (f"data is PoB2 {str(manifest.get('pob_commit'))[:12]}, ExileLens supports {str(supported_pob_head)[:12]}",),
                          versions, client)
    return DataStatus(DataState.CURRENT, (), versions, client)
