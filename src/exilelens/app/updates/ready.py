"""Persisted "update ready" state.

After a verified download, ``updates/ready.json`` records the *signed manifest envelope* plus the package
name, size and hash. On the next launch the record is never trusted because we wrote it: the envelope's
signature, the manifest↔version binding, the package size and its full SHA-256 are all re-verified (off
the UI thread) before the update is offered as ready again. Anything invalid is discarded.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from exilelens.app.updates.download import sha256_file
from exilelens.app.updates.manifest import (
    ManifestError,
    VerifiedUpdateManifest,
    bind_manifest_to_release,
    verify_signed_envelope,
)
from exilelens.app.updates.paths import download_cache_dir, ready_record_path
from exilelens.app.updates.version import ExileLensVersion

logger = logging.getLogger(__name__)

READY_SCHEMA = 1
MAX_READY_BYTES = 64 * 1024
_PACKAGE_NAME_RE = re.compile(r"ExileLens-v\d+\.\d+\.\d+(?:b\d+)?-win64\.zip")
_READY_KEYS = {"schema", "envelope", "tag", "version", "filename", "size", "sha256"}


@dataclass(frozen=True)
class ReadyUpdate:
    manifest: VerifiedUpdateManifest
    envelope: dict
    version: ExileLensVersion
    archive_path: Path


def write_ready_record(envelope: dict, manifest: VerifiedUpdateManifest) -> None:
    payload = {
        "schema": READY_SCHEMA,
        "envelope": envelope,
        "tag": manifest.tag,
        "version": manifest.version,
        "filename": manifest.artifact.filename,
        "size": manifest.artifact.size,
        "sha256": manifest.artifact.sha256,
    }
    path = ready_record_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def discard_ready_record(*, delete_archive: bool) -> None:
    path = ready_record_path()
    if delete_archive:
        for filename in _recorded_filenames(path):
            (download_cache_dir() / filename).unlink(missing_ok=True)
    path.unlink(missing_ok=True)


def _recorded_filenames(path: Path) -> set[str]:
    """Package names referenced by the record or its envelope — strict release names only, never paths."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    candidates = [payload.get("filename")]
    envelope = payload.get("envelope")
    if isinstance(envelope, dict) and isinstance(envelope.get("manifest"), dict):
        artifact = envelope["manifest"].get("artifact")
        if isinstance(artifact, dict):
            candidates.append(artifact.get("filename"))
    return {name for name in candidates if isinstance(name, str) and _PACKAGE_NAME_RE.fullmatch(name)}


def _verify_record(payload: object, installed: ExileLensVersion | None) -> ReadyUpdate:
    if not isinstance(payload, dict) or set(payload) != _READY_KEYS or payload.get("schema") != READY_SCHEMA:
        raise ManifestError("invalid_ready_record")
    envelope = payload["envelope"]
    manifest = verify_signed_envelope(envelope)
    version = ExileLensVersion.parse(payload["version"])
    if version is None:
        raise ManifestError("version_mismatch")
    bind_manifest_to_release(manifest, tag=str(payload["tag"]), version=version, installed=installed)
    artifact = manifest.artifact
    if (payload["filename"], payload["size"], payload["sha256"]) != (artifact.filename, artifact.size, artifact.sha256):
        raise ManifestError("ready_record_mismatch")
    archive = download_cache_dir() / artifact.filename
    try:
        if archive.stat().st_size != artifact.size:
            raise ManifestError("ready_archive_size_mismatch")
    except OSError as exc:
        raise ManifestError("ready_archive_missing") from exc
    if sha256_file(archive) != artifact.sha256:
        raise ManifestError("ready_archive_hash_mismatch")
    return ReadyUpdate(manifest=manifest, envelope=envelope, version=version, archive_path=archive)


def load_ready_update(installed: ExileLensVersion | None) -> ReadyUpdate | None:
    """Blocking (hashes the package): call from a worker thread. Invalid records are discarded."""
    path = ready_record_path()
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > MAX_READY_BYTES:
            raise ManifestError("invalid_ready_record")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _verify_record(payload, installed)
    except (ManifestError, OSError, ValueError, UnicodeError, TypeError, KeyError) as exc:
        reason = str(exc) if isinstance(exc, ManifestError) else type(exc).__name__
        logger.info("update_ready_record_discarded reason=%s", reason)
        # An installed/superseded or tampered package is never offered again.
        discard_ready_record(delete_archive=True)
        return None
