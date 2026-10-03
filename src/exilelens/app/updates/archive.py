from __future__ import annotations

import os
import stat
import zipfile
from pathlib import Path, PurePosixPath

# Bounds for an unattended updater. ExileLens v0.6.0 ships 204 entries, ~146 MB uncompressed, largest entry
# ~20 MB, worst compression ratio ~4.5:1 — every limit below leaves at least ~7x headroom.
MAX_ARCHIVE_ENTRIES = 10_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024  # 1 GiB total
MAX_ARCHIVE_ENTRY_BYTES = 256 * 1024 * 1024  # 256 MiB per entry
MAX_COMPRESSION_RATIO = 100  # per entry, enforced for entries larger than RATIO_CHECK_MIN_BYTES
RATIO_CHECK_MIN_BYTES = 1024 * 1024


class UnsafeArchiveError(ValueError):
    pass


def validate_zip_archive(path: Path, *, expected_root: str = "ExileLens/") -> list[zipfile.ZipInfo]:
    """Reject archives that could escape the staging root or exhaust disk/memory; return file entries."""
    if not path.is_file():
        raise UnsafeArchiveError("missing_archive")
    root = PurePosixPath(expected_root).parts[0]
    try:
        archive = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise UnsafeArchiveError("invalid_archive") from exc
    with archive:
        infos = archive.infolist()
        if not infos:
            raise UnsafeArchiveError("empty_archive")
        if len(infos) > MAX_ARCHIVE_ENTRIES:
            raise UnsafeArchiveError("too_many_entries")
        seen: set[str] = set()
        files: list[zipfile.ZipInfo] = []
        total = 0
        for info in infos:
            name = info.filename
            if "\\" in name or ":" in name or "\x00" in name:
                raise UnsafeArchiveError("unsafe_entry_name")
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or not pure.parts:
                raise UnsafeArchiveError("path_traversal")
            if pure.parts[0] != root:
                raise UnsafeArchiveError("entry_outside_root")
            folded = name.rstrip("/").casefold()
            if folded in seen:
                raise UnsafeArchiveError("duplicate_entry")
            seen.add(folded)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode) or stat.S_ISBLK(mode) or stat.S_ISCHR(mode) or stat.S_ISFIFO(mode):
                raise UnsafeArchiveError("unsupported_entry_type")
            if info.is_dir():
                continue
            if info.file_size > MAX_ARCHIVE_ENTRY_BYTES:
                raise UnsafeArchiveError("entry_too_large")
            if info.file_size > RATIO_CHECK_MIN_BYTES and info.file_size > MAX_COMPRESSION_RATIO * max(1, info.compress_size):
                raise UnsafeArchiveError("compression_ratio_exceeded")
            total += info.file_size
            if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise UnsafeArchiveError("archive_too_large")
            files.append(info)
        if not files:
            raise UnsafeArchiveError("missing_expected_root")
    return files


def extract_zip_to_staging(archive_path: Path, staging_dir: Path) -> Path:
    validate_zip_archive(archive_path)
    if staging_dir.exists():
        _remove_tree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "r") as archive:
        archive.extractall(staging_dir)
    extracted_root = staging_dir / "ExileLens"
    if not extracted_root.is_dir():
        raise UnsafeArchiveError("missing_extracted_root")
    return extracted_root


def _remove_tree(path: Path) -> None:
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            (Path(root) / name).unlink(missing_ok=True)
        for name in dirs:
            (Path(root) / name).rmdir()
    path.rmdir()
