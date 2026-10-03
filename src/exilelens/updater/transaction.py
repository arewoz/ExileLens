"""Journaled, crash-safe replacement of the onedir ExileLens install.

Windows has no atomic multi-entry directory-tree replacement, so the install is swapped entry by entry:

1. *Prepare* (slow, interruptible, install untouched): verify the downloaded package, copy the staged tree
   to ``<install>/.update-new``, verify that tree against the package's central directory (names, sizes,
   CRC-32), and back up every top-level entry that will be replaced.
2. *Journal*: record the install root and, per top-level entry, whether an old version existed.
3. *Swap* (fast renames on one volume): for each entry, ``X -> .update-old/X`` then ``.update-new/X -> X``.
   Sharing violations (antivirus scanners, indexers) are retried with bounded backoff.
4. *Commit*: delete the journal. ``.update-old`` stays as recovery material until the next healthy launch.

Rollback never trusts progress counters; it inspects the filesystem per entry, so it is idempotent and
can resume after the updater itself dies mid-way. An incomplete journal is always rolled back (never
rolled forward) and is only deleted after the rollback succeeds. The only window not covered is the
interval between the two renames of a single entry, which is milliseconds; it is still covered by the
next recovery run as long as the updater can execute.
"""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import shutil
import stat
import sys
import time
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from exilelens.updater import layout

logger = logging.getLogger(__name__)

JOURNAL_SCHEMA = 1
MAX_JOURNAL_BYTES = 64 * 1024
MAX_JOURNAL_ENTRIES = 64
RENAME_RETRY_SECONDS = 30.0
_SHARING_WINERRORS = {5, 32, 33}  # ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION
_HASH_CHUNK = 1024 * 1024


class InstallError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class JournalEntry:
    name: str
    had_old: bool


@dataclass(frozen=True)
class Journal:
    job_id: str
    install_root: Path
    entries: tuple[JournalEntry, ...]


# ----------------------------------------------------------------------------- filesystem helpers

_rename: Callable[[Path, Path], None] = os.replace
_sleep: Callable[[float], None] = time.sleep
_clock: Callable[[], float] = time.monotonic


def _retryable(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) in _SHARING_WINERRORS or exc.errno in {errno.EACCES, errno.EBUSY}


def _with_retry(action: Callable[[], None], *, budget_seconds: float = RENAME_RETRY_SECONDS) -> None:
    deadline = _clock() + budget_seconds
    delay = 0.1
    while True:
        try:
            action()
            return
        except OSError as exc:
            if not _retryable(exc) or _clock() >= deadline:
                raise
            _sleep(delay)
            delay = min(delay * 2, 1.0)


def _move(source: Path, target: Path) -> None:
    _with_retry(lambda: _rename(source, target))


def _clear_readonly(func, path, _exc) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _rmtree(path: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_clear_readonly)
    else:  # pragma: no cover - older interpreters
        shutil.rmtree(path, onerror=_clear_readonly)


def remove_path(path: Path) -> None:
    if not os.path.lexists(path):
        return
    if path.is_dir() and not path.is_symlink():
        _with_retry(lambda: _rmtree(path))
    else:
        _with_retry(lambda: path.unlink())


def valid_entry_name(name: object) -> bool:
    if not isinstance(name, str) or not name or len(name) > 255:
        return False
    if name in {".", "..", layout.INSTALL_NEW_DIR, layout.INSTALL_OLD_DIR}:
        return False
    return not any(ch in name for ch in '\\/:*?"<>|\x00')


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            hasher.update(chunk)
    return hasher.hexdigest()


def _crc32(path: Path) -> int:
    value = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            value = zlib.crc32(chunk, value)
    return value & 0xFFFFFFFF


# ----------------------------------------------------------------------------- provenance


def verify_package(zip_path: Path, *, sha256: str, size: int) -> None:
    """Re-check the downloaded package against the signed-manifest hash recorded in the job."""
    try:
        if zip_path.stat().st_size != size or _sha256(zip_path) != sha256:
            raise InstallError("package_mismatch")
    except OSError as exc:
        raise InstallError("package_missing") from exc


def verify_tree_against_zip(tree_root: Path, zip_path: Path, *, archive_root: str = layout.STAGED_ROOT_NAME) -> None:
    """The prepared tree must contain exactly the package's files, byte-identical by size and CRC-32."""
    expected: dict[str, zipfile.ZipInfo] = {}
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                parts = PurePosixPath(info.filename).parts
                if len(parts) < 2 or parts[0] != archive_root:
                    raise InstallError("provenance_mismatch")
                expected["/".join(parts[1:]).casefold()] = info
    except (OSError, zipfile.BadZipFile) as exc:
        raise InstallError("package_unreadable") from exc
    seen: set[str] = set()
    for path in tree_root.rglob("*"):
        if path.is_symlink():
            raise InstallError("provenance_mismatch")
        if path.is_dir():
            continue
        rel = path.relative_to(tree_root).as_posix().casefold()
        info = expected.get(rel)
        if info is None:
            raise InstallError("provenance_mismatch")
        if path.stat().st_size != info.file_size or _crc32(path) != info.CRC:
            raise InstallError("provenance_mismatch")
        seen.add(rel)
    if seen != set(expected):
        raise InstallError("provenance_mismatch")


# ----------------------------------------------------------------------------- journal


def write_journal(path: Path, journal: Journal) -> None:
    payload = {
        "schema": JOURNAL_SCHEMA,
        "job_id": journal.job_id,
        "install_root": str(journal.install_root),
        "entries": [{"name": e.name, "had_old": e.had_old} for e in journal.entries],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def read_journal(path: Path) -> Journal:
    """Strictly validate a journal before acting on it. Paths are never taken from entries."""
    try:
        if path.stat().st_size > MAX_JOURNAL_BYTES:
            raise InstallError("invalid_journal")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise InstallError("invalid_journal") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema", "job_id", "install_root", "entries"}:
        raise InstallError("invalid_journal")
    if payload["schema"] != JOURNAL_SCHEMA or not isinstance(payload["job_id"], str):
        raise InstallError("invalid_journal")
    root_text, raw_entries = payload["install_root"], payload["entries"]
    if not isinstance(root_text, str) or not Path(root_text).is_absolute():
        raise InstallError("invalid_journal")
    if not isinstance(raw_entries, list) or not 0 < len(raw_entries) <= MAX_JOURNAL_ENTRIES:
        raise InstallError("invalid_journal")
    entries: list[JournalEntry] = []
    names: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict) or set(raw) != {"name", "had_old"}:
            raise InstallError("invalid_journal")
        name, had_old = raw["name"], raw["had_old"]
        if not valid_entry_name(name) or type(had_old) is not bool or name.casefold() in names:
            raise InstallError("invalid_journal")
        names.add(name.casefold())
        entries.append(JournalEntry(name, had_old))
    return Journal(job_id=payload["job_id"], install_root=Path(root_text), entries=tuple(entries))


# ----------------------------------------------------------------------------- phases


def _ordered_entries(new_dir: Path) -> list[str]:
    names = [child.name for child in new_dir.iterdir()]
    if not all(valid_entry_name(name) for name in names) or len(names) > MAX_JOURNAL_ENTRIES:
        raise InstallError("invalid_package_layout")
    if layout.APP_EXECUTABLE_NAME not in names or layout.APP_INTERNAL_DIR not in names:
        raise InstallError("invalid_package_layout")
    # Executable last: during the swap window the old exe never starts against a half-replaced runtime.
    return sorted(names, key=lambda n: (n == layout.APP_EXECUTABLE_NAME, n.casefold()))


def prepare(
    *,
    install_root: Path,
    staged_root: Path,
    backup_root: Path,
    zip_path: Path | None,
    zip_sha256: str | None,
    zip_size: int | None,
) -> list[str]:
    """Build and verify ``.update-new`` and back up replaced entries. Never modifies installed entries."""
    new_dir = install_root / layout.INSTALL_NEW_DIR
    old_dir = install_root / layout.INSTALL_OLD_DIR
    remove_path(new_dir)
    # A leftover .update-old belongs to an earlier *committed* update (no journal exists at this point).
    remove_path(old_dir)
    if zip_path is not None:
        verify_package(zip_path, sha256=str(zip_sha256), size=int(zip_size or 0))
    if not layout.looks_like_install_root(staged_root):
        raise InstallError("staged_root_invalid")
    shutil.copytree(staged_root, new_dir)
    if zip_path is not None:
        verify_tree_against_zip(new_dir, zip_path)
    entries = _ordered_entries(new_dir)
    remove_path(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    for name in entries:
        source = install_root / name
        if source.is_dir():
            shutil.copytree(source, backup_root / name)
        elif source.exists():
            shutil.copy2(source, backup_root / name)
    return entries


def swap(*, install_root: Path, entries: list[str], journal_path: Path, job_id: str) -> Journal:
    new_dir = install_root / layout.INSTALL_NEW_DIR
    old_dir = install_root / layout.INSTALL_OLD_DIR
    journal = Journal(
        job_id=job_id,
        install_root=install_root,
        entries=tuple(JournalEntry(name, os.path.lexists(install_root / name)) for name in entries),
    )
    old_dir.mkdir(exist_ok=True)
    write_journal(journal_path, journal)
    for entry in journal.entries:
        if entry.had_old:
            _move(install_root / entry.name, old_dir / entry.name)
        _move(new_dir / entry.name, install_root / entry.name)
    return journal


def rollback(journal: Journal) -> None:
    """Restore every entry to its pre-swap state by inspecting the filesystem (idempotent, resumable)."""
    root = journal.install_root
    new_dir = root / layout.INSTALL_NEW_DIR
    old_dir = root / layout.INSTALL_OLD_DIR
    new_dir.mkdir(exist_ok=True)
    for entry in reversed(journal.entries):
        target, old, new = root / entry.name, old_dir / entry.name, new_dir / entry.name
        if os.path.lexists(old):
            # The old entry was moved aside; whatever sits at the target now is the new version.
            if os.path.lexists(target):
                if os.path.lexists(new):
                    remove_path(target)
                else:
                    _move(target, new)
            _move(old, target)
        elif not entry.had_old and os.path.lexists(target):
            # Entry did not exist before the update: the target is new content.
            if os.path.lexists(new):
                remove_path(target)
            else:
                _move(target, new)
        # Otherwise the old entry was never moved and is still in place.


def restore_from_backup(journal: Journal, backup_root: Path) -> None:
    root = journal.install_root
    for entry in journal.entries:
        if entry.had_old and not os.path.lexists(backup_root / entry.name):
            raise InstallError("backup_incomplete")
    for entry in journal.entries:
        target = root / entry.name
        remove_path(target)
        if entry.had_old:
            source = backup_root / entry.name
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)


def cleanup_work_dir(install_root: Path, name: str) -> None:
    try:
        remove_path(install_root / name)
    except OSError:
        logger.warning("update_cleanup_failed dir=%s", name)


def undo(journal: Journal, *, journal_path: Path, backup_root: Path) -> bool:
    """Roll back an incomplete swap; fall back to the backup copy. Journal removed only on success."""
    try:
        rollback(journal)
    except Exception:  # noqa: BLE001 - every failure falls back to the backup copy
        logger.exception("update_rollback_failed")
        try:
            restore_from_backup(journal, backup_root)
        except Exception:  # noqa: BLE001
            logger.exception("update_backup_restore_failed")
            return False
    journal_path.unlink(missing_ok=True)
    cleanup_work_dir(journal.install_root, layout.INSTALL_NEW_DIR)
    cleanup_work_dir(journal.install_root, layout.INSTALL_OLD_DIR)
    return True
