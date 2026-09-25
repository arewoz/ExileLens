from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from exilelens.app.updates.constants import MANIFEST_SCHEMA
from exilelens.app.updates.trust import PROD_SIGNING_KEY_ID, install_allowed_for_key, production_signing_configured, verify_key_for


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class UpdateArtifact:
    filename: str
    size: int
    sha256: str
    url: str


@dataclass(frozen=True)
class VerifiedUpdateManifest:
    channel: str
    version: str
    tag: str
    signing_key_id: str
    artifact: UpdateArtifact


def canonical_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def verify_signed_envelope(payload: object) -> VerifiedUpdateManifest:
    if not isinstance(payload, dict):
        raise ManifestError("invalid_envelope")
    manifest = payload.get("manifest")
    signature_b64 = payload.get("signature")
    if not isinstance(manifest, dict) or not isinstance(signature_b64, str):
        raise ManifestError("invalid_envelope")
    if int(manifest.get("schema") or 0) != MANIFEST_SCHEMA:
        raise ManifestError("unsupported_schema")
    signing_key_id = str(manifest.get("signing_key_id") or "").strip()
    if signing_key_id == PROD_SIGNING_KEY_ID and not production_signing_configured():
        raise ManifestError("production_signing_unavailable")
    public_key = verify_key_for(signing_key_id)
    if public_key is None:
        raise ManifestError("unknown_signing_key")
    if not install_allowed_for_key(signing_key_id):
        raise ManifestError("production_signing_unavailable")
    try:
        signature = _decode_signature(signature_b64)
    except ValueError as exc:
        raise ManifestError("invalid_signature") from exc
    message = canonical_manifest_bytes(manifest)
    if not _verify_ed25519(public_key, message, signature):
        raise ManifestError("signature_verification_failed")
    channel = str(manifest.get("channel") or "").strip().lower()
    version = str(manifest.get("version") or "").strip()
    tag = str(manifest.get("tag") or "").strip()
    artifact_raw = manifest.get("artifact")
    if not channel or not version or not tag or not isinstance(artifact_raw, dict):
        raise ManifestError("invalid_manifest_fields")
    filename = str(artifact_raw.get("filename") or "").strip()
    url = str(artifact_raw.get("url") or "").strip()
    sha256 = str(artifact_raw.get("sha256") or "").strip().lower()
    try:
        size = int(artifact_raw.get("size") or 0)
    except (TypeError, ValueError) as exc:
        raise ManifestError("invalid_artifact_size") from exc
    if not filename or not url or len(sha256) != 64 or size <= 0:
        raise ManifestError("invalid_artifact_fields")
    if not all(ch in "0123456789abcdef" for ch in sha256):
        raise ManifestError("invalid_artifact_hash")
    return VerifiedUpdateManifest(
        channel=channel,
        version=version,
        tag=tag,
        signing_key_id=signing_key_id,
        artifact=UpdateArtifact(filename=filename, size=size, sha256=sha256, url=url),
    )


def _decode_signature(value: str) -> bytes:
    import base64

    raw = base64.b64decode(value.strip(), validate=True)
    if len(raw) != 64:
        raise ValueError("bad signature length")
    return raw


def _verify_ed25519(public_key: bytes, message: bytes, signature: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    key = Ed25519PublicKey.from_public_bytes(public_key)
    try:
        key.verify(signature, message)
    except InvalidSignature:
        return False
    return True
