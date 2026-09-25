"""POB-REL-01 regression: PoB import and load reliability at the Engine boundary.

Covers the critical import scenarios with a deterministic stub worker session --
no Qt, no real PoB install, no subprocess:

- valid build loads and tracks source identity / revision / generation,
- invalid or corrupted input raises *before* the worker is touched and leaves
  no stale loaded state behind,
- a worker-level parse failure during an active session clears the loaded
  state (never presented as newly loaded),
- retry after a failed import recovers with the next generation,
- repeated import of the same bytes reuses the parse (no new generation),
- loading another build invalidates the per-build component caches,
- ``ensure_source_ready`` skips reloads while the file is unchanged and
  reloads after a save,
- a failed worker start leaves no half-open session,
- a missing/incompatible PoB folder is rejected with a typed error.

Real-PoB load/recovery behavior itself is covered by the integration suites
(``test_public_real_pob.py``, ``test_public_build_corpus.py``); the controller
keep-last-good path needs Qt and is intentionally out of scope here -- see
``docs/POB_IMPORT_LOAD_RELIABILITY.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from exilelens.build_sources import LocalPobBuildSource
from exilelens.config import PobConfig, validate_pob_path
from exilelens.engine import Engine, SubprocessWorkerClient
from exilelens.errors import BuildNotFound, BuildParseFailed, PobPathInvalid, WorkerUnhealthy

pytestmark = pytest.mark.itemcheck

_VALID_XML = b'<?xml version="1.0"?>\n<PathOfBuilding><Build level="1"/></PathOfBuilding>\n'


class _StubSession:
    """Deterministic stand-in for the PoB worker (subprocess branch).

    Emulates the bridge's revision-gated reuse: a ``load_build`` carrying the
    same revision token as the last load for that locator answers
    ``reloaded=False``; anything else re-parses. ``fail_load_paths`` maps a
    locator to an error the worker raises instead (e.g. a Lua-side parse
    failure that already passed Python-side validation).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_load_paths: dict[str, Exception] = {}
        self._loaded: dict[str, Any] = {}

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        params = dict(params or {})
        self.calls.append((method, params))
        if method == "load_build":
            locator = params.get("path")
            error = self.fail_load_paths.get(locator)
            if error is not None:
                # Mirror the bridge: a failed parse unloads the worker
                # globally (single-build STATE), so the next load must
                # re-parse even for already-seen bytes.
                self._loaded.clear()
                raise error
            revision = params.get("revision")
            if revision is not None and self._loaded.get(locator) == revision:
                return {"build": {"name": "stub"}, "reloaded": False, "revision": revision}
            self._loaded[locator] = revision
            return {"build": {"name": "stub"}, "reloaded": True, "revision": revision}
        if method == "get_build_info":
            return {"build": {"name": "stub"}}
        raise AssertionError(f"unexpected stub method {method!r}")

    def shutdown(self) -> None:
        return None

    def load_calls(self) -> list[dict[str, Any]]:
        return [params for method, params in self.calls if method == "load_build"]


def _engine(tmp_path: Path, stub: _StubSession) -> Engine:
    engine = Engine(PobConfig(pob_path=tmp_path))
    engine._session = stub  # type: ignore[attr-defined]
    return engine


def _write(path: Path, data: bytes) -> str:
    path.write_bytes(data)
    return str(path)


def test_valid_build_load_tracks_source_revision_and_generation(tmp_path: Path) -> None:
    stub = _StubSession()
    engine = _engine(tmp_path, stub)
    build = _write(tmp_path / "build.xml", _VALID_XML)

    result = engine.load_build(build)

    assert result["reloaded"] is True
    assert engine.loaded_source is not None
    assert engine.loaded_source.path == str(Path(build).resolve())
    assert engine.loaded_source_ref is not None
    assert engine.loaded_source_ref.key.startswith("LOCAL_POB:")
    assert engine.loaded_revision is not None
    assert engine.loaded_revision.token
    assert engine.source_generation == 1
    assert engine.reload_count == 1
    assert engine.last_load_reloaded is True
    # The exact validated bytes (with revision) reach the worker.
    assert len(stub.load_calls()) == 1
    assert stub.load_calls()[0]["revision"] == engine.loaded_revision.token


@pytest.mark.parametrize(
    ("name", "data", "error"),
    [
        ("missing.xml", None, BuildNotFound),
        ("empty.xml", b"", BuildParseFailed),
        ("whitespace.xml", b"  \n ", BuildParseFailed),
        ("garbage.xml", b"this is not xml at all {{{", BuildParseFailed),
        ("wrong-root.xml", b"<NotAPoBBuild/>", BuildParseFailed),
    ],
)
def test_corrupted_input_raises_before_worker_is_touched(
    tmp_path: Path, name: str, data: bytes | None, error: type[Exception]
) -> None:
    stub = _StubSession()
    engine = _engine(tmp_path, stub)
    path = str(tmp_path / name)
    if data is not None:
        _write(tmp_path / name, data)

    with pytest.raises(error):
        engine.load_build(path)

    # The worker was never contacted, and nothing claims a build is loaded.
    assert stub.calls == []
    assert engine.loaded_source is None
    assert engine.loaded_source_ref is None
    assert engine.loaded_revision is None
    assert engine.source_generation == 0
    assert engine.reload_count == 0


def test_worker_parse_failure_during_active_session_clears_loaded_state(tmp_path: Path) -> None:
    stub = _StubSession()
    engine = _engine(tmp_path, stub)
    build = _write(tmp_path / "build.xml", _VALID_XML)
    engine.load_build(build)
    assert engine.source_generation == 1

    # The file still validates: the failure happens inside the worker (e.g. PoB
    # rejects content Python cannot judge). Engine state must not survive it.
    stub.fail_load_paths[str(Path(build).resolve())] = BuildParseFailed("worker rejected build")
    with pytest.raises(BuildParseFailed):
        engine.load_build(build)

    assert engine.loaded_source is None
    assert engine.loaded_source_ref is None
    assert engine.loaded_revision is None
    # The failed attempt is not a generation: nothing new was established.
    assert engine.source_generation == 1


def test_retry_after_failed_import_recovers_with_next_generation(tmp_path: Path) -> None:
    stub = _StubSession()
    engine = _engine(tmp_path, stub)
    good = _write(tmp_path / "good.xml", _VALID_XML)
    bad = _write(tmp_path / "bad.xml", _VALID_XML)
    stub.fail_load_paths[str(Path(bad).resolve())] = BuildParseFailed("worker rejected build")

    engine.load_build(good)
    with pytest.raises(BuildParseFailed):
        engine.load_build(bad)

    result = engine.load_build(good)
    assert result["reloaded"] is True
    assert engine.loaded_source is not None
    assert engine.loaded_source.path == str(Path(good).resolve())
    assert engine.source_generation == 2
    assert engine.last_load_reloaded is True


def test_repeated_import_of_same_build_reuses_parse_without_new_generation(tmp_path: Path) -> None:
    stub = _StubSession()
    engine = _engine(tmp_path, stub)
    build = _write(tmp_path / "build.xml", _VALID_XML)

    first = engine.load_build(build)
    second = engine.load_build(build)

    assert first["reloaded"] is True
    assert second["reloaded"] is False
    assert engine.last_load_reloaded is False
    assert engine.source_generation == 1
    assert engine.reload_count == 1
    assert len(stub.load_calls()) == 2
    # Same revision token offered both times: reuse is by exact bytes, not path.
    assert stub.load_calls()[0]["revision"] == stub.load_calls()[1]["revision"]


def test_loading_another_build_invalidates_component_caches(tmp_path: Path) -> None:
    stub = _StubSession()
    engine = _engine(tmp_path, stub)
    engine._native_component_report_cache = {"stale": object()}  # type: ignore[attr-defined]
    engine._actor_ailment_offense_coverage_cache = {"stale": object()}  # type: ignore[attr-defined]
    first = _write(tmp_path / "first.xml", _VALID_XML)
    second = _write(tmp_path / "second.xml", _VALID_XML + b"<!-- different -->\n")

    engine.load_build(first)
    engine._native_component_report_cache["marker"] = object()  # type: ignore[attr-defined]
    engine._actor_ailment_offense_coverage_cache["marker"] = object()  # type: ignore[attr-defined]
    engine.load_build(second)

    assert engine.loaded_source is not None
    assert engine.loaded_source.path == str(Path(second).resolve())
    assert engine.source_generation == 2
    assert engine._native_component_report_cache == {}  # type: ignore[attr-defined]
    assert engine._actor_ailment_offense_coverage_cache == {}  # type: ignore[attr-defined]


def test_ensure_source_ready_skips_reload_until_save(tmp_path: Path) -> None:
    stub = _StubSession()
    engine = _engine(tmp_path, stub)
    build = _write(tmp_path / "build.xml", _VALID_XML)
    source = LocalPobBuildSource(build)

    engine.ensure_source_ready(source)
    assert engine.last_load_reloaded is True
    assert len(stub.load_calls()) == 1

    engine.ensure_source_ready(source)
    assert engine.last_load_reloaded is False
    assert len(stub.load_calls()) == 1
    assert engine.source_generation == 1

    with open(build, "ab") as stream:
        stream.write(b"<!-- saved from PoB -->\n")
    engine.ensure_source_ready(source)
    assert engine.last_load_reloaded is True
    assert len(stub.load_calls()) == 2
    assert engine.source_generation == 2


def test_failed_worker_start_leaves_no_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(self: SubprocessWorkerClient) -> None:
        raise WorkerUnhealthy("boot failed", {"method": "ping"})

    monkeypatch.setattr(SubprocessWorkerClient, "start", _boom)
    engine = Engine(PobConfig(pob_path=tmp_path), use_subprocess=True)
    with pytest.raises(WorkerUnhealthy):
        engine.start()
    assert engine._session is None  # type: ignore[attr-defined]


def test_missing_pob_installation_is_rejected_with_typed_error(tmp_path: Path) -> None:
    with pytest.raises(PobPathInvalid) as excinfo:
        validate_pob_path(PobConfig(pob_path=tmp_path / "does-not-exist"))
    assert excinfo.value.code == "POB_PATH_INVALID"


def test_pob_like_folder_missing_runtime_reports_precisely(tmp_path: Path) -> None:
    # A folder that looks like PoB (Data/Modules present) but lacks runtime
    # files gets the specific message, not the generic chooser text.
    (tmp_path / "Data").mkdir()
    (tmp_path / "Modules").mkdir()
    with pytest.raises(PobPathInvalid) as excinfo:
        validate_pob_path(PobConfig(pob_path=tmp_path))
    assert excinfo.value.code == "POB_PATH_INVALID"
    assert "looks like a Path of Building installation" in excinfo.value.message
