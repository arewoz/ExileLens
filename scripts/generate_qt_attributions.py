"""Generate packaging/third_party_licenses/qt/QT_THIRD_PARTY_ATTRIBUTIONS.txt from the official Qt 6.11.2 source metadata.

Input: the extracted official source archives (not committed; see docs/release-1.0/ARTIFACT_INVENTORY.md for URLs and hashes)
  qtbase-everywhere-src-6.11.2 and qtsvg-everywhere-src-6.11.2.
Every statement comes from a ``qt_attribution.json`` and every license text is copied verbatim from the component's own license file
or from the SPDX text under the module's ``LICENSES`` folder. Nothing here is written by hand.

Scope: only the Qt modules/plugins that really ship in ExileLens (QtCore, QtGui, QtWidgets, QtNetwork, QtSvg and the qwindows /
qjpeg / qgif / qico / qsvg / TLS / style plugins) and only components that Qt's metadata ties to Windows or to all platforms. macOS-,
Linux-, Android-, Wayland-, xcb-, ARM-only components, QtSql/QtDBus/QtTest and build-time-only data are not listed.

Usage: python scripts/generate_qt_attributions.py <dir with the two extracted trees> [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[1] / "packaging" / "third_party_licenses" / "qt" / "QT_THIRD_PARTY_ATTRIBUTIONS.txt"

#: (source tree, directory holding qt_attribution.json, component Id, shipped in)
COMPONENTS = (
    ("qtbase", "src/3rdparty/blake2", "blake2", "Qt6Core.dll"),
    ("qtbase", "src/3rdparty/double-conversion", "doubleconversion", "Qt6Core.dll"),
    ("qtbase", "src/3rdparty/easing", "easing", "Qt6Core.dll"),
    ("qtbase", "src/3rdparty/md4", "md4", "Qt6Core.dll"),
    ("qtbase", "src/3rdparty/md5", "md5", "Qt6Core.dll"),
    ("qtbase", "src/3rdparty/pcre2", "pcre2", "Qt6Core.dll"),
    ("qtbase", "src/3rdparty/pcre2", "pcre2-sljit", "Qt6Core.dll"),
    ("qtbase", "src/3rdparty/rfc6234", "rfc6234", "Qt6Core.dll"),
    ("qtbase", "src/3rdparty/sha1", "sha1", "Qt6Core.dll"),
    ("qtbase", "src/3rdparty/sha3", "sha3_endian", "Qt6Core.dll"),
    ("qtbase", "src/3rdparty/sha3", "sha3_keccak", "Qt6Core.dll"),
    ("qtbase", "src/3rdparty/siphash", "siphash", "Qt6Core.dll"),
    ("qtbase", "src/3rdparty/tinycbor", "tinycbor", "Qt6Core.dll"),
    ("qtbase", "src/3rdparty/zlib", "zlib", "Qt6Core.dll"),
    ("qtbase", "src/corelib/global", "tlexpected", "Qt6Core.dll (private headers)"),
    ("qtbase", "src/corelib/mimetypes/3rdparty", "tika-mimetypes", "Qt6Core.dll"),
    ("qtbase", "src/corelib/text", "unicode-character-database", "Qt6Core.dll"),
    ("qtbase", "src/corelib/text", "unicode-cldr", "Qt6Core.dll"),
    ("qtbase", "src/3rdparty/D3D12MemoryAllocator", "d3d12memoryallocator", "Qt6Gui.dll"),
    ("qtbase", "src/3rdparty/VulkanMemoryAllocator", "vulkanmemoryallocator", "Qt6Gui.dll"),
    ("qtbase", "src/3rdparty/emoji-segmenter", "emoji-segmenter", "Qt6Gui.dll"),
    ("qtbase", "src/3rdparty/freetype", "freetype", "Qt6Gui.dll, platform plugins"),
    ("qtbase", "src/3rdparty/freetype", "freetype-zlib", "Qt6Gui.dll, platform plugins"),
    ("qtbase", "src/3rdparty/freetype", "freetype-bdf", "Qt6Gui.dll, platform plugins"),
    ("qtbase", "src/3rdparty/freetype", "freetype-pcf", "Qt6Gui.dll, platform plugins"),
    ("qtbase", "src/gui/painting", "grayraster", "Qt6Gui.dll"),
    ("qtbase", "src/3rdparty/harfbuzz-ng", "harfbuzz-ng", "Qt6Gui.dll"),
    ("qtbase", "src/3rdparty/icc", "icc-srgb-color-profile", "Qt6Gui.dll"),
    ("qtbase", "src/3rdparty/libpng", "libpng", "Qt6Gui.dll"),
    ("qtbase", "src/3rdparty/md4c", "md4c", "Qt6Gui.dll"),
    ("qtbase", "src/gui/painting", "smooth-scaling-algorithm", "Qt6Gui.dll"),
    ("qtbase", "src/gui/painting", "xserverhelper", "Qt6Gui.dll"),
    ("qtbase", "src/gui/rhi", "rhi-miniengine-d3d12-mipmap", "Qt6Gui.dll"),
    ("qtbase", "src/gui/text", "aglfn", "Qt6Gui.dll"),
    ("qtbase", "src/gui/opengl", "opengl-headers", "Qt6Gui.dll (headers)"),
    ("qtbase", "src/gui/opengl", "opengl-es2-headers", "Qt6Gui.dll (headers)"),
    ("qtbase", "src/3rdparty/libpsl", "psl-data", "Qt6Network.dll"),
    ("qtbase", "src/3rdparty/libpsl", "libpsl", "Qt6Network.dll"),
    ("qtbase", "src/3rdparty/libjpeg", "libjpeg", "plugins\\imageformats\\qjpeg.dll"),
    ("qtbase", "src/3rdparty/wintab", "wintab", "plugins\\platforms\\qwindows.dll"),
    ("qtsvg", "src/svg", "xsvg", "Qt6Svg.dll"),
)
LICENSE_NAMES = {"AND", "OR", "WITH"}


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise AssertionError(path)


def _entry(root: Path, directory: str, ident: str) -> dict:
    path = root / directory / "qt_attribution.json"
    data = json.loads(_read_text(path), strict=False)
    entries = data if isinstance(data, list) else [data]
    for item in entries:
        if item.get("Id") == ident:
            return item
    raise SystemExit(f"{path}: no component {ident!r}")


def _spdx_ids(expression: str) -> list[str]:
    return [token for token in expression.replace("(", " ").replace(")", " ").split() if token not in LICENSE_NAMES]


def render(trees: dict[str, Path]) -> str:
    out: list[str] = []
    versions = {name: tree.name for name, tree in trees.items()}
    out.append("QT THIRD-PARTY COMPONENT NOTICES (shipped Qt modules only)")
    out.append("=" * 60)
    out.append("")
    out.append("ExileLens uses Qt " + versions["qtbase"].rsplit("-", 1)[-1] + " under the LGPL-3.0 (see QT_LGPL_COMPLIANCE.txt). The Qt libraries")
    out.append("that ship in this package contain the third-party components below. This list is generated from the official Qt source")
    out.append("metadata (qt_attribution.json) of " + ", ".join(sorted(versions.values())) + ";")
    out.append("license texts are copied verbatim from the component's own license file or from the SPDX texts in the Qt source")
    out.append("LICENSES folders. Components that Qt ties only to other platforms (macOS, Linux, Android, Wayland, xcb, ARM) or to Qt")
    out.append("modules that are not shipped (SQL, D-Bus, Test, Quick, PDF, WebEngine, ...) are not listed.")
    out.append("")
    spdx_needed: dict[str, Path] = {}
    out.append("COMPONENTS")
    out.append("-" * 10)
    bodies: list[str] = []
    for tree, directory, ident, shipped in COMPONENTS:
        root = trees[tree]
        item = _entry(root, directory, ident)
        out.append(f"  {item.get('Name', ident)}  [{item.get('LicenseId', '?')}]  in {shipped}")
        block = [f"### {item.get('Name', ident)}", f"Component id : {ident}  (source: {tree}/{directory}/qt_attribution.json)",
                 f"Shipped in   : {shipped}"]
        for label, key in (("Version", "Version"), ("Used for", "QtUsage"), ("Description", "Description"), ("Homepage", "Homepage"),
                           ("License", "License"), ("SPDX id", "LicenseId")):
            if item.get(key):
                block.append(f"{label:<13}: {' '.join(str(item[key]).split())}")
        copyright_ = item.get("Copyright")
        if copyright_:
            rows = copyright_ if isinstance(copyright_, list) else [copyright_]
            block.append("Copyright    :")
            block.extend("  " + " ".join(str(row).split()) for row in rows)
        license_file = item.get("LicenseFile")
        if license_file:
            path = (root / directory / license_file).resolve()
            block.append(f"License file : {license_file}")
            block.append("-" * 20 + " begin license text " + "-" * 20)
            block.append(_read_text(path).rstrip("\n"))
            block.append("-" * 20 + " end license text " + "-" * 22)
        else:
            for spdx in _spdx_ids(str(item.get("LicenseId", ""))):
                candidate = root / "LICENSES" / f"{spdx}.txt"
                if candidate.is_file():
                    spdx_needed.setdefault(spdx, candidate)
            block.append("License text : see the SPDX license text(s) in the appendix below.")
        bodies.append("\n".join(block))
    out.append("")
    out.append("COMPONENT DETAILS")
    out.append("-" * 17)
    out.append("")
    out.append("\n\n".join(bodies))
    out.append("")
    out.append("APPENDIX: SPDX LICENSE TEXTS (verbatim from the Qt source LICENSES folders)")
    out.append("-" * 73)
    for spdx in sorted(spdx_needed):
        out.append("")
        out.append(f"=== {spdx} ({spdx_needed[spdx].parent.parent.name}/LICENSES/{spdx}.txt) ===")
        out.append(_read_text(spdx_needed[spdx]).rstrip("\n"))
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path, help="folder containing the extracted qtbase-everywhere-src-* and qtsvg-everywhere-src-* trees")
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed file differs")
    args = parser.parse_args(argv)
    trees = {}
    for name in ("qtbase", "qtsvg"):
        matches = sorted(args.sources.glob(f"{name}-everywhere-src-*"))
        if len(matches) != 1:
            raise SystemExit(f"expected exactly one {name}-everywhere-src-* folder in {args.sources}")
        trees[name] = matches[0]
    text = render(trees).replace("\r\n", "\n")
    if args.check:
        current = OUTPUT.read_bytes().decode("utf-8").replace("\r\n", "\n") if OUTPUT.is_file() else ""
        if current != text:
            print("QT_THIRD_PARTY_ATTRIBUTIONS.txt is stale", file=sys.stderr)
            return 1
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(text.encode("utf-8"))
    print(f"wrote {OUTPUT} ({len(text)} chars, {len(COMPONENTS)} components)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
