"""TRUST-01C: bounded, local discovery of Path of Building Community (PoE2) installations.

Discovery finds candidates; PoB validation decides whether they are usable.

Every path proposed by any source (explicit override, saved path, uninstall registry, App Paths,
standard locations, Start Menu shortcuts, shallow folder scan) goes through the one existing
validation boundary, `config._is_discoverable_pob2` (`validate_pob_path` + manifest provenance + PoB1
rejection). Directory names, registry strings and shortcut names are never trusted by themselves.

Local only: no network, no process launch, no recursion. Registry and shortcut readers are injectable so
tests and non-Windows hosts never need a real registry.
"""

from __future__ import annotations

import logging
import os
import re
import struct
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from exilelens.config import (
    _POB_INSTALL_DIRECTORY_NAMES,
    _is_discoverable_pob2,
    detect_pob_identity,
    pob_installation_candidates,
    required_pob_files,
    PobConfig,
)

logger = logging.getLogger(__name__)

# Source priority (lower = stronger). Explicit user intent and a working saved path are tier 0.
SOURCE_EXPLICIT = "explicit"
SOURCE_SAVED = "saved"
SOURCE_REGISTRY = "registry"
SOURCE_APP_PATHS = "app_paths"
SOURCE_STANDARD = "standard"
SOURCE_SHORTCUT = "shortcut"
SOURCE_SCAN = "scan"
SOURCE_PRIORITY = {
    SOURCE_EXPLICIT: 0,
    SOURCE_SAVED: 1,
    SOURCE_REGISTRY: 2,
    SOURCE_APP_PATHS: 3,
    SOURCE_STANDARD: 4,
    SOURCE_SHORTCUT: 5,
    SOURCE_SCAN: 6,
}
_USER_INTENT_SOURCES = frozenset({SOURCE_EXPLICIT, SOURCE_SAVED})

# Explicit bounds (startup must stay unnoticeable even on slow OneDrive/network folders).
SCAN_MAX_CHILDREN_PER_ROOT = 400
SCAN_MAX_MATCHES_PER_ROOT = 8
REGISTRY_MAX_SUBKEYS = 3000
SHORTCUT_MAX_FILES = 64
SHORTCUT_MAX_BYTES = 64 * 1024
DISCOVERY_TIME_BUDGET_SECONDS = 3.0

_POB2_EXE = "Path of Building-PoE2.exe"
_NAME_LOOKS_LIKE_POB = re.compile(r"path\s*of\s*building|pathofbuilding|\bpob\b|pob2|pob-?poe2", re.IGNORECASE)
_VERSION_PARTS = re.compile(r"\d+")


@dataclass(frozen=True)
class PobInstallationCandidate:
    path: Path
    source: str
    source_priority: int
    layout: str = "unknown"
    identity_status: str = "unknown"
    version: str = "unknown"
    valid: bool = True
    reason: str = ""
    sources: tuple[str, ...] = field(default_factory=tuple)  # every source that found it (diagnostics)

    @property
    def user_intent(self) -> bool:
        return self.source in _USER_INTENT_SOURCES

    def version_key(self) -> tuple[int, ...]:
        """Parsed from the existing manifest version; unknown sorts below every known version."""
        if self.version == "unknown":
            return ()
        return tuple(int(part) for part in _VERSION_PARTS.findall(self.version)[:4])

    def display(self) -> str:
        kind = "Installed application" if self.layout == "installed" else "Developer checkout" if self.layout == "source" else "Installation"
        version = f"Version {self.version}" if self.version != "unknown" else "Version unknown"
        return f"{version} · {kind} · {shorten_path(self.path)}"


@dataclass(frozen=True)
class PobDiscoveryResult:
    candidates: tuple[PobInstallationCandidate, ...]
    selected: PobInstallationCandidate | None  # None when there is nothing or the choice is ambiguous
    ambiguous: tuple[PobInstallationCandidate, ...] = ()


def shorten_path(path: Path | str, limit: int = 56) -> str:
    text = str(path)
    if len(text) <= limit:
        return text
    return text[:18] + "…" + text[-(limit - 19):]


def canonical_key(path: Path | str) -> str:
    """Case-insensitive, normalised identity of a directory; never raises and never needs it to exist."""
    try:
        raw = os.path.abspath(os.path.expanduser(str(path)))
        try:
            raw = os.path.realpath(raw)
        except OSError:
            pass
        return os.path.normcase(os.path.normpath(raw))
    except (OSError, ValueError):
        return os.path.normcase(os.path.normpath(str(path)))


# ----------------------------------------------------------------------- Windows sources


def _clean_registry_path(value: object) -> Path | None:
    text = str(value or "").strip().strip('"').strip()
    if not text:
        return None
    return Path(text)


def _directory_of(value: object) -> Path | None:
    """Directory named by an `InstallLocation`, `DisplayIcon` (`"x.exe",0`) or `UninstallString`."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith('"'):
        end = text.find('"', 1)
        text = text[1:end] if end > 0 else text[1:]
    else:
        text = re.sub(r",\s*-?\d+$", "", text)
        lowered = text.lower()
        if ".exe" in lowered:
            text = text[: lowered.index(".exe") + 4]
    path = Path(text)
    return path.parent if path.suffix.lower() == ".exe" else path


def registry_install_locations() -> list[Path]:
    """Install directories of uninstall entries whose DisplayName mentions Path of Building.

    `DisplayName` only selects which entries to read; the directory it points at still has to pass PoB2
    validation. Reads HKCU, HKLM and the WOW6432 view; at most `REGISTRY_MAX_SUBKEYS` subkeys per hive.
    """
    try:
        import winreg
    except ImportError:  # non-Windows
        return []
    found: list[Path] = []
    base = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    hives = (
        (winreg.HKEY_CURRENT_USER, 0),
        (winreg.HKEY_LOCAL_MACHINE, getattr(winreg, "KEY_WOW64_64KEY", 0)),
        (winreg.HKEY_LOCAL_MACHINE, getattr(winreg, "KEY_WOW64_32KEY", 0)),
    )
    for hive, view in hives:
        try:
            with winreg.OpenKey(hive, base, 0, winreg.KEY_READ | view) as root:
                count = min(winreg.QueryInfoKey(root)[0], REGISTRY_MAX_SUBKEYS)
                for index in range(count):
                    try:
                        with winreg.OpenKey(root, winreg.EnumKey(root, index)) as entry:
                            name = str(winreg.QueryValueEx(entry, "DisplayName")[0])
                            if not _NAME_LOOKS_LIKE_POB.search(name):
                                continue
                            location = None
                            for value_name in ("InstallLocation", "DisplayIcon", "UninstallString"):
                                try:
                                    location = _directory_of(winreg.QueryValueEx(entry, value_name)[0])
                                except OSError:
                                    continue
                                if location is not None:
                                    break
                            if location is not None:
                                found.append(location)
                    except OSError:
                        continue
        except OSError:
            continue
    return found


def app_paths_locations() -> list[Path]:
    """Directory of the PoB2 executable registered under Windows App Paths (only the one real exe name)."""
    try:
        import winreg
    except ImportError:
        return []
    found: list[Path] = []
    key = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{_POB2_EXE}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key) as entry:
                for value_name in ("Path", ""):
                    try:
                        directory = _directory_of(winreg.QueryValueEx(entry, value_name)[0])
                    except OSError:
                        continue
                    if directory is not None:
                        found.append(directory)
                        break
        except OSError:
            continue
    return found


def parse_lnk_target(data: bytes) -> Path | None:
    """Local target of a Windows `.lnk` (Shell Link LinkInfo.LocalBasePath); None when not resolvable."""
    try:
        if len(data) < 0x4C or struct.unpack_from("<I", data, 0)[0] != 0x4C:
            return None
        flags = struct.unpack_from("<I", data, 0x14)[0]
        offset = 0x4C
        if flags & 0x01:  # HasLinkTargetIDList
            offset += 2 + struct.unpack_from("<H", data, offset)[0]
        if not flags & 0x02:  # HasLinkInfo
            return None
        info = offset
        header_size, info_flags, _volume, local_base = struct.unpack_from("<IIII", data, info + 4)
        if not info_flags & 0x01 or not local_base:
            return None
        end = data.index(b"\x00", info + local_base)
        text = data[info + local_base : end].decode("mbcs" if os.name == "nt" else "latin-1", "replace")
        return Path(text) if text else None
    except (struct.error, ValueError, OSError):
        return None


def shortcut_locations(environ: Mapping[str, str] | None = None) -> list[Path]:
    """Install directories behind a few Start Menu shortcuts whose file name mentions Path of Building.

    Only the Programs folder itself and its immediate subfolders are listed; never a recursive walk.
    """
    env = os.environ if environ is None else environ
    roots = []
    for variable, tail in (("APPDATA", "Microsoft/Windows/Start Menu/Programs"), ("PROGRAMDATA", "Microsoft/Windows/Start Menu/Programs")):
        base = str(env.get(variable) or "").strip()
        if base:
            roots.append(Path(base) / tail)
    found: list[Path] = []
    inspected = 0
    for root in roots:
        folders = [root]
        try:
            with os.scandir(root) as entries:
                for count, entry in enumerate(entries):
                    if count >= SCAN_MAX_CHILDREN_PER_ROOT:
                        break
                    if _NAME_LOOKS_LIKE_POB.search(entry.name) and entry.is_dir(follow_symlinks=False):
                        folders.append(Path(entry.path))
        except OSError:
            continue
        for folder in folders:
            try:
                with os.scandir(folder) as entries:
                    for count, entry in enumerate(entries):
                        if count >= SCAN_MAX_CHILDREN_PER_ROOT or inspected >= SHORTCUT_MAX_FILES:
                            break
                        if not entry.name.lower().endswith(".lnk") or not _NAME_LOOKS_LIKE_POB.search(entry.name):
                            continue
                        inspected += 1
                        try:
                            if entry.stat().st_size > SHORTCUT_MAX_BYTES:
                                continue
                            target = parse_lnk_target(Path(entry.path).read_bytes())
                        except OSError:
                            continue
                        if target is not None:
                            found.append(target.parent if target.suffix.lower() == ".exe" else target)
            except OSError:
                continue
    return found


# ----------------------------------------------------------------------- shallow scan


def _scan_roots(env: Mapping[str, str]) -> list[Path]:
    roots: list[Path] = []
    local = str(env.get("LOCALAPPDATA") or "").strip()
    if local:
        roots.append(Path(local) / "Programs")
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        base = str(env.get(variable) or "").strip()
        if base:
            roots.append(Path(base))
    profile = str(env.get("USERPROFILE") or "").strip()
    if profile:
        roots.extend(Path(profile) / name for name in ("Documents", "Downloads", "Desktop"))
    for variable in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        base = str(env.get(variable) or "").strip()
        if base:
            roots.append(Path(base) / "Documents")
    return roots


def shallow_scan_locations(
    env: Mapping[str, str],
    *,
    deadline: float,
    max_children: int = SCAN_MAX_CHILDREN_PER_ROOT,
    max_matches: int = SCAN_MAX_MATCHES_PER_ROOT,
) -> list[Path]:
    """Depth-1 only: child folders of a few roots whose own name looks PoB-related. No recursion."""
    found: list[Path] = []
    for root in _scan_roots(env):
        if time.monotonic() > deadline:
            break
        matches = 0
        try:
            with os.scandir(root) as entries:
                for count, entry in enumerate(entries):
                    if count >= max_children or matches >= max_matches or time.monotonic() > deadline:
                        break
                    try:
                        if entry.is_dir(follow_symlinks=False) and _NAME_LOOKS_LIKE_POB.search(entry.name):
                            found.append(Path(entry.path))
                            matches += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return found


# ----------------------------------------------------------------------- core


def _has_required_runtime_files(path: Path) -> bool:
    """Cheap pre-filter (plain `exists`) so the `git` probe inside full validation only runs on real candidates."""
    try:
        files = required_pob_files(PobConfig(path))
        return all(p.exists() for label, p in files.items() if not label.startswith("ExileLens"))
    except OSError:
        return False


def _validated(path: Path, source: str) -> PobInstallationCandidate | None:
    try:
        if not path.is_dir() or not _has_required_runtime_files(path) or not _is_discoverable_pob2(path):
            return None
        identity = detect_pob_identity(path)
    except OSError:
        return None
    return PobInstallationCandidate(
        path=path,
        source=source,
        source_priority=SOURCE_PRIORITY[source],
        layout=identity.layout,
        identity_status=identity.status,
        version=identity.version,
        sources=(source,),
    )


def _rank_key(candidate: PobInstallationCandidate):
    # 1 user intent  2 verified official  3 installed app over source checkout
    # 4 higher known version  5 source confidence  6 path (final deterministic tie-break only)
    return (
        0 if candidate.user_intent else 1,
        candidate.source_priority if candidate.user_intent else 0,
        0 if candidate.identity_status == "verified" else 1,
        0 if candidate.layout == "installed" else 1,
        tuple(-part for part in candidate.version_key()) if candidate.version_key() else (1,),
        candidate.source_priority,
        canonical_key(candidate.path),
    )


def _equivalent(a: PobInstallationCandidate, b: PobInstallationCandidate) -> bool:
    return (
        (a.identity_status == "verified") == (b.identity_status == "verified")
        and a.layout == b.layout
        and a.version_key() == b.version_key()
    )


def discover_pob_installations(
    environ: Mapping[str, str] | None = None,
    *,
    saved_path: str = "",
    registry_provider: Callable[[], Iterable[Path]] | None = None,
    app_paths_provider: Callable[[], Iterable[Path]] | None = None,
    shortcut_provider: Callable[[], Iterable[Path]] | None = None,
    scan: bool = True,
    time_budget_seconds: float = DISCOVERY_TIME_BUDGET_SECONDS,
) -> list[PobInstallationCandidate]:
    """All validated PoB2 installations in deterministic ranked order, duplicates collapsed."""
    env = os.environ if environ is None else environ
    deadline = time.monotonic() + time_budget_seconds
    if registry_provider is None:
        registry_provider = registry_install_locations
    if app_paths_provider is None:
        app_paths_provider = app_paths_locations
    if shortcut_provider is None:
        shortcut_provider = lambda: shortcut_locations(env)  # noqa: E731

    proposals: list[tuple[Path, str]] = []
    explicit = str(env.get("POB2_PATH") or "").strip()
    if explicit:
        proposals.append((Path(explicit).expanduser(), SOURCE_EXPLICIT))
    if str(saved_path or "").strip():
        proposals.append((Path(str(saved_path).strip()), SOURCE_SAVED))

    def safe(provider: Callable[[], Iterable[Path]], source: str) -> None:
        if time.monotonic() > deadline:
            return
        try:
            proposals.extend((Path(p), source) for p in provider())
        except Exception:  # noqa: BLE001 - a broken source must never break discovery
            logger.warning("pob_discovery_source_failed source=%s", source)

    safe(registry_provider, SOURCE_REGISTRY)
    safe(app_paths_provider, SOURCE_APP_PATHS)
    # Exact standard locations (POB2_PATH is already handled above as explicit).
    standard = [p for p in pob_installation_candidates(env) if not (explicit and canonical_key(p) == canonical_key(explicit))]
    proposals.extend((p, SOURCE_STANDARD) for p in standard)
    safe(shortcut_provider, SOURCE_SHORTCUT)
    if scan:
        safe(lambda: shallow_scan_locations(env, deadline=deadline), SOURCE_SCAN)

    merged: dict[str, PobInstallationCandidate] = {}
    for path, source in proposals:
        key = canonical_key(path)
        existing = merged.get(key)
        if existing is not None:
            # Same installation found again: keep the strongest provenance, remember all sources.
            strongest = source if SOURCE_PRIORITY[source] < existing.source_priority else existing.source
            merged[key] = replace(
                existing,
                source=strongest,
                source_priority=SOURCE_PRIORITY[strongest],
                sources=tuple(dict.fromkeys((*existing.sources, source))),
            )
            continue
        candidate = _validated(path, source)
        if candidate is not None:
            merged[key] = candidate
    ranked = sorted(merged.values(), key=_rank_key)
    logger.info(
        "pob_discovery_done candidates=%d sources=%s",
        len(ranked),
        ",".join(sorted({s for c in ranked for s in c.sources})),
    )
    return ranked


def choose_pob_installation(candidates: Iterable[PobInstallationCandidate]) -> PobDiscoveryResult:
    """Pick one clearly best installation, or report ambiguity instead of guessing."""
    ranked = tuple(candidates)
    if not ranked:
        return PobDiscoveryResult((), None)
    best = ranked[0]
    if best.user_intent:
        return PobDiscoveryResult(ranked, best)
    tied = tuple(c for c in ranked if _equivalent(best, c))
    if len(tied) > 1:
        return PobDiscoveryResult(ranked, None, tied)
    return PobDiscoveryResult(ranked, best)


def find_pob_installation(environ: Mapping[str, str] | None = None, *, saved_path: str = "", **providers) -> PobDiscoveryResult:
    return choose_pob_installation(discover_pob_installations(environ, saved_path=saved_path, **providers))


def detect_common_pob_installation(environ: Mapping[str, str] | None = None, *, saved_path: str = "") -> Path | None:
    """The one clearly best validated installation, or None (nothing found, or ambiguous: never guess)."""
    selected = find_pob_installation(environ, saved_path=saved_path).selected
    return selected.path if selected is not None else None


def auto_configure_pob_path(current_path: str, environ: Mapping[str, str] | None = None) -> tuple[str, PobDiscoveryResult | None]:
    """Startup policy. Returns (path_to_use, discovery_result).

    A configured path that still validates is kept untouched and discovery is not even run. Otherwise the
    saved value is only replaced when exactly one clearly best validated installation exists; the caller
    saves it after this returns (i.e. after validation succeeded).
    """
    current = str(current_path or "").strip()
    if current and _validated(Path(current), SOURCE_SAVED) is not None:
        return current, None
    result = find_pob_installation(environ)
    if result.selected is not None:
        return str(result.selected.path), result
    return current, result
