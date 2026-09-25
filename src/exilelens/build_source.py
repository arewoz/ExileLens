"""The exact PoB build bytes a load is based on.

A build snapshot is identified by what was actually read, not by its path: path, size,
mtime and a sha256 of the bytes. The same bytes are handed to the PoB worker, so the
revision recorded as "loaded" is the one that was parsed, even if PoB saves again a
millisecond later. Validation happens here, before the worker is touched, so a
half-written or broken file can never replace a working build.
"""

from __future__ import annotations

import hashlib
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from exilelens.errors import BuildNotFound, BuildParseFailed

_STABLE_READ_ATTEMPTS = 3


@dataclass(frozen=True)
class BuildSource:
    path: str
    mtime_ns: int
    size: int
    sha256: str
    data: bytes = field(repr=False)

    @property
    def revision(self) -> str:
        """Token the worker compares to decide whether it may reuse its parse."""
        return f"{self.mtime_ns}:{self.size}:{self.sha256[:16]}"

    @property
    def short_sha(self) -> str:
        return self.sha256[:12]

    def matches_stat(self, stat: tuple[int, int] | None) -> bool:
        return stat is not None and stat == (self.mtime_ns, self.size)


def read_build_stat(path: str | Path) -> tuple[int, int] | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return int(stat.st_mtime_ns), int(stat.st_size)


def read_build_source(path: str | Path) -> BuildSource:
    """Read and validate a PoB build file. Raises BuildNotFound / BuildParseFailed.

    The file is re-read if its size or mtime moved during the read (PoB saves by
    truncating and rewriting in place), up to a small bounded number of attempts.
    """
    resolved = str(Path(path).resolve())
    data = b""
    before: tuple[int, int] | None = None
    for _ in range(_STABLE_READ_ATTEMPTS):
        before = read_build_stat(resolved)
        if before is None:
            raise BuildNotFound(f"The build file no longer exists: {resolved}", {"path": resolved})
        try:
            data = Path(resolved).read_bytes()
        except OSError as exc:
            raise BuildNotFound(f"The build file could not be read: {resolved} ({exc})", {"path": resolved}) from exc
        after = read_build_stat(resolved)
        if after == before and len(data) == before[1]:
            break
    else:
        raise BuildParseFailed(
            "The build file kept changing while it was read (is Path of Building still saving?)",
            {"path": resolved},
        )
    if not data.strip():
        raise BuildParseFailed(f"The build file is empty: {resolved}", {"path": resolved})
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise BuildParseFailed(
            f"The build file is not valid XML ({exc}); it may be incomplete.", {"path": resolved}
        ) from exc
    if not root.tag.startswith("PathOfBuilding"):
        raise BuildParseFailed(
            f"The file is not a Path of Building build (root <{root.tag}>).", {"path": resolved}
        )
    assert before is not None
    return BuildSource(
        path=resolved,
        mtime_ns=before[0],
        size=before[1],
        sha256=hashlib.sha256(data).hexdigest(),
        data=data,
    )
