"""Release binary provenance: validate PyInstaller native-binary origins and write ``binary_manifest.json``.

The COLLECT TOC is produced by PyInstaller during the same clean build. It is the authoritative mapping between every collected
native file and its source; files discovered through an arbitrary host PATH are rejected.

Schema 2 (1.0-C):

* ``executables``: BOTH shipped executables (``ExileLens.exe`` and ``ExileLensUpdater.exe``) with hash, size and their build inputs.
* ``binaries``: every native file in the package with hash, size and an ORIGIN that is ``<root kind>/<path relative to that root>``.
  No absolute path (and so no developer user name) is ever written to the shipped manifest.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
import platform
import sys
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 2
NATIVE_SUFFIXES = {".exe", ".dll", ".pyd"}
NATIVE_TYPES = {"BINARY", "EXTENSION", "EXECUTABLE"}
GUI_EXE = "ExileLens.exe"
UPDATER_REL = "_internal/ExileLensUpdater.exe"

#: Build inputs recorded per executable: (label, repo-relative path).
_INPUTS = {
    "gui": {
        "spec": "packaging/exilelens-gui.spec",
        "version_resource": "packaging/version_info.txt",
        "icon": "assets/app/exilelens.ico",
        "entry_point": "src/exilelens/app/main.py",
    },
    "updater": {
        "spec": "packaging/exilelens-updater.spec",
        "version_resource": "packaging/version_info_updater.txt",
        "icon": "assets/app/exilelens.ico",
        "entry_point": "src/exilelens/updater/__main__.py",
    },
}


def _resolve(path: str | Path) -> Path:
    return Path(path).resolve(strict=False)


def _is_beneath(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def read_toc(path: Path) -> list[tuple[str, str, str]]:
    try:
        data = ast.literal_eval(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as exc:
        raise ValueError(f"Cannot read PyInstaller COLLECT TOC {path.name}: {exc}") from exc
    # PyInstaller 6 writes ``([entries],)`` for COLLECT, while some versions serialize the entries list directly.
    if isinstance(data, tuple) and len(data) == 1 and isinstance(data[0], list):
        data = data[0]
    if not isinstance(data, list):
        raise ValueError(f"PyInstaller COLLECT TOC {path.name} is not a list")
    rows: list[tuple[str, str, str]] = []
    for entry in data:
        if not isinstance(entry, tuple) or len(entry) != 3:
            continue
        packaged, source, kind = entry
        if isinstance(packaged, str) and isinstance(source, str) and isinstance(kind, str):
            rows.append((packaged, source, kind))
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def origin_label(source: Path, roots: list[tuple[str, Path]]) -> str | None:
    """``kind/relative/path`` for the first approved root that contains ``source`` (most specific root first), else None."""
    for kind, root in roots:
        if _is_beneath(source, root):
            return f"{kind}/{source.relative_to(root).as_posix()}"
    return None


def _executable_record(role: str, relative: str, dist_root: Path, repo_root: Path) -> dict[str, object]:
    path = dist_root / relative
    inputs = _INPUTS[role]
    record: dict[str, object] = {
        "role": role,
        "relative_path": relative,
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
        "inputs": {},
    }
    recorded: dict[str, dict[str, str]] = {}
    for label, rel in inputs.items():
        source = repo_root / rel
        recorded[label] = {"path": rel, "sha256": sha256_file(source) if source.is_file() else "missing"}
    record["inputs"] = recorded
    return record


def validate_and_write_manifest(args: Namespace) -> dict[str, object]:
    repo_root = _resolve(args.repo_root)
    venv_root = _resolve(args.venv_root)
    build_root = _resolve(args.build_root)
    dist_root = _resolve(args.dist_root)
    toc_path = _resolve(args.collect_toc)
    manifest_path = _resolve(args.manifest)
    system_roots = [_resolve(path) for path in args.system_root]
    explicit_roots = [_resolve(path) for path in args.approved_root]
    # Most specific first: the release venv and build tree normally sit INSIDE the repo checkout.
    labelled: list[tuple[str, Path]] = [("release-venv", venv_root), ("build", build_root)]
    labelled += [("python-runtime", root) for root in explicit_roots]
    labelled += [("windows" if index else "windows-system32", root) for index, root in enumerate(system_roots)]
    labelled.append(("repo", repo_root))

    sources: dict[str, Path] = {}
    for packaged, source, kind in read_toc(toc_path):
        if kind not in NATIVE_TYPES and Path(packaged).suffix.lower() not in NATIVE_SUFFIXES:
            continue
        sources[packaged.replace("/", "\\").lower()] = _resolve(source)

    updater_built = _resolve(args.updater_built) if getattr(args, "updater_built", None) else None
    updater_staged = dist_root / UPDATER_REL
    binaries: list[dict[str, object]] = []
    failures: list[str] = []
    for packaged_file in sorted(path for path in dist_root.rglob("*") if path.is_file() and path.suffix.lower() in NATIVE_SUFFIXES):
        relative = packaged_file.relative_to(dist_root)
        if relative.as_posix() == UPDATER_REL:
            # The updater is built once, outside the GUI COLLECT. The shipped copy must be byte-identical to that build.
            if updater_built is None or not updater_built.is_file():
                failures.append(f"{relative}: the single updater build output was not supplied")
            elif sha256_file(updater_built) != sha256_file(packaged_file):
                failures.append(f"{relative}: differs from the updater build output (it must be built exactly once and copied)")
            else:
                binaries.append({
                    "relative_path": relative.as_posix(),
                    "sha256": sha256_file(packaged_file),
                    "size": packaged_file.stat().st_size,
                    "origin": "build/updater (packaging/exilelens-updater.spec)",
                })
            continue
        toc_relative = relative
        if relative.parts and relative.parts[0].lower() == "_internal":
            toc_relative = Path(*relative.parts[1:])
        key = str(toc_relative).replace("/", "\\").lower()
        source = sources.get(key)
        if source is None:
            failures.append(f"{relative}: no source entry in the COLLECT TOC")
            continue
        label = origin_label(source, labelled)
        if label is None:
            failures.append(f"{relative}: source is outside the approved origins")
            continue
        binaries.append({
            "relative_path": relative.as_posix(),
            "sha256": sha256_file(packaged_file),
            "size": packaged_file.stat().st_size,
            "origin": label,
        })
    for required in (GUI_EXE, UPDATER_REL):
        if not (dist_root / required).is_file():
            failures.append(f"{required}: not present in the distribution")
    if failures:
        raise ValueError("Release binary provenance validation failed:\n  " + "\n  ".join(failures))

    lock = repo_root / "packaging" / "requirements-release.lock"
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "product": "ExileLens",
        "git_commit": args.git_commit,
        "application_version": args.application_version,
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "pyinstaller_version": _metadata_version("PyInstaller"),
        "pyside6_version": _metadata_version("PySide6"),
        "architecture": platform.machine() or "unknown",
        "release_lock_sha256": sha256_file(lock) if lock.is_file() else "missing",
        "build_timestamp_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "executables": [
            _executable_record("gui", GUI_EXE, dist_root, repo_root),
            _executable_record("updater", UPDATER_REL, dist_root, repo_root),
        ],
        "binaries": binaries,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload
