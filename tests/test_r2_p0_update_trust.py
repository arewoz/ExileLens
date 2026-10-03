"""R2-P0: update trust profiles, manifest↔release binding, downloader and archive hardening."""

from __future__ import annotations

import base64
import hashlib
import sys
import urllib.error
import zipfile
from pathlib import Path

import pytest

from exilelens.app.updates import trust
from exilelens.app.updates.archive import (
    MAX_ARCHIVE_ENTRIES,
    UnsafeArchiveError,
    validate_zip_archive,
)
from exilelens.app.updates.download import DownloadError, DownloadManager
from exilelens.app.updates.manifest import (
    ManifestError,
    bind_manifest_to_release,
    canonical_manifest_bytes,
    verify_signed_envelope,
)
from exilelens.app.updates.version import ExileLensVersion

pytestmark = pytest.mark.smoke

ROOT = Path(__file__).resolve().parents[1]
TEST_KEY = ROOT / "fixtures" / "update_signing" / "test_signing_key.pem"


def _manifest(version: str = "0.7.0", *, key_id: str = trust.TEST_SIGNING_KEY_ID, **overrides) -> dict:
    tag = overrides.pop("tag", f"v{version}")
    filename = overrides.pop("filename", f"ExileLens-{tag}-win64.zip")
    url = overrides.pop("url", f"https://github.com/arewoz/ExileLens/releases/download/{tag}/{filename}")
    manifest = {
        "schema": 1,
        "channel": "stable",
        "version": version,
        "tag": tag,
        "signing_key_id": key_id,
        "artifact": {"filename": filename, "size": 4, "sha256": "ab" * 32, "url": url},
    }
    manifest.update(overrides)
    return manifest


def _sign(manifest: dict) -> dict:
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(TEST_KEY.read_bytes(), password=None)
    signature = key.sign(canonical_manifest_bytes(manifest))
    return {"manifest": manifest, "signature": base64.b64encode(signature).decode("ascii")}


# ----------------------------------------------------------------------------- trust profiles


def test_release_build_rejects_test_signed_manifest(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    envelope = _sign(_manifest())
    # Even an explicit test-profile request is ignored by a frozen (shipping) build.
    monkeypatch.setenv(trust.TRUST_PROFILE_ENV, "test")
    with trust.use_test_trust_profile():
        assert trust.active_trust_profile() == trust.PRODUCTION_PROFILE
        assert sorted(trust.trusted_update_keys()) == [trust.PROD_SIGNING_KEY_ID]
        with pytest.raises(ManifestError, match="unknown_signing_key"):
            verify_signed_envelope(envelope)


def test_source_default_profile_is_production(monkeypatch) -> None:
    monkeypatch.delenv(trust.TRUST_PROFILE_ENV, raising=False)
    assert trust.active_trust_profile(frozen=False) == trust.PRODUCTION_PROFILE
    with pytest.raises(ManifestError, match="unknown_signing_key"):
        verify_signed_envelope(_sign(_manifest()))


def test_test_profile_supports_deterministic_test_signing(monkeypatch) -> None:
    with trust.use_test_trust_profile():
        assert verify_signed_envelope(_sign(_manifest())).signing_key_id == trust.TEST_SIGNING_KEY_ID
    monkeypatch.setenv(trust.TRUST_PROFILE_ENV, "test")
    assert verify_signed_envelope(_sign(_manifest())).version == "0.7.0"


def test_trust_report_is_secret_free_and_shipping_set_is_production_only() -> None:
    report = trust.trust_report(frozen=True)
    assert report == {"schema": 1, "frozen": True, "profile": "production", "key_ids": ["exilelens-prod-1"]}
    assert not set(trust.PRODUCTION_VERIFY_KEYS) & set(trust.TEST_VERIFY_KEYS)
    assert "BEGIN" not in str(report)


def test_release_gate_blocks_if_test_key_enters_shipping_set(monkeypatch) -> None:
    from exilelens.ops import release_gate

    assert release_gate._update_trust_set(ROOT).status.value == "PASS"
    monkeypatch.setattr(trust, "PRODUCTION_VERIFY_KEYS", {**trust.PRODUCTION_VERIFY_KEYS, **trust.TEST_VERIFY_KEYS})
    assert release_gate._update_trust_set(ROOT).status.value == "BLOCKED"


def test_published_v060_manifest_shape_binds_under_production_rules() -> None:
    from exilelens.app.updates.manifest import VerifiedUpdateManifest, UpdateArtifact

    url = "https://github.com/arewoz/ExileLens/releases/download/v0.6.0/ExileLens-v0.6.0-win64.zip"
    manifest = VerifiedUpdateManifest(
        "stable", "0.6.0", "v0.6.0", trust.PROD_SIGNING_KEY_ID,
        UpdateArtifact("ExileLens-v0.6.0-win64.zip", 69927974, "9e" * 32, url),
    )
    bound = bind_manifest_to_release(
        manifest, tag="v0.6.0", version=ExileLensVersion.parse("0.6.0"),
        installed=ExileLensVersion.parse("0.5.0b1"), release_zip_name="ExileLens-v0.6.0-win64.zip",
    )
    assert str(bound) == "0.6.0"


# ----------------------------------------------------------------------------- manifest ↔ release binding


def _verified(**overrides):
    with trust.use_test_trust_profile():
        return verify_signed_envelope(_sign(_manifest(**overrides)))


def _bind(manifest, *, tag="v0.7.0", version="0.7.0", installed="0.6.0", zip_name="ExileLens-v0.7.0-win64.zip"):
    return bind_manifest_to_release(
        manifest,
        tag=tag,
        version=ExileLensVersion.parse(version),
        installed=ExileLensVersion.parse(installed) if installed else None,
        release_zip_name=zip_name,
    )


def test_binding_accepts_matching_release() -> None:
    assert str(_bind(_verified())) == "0.7.0"


def test_binding_rejects_tag_mismatch() -> None:
    with pytest.raises(ManifestError, match="tag_mismatch"):
        _bind(_verified(), tag="v0.8.0", version="0.8.0")


def test_binding_rejects_valid_old_manifest_attached_to_newer_looking_release() -> None:
    old = _verified(version="0.6.5")
    with pytest.raises(ManifestError, match="tag_mismatch"):
        _bind(old, tag="v9.0.0", version="9.0.0", zip_name="ExileLens-v0.6.5-win64.zip")


def test_binding_rejects_version_mismatch_inside_signed_manifest() -> None:
    inconsistent = _verified(version="0.7.0", tag="v0.7.1", filename="ExileLens-v0.7.1-win64.zip")
    with pytest.raises(ManifestError, match="tag_mismatch"):
        _bind(inconsistent, tag="v0.7.1", version="0.7.1")
    with pytest.raises(ManifestError, match="version_mismatch"):
        _bind(_verified(), tag="v0.7.0", version="0.7.1")


@pytest.mark.parametrize("installed", ["0.7.0", "0.8.0"])
def test_binding_rejects_downgrade_and_same_version_reinstall(installed: str) -> None:
    with pytest.raises(ManifestError, match="not_newer"):
        _bind(_verified(), installed=installed)


def test_binding_rejects_artifact_filename_mismatch() -> None:
    renamed = _verified(
        filename="ExileLens-v0.7.0-win64-evil.zip",
        url="https://github.com/arewoz/ExileLens/releases/download/v0.7.0/ExileLens-v0.7.0-win64-evil.zip",
    )
    with pytest.raises(ManifestError, match="artifact_name_mismatch"):
        _bind(renamed)
    with pytest.raises(ManifestError, match="artifact_name_mismatch"):
        _bind(_verified(), zip_name="ExileLens-v0.7.0-win64 (1).zip")


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/evil/ExileLens/releases/download/v0.7.0/ExileLens-v0.7.0-win64.zip",
        "https://example.test/ExileLens-v0.7.0-win64.zip",
        "http://github.com/arewoz/ExileLens/releases/download/v0.7.0/ExileLens-v0.7.0-win64.zip",
        "https://github.com/arewoz/ExileLens/releases/download/v0.6.0/ExileLens-v0.7.0-win64.zip",
    ],
)
def test_binding_rejects_artifact_url_outside_official_release(url: str) -> None:
    with pytest.raises(ManifestError, match="artifact_url_mismatch"):
        _bind(_verified(url=url))


# ----------------------------------------------------------------------------- downloader


class _Response:
    def __init__(self, data: bytes, *, status: int = 200, headers: dict | None = None) -> None:
        self._data = data
        self.status = status
        self.headers = headers or {}

    def read(self, size: int) -> bytes:
        chunk, self._data = self._data[:size], self._data[size:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


BODY = bytes(range(256)) * 8
DIGEST = hashlib.sha256(BODY).hexdigest()


def _download(tmp_path: Path, opener, *, size: int = len(BODY), digest: str = DIGEST):
    return DownloadManager(opener).download(
        url="https://example.test/pkg.zip",
        destination=tmp_path / "pkg.zip",
        expected_size=size,
        expected_sha256=digest,
    )


def test_download_never_writes_beyond_expected_size(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="size_mismatch"):
        _download(tmp_path, lambda req, timeout: _Response(BODY + b"x" * 10_000_000))
    assert not (tmp_path / "pkg.zip.part").exists()
    assert not (tmp_path / "pkg.zip").exists()


def test_resume_requires_partial_content_with_matching_range(tmp_path: Path) -> None:
    (tmp_path / "pkg.zip.part").write_bytes(BODY[:1000])
    seen: list[str | None] = []

    def opener(request, timeout):
        seen.append(request.get_header("Range"))
        return _Response(BODY[1000:], status=206, headers={"Content-Range": f"bytes 1000-{len(BODY) - 1}/{len(BODY)}"})

    result = _download(tmp_path, opener)
    assert seen == ["bytes=1000-"]
    assert result.path.read_bytes() == BODY


def test_resume_restarts_from_zero_when_server_ignores_range(tmp_path: Path) -> None:
    (tmp_path / "pkg.zip.part").write_bytes(b"garbage-prefix")
    result = _download(tmp_path, lambda req, timeout: _Response(BODY, status=200))
    assert result.path.read_bytes() == BODY


def test_resume_with_mismatched_content_range_restarts_cleanly(tmp_path: Path) -> None:
    (tmp_path / "pkg.zip.part").write_bytes(BODY[:1000])
    calls: list[str | None] = []

    def opener(request, timeout):
        calls.append(request.get_header("Range"))
        if request.get_header("Range"):
            return _Response(BODY[500:], status=206, headers={"Content-Range": f"bytes 500-{len(BODY) - 1}/{len(BODY)}"})
        return _Response(BODY)

    assert _download(tmp_path, opener).path.read_bytes() == BODY
    assert calls == ["bytes=1000-", None]


def test_resume_416_discards_partial_and_restarts(tmp_path: Path) -> None:
    (tmp_path / "pkg.zip.part").write_bytes(BODY[:10])
    calls: list[str | None] = []

    def opener(request, timeout):
        calls.append(request.get_header("Range"))
        if request.get_header("Range"):
            raise urllib.error.HTTPError(request.full_url, 416, "range", {}, None)
        return _Response(BODY)

    assert _download(tmp_path, opener).path.read_bytes() == BODY
    assert calls == ["bytes=10-", None]


def test_complete_part_is_verified_locally_without_a_request(tmp_path: Path) -> None:
    (tmp_path / "pkg.zip.part").write_bytes(BODY)

    def opener(request, timeout):  # pragma: no cover - must not be called
        raise AssertionError("no request expected")

    assert _download(tmp_path, opener).path.read_bytes() == BODY


def test_short_read_keeps_part_for_resume_and_is_never_promoted(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="size_mismatch"):
        _download(tmp_path, lambda req, timeout: _Response(BODY[:100]))
    assert (tmp_path / "pkg.zip.part").stat().st_size == 100
    assert not (tmp_path / "pkg.zip").exists()


def test_stall_guard_measures_time_between_chunks(tmp_path: Path, monkeypatch) -> None:
    from exilelens.app.updates import download as download_module

    monkeypatch.setattr(download_module, "DOWNLOAD_CHUNK_BYTES", 512)
    ticks = iter([0.0, 1.0, 500.0, 501.0, 502.0])

    manager = DownloadManager(lambda req, timeout: _Response(BODY), clock=lambda: next(ticks))
    with pytest.raises(DownloadError, match="stall_timeout"):
        manager.download(
            url="https://example.test/pkg.zip",
            destination=tmp_path / "pkg.zip",
            expected_size=len(BODY),
            expected_sha256=DIGEST,
        )
    assert not (tmp_path / "pkg.zip").exists()


def test_hash_mismatch_discards_part(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="hash_mismatch"):
        _download(tmp_path, lambda req, timeout: _Response(BODY), digest="0" * 64)
    assert not (tmp_path / "pkg.zip.part").exists()


# ----------------------------------------------------------------------------- archive limits


def _zip(path: Path, entries: dict[str, bytes], *, compression=zipfile.ZIP_DEFLATED) -> Path:
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name, data in entries.items():
            info = zipfile.ZipInfo("placeholder")
            info.filename = name  # bypass ZipInfo's separator normalisation to model hostile archives
            info.compress_type = compression
            archive.writestr(info, data)
    return path


def test_archive_accepts_release_shaped_package(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "ok.zip", {"ExileLens/ExileLens.exe": b"x", "ExileLens/_internal/a.dll": b"y"})
    assert [info.filename for info in validate_zip_archive(archive)] == ["ExileLens/ExileLens.exe", "ExileLens/_internal/a.dll"]


@pytest.mark.parametrize(
    ("entries", "reason"),
    [
        ({"Other/ExileLens.exe": b"x"}, "entry_outside_root"),
        ({"ExileLens/../evil.exe": b"x"}, "path_traversal"),
        # zipfile normalises "\\" to "/" on Windows; elsewhere the raw backslash is rejected outright.
        ({"ExileLens\\..\\evil.exe": b"x"}, "path_traversal" if sys.platform == "win32" else "unsafe_entry_name"),
        ({"ExileLens/C:evil.exe": b"x"}, "unsafe_entry_name"),
        ({"ExileLens/a.txt": b"x", "ExileLens/A.TXT": b"y"}, "duplicate_entry"),
    ],
)
def test_archive_rejects_unsafe_names(tmp_path: Path, entries: dict, reason: str) -> None:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        archive = _zip(tmp_path / "bad.zip", entries)
    with pytest.raises(UnsafeArchiveError, match=reason):
        validate_zip_archive(archive)


def test_archive_rejects_compression_bombs(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "bomb.zip", {"ExileLens/zeros.bin": b"\0" * (8 * 1024 * 1024)})
    with pytest.raises(UnsafeArchiveError, match="compression_ratio_exceeded"):
        validate_zip_archive(archive)


def test_archive_rejects_too_many_entries(tmp_path: Path, monkeypatch) -> None:
    from exilelens.app.updates import archive as archive_module

    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_ENTRIES", 3)
    archive = _zip(tmp_path / "many.zip", {f"ExileLens/{i}.txt": b"x" for i in range(4)})
    with pytest.raises(UnsafeArchiveError, match="too_many_entries"):
        validate_zip_archive(archive)
    assert MAX_ARCHIVE_ENTRIES >= 10 * 204  # ample headroom over the real v0.6.0 package


def test_archive_rejects_oversized_totals(tmp_path: Path, monkeypatch) -> None:
    from exilelens.app.updates import archive as archive_module

    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 10)
    archive = _zip(tmp_path / "big.zip", {"ExileLens/a.bin": b"123456", "ExileLens/b.bin": b"123456"}, compression=zipfile.ZIP_STORED)
    with pytest.raises(UnsafeArchiveError, match="archive_too_large"):
        validate_zip_archive(archive)
    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_ENTRY_BYTES", 5)
    with pytest.raises(UnsafeArchiveError, match="entry_too_large"):
        validate_zip_archive(archive)
