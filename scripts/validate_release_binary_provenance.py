"""Validate PyInstaller native-binary origins and write a release manifest.

The COLLECT TOC is produced by PyInstaller during the same clean build.  It is
the authoritative mapping between every collected native file and its source.
This deliberately rejects files discovered through an arbitrary host PATH.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

NATIVE_SUFFIXES = {".exe", ".dll", ".pyd"}
NATIVE_TYPES = {"BINARY", "EXTENSION", "EXECUTABLE"}


def _resolve(path: str | Path) -> Path:
    return Path(path).resolve(strict=False)


def _is_beneath(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _read_toc(path: Path) -> list[tuple[str, str, str]]:
    try:
        data = ast.literal_eval(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as exc:
        raise ValueError(f"Cannot read PyInstaller COLLECT TOC {path}: {exc}") from exc
    # PyInstaller 6 writes ``([entries],)`` for COLLECT, while some versions
    # serialize the entries list directly.
    if isinstance(data, tuple) and len(data) == 1 and isinstance(data[0], list):
        data = data[0]
    if not isinstance(data, list):
        raise ValueError(f"PyInstaller COLLECT TOC {path} is not a list")
    rows: list[tuple[str, str, str]] = []
    for entry in data:
        if not isinstance(entry, tuple) or len(entry) != 3:
            continue
        packaged, source, kind = entry
        if isinstance(packaged, str) and isinstance(source, str) and isinstance(kind, str):
            rows.append((packaged, source, kind))
    return rows


def _sha256(path: Path) -> str:
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


def validate_and_write_manifest(args: argparse.Namespace) -> dict[str, object]:
    repo_root = _resolve(args.repo_root)
    venv_root = _resolve(args.venv_root)
    build_root = _resolve(args.build_root)
    dist_root = _resolve(args.dist_root)
    toc_path = _resolve(args.collect_toc)
    manifest_path = _resolve(args.manifest)
    system_roots = [_resolve(path) for path in args.system_root]
    explicit_roots = [_resolve(path) for path in args.approved_root]
    approved_roots = [repo_root, venv_root, build_root, *system_roots, *explicit_roots]

    sources: dict[str, Path] = {}
    for packaged, source, kind in _read_toc(toc_path):
        if kind not in NATIVE_TYPES and Path(packaged).suffix.lower() not in NATIVE_SUFFIXES:
            continue
        sources[packaged.replace("/", "\\").lower()] = _resolve(source)

    binaries: list[dict[str, object]] = []
    failures: list[str] = []
    for packaged_file in sorted(path for path in dist_root.rglob("*") if path.is_file() and path.suffix.lower() in NATIVE_SUFFIXES):
        relative = packaged_file.relative_to(dist_root)
        toc_relative = relative
        if relative.parts and relative.parts[0].lower() == "_internal":
            toc_relative = Path(*relative.parts[1:])
        key = str(toc_relative).replace("/", "\\").lower()
        source = sources.get(key)
        if source is None:
            failures.append(f"{relative}: no source entry in {toc_path}")
            continue
        if not any(_is_beneath(source, root) for root in approved_roots):
            allowed = "; ".join(str(root) for root in approved_roots)
            failures.append(
                f"{relative}: source {source} is outside approved origins ({allowed})"
            )
            continue
        binaries.append(
            {
                "relative_path": relative.as_posix(),
                "sha256": _sha256(packaged_file),
                "size": packaged_file.stat().st_size,
                "origin_path": str(source),
            }
        )

    if failures:
        raise ValueError("Release binary provenance validation failed:\n  " + "\n  ".join(failures))

    payload: dict[str, object] = {
        "schema_version": 1,
        "product": "ExileLens",
        "git_commit": args.git_commit,
        "application_version": args.application_version,
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "pyinstaller_version": _metadata_version("PyInstaller"),
        "pyside6_version": _metadata_version("PySide6"),
        "build_timestamp_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "binaries": binaries,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--venv-root", required=True)
    parser.add_argument("--build-root", required=True)
    parser.add_argument("--dist-root", required=True)
    parser.add_argument("--collect-toc", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--application-version", required=True)
    parser.add_argument("--system-root", action="append", default=[])
    parser.add_argument("--approved-root", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    try:
        payload = validate_and_write_manifest(parse_args())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Validated {len(payload['binaries'])} native binaries; manifest: generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
