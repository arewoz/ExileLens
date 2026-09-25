"""Focused coverage for bounded Path of Building 2 installation discovery."""

from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from exilelens.app.settings import AppSettings
from exilelens.config import detect_common_pob_installation, pob_installation_candidates
from exilelens.ui.settings_dialog import SetupDialog


pytestmark = pytest.mark.itemcheck

_POB2_SOURCE = "https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/dev/"
_POB1_SOURCE = "https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding/dev/"


def _make_install(root: Path, *, source: str | None = _POB2_SOURCE, complete: bool = True) -> Path:
    files = (
        "Launch.lua",
        "Modules/Main.lua",
        "Modules/Build.lua",
        "Data/ModItem.lua",
        "lua51.dll",
        "lua/xml.lua",
    )
    for relative in files if complete else files[:2]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    if source is not None:
        (root / "manifest.xml").write_text(
            '<?xml version="1.0"?><PoBVersion><Version number="0.23.1" />'
            f'<Source part="default" url="{source}" /></PoBVersion>',
            encoding="utf-8",
        )
    return root


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({"POB2_PATH": r"D:\Custom\PoB2"}, Path(r"D:\Custom\PoB2")),
        ({"APPDATA": r"C:\Users\Player\AppData\Roaming"}, Path(r"C:\Users\Player\AppData\Roaming\Path of Building Community (PoE2)")),
        ({"LOCALAPPDATA": r"C:\Users\Player\AppData\Local"}, Path(r"C:\Users\Player\AppData\Local\Path of Building Community (PoE2)")),
        ({"ProgramFiles": r"C:\Program Files"}, Path(r"C:\Program Files\Path of Building Community (PoE2)")),
        ({"USERPROFILE": r"C:\Users\Player"}, Path(r"C:\Users\Player\Documents\Path of Building Community (PoE2)")),
        ({"OneDrive": r"C:\Users\Player\OneDrive"}, Path(r"C:\Users\Player\OneDrive\Documents\Path of Building Community (PoE2)")),
    ],
)
def test_candidate_matrix_has_deterministic_first_location(environment: dict[str, str], expected: Path) -> None:
    assert pob_installation_candidates(environment)[0] == expected


def test_candidate_precedence_preserves_existing_locations_before_portable_fallbacks(tmp_path: Path) -> None:
    environment = {
        "POB2_PATH": str(tmp_path / "explicit"),
        "APPDATA": str(tmp_path / "roaming"),
        "LOCALAPPDATA": str(tmp_path / "local"),
        "ProgramFiles": str(tmp_path / "program-files"),
        "ProgramFiles(x86)": str(tmp_path / "program-files-x86"),
        "USERPROFILE": str(tmp_path / "profile"),
    }
    expected = (
        tmp_path / "explicit",
        tmp_path / "roaming" / "Path of Building Community (PoE2)",
        tmp_path / "local" / "Path of Building Community (PoE2)",
        tmp_path / "local" / "Programs" / "Path of Building Community (PoE2)",
        tmp_path / "program-files" / "Path of Building Community (PoE2)",
        tmp_path / "program-files-x86" / "Path of Building Community (PoE2)",
    )
    assert pob_installation_candidates(environment)[: len(expected)] == expected


def test_discovery_uses_first_valid_candidate_and_falls_back_from_incomplete_install(tmp_path: Path) -> None:
    explicit = _make_install(tmp_path / "explicit", complete=False)
    appdata = _make_install(tmp_path / "roaming" / "Path of Building Community (PoE2)")
    environment = {"POB2_PATH": str(explicit), "APPDATA": str(tmp_path / "roaming")}

    assert detect_common_pob_installation(environment) == appdata


def test_discovery_prefers_valid_explicit_custom_path(tmp_path: Path) -> None:
    explicit = _make_install(tmp_path / "explicit")
    _make_install(tmp_path / "roaming" / "Path of Building Community (PoE2)")

    assert detect_common_pob_installation(
        {"POB2_PATH": str(explicit), "APPDATA": str(tmp_path / "roaming")}
    ) == explicit


@pytest.mark.parametrize(
    "relative",
    [
        Path("Documents") / "Path of Building Community (PoE2)",
        Path("Downloads") / "PathOfBuilding-PoE2",
        Path("Desktop") / "PathOfBuilding-PoE2",
    ],
)
def test_discovery_supports_bounded_profile_portable_locations(tmp_path: Path, relative: Path) -> None:
    candidate = _make_install(tmp_path / "profile" / relative)

    assert detect_common_pob_installation({"USERPROFILE": str(tmp_path / "profile")}) == candidate


@pytest.mark.parametrize("source", [_POB1_SOURCE, "https://example.invalid/not-pob2/"])
def test_discovery_rejects_complete_lookalike_with_mismatched_manifest(tmp_path: Path, source: str) -> None:
    lookalike = _make_install(tmp_path / "lookalike", source=source)

    assert detect_common_pob_installation({"POB2_PATH": str(lookalike)}) is None


def test_discovery_accepts_legacy_complete_install_without_manifest(tmp_path: Path) -> None:
    legacy = _make_install(tmp_path / "legacy", source=None)

    assert detect_common_pob_installation({"POB2_PATH": str(legacy)}) == legacy


def test_discovery_rejects_pob1_executable_lookalike_without_manifest(tmp_path: Path) -> None:
    lookalike = _make_install(tmp_path / "legacy-pob1", source=None)
    (lookalike / "Path of Building.exe").write_text("", encoding="utf-8")

    assert detect_common_pob_installation({"POB2_PATH": str(lookalike)}) is None


def test_discovery_handles_missing_environment_and_inaccessible_candidate(monkeypatch, tmp_path: Path) -> None:
    assert detect_common_pob_installation({}) is None

    denied = tmp_path / "denied"
    fallback = _make_install(tmp_path / "roaming" / "Path of Building Community (PoE2)")
    original = Path.exists

    def guarded_exists(path: Path) -> bool:
        if path == denied:
            raise PermissionError("denied for test")
        return original(path)

    monkeypatch.setattr(Path, "exists", guarded_exists)
    assert detect_common_pob_installation({"POB2_PATH": str(denied), "APPDATA": str(tmp_path / "roaming")}) == fallback


def test_setup_preserves_saved_path_without_running_detection(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    assert app is not None
    saved = _make_install(tmp_path / "saved")
    settings = AppSettings(pob_path=str(saved))

    def unexpected_detection():
        raise AssertionError("saved paths must not be replaced by auto-discovery")

    monkeypatch.setattr("exilelens.ui.settings_dialog.detect_common_pob_installation", unexpected_detection)
    dialog = SetupDialog(settings)
    try:
        assert dialog._pob_edit.text() == str(saved)
    finally:
        dialog.close()


def test_setup_reports_detected_path_and_retains_manual_browse(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    assert app is not None
    detected = _make_install(tmp_path / "detected")
    monkeypatch.setattr("exilelens.ui.settings_dialog.detect_common_pob_installation", lambda: detected)

    dialog = SetupDialog(AppSettings(pob_path=""))
    try:
        assert dialog._pob_edit.text() == str(detected)
        assert "detected automatically" in dialog._status.text()
        assert any(button.text() == "Browse…" for button in dialog.findChildren(QPushButton))
    finally:
        dialog.close()
