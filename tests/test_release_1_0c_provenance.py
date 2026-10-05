"""1.0-C: binary provenance covers BOTH executables with no absolute paths, the spec audit is structural, and the updater carries
the same canonical version resource as the GUI. Synthetic distributions only: no PyInstaller build."""

from __future__ import annotations

import json
import re
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from exilelens._version import __version__, windows_version_tuple
from exilelens.ops import binary_provenance as bp
from exilelens.ops import packaging_spec
from exilelens.ops.packaging_version import EXECUTABLES, GUI, UPDATER, render_version_info
from exilelens.ops.release_gate import _artifact_executables, _spec_audit, _version_files_coherent
from exilelens.ops.models import GateVerdict

pytestmark = pytest.mark.itemcheck

ROOT = Path(__file__).resolve().parents[1]
GUI_SPEC = (ROOT / "packaging" / "exilelens-gui.spec").read_text(encoding="utf-8")
UPDATER_SPEC = (ROOT / "packaging" / "exilelens-updater.spec").read_text(encoding="utf-8")


# --- version resources --------------------------------------------------------------------------------------------------


def test_both_executables_share_the_one_canonical_version():
    gui, updater = render_version_info(identity=GUI), render_version_info(identity=UPDATER)
    numeric = ", ".join(str(n) for n in windows_version_tuple(__version__))
    for text in (gui, updater):
        assert f"filevers=({numeric})" in text and f"prodvers=({numeric})" in text
        assert f"StringStruct('FileVersion', '{__version__}')" in text and f"StringStruct('ProductVersion', '{__version__}')" in text
        assert "StringStruct('ProductName', 'ExileLens')" in text and "StringStruct('CompanyName', 'ExileLens')" in text
    assert "StringStruct('OriginalFilename', 'ExileLensUpdater.exe')" in updater
    assert "StringStruct('FileDescription', 'ExileLens Updater')" in updater
    assert "StringStruct('OriginalFilename', 'ExileLens.exe')" in gui and "StringStruct('FileDescription', 'ExileLens')" in gui
    assert [e.file_name for e in EXECUTABLES] == ["ExileLens.exe", "ExileLensUpdater.exe"]


def test_committed_version_resources_are_current_for_both_executables():
    for identity in EXECUTABLES:
        on_disk = (ROOT / identity.version_file).read_text(encoding="utf-8")
        assert on_disk == render_version_info(identity=identity), identity.version_file
    assert _version_files_coherent(ROOT).status == GateVerdict.PASS


def test_there_is_no_second_updater_version():
    source = (ROOT / "src" / "exilelens" / "ops" / "packaging_version.py").read_text(encoding="utf-8")
    assert "__version__" in source and "UPDATER_VERSION" not in source
    assert "version_info_updater.txt" in UPDATER_SPEC and "exilelens.ico" in UPDATER_SPEC


@pytest.mark.skipif(sys.platform != "win32", reason="Windows version resources")
def test_the_version_resource_reader_reads_a_real_executable():
    from exilelens.ops.pe_version import read_version_strings

    strings = read_version_strings(Path(sys.executable))
    assert strings and strings.get("ProductName")
    assert read_version_strings(ROOT / "README.md") is None


# --- spec audit ---------------------------------------------------------------------------------------------------------


def test_the_real_specs_pass_the_structural_audit():
    assert packaging_spec.audit_specs(ROOT) == []
    assert _spec_audit(ROOT).status == GateVerdict.PASS


@pytest.mark.parametrize(
    "old,new,fragment",
    [
        ("    upx=False,\n    upx_exclude", "    upx=True,\n    upx_exclude", "upx=False"),
        ("hookspath=[],", 'hookspath=["hooks"],', "hookspath"),
        ('str(repo_root / "packaging" / "pyi_runtime_qt_dll.py")', '"other_hook.py"', "runtime hook"),
        ('    "PySide6.QtCharts",\n', "", "QtCharts"),
        ('    "pytest",\n    "unittest",\n    "test",', '    "unittest",\n    "test",', "pytest"),
        ("    console=False,", "    console=True,", "windowed"),
        ("exclude_binaries=True,", "exclude_binaries=False,", "onedir"),
        ("codesign_identity=None,", 'codesign_identity="Developer ID",', "code-signing"),
        ('"exilelens.ico"', '"other.ico"', "icon"),
        ('"packaging" / "version_info.txt"', '"packaging" / "other.txt"', "version resource"),
        ('src_root / "exilelens" / "app" / "main.py"', 'src_root / "exilelens" / "other.py"', "entry point"),
    ],
)
def test_gui_spec_regressions_are_caught(old, new, fragment):
    assert old in GUI_SPEC, old
    problems = packaging_spec.audit_gui_spec(GUI_SPEC.replace(old, new, 1))
    assert problems and any(fragment.lower() in p.lower() for p in problems), problems


@pytest.mark.parametrize(
    "old,new,fragment",
    [
        ('"PySide6",\n        "shiboken6",', '"shiboken6",', "PySide6"),
        ("    upx=False,\n    console=True,", "    upx=True,\n    console=True,", "upx"),
        ("    console=True,", "    console=False,", "console"),
        ('"exilelens.updater.install",', '"cryptography.hazmat",', "hiddenimports"),
        ("version_info_updater.txt", "version_info.txt", "version resource"),
        ("binaries=[],", 'binaries=[("x.dll", ".")],', "binaries"),
        ('src_root / "exilelens" / "updater" / "__main__.py"', 'src_root / "exilelens" / "app" / "main.py"', "entry point"),
        ('name="ExileLensUpdater",', 'name="Other",', "name"),
    ],
)
def test_updater_spec_regressions_are_caught(old, new, fragment):
    assert old in UPDATER_SPEC, old
    problems = packaging_spec.audit_updater_spec(UPDATER_SPEC.replace(old, new, 1))
    assert problems and any(fragment.lower() in p.lower() for p in problems), problems


def test_an_updater_spec_that_adds_a_collect_step_is_rejected():
    mutated = UPDATER_SPEC + "\ncoll = COLLECT(exe, a.binaries, name='ExileLensUpdater')\n"
    assert any("onefile" in p for p in packaging_spec.audit_updater_spec(mutated))


# --- manifest -----------------------------------------------------------------------------------------------------------


def _distribution(tmp_path: Path) -> Namespace:
    venv = tmp_path / "repo" / ".release-venv"
    runtime = tmp_path / "python312"
    system = tmp_path / "windows" / "System32"
    build = tmp_path / "repo" / "build" / "exilelens-gui"
    sources = {
        "PySide6/Qt6Core.dll": venv / "Lib" / "site-packages" / "PySide6" / "Qt6Core.dll",
        "python312.dll": runtime / "python312.dll",
        "VCRUNTIME140.dll": system / "VCRUNTIME140.dll",
    }
    dist = tmp_path / "repo" / "dist" / "ExileLens"
    (dist / "_internal" / "PySide6").mkdir(parents=True)
    toc = []
    for packaged, source in sources.items():
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(packaged.encode())
        (dist / "_internal" / packaged).parent.mkdir(parents=True, exist_ok=True)
        (dist / "_internal" / packaged).write_bytes(packaged.encode())
        toc.append((packaged.replace("/", "\\"), str(source), "BINARY"))
    (dist / "ExileLens.exe").write_bytes(b"gui-exe")
    updater = tmp_path / "repo" / "dist" / "ExileLensUpdater.exe"
    updater.write_bytes(b"updater-exe-built-once")
    (dist / "_internal" / "ExileLensUpdater.exe").write_bytes(b"updater-exe-built-once")
    build.mkdir(parents=True, exist_ok=True)
    (build / "ExileLens.exe").write_bytes(b"gui-exe")
    toc.append(("ExileLens.exe", str(build / "ExileLens.exe"), "EXECUTABLE"))
    toc_path = build / "COLLECT-00.toc"
    toc_path.write_text(repr((toc,)), encoding="utf-8")
    return Namespace(
        repo_root=str(ROOT), venv_root=str(venv), build_root=str(build), dist_root=str(dist), collect_toc=str(toc_path),
        manifest=str(dist / "binary_manifest.json"), git_commit="a" * 40, application_version=__version__,
        updater_built=str(updater), system_root=[str(system), str(tmp_path / "windows")], approved_root=[str(runtime)],
    )


def test_manifest_covers_both_executables_and_ships_no_absolute_path(tmp_path):
    args = _distribution(tmp_path)
    payload = bp.validate_and_write_manifest(args)
    text = Path(args.manifest).read_text(encoding="utf-8")
    assert payload["schema_version"] == 2
    roles = {row["role"]: row for row in payload["executables"]}
    assert set(roles) == {"gui", "updater"}
    assert roles["gui"]["relative_path"] == "ExileLens.exe" and roles["updater"]["relative_path"] == "_internal/ExileLensUpdater.exe"
    assert roles["gui"]["sha256"] == bp.sha256_file(Path(args.dist_root) / "ExileLens.exe")
    assert roles["updater"]["sha256"] == bp.sha256_file(Path(args.updater_built))  # the shipped updater IS the single build output
    for role, row in roles.items():
        assert set(row["inputs"]) == {"spec", "version_resource", "icon", "entry_point"}
        assert all(v["sha256"] not in ("missing", "") and not re.search(r"[A-Za-z]:[\\/]", v["path"]) for v in row["inputs"].values()), role
    for key in ("git_commit", "application_version", "python_version", "pyinstaller_version", "architecture", "build_timestamp_utc", "release_lock_sha256"):
        assert payload[key], key
    # origins are "<root kind>/<relative path>", never absolute
    origins = {row["relative_path"]: row["origin"] for row in payload["binaries"]}
    assert origins["_internal/PySide6/Qt6Core.dll"] == "release-venv/Lib/site-packages/PySide6/Qt6Core.dll"
    assert origins["_internal/python312.dll"] == "python-runtime/python312.dll"
    assert origins["_internal/VCRUNTIME140.dll"].startswith("windows-system32/")
    assert "_internal/ExileLensUpdater.exe" in origins
    assert not re.search(r"[A-Za-z]:[\\/]", text), "an absolute drive path would ship in binary_manifest.json"
    assert str(tmp_path) not in text and "origin_path" not in text


def test_a_rebuilt_or_different_updater_is_rejected(tmp_path):
    args = _distribution(tmp_path)
    Path(args.updater_built).write_bytes(b"a second, different build")
    with pytest.raises(ValueError, match="built exactly once"):
        bp.validate_and_write_manifest(args)


def test_missing_updater_or_unknown_native_file_or_foreign_origin_is_rejected(tmp_path):
    args = _distribution(tmp_path)
    (Path(args.dist_root) / "_internal" / "ExileLensUpdater.exe").unlink()
    with pytest.raises(ValueError, match="ExileLensUpdater.exe"):
        bp.validate_and_write_manifest(args)

    args = _distribution(tmp_path / "b")
    (Path(args.dist_root) / "_internal" / "stray.dll").write_bytes(b"x")
    with pytest.raises(ValueError, match="no source entry"):
        bp.validate_and_write_manifest(args)

    args = _distribution(tmp_path / "c")
    foreign = tmp_path / "c" / "somewhere-else" / "evil.dll"
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"x")
    (Path(args.dist_root) / "_internal" / "evil.dll").write_bytes(b"x")
    toc = Path(args.collect_toc)
    rows = eval(toc.read_text(encoding="utf-8"))[0]  # noqa: S307 - our own just-written literal
    rows.append(("evil.dll", str(foreign), "BINARY"))
    toc.write_text(repr((rows,)), encoding="utf-8")
    with pytest.raises(ValueError, match="outside the approved origins"):
        bp.validate_and_write_manifest(args)


def test_origin_label_prefers_the_most_specific_root(tmp_path):
    roots = [("release-venv", tmp_path / "repo" / ".release-venv"), ("repo", tmp_path / "repo")]
    assert bp.origin_label(tmp_path / "repo" / ".release-venv" / "x.dll", roots) == "release-venv/x.dll"
    assert bp.origin_label(tmp_path / "repo" / "assets" / "a.dll", roots) == "repo/assets/a.dll"
    assert bp.origin_label(tmp_path / "elsewhere" / "a.dll", roots) is None


def test_the_artifact_gate_blocks_a_package_without_both_executables(tmp_path):
    (tmp_path / "dist" / "ExileLens").mkdir(parents=True)
    result = _artifact_executables(tmp_path, required=True)
    assert result.status == GateVerdict.BLOCKED
    assert "ExileLens.exe missing" in result.detail and "ExileLensUpdater.exe missing" in result.detail
    assert _artifact_executables(tmp_path, required=False).status == GateVerdict.PASS  # pre-build makes no artifact claim
    assert "not required pre-build" in _artifact_executables(tmp_path, required=False).detail


def test_the_manifest_json_schema_is_stable(tmp_path):
    args = _distribution(tmp_path)
    bp.validate_and_write_manifest(args)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    assert list(manifest) == sorted(manifest)  # sort_keys: deterministic file layout
