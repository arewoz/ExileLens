"""Canonical ExileLens version and bounded release-identity access.

``__version__`` is the authoritative application version. Packaged builds add
their deterministic build-toolchain identity in ``build_stamp.json`` beside the
executable; source runs never require or consume that stamp.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__version__ = "0.2.1b1"

_STAMP_NAME = "build_stamp.json"
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_PYTHON_RE = re.compile(r"\d+\.\d+\.\d+")
_TOOL_VERSION_RE = re.compile(r"\d+(?:\.\d+)+(?:[a-z0-9.+-]*)", re.IGNORECASE)
_BUILD_MODES = {"onedir", "onefile"}
UNKNOWN = "unknown"


@dataclass(frozen=True)
class BuildIdentity:
    """Explicit, allowlisted facts suitable for support diagnostics."""

    version: str
    git_commit: str
    execution_mode: str
    build_mode: str
    python_version: str
    pyinstaller_version: str


def is_packaged() -> bool:
    """Return whether this is a frozen executable rather than a source run."""
    return bool(getattr(sys, "frozen", False))


def windows_version_tuple(version: str = __version__) -> tuple[int, int, int, int]:
    """Map canonical ``X.Y.ZbN`` versions to Windows' numeric four-part form."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:b(\d+))?", version)
    if match is None:
        raise ValueError("canonical version must be X.Y.Z or X.Y.ZbN")
    major, minor, patch, beta = match.groups()
    return int(major), int(minor), int(patch), int(beta or 0)


def build_identity() -> BuildIdentity:
    """Return bounded identity without exposing stamp errors, paths, or metadata."""
    if not is_packaged():
        return BuildIdentity(
            version=__version__,
            git_commit=_source_commit(),
            execution_mode="source",
            build_mode=UNKNOWN,
            python_version=_runtime_python_version(),
            pyinstaller_version=UNKNOWN,
        )

    stamp = _load_packaged_stamp()
    if stamp is None:
        return BuildIdentity(__version__, UNKNOWN, "packaged", UNKNOWN, UNKNOWN, UNKNOWN)
    return BuildIdentity(
        # The bundled source constant remains authoritative even if a copied
        # sidecar stamp is stale or malformed.
        version=__version__,
        git_commit=_valid_commit(stamp.get("git_commit")),
        execution_mode="packaged",
        build_mode=_valid_build_mode(stamp.get("build_mode")),
        python_version=_valid_python_version(stamp.get("python_version")),
        pyinstaller_version=_valid_tool_version(stamp.get("pyinstaller_version")),
    )


def git_commit() -> str:
    """Return a full, validated source commit identifier or ``unknown``."""
    return build_identity().git_commit


def _load_packaged_stamp() -> dict[str, Any] | None:
    for path in _packaged_stamp_paths():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, UnicodeError):
            continue
        if not isinstance(payload, dict):
            continue
        # Reject a contradictory stamp as a whole; unsupported fields are never
        # read and therefore cannot enter identity or copied diagnostics.
        if (
            payload.get("schema_version") != 1
            or payload.get("product") != "ExileLens"
            or payload.get("version") != __version__
        ):
            continue
        return payload
    return None


def _packaged_stamp_paths() -> tuple[Path, ...]:
    paths: list[Path] = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        paths.append(Path(bundle) / _STAMP_NAME)
    paths.append(Path(sys.executable).resolve().parent / _STAMP_NAME)
    return tuple(paths)


def _source_commit() -> str:
    explicit = _valid_commit(os.environ.get("EXILELENS_GIT_COMMIT"))
    if explicit != UNKNOWN:
        return explicit
    return _valid_commit(_git_rev_parse())


def _git_rev_parse() -> str:
    root = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def _runtime_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _valid_commit(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if _COMMIT_RE.fullmatch(text) else UNKNOWN


def _valid_build_mode(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text in _BUILD_MODES else UNKNOWN


def _valid_python_version(value: object) -> str:
    text = str(value or "").strip()
    return text if _PYTHON_RE.fullmatch(text) else UNKNOWN


def _valid_tool_version(value: object) -> str:
    text = str(value or "").strip()
    return text if _TOOL_VERSION_RE.fullmatch(text) else UNKNOWN
