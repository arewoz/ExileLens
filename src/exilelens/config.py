from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import xml.etree.ElementTree as ET

from exilelens import SUPPORTED_POB_HEAD
from exilelens._paths import bridge_lua_path, pob_headless_wrapper_path, pob_simplegraphic_def_path
from exilelens.errors import PobPathInvalid, UnsupportedPobRevision

_POB_VERSION = re.compile(r"\d+\.\d+\.\d+(?:[A-Za-z0-9.+-]*)?")


@dataclass(frozen=True)
class PobIdentity:
    """Bounded, local metadata about a selected Path of Building installation."""

    version: str = "unknown"
    layout: str = "unknown"
    revision: str = "unknown"
    status: str = "unknown"
    manifest_version: str = "unknown"
    reason: str = ""


_POB2_REPO_MARKER = "PathOfBuildingCommunity/PathOfBuilding-PoE2/"
_POB1_REPO_MARKER = "PathOfBuildingCommunity/PathOfBuilding/"


def _manifest_provenance(root: ET.Element) -> str:
    """Return whether a manifest looks like official PoB2 metadata or mismatches.

    Official PoB2 manifests embed a canonical source URL in a ``Source`` element.
    When present, a mismatch is a stronger signal than a missing version number:
    it indicates stale or unrelated metadata, but it does not prove the runtime is
    invalid. The app keeps using the running PoB2 install while showing the version
    as unverified.
    """
    tags = {"Source", "Repository", "Repo", "RepositoryUrl", "App", "Application"}
    candidates: list[str] = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in tags:
            continue
        for key in ("url", "href", "value", "name"):
            value = str(node.get(key) or "").strip()
            if value:
                candidates.append(value)
        text = str(node.text or "").strip()
        if text:
            candidates.append(text)
    for value in candidates:
        lower = value.lower()
        if _POB2_REPO_MARKER.lower() in lower:
            return "official"
        if _POB1_REPO_MARKER.lower() in lower:
            return "mismatch"
        if value and ("://" in value or "/" in value or "@" in value or "." in value):
            return "mismatch"
    return "none"


@lru_cache(maxsize=32)
def _manifest_identity(contents: bytes) -> PobIdentity:
    """Parse one bounded manifest body; caching avoids repeated XML parsing."""
    try:
        manifest_root = ET.fromstring(contents)
    except (ET.ParseError, OSError, ValueError):
        return PobIdentity(status="malformed", reason="manifest.xml is malformed or unreadable")

    tag = manifest_root.tag.rsplit("}", 1)[-1]
    if tag != "PoBVersion":
        return PobIdentity(status="malformed", reason="manifest.xml does not contain a PoBVersion root")

    node = manifest_root.find("./Version")
    version = str(node.get("number", "") if node is not None else "").strip()
    if not _POB_VERSION.fullmatch(version):
        return PobIdentity(version="unknown", status="malformed", manifest_version=version or "unknown", reason="manifest.xml version is missing or malformed")

    provenance = _manifest_provenance(manifest_root)
    if provenance != "official":
        return PobIdentity(
            version="unknown",
            status="unverified",
            manifest_version=version,
            reason=(
                "manifest identity does not match a validated PoB2 installation"
                if provenance == "mismatch"
                else "manifest has no trusted PoB2 provenance field"
            ),
        )
    return PobIdentity(version=version, status="verified", manifest_version=version)


def detect_pob_identity(path: Path | str) -> PobIdentity:
    """Read the human-readable PoB version from its root manifest, safely.

    Identity is informational: malformed or absent metadata never prevents PoB
    from being used and no path or manifest content is returned to callers.
    """
    root = Path(path)
    if (root / "src" / "Launch.lua").is_file():
        layout = "source"
    elif (root / "Launch.lua").is_file():
        layout = "installed"
    else:
        layout = "unknown"
    manifest = root / "manifest.xml"
    try:
        stat = manifest.stat()
        if stat.st_size > 1_000_000:
            metadata = PobIdentity(layout=layout, status="unverified", reason="manifest.xml is larger than the safe size limit")
        else:
            metadata = _manifest_identity(manifest.read_bytes())
    except (ET.ParseError, OSError, ValueError):
        metadata = PobIdentity(layout=layout, status="missing", reason="manifest.xml is missing or unreadable")
    return PobIdentity(
        version=metadata.version,
        layout=layout,
        revision="unknown",
        status=metadata.status,
        manifest_version=metadata.manifest_version,
        reason=metadata.reason,
    )


@dataclass(frozen=True)
class PobConfig:
    pob_path: Path
    supported_head: str = SUPPORTED_POB_HEAD

    @property
    def layout(self) -> str:
        return detect_pob_identity(self.pob_path).layout

    @property
    def program_path(self) -> Path:
        return self.pob_path / "src" if self.layout == "source" else self.pob_path

    @property
    def src_path(self) -> Path:
        """Compatibility alias for the directory containing PoB's Lua program."""
        return self.program_path

    @property
    def runtime_path(self) -> Path:
        return self.pob_path / "runtime" if self.layout == "source" else self.pob_path

    @property
    def lua_modules_path(self) -> Path:
        return self.runtime_path / "lua"

    @property
    def lua_dll(self) -> Path:
        return self.runtime_path / "lua51.dll"

    @property
    def headless_wrapper(self) -> Path:
        return pob_headless_wrapper_path()

    @property
    def simplegraphic_def(self) -> Path:
        return pob_simplegraphic_def_path()

    @property
    def bridge_lua(self) -> Path:
        return bridge_lua_path()


def load_config() -> PobConfig:
    raw = (os.environ.get("POB2_PATH") or "").strip()
    return PobConfig(pob_path=Path(raw).resolve() if raw else Path())


def required_pob_files(config: PobConfig) -> dict[str, Path]:
    """Files supplied by PoB and ExileLens that the headless worker needs."""
    return {
        "pob_root": config.pob_path,
        "Launch.lua": config.program_path / "Launch.lua",
        "Modules/Main.lua": config.program_path / "Modules" / "Main.lua",
        "Modules/Build.lua": config.program_path / "Modules" / "Build.lua",
        "Data/ModItem.lua": config.program_path / "Data" / "ModItem.lua",
        "lua51.dll": config.lua_dll,
        "lua/xml.lua": config.lua_modules_path / "xml.lua",
        "ExileLens bridge.lua": config.bridge_lua,
        "ExileLens headless wrapper": config.headless_wrapper,
        "ExileLens SimpleGraphic definitions": config.simplegraphic_def,
    }


_POB_INSTALL_DIRECTORY_NAMES = (
    "Path of Building Community (PoE2)",
    "PathOfBuilding-PoE2",
)


def pob_installation_candidates(environ: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """Return bounded PoB2 candidates in deterministic preference order.

    This intentionally checks exact paths only. ``POB2_PATH`` is the supported
    custom-location override; the remaining entries cover normal installers and
    common places where a portable archive is extracted without recursively
    walking user folders.
    """
    env = os.environ if environ is None else environ
    candidates: list[Path] = []

    explicit = str(env.get("POB2_PATH") or "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())

    standard_name = _POB_INSTALL_DIRECTORY_NAMES[0]
    for variable, suffix in (
        ("APPDATA", standard_name),
        ("LOCALAPPDATA", standard_name),
        ("LOCALAPPDATA", f"Programs/{standard_name}"),
        ("ProgramFiles", standard_name),
        ("ProgramFiles(x86)", standard_name),
    ):
        base = str(env.get(variable) or "").strip()
        if base:
            candidates.append(Path(base) / suffix)

    portable_roots: list[Path] = []
    user_profile = str(env.get("USERPROFILE") or "").strip()
    if user_profile:
        profile = Path(user_profile)
        portable_roots.extend((profile / "Documents", profile, profile / "Downloads", profile / "Desktop"))
    for variable in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        base = str(env.get(variable) or "").strip()
        if base:
            portable_roots.append(Path(base) / "Documents")

    for root in portable_roots:
        for directory_name in _POB_INSTALL_DIRECTORY_NAMES:
            candidates.append(root / directory_name)

    # Windows paths are case-insensitive. Deduplication also prevents OneDrive
    # aliases from probing the same directory repeatedly.
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.normpath(str(candidate)))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return tuple(unique)


def _is_discoverable_pob2(candidate: Path) -> bool:
    try:
        config = PobConfig(candidate)
        validate_pob_path(config)
        identity = detect_pob_identity(candidate)
    except (OSError, PobPathInvalid, UnsupportedPobRevision):
        return False

    # A missing manifest remains compatible with older PoB2 packages. A
    # manifest that explicitly identifies another repository is stronger
    # evidence and must not make a PoB1/untrusted lookalike auto-selectable.
    if identity.status == "unverified" and "does not match" in identity.reason:
        return False
    try:
        if (candidate / "Path of Building.exe").is_file() and not (
            candidate / "Path of Building-PoE2.exe"
        ).is_file():
            return False
    except OSError:
        return False
    return True


def detect_common_pob_installation(environ: Mapping[str, str] | None = None) -> Path | None:
    """Return the first validated PoB2 installation from the bounded candidates."""
    for candidate in pob_installation_candidates(environ):
        if _is_discoverable_pob2(candidate):
            return candidate
    return None


def validate_pob_path(config: PobConfig) -> dict:
    missing = []
    for label, path in required_pob_files(config).items():
        if not path.exists():
            missing.append(label)
    if missing:
        looks_like_pob = any((config.pob_path / name).exists() for name in ("Data", "Modules", "Assets", "Launch.lua"))
        if looks_like_pob:
            message = (
                "This folder looks like a Path of Building installation, but required runtime files "
                f"could not be found: {', '.join(missing)}"
            )
        else:
            message = (
                "Path of Building files could not be found. Choose the installation folder "
                f"that contains Launch.lua and lua51.dll (missing: {', '.join(missing)})."
            )
        raise PobPathInvalid(message, {"missing": missing, "pob_path": str(config.pob_path), "layout": config.layout})

    head = None
    try:
        result = subprocess.run(
            ["git", "-C", str(config.pob_path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            # The frozen app is windowed; without this every probe flashes a console.
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        head = result.stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        head = None

    if head and head != config.supported_head:
        raise UnsupportedPobRevision(
            f"PoB HEAD {head} is not the tested revision {config.supported_head}",
            {"actual_head": head, "supported_head": config.supported_head},
        )

    return {
        "pob_path": str(config.pob_path),
        "layout": config.layout,
        "program_path": str(config.program_path),
        "runtime_path": str(config.runtime_path),
        "head": head,
        "version": detect_pob_identity(config.pob_path).version,
        "supported_head": config.supported_head,
        "bridge_lua": str(config.bridge_lua),
    }


def fingerprint_hash(components: dict) -> str:
    payload = json.dumps(components, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
