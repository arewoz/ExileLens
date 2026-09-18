"""Offline coverage for bounded selected-PoB version visibility."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from poe2value.app.diagnostics import build_global_diagnostics
from poe2value.app.setup_status import SetupCheck
from poe2value.config import detect_pob_identity
from poe2value.ui.health import derive_health, header_status


_POE2_SOURCE = "https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/{branch}/"
_POB1_SOURCE = "https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding/{branch}/"


def _manifest(root: Path, version: str, source: str | None = _POE2_SOURCE) -> None:
    source_xml = f'<Source part="default" url="{source}" />' if source else ""
    (root / "manifest.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<PoBVersion>\n    <Version number="{version}" />\n    {source_xml}\n</PoBVersion>\n',
        encoding="utf-8",
    )


@pytest.mark.parametrize("source", [False, True])
def test_detect_pob_identity_reads_installed_and_source_layouts(tmp_path: Path, source: bool) -> None:
    launch = tmp_path / "src" / "Launch.lua" if source else tmp_path / "Launch.lua"
    launch.parent.mkdir(parents=True, exist_ok=True)
    launch.write_text("", encoding="utf-8")
    _manifest(tmp_path, "0.23.1")
    identity = detect_pob_identity(tmp_path)
    assert identity.version == "0.23.1"
    assert identity.layout == ("source" if source else "installed")
    assert identity.revision == "unknown"


@pytest.mark.parametrize("contents", [None, "<Root>", "<Root><PoBVersion /></Root>", '<Root><PoBVersion><Version number="not-a-version" /></PoBVersion></Root>'])
def test_detect_pob_identity_degrades_malformed_or_missing_manifest(tmp_path: Path, contents: str | None) -> None:
    (tmp_path / "Launch.lua").write_text("", encoding="utf-8")
    if contents is not None:
        (tmp_path / "manifest.xml").write_text(contents, encoding="utf-8")
    assert detect_pob_identity(tmp_path).version == "unknown"


class _Controller:
    build_info = SimpleNamespace(state=None, path="", name="")
    price_check_hotkey = None

    def __init__(self, path: Path) -> None:
        self.settings = SimpleNamespace(pob_path=str(path), overlay_enabled=False)

    def engine_status(self) -> str:
        return "ready"

    def active_build_status(self):
        return None


def test_pob1_2473_manifest_is_untrusted_but_runtime_layout_remains_usable(tmp_path: Path) -> None:
    (tmp_path / "Launch.lua").write_text("", encoding="utf-8")
    _manifest(tmp_path, "2.47.3", _POB1_SOURCE)
    identity = detect_pob_identity(tmp_path)
    assert identity.version == "unknown"
    assert identity.manifest_version == "2.47.3"
    assert identity.status == "unverified"
    assert "does not match" in identity.reason


def test_manifest_without_provenance_is_unverified(tmp_path: Path) -> None:
    (tmp_path / "Launch.lua").write_text("", encoding="utf-8")
    _manifest(tmp_path, "0.23.1", None)
    identity = detect_pob_identity(tmp_path)
    assert identity.version == "unknown"
    assert identity.status == "unverified"
    assert "no trusted" in identity.reason


def test_health_header_and_diagnostics_show_actual_version_without_paths(monkeypatch, tmp_path: Path) -> None:
    _manifest(tmp_path, "0.23.1")
    controller = _Controller(tmp_path)
    monkeypatch.setattr("poe2value.app.setup_status.check_pob_folder", lambda _path: SetupCheck(True, "FOUND"))
    health = derive_health(controller, controller.settings)
    assert health.pob.value == "Connected · v0.23.1"
    assert header_status(health) == ("PoB connected · v0.23.1", "ok")
    diagnostics = build_global_diagnostics(controller)
    report = diagnostics.render()
    assert "Version: 0.23.1" in report
    assert f"Version: {tmp_path}" not in report
    assert diagnostics.supported_pob_revision != diagnostics.pob_version


def test_untrusted_manifest_is_hidden_from_health_and_labeled_in_diagnostics(
    monkeypatch, tmp_path: Path
) -> None:
    _manifest(tmp_path, "2.47.3", _POB1_SOURCE)
    controller = _Controller(tmp_path)
    monkeypatch.setattr("poe2value.app.setup_status.check_pob_folder", lambda _path: SetupCheck(True, "FOUND"))
    health = derive_health(controller, controller.settings)
    assert health.pob.value == "Connected"
    assert header_status(health) == ("PoB connected", "ok")
    diagnostics = build_global_diagnostics(controller)
    report = diagnostics.render()
    assert "Version: unknown" in report
    assert "Manifest reported version (raw): 2.47.3" in report
    assert "Version status: unverified" in report
    assert "does not match" in report


def test_unknown_version_preserves_connected_wording(monkeypatch, tmp_path: Path) -> None:
    controller = _Controller(tmp_path)
    monkeypatch.setattr("poe2value.app.setup_status.check_pob_folder", lambda _path: SetupCheck(True, "FOUND"))
    health = derive_health(controller, controller.settings)
    assert health.pob.value == "Connected"
    assert header_status(health) == ("PoB connected", "ok")


def test_manifest_cache_refreshes_when_metadata_changes(tmp_path: Path) -> None:
    (tmp_path / "Launch.lua").write_text("", encoding="utf-8")
    _manifest(tmp_path, "0.23.1")
    assert detect_pob_identity(tmp_path).version == "0.23.1"
    _manifest(tmp_path, "0.24.0")
    assert detect_pob_identity(tmp_path).version == "0.24.0"


def test_clean_pob1_folder_remains_rejected(tmp_path: Path) -> None:
    (tmp_path / "Launch.lua").write_text("", encoding="utf-8")
    from poe2value.app.setup_status import check_pob_folder

    check = check_pob_folder(str(tmp_path))
    assert not check.ok
    assert check.label == "INCOMPATIBLE POB INSTALLATION"
