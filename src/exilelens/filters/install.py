"""Filter installation utilities for FILTER-04.

Safe installation of generated filter files to the PoE2 filter directory.
"""

from __future__ import annotations

import os
import hashlib
import re
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass

from exilelens.filters.validation import validate_all


@dataclass
class InstallationResult:
    """Result of a filter installation operation."""
    success: bool
    filter_name: str
    destination: Path
    profile: str
    theme: str
    error_message: str = ""
    bytes_written: int = 0
    verified: bool = False


@dataclass
class BatchInstallationResult:
    """Result of a batch installation operation."""
    results: List[InstallationResult]
    successful: int
    failed: int

    @property
    def all_successful(self) -> bool:
        return self.failed == 0


# The normal application keeps one selectable file per strictness level.
DEFAULT_FILTER_FILENAME = "ExileLens_Recommended.filter"
LEGACY_FILTER_FILENAME = "ExileLens_Test.filter"
TEST_FILTER_FILENAME = DEFAULT_FILTER_FILENAME  # compatibility for existing developer callers

# Batch filter filename pattern
BATCH_FILTER_PATTERN = "ExileLens_{profile}_{theme}.filter"


def get_filter_path(filter_dir: Path, profile: str = "Recommended") -> Path:
    """Return a safe, recognizable name using the approved strictness level."""
    from exilelens.filters.profile_policy import normalize_level
    level, _ = normalize_level(profile)
    return Path(filter_dir) / f"ExileLens_{level.replace(' ', '_')}.filter"


get_test_filter_path = get_filter_path  # compatibility for existing developer callers


def get_batch_filter_path(filter_dir: Path, profile: str, theme: str) -> Path:
    """Get the path for a batch filter file."""
    from exilelens.filters.profiles import FilterThemeName
    from exilelens.filters.profile_policy import normalize_level
    level, _ = normalize_level(profile)
    native_theme = FilterThemeName(theme).value
    filename = BATCH_FILTER_PATTERN.format(profile=level.replace(" ", "_"),
                                          theme=native_theme.replace(" ", "_"))
    return Path(filter_dir) / filename


def validate_filter_content(filter_text: str) -> Tuple[bool, str]:
    """Use the same fail-closed serialized validator as development and UI."""
    if not filter_text or not filter_text.strip():
        return False, "Filter content is empty"

    validation = validate_all(filter_text)
    if not validation.passed:
        return False, "; ".join(validation.errors[:8])

    return True, ""


OWNERSHIP_HEADER = "# ExileLens Build-Aware Loot Filter"


def _owned(content: bytes) -> bool:
    try:
        return OWNERSHIP_HEADER in content.decode("utf-8-sig").splitlines()[:3]
    except UnicodeError:
        return False


def write_filter_safely(filter_text: str, destination: Path) -> Tuple[bool, int, str]:
    """Replace only ExileLens-owned files, atomically, with rollback on verification failure."""
    destination = Path(destination)
    if not re.fullmatch(r"ExileLens_[A-Za-z0-9_]+\.filter", destination.name) or destination.is_symlink():
        return False, 0, "Destination is not an ExileLens-owned filter filename"
    valid, error = validate_filter_content(filter_text)
    if not valid:
        return False, 0, f"Validation failed: {error}"
    content = filter_text.encode("utf-8")
    if not _owned(content):
        return False, 0, "Generated file is missing the ExileLens ownership header"
    staged = backup = None
    replaced = False
    old = None
    preserve_backup = False
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            old = destination.read_bytes()
            if not _owned(old):
                return False, 0, "Existing file is not owned by ExileLens"

        def stage(data):
            with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent,
                                             prefix=".exilelens_", suffix=".tmp", delete=False) as handle:
                path = Path(handle.name)
                try:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                except OSError:
                    handle.close()
                    path.unlink(missing_ok=True)
                    raise
            return path

        staged = stage(content)
        if old is not None:
            backup = stage(old)
        # Detect edits that occurred during validation/staging before replacing anything.
        if destination.is_symlink() or (destination.read_bytes() if destination.exists() else None) != old:
            return False, 0, "Existing file changed during installation; retry after checking it"
        os.replace(staged, destination)
        staged = None
        replaced = True
        if destination.read_bytes() != content:
            raise OSError("Written content does not match source")
        return True, len(content), ""
    except OSError as exc:
        recovery = ""
        if replaced:
            try:
                if backup is not None:
                    os.replace(backup, destination)
                    backup = None
                    recovery = "; previous filter restored"
                else:
                    destination.unlink(missing_ok=True)
            except OSError as rollback_error:
                preserve_backup = True
                recovery = f"; recovery failed: {rollback_error}; previous bytes preserved at {backup}"
        return False, 0, f"Installation failed: {exc}{recovery}"
    finally:
        for path in (staged, None if preserve_backup else backup):
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


def install_test_filter(
    filter_text: str,
    filter_dir: Path,
    profile: str,
    theme: str
) -> InstallationResult:
    """Install ExileLens_<Strictness>.filter.

    Changing theme or build replaces that profile's owned file. Different
    strictness levels remain separately selectable in the game.

    Args:
        filter_text: Generated filter content
        filter_dir: PoE2 filter directory
        profile: Selected profile name
        theme: Selected theme name

    Returns:
        InstallationResult with success status and details
    """
    destination = get_filter_path(filter_dir, profile)
    if destination.exists():
        try:
            if "# ExileLens Build-Aware Loot Filter" not in destination.read_text(encoding="utf-8"):
                return InstallationResult(False, destination.name, destination, profile, theme,
                                          error_message="Existing file is not owned by ExileLens")
        except (OSError, UnicodeError) as exc:
            return InstallationResult(False, destination.name, destination, profile, theme,
                                      error_message=f"Cannot verify existing file: {exc}")

    success, bytes_written, error = write_filter_safely(filter_text, destination)

    if success:
        verified = True
        return InstallationResult(
            success=True,
            filter_name=destination.name,
            destination=destination,
            profile=profile,
            theme=theme,
            bytes_written=bytes_written,
            verified=verified
        )
    else:
        return InstallationResult(
            success=False,
            filter_name=destination.name,
            destination=destination,
            profile=profile,
            theme=theme,
            error_message=error
        )


def install_batch_filters(
    filters: List[Tuple[str, str, str]],  # (filter_text, profile, theme)
    filter_dir: Path
) -> BatchInstallationResult:
    """Install a validated profile/theme matrix as separate files.

    Args:
        filters: List of (filter_text, profile, theme) tuples
        filter_dir: PoE2 filter directory

    Returns:
        BatchInstallationResult with individual results
    """
    # A bad member must not leave a partly replaced matrix.
    failures = [(profile, theme, error) for content, profile, theme in filters
                for valid, error in [validate_filter_content(content)] if not valid]
    if failures:
        summary = "; ".join(f"{profile}/{theme}: {error}" for profile, theme, error in failures)
        results = [InstallationResult(False, get_batch_filter_path(Path(filter_dir), profile, theme).name,
                                      get_batch_filter_path(Path(filter_dir), profile, theme), profile, theme,
                                      error_message=f"Batch validation failed: {summary}")
                   for _, profile, theme in filters]
        return BatchInstallationResult(results=results, successful=0, failed=len(results))

    results = []

    for filter_text, profile, theme in filters:
        result = install_batch_filter(filter_text, filter_dir, profile, theme)
        results.append(result)

    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful

    return BatchInstallationResult(
        results=results,
        successful=successful,
        failed=failed
    )


def install_batch_filter(
    filter_text: str,
    filter_dir: Path,
    profile: str,
    theme: str
) -> InstallationResult:
    """Install a single batch filter file.

    Args:
        filter_text: Generated filter content
        filter_dir: PoE2 filter directory
        profile: Profile name
        theme: Theme name

    Returns:
        InstallationResult
    """
    destination = get_batch_filter_path(Path(filter_dir), profile, theme)

    # Check if file exists and is not an ExileLens filter
    success, bytes_written, error = write_filter_safely(
        filter_text,
        destination
    )

    if success:
        verified = True
        return InstallationResult(
            success=True,
            filter_name=destination.name,
            destination=destination,
            profile=profile,
            theme=theme,
            bytes_written=bytes_written,
            verified=verified
        )
    else:
        return InstallationResult(
            success=False,
            filter_name=destination.name,
            destination=destination,
            profile=profile,
            theme=theme,
            error_message=error
        )


def get_installed_filter_info(filter_dir: Path, profile: str = "Recommended") -> Optional[dict]:
    """Inspect the selected profile's file, or the untouched legacy file.

    Returns:
        Dict with filter info, or None if not installed.
    """
    test_path = get_filter_path(filter_dir, profile)
    if not test_path.exists():
        test_path = Path(filter_dir) / LEGACY_FILTER_FILENAME
    if not test_path.exists():
        return None

    try:
        raw = test_path.read_bytes()
        if not _owned(raw):
            return None
        content = raw.decode("utf-8")
        lines = content.splitlines()

        # Extract metadata from header
        info = {
            "path": test_path.name,
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        from exilelens.filters.intel_generate import filter_body_sha256
        info["body_sha256"] = filter_body_sha256(content)

        for line in lines[:30]:
            if line.startswith("# Build:"):
                info["build"] = line.replace("# Build:", "").strip()
            elif line.startswith("# Profile:"):
                info["profile"] = line.replace("# Profile:", "").strip()
            elif line.startswith("# Theme:"):
                info["theme"] = line.replace("# Theme:", "").strip()
            elif line.startswith("# Generated:"):
                info["generated"] = line.replace("# Generated:", "").strip()
            elif line.startswith("# Version:"):
                info["version"] = line.replace("# Version:", "").strip()
            elif line.startswith("# Data:"):
                info["data"] = line.replace("# Data:", "").strip()
            elif line.startswith("# Build Intelligence:"):
                info["intelligence"] = line.replace("# Build Intelligence:", "").strip()

        return info
    except (OSError, UnicodeError):
        return None


def open_filter_folder(filter_dir: Path) -> bool:
    """Open the filter directory in Windows Explorer.

    Returns:
        True if successful, False otherwise.
    """
    try:
        import subprocess
        subprocess.run(["explorer", str(filter_dir)], check=False)
        return True
    except Exception:
        return False
