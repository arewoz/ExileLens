"""1.0-C: the Qt surface/attribution/source-offer and dependency-inventory claims, the artifact gate that enforces them, and the
packaging documents that describe the pipeline. Synthetic distributions only (the real artifact is verified by `release-gate
--require-artifact`)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from exilelens.ops import release_gate as rg
from exilelens.ops.models import GateVerdict

pytestmark = pytest.mark.itemcheck

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "release-1.0" / "ARTIFACT_INVENTORY.md"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


# --- Qt surface ---------------------------------------------------------------------------------------------------------


def test_spec_and_gate_agree_on_the_removed_qt_binaries():
    spec = _read("packaging/exilelens-gui.spec")
    tokens = tuple(re.findall(r'"([^"]+)"', re.search(r"_UNUSED_QT_BINARY_TOKENS = \(([^)]*)\)", spec).group(1)))
    assert tokens == rg.UNUSED_QT_BINARY_TOKENS
    assert "_EXCLUDED_QT_BINARY_TOKENS = _GPL_ONLY_QT_BINARY_TOKENS + _UNUSED_QT_BINARY_TOKENS" in spec
    assert rg._gpl_only_qt(ROOT).status is GateVerdict.PASS


def test_the_approved_qt_surface_is_only_qtbase_and_qtsvg_modules():
    assert set(rg.EXPECTED_QT_LIBRARIES) == {"Qt6Core", "Qt6Gui", "Qt6Network", "Qt6Svg", "Qt6Widgets"}  # the five modules src/ imports
    imported = set()
    for path in (ROOT / "src").rglob("*.py"):
        imported.update(re.findall(r"(?m)^\s*(?:from|import)\s+PySide6\.(Qt[A-Za-z0-9]+)", path.read_text(encoding="utf-8")))
    assert imported == {"QtCore", "QtGui", "QtWidgets", "QtSvg", "QtNetwork"}
    assert not any(token in plugin for plugin in rg.EXPECTED_QT_PLUGINS for token in (*rg.GPL_ONLY_QT_BINARY_TOKENS, *rg.UNUSED_QT_BINARY_TOKENS))


def _qt_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist" / "ExileLens"
    pyside = dist / "_internal" / "PySide6"
    for lib in rg.EXPECTED_QT_LIBRARIES:
        (pyside / f"{lib}.dll").parent.mkdir(parents=True, exist_ok=True)
        (pyside / f"{lib}.dll").write_bytes(b"MZ")
    for plugin in rg.EXPECTED_QT_PLUGINS:
        target = pyside / "plugins" / f"{plugin}.dll"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"MZ")
    (dist / "ExileLens.exe").write_bytes(b"MZ")
    return dist


def _qt_problems(tmp_path: Path) -> str:
    (tmp_path / ".python-version").write_text("3.12.10", encoding="utf-8")
    result = rg._artifact_qt_and_dependencies(tmp_path, required=True)
    assert result.status is GateVerdict.BLOCKED  # the rest of the synthetic package is deliberately incomplete
    return result.detail


def test_the_artifact_gate_names_each_qt_deviation(tmp_path):
    dist = _qt_dist(tmp_path)
    baseline = _qt_problems(tmp_path)
    assert "Qt libraries differ" not in baseline and "Qt plugins differ" not in baseline and "GPL-only or removed" not in baseline

    (dist / "_internal" / "PySide6" / "Qt6Pdf.dll").write_bytes(b"MZ")
    detail = _qt_problems(tmp_path)
    assert "Qt libraries differ" in detail and "Qt6Pdf" in detail and "GPL-only or removed Qt binaries" in detail
    (dist / "_internal" / "PySide6" / "Qt6Pdf.dll").unlink()

    gpl = dist / "_internal" / "PySide6" / "Qt6VirtualKeyboard.dll"
    gpl.write_bytes(b"MZ")
    assert "GPL-only or removed Qt binaries" in _qt_problems(tmp_path)
    gpl.unlink()

    (dist / "_internal" / "PySide6" / "plugins" / "imageformats" / "qwebp.dll").write_bytes(b"MZ")
    assert "Qt plugins differ" in _qt_problems(tmp_path) and "qwebp" in _qt_problems(tmp_path)
    (dist / "_internal" / "PySide6" / "plugins" / "imageformats" / "qwebp.dll").unlink()

    (dist / "_internal" / "PySide6" / "Qt6Svg.dll").unlink()
    assert "missing: ['Qt6Svg']" in _qt_problems(tmp_path)


def test_qt_files_outside_the_pyside_folder_and_an_oversized_exe_are_reported(tmp_path):
    dist = _qt_dist(tmp_path)
    (dist / "_internal" / "Qt6Core.dll").write_bytes(b"MZ")
    assert "Qt file outside _internal\\PySide6" in _qt_problems(tmp_path)
    (dist / "_internal" / "Qt6Core.dll").unlink()
    (dist / "ExileLens.exe").write_bytes(b"\0" * (9 * 1024 * 1024))
    assert "must stay separate files" in _qt_problems(tmp_path)


def test_the_gate_checks_notices_against_the_bundled_runtime_openssl_cffi_and_pycparser(tmp_path):
    dist = _qt_dist(tmp_path)
    internal = dist / "_internal"
    (dist / "THIRD_PARTY_NOTICES.txt").write_text("OpenSSL 3.0.16 and OpenSSL 4.0.1", encoding="utf-8")
    (internal / "libcrypto-3.dll").write_bytes(b"MZ OpenSSL 3.0.99 1 Jan 2030")
    (internal / "cryptography" / "hazmat" / "bindings").mkdir(parents=True)
    (internal / "cryptography" / "hazmat" / "bindings" / "_rust.pyd").write_bytes(b"MZ OpenSSL 4.0.1 9 Jun 2026")
    (internal / "pycparser").mkdir()
    detail = _qt_problems(tmp_path)
    assert "notices do not state the Python runtime's OpenSSL ['3.0.99']" in detail
    assert "cffi's backend is not bundled" in detail and "pycparser is bundled" in detail
    assert "statically linked OpenSSL" not in detail  # 4.0.1 is stated


def test_the_new_qt_and_dependency_gate_is_not_an_artifact_claim_before_a_build():
    result = rg._artifact_qt_and_dependencies(ROOT, required=False)
    assert result.status is GateVerdict.PASS and "not required pre-build" in result.detail


# --- Qt attributions ----------------------------------------------------------------------------------------------------


def _generator():
    spec = importlib.util.spec_from_file_location("generate_qt_attributions", ROOT / "scripts" / "generate_qt_attributions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_listed_qt_component_has_a_notice_and_license_text_in_the_shipped_file():
    generator = _generator()
    text = _read("packaging/third_party_licenses/qt/QT_THIRD_PARTY_ATTRIBUTIONS.txt")
    assert text.startswith("QT THIRD-PARTY COMPONENT NOTICES (shipped Qt modules only)")
    for tree, directory, ident, shipped in generator.COMPONENTS:
        assert f"Component id : {ident}  (source: {tree}/{directory}/qt_attribution.json)" in text, ident
    for must_have in ("PCRE2", "FreeType", "HarfBuzz", "LibPNG", "Data Compression Library (zlib)", "Unicode Common Locale Data Repository",
                      "LibJPEG-turbo", "XSVG", "Wintab API", "The Public Suffix List"):
        assert must_have in text
    appendix = {m for m in re.findall(r"(?m)^=== (\S+) \(", text)}
    assert {"Apache-2.0", "Unicode-3.0", "CC0-1.0", "BSD-3-Clause", "IJG"} <= appendix
    details = text.split("COMPONENT DETAILS", 1)[1].split("APPENDIX: SPDX LICENSE TEXTS", 1)[0]
    # a component block starts with "### <name>" immediately followed by its "Component id" line (license texts may contain "###" too)
    blocks = re.split(r"(?m)^### (?=[^\n]*\nComponent id : )", details)[1:]
    assert len(blocks) == len(generator.COMPONENTS)
    for block in blocks:  # every component carries its own license text or points at an SPDX text that is in the appendix
        if "-- begin license text --" in block.replace("-" * 20, "--"):
            continue
        spdx = re.search(r"SPDX id\s+: (.+)", block).group(1)
        needed = {token for token in re.split(r"[ ()]+", spdx) if token and token not in ("AND", "OR", "WITH")}
        assert needed & appendix, (block.splitlines()[0], needed)
    # nothing for modules / platforms that do not ship
    for absent in ("SQLite", "libdbus", "Wayland", "Catch2", "Cocoa Platform Plugin", "Vulkan API Registry"):
        component_list = text.split("COMPONENTS\n----------", 1)[1].split("COMPONENT DETAILS", 1)[0]
        assert absent not in component_list  # the list names nothing for modules / platforms that do not ship


def test_notices_and_license_folder_describe_the_measured_package():
    notices = _read("packaging/THIRD_PARTY_NOTICES.txt")
    assert "pycparser, which cffi needs only to build its extension, is not bundled" in notices
    assert "License: BSD-3-Clause\n  (full text: third_party_licenses\\pycparser" not in notices
    assert "OpenSSL 3.0.16" in notices and "OpenSSL 4.0.1" in notices and "BZIP2-LICENSE.txt" in notices
    assert "QT_THIRD_PARTY_ATTRIBUTIONS.txt" in notices and "Microsoft Visual C++ runtime" in notices
    assert not (ROOT / "packaging" / "third_party_licenses" / "pycparser").exists()
    assert "third_party_licenses\\qt\\QT_THIRD_PARTY_ATTRIBUTIONS.txt" in _read("packaging/QT_LGPL_COMPLIANCE.txt")


# --- source offer -------------------------------------------------------------------------------------------------------

ARCHIVES = {
    "qtbase-everywhere-src-6.11.2.tar.xz": ("cb3b718e2e589b61bd781b4596604a5b", "5b2e00eccaf5a4d8c14134ffa0ea8dfd0a35ae1ffc7f8d87fa4305a1ed23cf22"),
    "qtsvg-everywhere-src-6.11.2.tar.xz": ("fb1c8366fe3de6ed3ca248bf4ae88c37", "d594337feca84c26fb67fe87b85e6a5c12fda404b611d905f9d138210c311876"),
    "pyside-setup-everywhere-src-6.11.2.tar.xz": (None, "cba47efbaad1bedd529725cbc14e21f156c7a19366f07b3edfbb076ffd7afdf8"),
}


def test_the_source_offer_lists_exactly_the_archives_the_shipped_libraries_come_from():
    offer = _read("packaging/QT_LGPL_COMPLIANCE.txt")
    evidence = INVENTORY.read_text(encoding="utf-8").replace("\r\n", "\n")
    for name, (md5, sha256) in ARCHIVES.items():
        assert name in offer and name in evidence, name
        assert sha256 in offer and sha256 in evidence, name
        if md5:
            assert md5 in offer and md5 in evidence, name
    for url in ("https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/", "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/"):
        assert url in offer and url in evidence
    assert "single" in offer  # the complete archive stays mentioned as a superset, never required


def test_the_inventory_document_records_the_real_build_and_the_replacement_proof():
    text = INVENTORY.read_text(encoding="utf-8")
    for needed in ("SHA-256", "Qt6Core.dll", "qwindows.dll", "pycparser", "libcrypto-3.dll", "OpenSSL 3.0.16", "OpenSSL 4.0.1", "replacement"):
        assert needed in text, needed
    assert not re.search(r"[A-Za-z]:\\Users\\", text), "the evidence document must not contain a personal path"


# --- documents ----------------------------------------------------------------------------------------------------------


def test_packaging_docs_describe_the_actual_pipeline():
    packaging = _read("docs/PACKAGING.md")
    signing = _read("docs/UPDATE_RELEASE_SIGNING.md")
    for needed in (".python-version", "--require-hashes", "lock_release_deps.py --check", "exactly once", "binary_manifest.json",
                   "leak_scan", "release-gate --require-artifact", "dry_run", "contaminated", "version_info_updater.txt"):
        assert needed in packaging, needed
    assert "pip install pyinstaller" not in packaging.lower()
    assert "Upload all assets to the GitHub Release" not in signing
    for needed in ("concurrency", "persist", "production-release", "dry_run", "smoke_disposable_update_tests.ps1", "main"):
        assert needed in signing, needed


def _spec_binary_filter(rows):
    """Apply the spec's own `a.binaries = [...]` comprehension (parsed from packaging/exilelens-gui.spec, not re-implemented) to rows."""
    import ast
    from types import SimpleNamespace

    tree = ast.parse(_read("packaging/exilelens-gui.spec"))
    namespace: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id.startswith("_") and node.targets[0].id.endswith("TOKENS"):
            namespace[node.targets[0].id] = eval(compile(ast.Expression(node.value), "spec", "eval"), {}, dict(namespace))  # noqa: S307
    target = next(n for n in tree.body if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "a.binaries")
    namespace["a"] = SimpleNamespace(binaries=rows)
    return eval(compile(ast.Expression(target.value), "spec", "eval"), {}, namespace)  # noqa: S307


def test_the_spec_filter_removes_every_gpl_only_and_unused_qt_binary_it_could_be_offered():
    rows = [(name, "src", "BINARY") for name in (
        "PySide6/Qt6VirtualKeyboard.dll", "PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll", "PySide6/Qt6Charts.dll",
        "PySide6/Qt6DataVisualization.dll", "PySide6/Qt6Graphs.dll", "PySide6/Qt6HttpServer.dll", "PySide6/Qt6NetworkAuth.dll",
        "PySide6/Qt6Pdf.dll", "PySide6/plugins/imageformats/qpdf.dll", "PySide6/Qt6Qml.dll", "PySide6/Qt6QmlModels.dll",
        "PySide6/Qt6Quick.dll", "PySide6/Qt6OpenGL.dll", "PySide6/opengl32sw.dll", "PySide6/plugins/imageformats/qwebp.dll",
        "PySide6/plugins/imageformats/qtiff.dll", "PySide6/plugins/imageformats/qtga.dll", "PySide6/plugins/imageformats/qicns.dll",
        "PySide6/plugins/imageformats/qwbmp.dll",
    )]
    keep = [(f"PySide6/{lib}.dll", "src", "BINARY") for lib in rg.EXPECTED_QT_LIBRARIES]
    keep += [(f"PySide6/plugins/{plugin}.dll", "src", "BINARY") for plugin in rg.EXPECTED_QT_PLUGINS]
    keep += [("python312.dll", "src", "BINARY"), ("cryptography/hazmat/bindings/_rust.pyd", "src", "EXTENSION")]
    assert _spec_binary_filter(rows + keep) == keep
