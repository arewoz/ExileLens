"""The small boundary between a build's origin and PoB's load input.

Only LOCAL_POB is implemented. A source supplies a stable logical identity, a
revision observation, and validated bytes for the existing PoB loader.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol

from exilelens.build_source import BuildSource as LocalPobSnapshot
from exilelens.build_source import read_build_source, read_build_stat


class BuildSourceKind(str, Enum):
    LOCAL_POB = "LOCAL_POB"
    API_CHARACTER = "API_CHARACTER"


@dataclass(frozen=True)
class BuildSourceRef:
    kind: BuildSourceKind
    identity: str

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.identity}"


@dataclass(frozen=True)
class BuildRevision:
    # The worker's parse-reuse token may include a content hash. The cheap
    # freshness observation can be a file stat today or an API revision later.
    token: str
    freshness_token: str


@dataclass(frozen=True)
class PobEngineInput:
    source_ref: BuildSourceRef
    revision: BuildRevision
    data: bytes
    locator: str
    local_snapshot: LocalPobSnapshot | None = None


class BuildSource(Protocol):
    @property
    def ref(self) -> BuildSourceRef: ...

    def current_revision(self) -> BuildRevision | None: ...

    def prepare_engine_input(self) -> PobEngineInput: ...


def local_input_from_snapshot(snapshot: LocalPobSnapshot) -> PobEngineInput:
    freshness = f"{snapshot.mtime_ns}:{snapshot.size}"
    return PobEngineInput(
        source_ref=BuildSourceRef(BuildSourceKind.LOCAL_POB, os.path.normcase(snapshot.path)),
        revision=BuildRevision(snapshot.revision, freshness),
        data=snapshot.data,
        locator=snapshot.path,
        local_snapshot=snapshot,
    )


@dataclass(frozen=True)
class LocalPobBuildSource:
    path: str | Path
    _resolved_path: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_resolved_path", str(Path(self.path).resolve()))

    @property
    def resolved_path(self) -> str:
        return self._resolved_path

    @property
    def ref(self) -> BuildSourceRef:
        return BuildSourceRef(BuildSourceKind.LOCAL_POB, os.path.normcase(self.resolved_path))

    def current_revision(self) -> BuildRevision | None:
        stat = read_build_stat(self.resolved_path)
        if stat is None:
            return None
        freshness = f"{stat[0]}:{stat[1]}"
        return BuildRevision(freshness, freshness)

    def prepare_engine_input(self) -> PobEngineInput:
        return local_input_from_snapshot(read_build_source(self.resolved_path))
