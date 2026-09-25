from __future__ import annotations

import os
import stat
import zipfile
from pathlib import Path, PurePosixPath


class UnsafeArchiveError(ValueError):
    pass


def validate_zip_archive(path: Path, *, expected_root: str = "ExileLens/") -> None:
    if not path.is_file():
        raise UnsafeArchiveError("missing_archive")
    root = PurePosixPath(expected_root)
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        if not names:
            raise UnsafeArchiveError("empty_archive")
        seen_root = False
        for name in names:
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts:
                raise UnsafeArchiveError("path_traversal")
            if pure.parts and pure.parts[0] == root.parts[0]:
                seen_root = True
            info = archive.getinfo(name)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode) or stat.S_ISBLK(mode) or stat.S_ISCHR(mode):
                raise UnsafeArchiveError("unsupported_entry_type")
        if not seen_root:
            raise UnsafeArchiveError("missing_expected_root")


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
