"""TRUST-01C: PoB2 auto-detect v2 (registry / shortcuts / bounded scan) behind one validation boundary."""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

import pytest

from exilelens import pob_discovery as pd
from exilelens.pob_discovery import (
    auto_configure_pob_path,
    choose_pob_installation,
    discover_pob_installations,
    find_pob_installation,
    parse_lnk_target,
)

pytestmark = pytest.mark.itemcheck

_POB2 = "https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/dev/"
_POB1 = "https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding/dev/"


def _install(root: Path, *, version: str = "0.23.1", source: str | None = _POB2, complete: bool = True, layout: str = "installed") -> Path:
    base = root / "src" if layout == "source" else root
    files = ("Launch.lua", "Modules/Main.lua", "Modules/Build.lua", "Data/ModItem.lua", "lua/xml.lua")
    for relative in files if complete else files[:2]:
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    runtime = root / "runtime" if layout == "source" else root
    runtime.mkdir(parents=True, exist_ok=True)
    if complete:
        (runtime / "lua51.dll").write_text("", encoding="utf-8")
        if layout == "source":
            (runtime / "lua").mkdir(parents=True, exist_ok=True)
            (runtime / "lua" / "xml.lua").write_text("", encoding="utf-8")
    if source is not None:
        (root / "manifest.xml").write_text(
            f'<?xml version="1.0"?><PoBVersion><Version number="{version}" /><Source part="default" url="{source}" /></PoBVersion>',
            encoding="utf-8",
        )
    return root


def _discover(tmp_path: Path, env=None, **kwargs):
    env = {"USERPROFILE": str(tmp_path / "profile"), **(env or {})}
    kwargs.setdefault("registry_provider", lambda: [])
    kwargs.setdefault("app_paths_provider", lambda: [])
    kwargs.setdefault("shortcut_provider", lambda: [])
    return discover_pob_installations(env, **kwargs)


def test_valid_explicit_path_wins_and_invalid_one_is_not_selected(tmp_path: Path) -> None:
    explicit = _install(tmp_path / "explicit")
    registry = _install(tmp_path / "reg", version="9.9.9")
    result = choose_pob_installation(_discover(tmp_path, {"POB2_PATH": str(explicit)}, registry_provider=lambda: [registry]))
    assert result.selected.path == explicit and result.selected.source == "explicit"
    bad = _discover(tmp_path, {"POB2_PATH": str(tmp_path / "nothing")}, registry_provider=lambda: [registry])
    assert [c.path for c in bad] == [registry]


def test_valid_saved_path_stays_preferred_and_is_never_replaced(tmp_path: Path) -> None:
    saved = _install(tmp_path / "saved", version="0.1.0")
    better = _install(tmp_path / "better", version="9.0.0")
    ranked = _discover(tmp_path, registry_provider=lambda: [better], saved_path=str(saved))
    assert ranked[0].path == saved and ranked[0].source == "saved"
    path, result = auto_configure_pob_path(str(saved), {"USERPROFILE": str(tmp_path / "profile")})
    assert path == str(saved) and result is None  # discovery did not even run


def test_registry_location_found_false_positive_and_pob1_rejected(tmp_path: Path) -> None:
    good = _install(tmp_path / "poe2")
    lookalike = tmp_path / "Path of Building Community (PoE2)"
    lookalike.mkdir()
    pob1 = _install(tmp_path / "pob1", source=_POB1)
    exe_pob1 = _install(tmp_path / "pob1exe")
    (exe_pob1 / "Path of Building.exe").write_text("", encoding="utf-8")
    ranked = _discover(tmp_path, registry_provider=lambda: [good, lookalike, pob1, exe_pob1])
    assert [c.path for c in ranked] == [good] and ranked[0].source == "registry"


def test_duplicates_collapse_and_keep_strongest_source(tmp_path: Path) -> None:
    appdata = tmp_path / "roaming"
    install = _install(appdata / "Path of Building Community (PoE2)")
    ranked = _discover(
        tmp_path,
        {"APPDATA": str(appdata)},
        registry_provider=lambda: [Path(str(install).upper()), install],
    )
    assert len(ranked) == 1 and ranked[0].source == "registry"
    assert set(ranked[0].sources) >= {"registry", "standard"}


def test_ranking_verified_installed_version_then_source(tmp_path: Path) -> None:
    unverified = _install(tmp_path / "a", source=None, version="9.0.0")
    source_checkout = _install(tmp_path / "b", layout="source", version="0.30.0")
    old_installed = _install(tmp_path / "c", version="0.20.0")
    new_installed = _install(tmp_path / "d", version="0.23.1")
    ranked = _discover(tmp_path, registry_provider=lambda: [unverified, source_checkout, old_installed, new_installed])
    assert [c.path for c in ranked] == [new_installed, old_installed, source_checkout, unverified]
    assert choose_pob_installation(ranked).selected.path == new_installed


def test_equivalent_installs_are_ambiguous_not_guessed(tmp_path: Path) -> None:
    one = _install(tmp_path / "one")
    two = _install(tmp_path / "two")
    result = choose_pob_installation(_discover(tmp_path, registry_provider=lambda: [one, two]))
    assert result.selected is None and {c.path for c in result.ambiguous} == {one, two}
    assert "Version 0.23.1" in result.ambiguous[0].display()
    # user intent is never ambiguous
    explicit = choose_pob_installation(_discover(tmp_path, {"POB2_PATH": str(one)}, registry_provider=lambda: [two]))
    assert explicit.selected.path == one


def test_shallow_scan_finds_renamed_folder_but_never_recurses(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    portable = _install(profile / "Downloads" / "PathOfBuilding-PoE2-portable")
    _install(profile / "Downloads" / "stuff" / "deeper" / "PathOfBuilding-PoE2")
    _install(profile / "Downloads" / "stuff" / "PathOfBuilding-PoE2")
    ranked = _discover(tmp_path)
    assert [c.path for c in ranked] == [portable] and ranked[0].source == "scan"


def test_scan_obeys_entry_bounds_and_survives_inaccessible_directories(tmp_path: Path, monkeypatch) -> None:
    downloads = tmp_path / "profile" / "Downloads"
    for i in range(30):
        (downloads / f"folder{i:02d}").mkdir(parents=True)
    late = _install(downloads / "zz-PathOfBuilding-PoE2")
    found = pd.shallow_scan_locations({"USERPROFILE": str(tmp_path / "profile")}, deadline=float("inf"), max_children=5)
    assert late not in found
    real_scandir = os.scandir

    def deny(path, *a, **k):
        if "Documents" in str(path):
            raise PermissionError("denied")
        return real_scandir(path, *a, **k)

    monkeypatch.setattr(pd.os, "scandir", deny)
    assert late in pd.shallow_scan_locations({"USERPROFILE": str(tmp_path / "profile")}, deadline=float("inf"))


def test_broken_sources_and_missing_registry_do_not_crash(tmp_path: Path, monkeypatch) -> None:
    def boom():
        raise OSError("registry unavailable")

    assert _discover(tmp_path, registry_provider=boom, shortcut_provider=boom, app_paths_provider=boom) == []
    monkeypatch.setitem(sys.modules, "winreg", None)  # import raises ImportError, as on non-Windows
    assert pd.registry_install_locations() == [] and pd.app_paths_locations() == []


def test_nothing_found_falls_back_to_manual_browse(tmp_path: Path) -> None:
    result = find_pob_installation(
        {"USERPROFILE": str(tmp_path / "profile")},
        registry_provider=lambda: [], app_paths_provider=lambda: [], shortcut_provider=lambda: [],
    )
    assert result.selected is None and result.candidates == () and result.ambiguous == ()


def test_invalid_saved_path_may_be_replaced_only_by_a_single_clear_install(tmp_path: Path, monkeypatch) -> None:
    only = _install(tmp_path / "only")
    monkeypatch.setattr(pd, "registry_install_locations", lambda: [only])
    monkeypatch.setattr(pd, "app_paths_locations", lambda: [])
    monkeypatch.setattr(pd, "shortcut_locations", lambda env=None: [])
    env = {"USERPROFILE": str(tmp_path / "profile")}
    path, result = auto_configure_pob_path(str(tmp_path / "gone"), env)
    assert path == str(only) and result.selected is not None
    other = _install(tmp_path / "other")
    monkeypatch.setattr(pd, "registry_install_locations", lambda: [only, other])
    path, result = auto_configure_pob_path(str(tmp_path / "gone"), env)
    assert path == str(tmp_path / "gone") and result.ambiguous  # nothing is overwritten on ambiguity


def _lnk(target: str) -> bytes:
    local = target.encode("latin-1") + b"\x00"
    info_header = 28
    info = struct.pack("<IIIIIII", info_header + len(local) + 1, info_header, 1, 0, info_header, 0, info_header + len(local)) + local + b"\x00"
    header = struct.pack("<I", 0x4C) + b"\x00" * 16 + struct.pack("<I", 0x02) + b"\x00" * (0x4C - 24)
    return header + info


def test_lnk_target_is_resolved_without_dependencies(tmp_path: Path) -> None:
    assert parse_lnk_target(_lnk(r"C:\Apps\PoB2\Path of Building-PoE2.exe")) == Path(r"C:\Apps\PoB2\Path of Building-PoE2.exe")
    assert parse_lnk_target(b"not a shortcut") is None
    programs = tmp_path / "roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    programs.mkdir(parents=True)
    (programs / "Path of Building Community (PoE2).lnk").write_bytes(_lnk(str(tmp_path / "x" / "Path of Building-PoE2.exe")))
    (programs / "Unrelated.lnk").write_bytes(_lnk(str(tmp_path / "y" / "app.exe")))
    assert pd.shortcut_locations({"APPDATA": str(tmp_path / "roaming")}) == [tmp_path / "x"]


def test_registry_value_parsing() -> None:
    assert pd._directory_of('"C:\\Users\\P\\PoB (PoE2)"') == Path("C:/Users/P/PoB (PoE2)")
    assert pd._directory_of('"C:\\Users\\P\\PoB\\Path of Building-PoE2.exe",0') == Path("C:/Users/P/PoB")
    assert pd._directory_of("C:\\Apps\\PoB\\uninstall.exe /S") == Path("C:/Apps/PoB")
    assert pd._directory_of("") is None
