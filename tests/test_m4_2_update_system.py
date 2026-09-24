"""Focused offline coverage for the M4.2 secure update pipeline."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from exilelens.app import update_check
from exilelens.app.settings import AppSettings
from exilelens.app.updates.archive import UnsafeArchiveError, extract_zip_to_staging, validate_zip_archive
from exilelens.app.updates.channels import UpdateChannel, release_matches_channel
from exilelens.app.updates.download import DownloadManager, DownloadError
from exilelens.app.updates.manifest import ManifestError, canonical_manifest_bytes, verify_signed_envelope
from exilelens.app.updates.trust import TEST_SIGNING_KEY_ID
from exilelens.app.updates.version import ExileLensVersion, Release, parse_release_payload
from exilelens.app.updates import service as update_service_module
from exilelens.updater import install as updater_install

pytestmark = pytest.mark.smoke


def _sign_manifest(manifest: dict, private_key_path: Path) -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64

    key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
    assert isinstance(key, Ed25519PrivateKey)
    signature = key.sign(canonical_manifest_bytes(manifest))
    return {"manifest": manifest, "signature": base64.b64encode(signature).decode("ascii")}


@pytest.fixture
def test_private_key() -> Path:
    path = Path(__file__).resolve().parents[1] / "fixtures/update_signing/test_signing_key.pem"
    assert path.is_file()
    return path


def test_channel_filters_prerelease_final_versions() -> None:
    beta = Release(
        ExileLensVersion.parse("0.4.0b2"),
        update_check.GITHUB_RELEASES_URL,
        "v0.4.0b2",
        True,
    )
    stable = Release(
        ExileLensVersion.parse("0.4.0"),
        update_check.GITHUB_RELEASES_URL,
        "v0.4.0",
        False,
    )
    assert release_matches_channel(beta, UpdateChannel.BETA)
    assert not release_matches_channel(beta, UpdateChannel.STABLE)
    assert release_matches_channel(stable, UpdateChannel.STABLE)


def test_parse_release_collects_manifest_and_zip_assets() -> None:
    payload = {
        "tag_name": "v0.4.0b2",
        "draft": False,
        "prerelease": True,
        "assets": [
            {"name": "ExileLens-v0.4.0b2-win64.update.json", "browser_download_url": "https://example.test/manifest"},
            {"name": "ExileLens-v0.4.0b2-win64.zip", "browser_download_url": "https://example.test/zip"},
        ],
    }
    release = parse_release_payload(payload)
    assert release is not None
    assert release.manifest_asset_url == "https://example.test/manifest"
    assert release.zip_asset_url == "https://example.test/zip"


def test_signed_manifest_roundtrip(test_private_key: Path) -> None:
    manifest = {
        "schema": 1,
        "channel": "beta",
        "version": "0.4.0b2",
        "tag": "v0.4.0b2",
        "signing_key_id": TEST_SIGNING_KEY_ID,
        "artifact": {
            "filename": "ExileLens-v0.4.0b2-win64.zip",
            "size": 4,
            "sha256": "0" * 63 + "1",
            "url": "https://example.test/zip",
        },
    }
    envelope = _sign_manifest(manifest, test_private_key)
    verified = verify_signed_envelope(envelope)
    assert verified.version == "0.4.0b2"


def test_bad_signature_is_rejected(test_private_key: Path) -> None:
    manifest = {
        "schema": 1,
        "channel": "beta",
        "version": "0.4.0b2",
        "tag": "v0.4.0b2",
        "signing_key_id": TEST_SIGNING_KEY_ID,
        "artifact": {
            "filename": "ExileLens-v0.4.0b2-win64.zip",
            "size": 4,
            "sha256": "0" * 63 + "1",
            "url": "https://example.test/zip",
        },
    }
    envelope = _sign_manifest(manifest, test_private_key)
    envelope["signature"] = "AAAA" + envelope["signature"][4:]
    with pytest.raises(ManifestError, match="signature_verification_failed"):
        verify_signed_envelope(envelope)


def test_prod_manifest_blocked_until_public_key_provisioned(test_private_key: Path) -> None:
    manifest = {
        "schema": 1,
        "channel": "stable",
        "version": "0.4.0",
        "tag": "v0.4.0",
        "signing_key_id": "exilelens-prod-1",
        "artifact": {
            "filename": "ExileLens-v0.4.0-win64.zip",
            "size": 4,
            "sha256": "0" * 63 + "1",
            "url": "https://example.test/zip",
        },
    }
    envelope = _sign_manifest(manifest, test_private_key)
    with pytest.raises(ManifestError, match="production_signing_unavailable"):
        verify_signed_envelope(envelope)


def test_zip_path_traversal_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(UnsafeArchiveError):
        validate_zip_archive(archive)


def test_download_verifies_size_and_hash(tmp_path: Path) -> None:
    body = b"test-payload"
    import hashlib

    digest = hashlib.sha256(body).hexdigest()

    class _Response:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def read(self, size: int) -> bytes:
            if not self._data:
                return b""
            chunk, self._data = self._data[:size], self._data[size:]
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    def opener(request, timeout):
        return _Response(body)

    destination = tmp_path / "pkg.zip"
    result = DownloadManager(opener).download(
        url="https://example.test/pkg.zip",
        destination=destination,
        expected_size=len(body),
        expected_sha256=digest,
    )
    assert result.path == destination
    with pytest.raises(DownloadError, match="hash_mismatch"):
        DownloadManager(opener).download(
            url="https://example.test/pkg.zip",
            destination=tmp_path / "bad.zip",
            expected_size=len(body),
            expected_sha256="0" * 64,
        )


def test_updater_install_and_restore_backup(tmp_path: Path) -> None:
    install_root = tmp_path / "install"
    install_root.mkdir()
    (install_root / "ExileLens.exe").write_bytes(b"old")
    staged = tmp_path / "stage" / "ExileLens"
    staged.mkdir(parents=True)
    (staged / "ExileLens.exe").write_bytes(b"new")
    backup = tmp_path / "backup"
    updater_install.install_verified_update(install_root=install_root, staged_root=staged, backup_root=backup)
    assert (install_root / "ExileLens.exe").read_bytes() == b"new"
    updater_install.restore_backup(install_root=install_root, backup_root=backup)
    assert (install_root / "ExileLens.exe").read_bytes() == b"old"


def test_update_service_emits_available_with_prerelease(monkeypatch) -> None:
    from exilelens.app import update_check

    service = update_check.UpdateService(AppSettings())
    monkeypatch.setattr(update_service_module, "save_settings", lambda _settings: None)
    monkeypatch.setattr(update_service_module, "is_packaged", lambda: True)
    states = []
    service.state_changed.connect(lambda state, value: states.append((state, value)))
    newer = ExileLensVersion.parse("9.9.9b1")
    release = Release(newer, update_check.GITHUB_RELEASES_URL, "v9.9.9b1", True)
    service._finish_check(release, manual=True)
    assert states[-1][0] == "available"


def test_e2e_staged_zip_install(tmp_path: Path, test_private_key: Path) -> None:
    install_root = tmp_path / "install"
    install_root.mkdir()
    (install_root / "ExileLens.exe").write_text("old", encoding="utf-8")
    archive = tmp_path / "ExileLens-v9.9.9b9-win64.zip"
    staged_payload_root = tmp_path / "payload" / "ExileLens"
    staged_payload_root.mkdir(parents=True)
    (staged_payload_root / "ExileLens.exe").write_text("new", encoding="utf-8")
    with zipfile.ZipFile(archive, "w") as zf:
        for path in staged_payload_root.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=str(Path("ExileLens") / path.relative_to(staged_payload_root)))
    extracted = extract_zip_to_staging(archive, tmp_path / "staging")
    backup = tmp_path / "backup"
    updater_install.install_verified_update(install_root=install_root, staged_root=extracted, backup_root=backup)
    assert (install_root / "ExileLens.exe").read_text(encoding="utf-8") == "new"
