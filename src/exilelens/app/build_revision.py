"""Lightweight on-disk PoB build file revision tracking."""

from __future__ import annotations

import hashlib
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from exilelens.errors import BuildNotFound, BuildSourceIncomplete


@dataclass(frozen=True)
class BuildFileRevision:
    path: str
    mtime_ns: int
    size: int
    sha256: str = ""

    def changed_from(self, other: BuildFileRevision | None) -> bool:
        if other is None:
            return True
        if self.path != other.path:
            return True
        return self.mtime_ns != other.mtime_ns or self.size != other.size

    def token(self) -> str:
        """Compact identity handed to the PoB worker for the loaded generation."""
        return f"{self.mtime_ns}:{self.size}:{self.sha256[:16]}"


@dataclass(frozen=True)
class BuildSource:
    """Exact bytes of one build revision, validated as complete XML."""

    revision: BuildFileRevision
    text: str | None  # None when the file is not UTF-8; the worker then reads the file itself


def read_build_revision(path: str | Path) -> BuildFileRevision | None:
    resolved = str(Path(path).resolve())
    try:
        stat = os.stat(resolved)
    except OSError:
        return None
    return BuildFileRevision(path=resolved, mtime_ns=int(stat.st_mtime_ns), size=int(stat.st_size))


def read_build_source(path: str | Path) -> BuildSource:
    """Read one stable, well-formed revision of a build file.

    PoB saves by truncate + rewrite on the same path, so a read can observe an
    empty or half-written file.  That surfaces as BuildSourceIncomplete and must
    never be treated as a loadable revision.
    """
    resolved = str(Path(path).resolve())
    try:
        before = os.stat(resolved)
        data = Path(resolved).read_bytes()
        after = os.stat(resolved)
    except FileNotFoundError as exc:
        raise BuildNotFound(f"build not found: {resolved}", {"path": resolved}) from exc
    except OSError as exc:
        raise BuildSourceIncomplete(f"cannot read build file: {exc}", {"path": resolved}) from exc
    if (
        before.st_mtime_ns != after.st_mtime_ns
        or before.st_size != after.st_size
        or len(data) != after.st_size
    ):
        raise BuildSourceIncomplete("build file changed while it was being read", {"path": resolved})
    if not data.strip():
        raise BuildSourceIncomplete("build file is empty", {"path": resolved})
    try:
        ET.fromstring(data)
    except ET.ParseError as exc:
        raise BuildSourceIncomplete(f"build XML is incomplete or malformed: {exc}", {"path": resolved}) from exc
    try:
        # Lua reads the file in text mode, which folds CRLF; mirror that so PoB sees identical item text.
        text: str | None = data.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        text = None
    revision = BuildFileRevision(
        path=resolved,
        mtime_ns=int(after.st_mtime_ns),
        size=int(after.st_size),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    return BuildSource(revision=revision, text=text)
