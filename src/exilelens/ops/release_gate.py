"""Release gate: PASS or BLOCKED from executable checks. No invented numeric score."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from exilelens import SUPPORTED_POB_HEAD, __version__
from exilelens.ops.compatibility import load_manifest, validate_against_code
from exilelens.ops.models import CheckResult, CompatibilityStatus, GateVerdict, Severity
from exilelens.ops.paths import repo_root
from exilelens.ops.packaging_version import EXECUTABLES, UPDATER, render_version_info
from exilelens.ops.regression import load_registry

#: Verified third-party license material that ships in the package, byte-for-byte as committed under packaging/third_party_licenses
#: (provenance: that folder's README.txt and docs/1.0-HARDENING-PLAN.md). Identity is checked by comparing the packaged copy with the
#: committed one, never by size.
THIRD_PARTY_LICENSE_FILES = (
    "packaging/third_party_licenses/README.txt",
    "packaging/third_party_licenses/qt/LGPL-3.0.txt",
    "packaging/third_party_licenses/qt/GPL-3.0.txt",
    "packaging/third_party_licenses/qt/QT_THIRD_PARTY_ATTRIBUTIONS.txt",
    "packaging/third_party_licenses/python/LICENSE.txt",
    "packaging/third_party_licenses/python/LICENSES-incorporated-software.rst",
    "packaging/third_party_licenses/python/BZIP2-LICENSE.txt",
    "packaging/third_party_licenses/openssl/LICENSE.txt",
    "packaging/third_party_licenses/cryptography/LICENSE",
    "packaging/third_party_licenses/cryptography/LICENSE.APACHE",
    "packaging/third_party_licenses/cryptography/LICENSE.BSD",
    "packaging/third_party_licenses/cryptography/SBOM-openssl.json",
    "packaging/third_party_licenses/cryptography/SBOM-rust-crates.cyclonedx.json",
    "packaging/third_party_licenses/cffi/LICENSE",
    "packaging/third_party_licenses/pyinstaller/COPYING.txt",
)

#: What must sit next to ExileLens.exe in the release package: (name in dist/ExileLens, committed source).
DISTRIBUTION_FILES = (
    ("README.txt", "packaging/README.txt"),
    ("LICENSE", "LICENSE"),
    ("THIRD_PARTY_NOTICES.txt", "packaging/THIRD_PARTY_NOTICES.txt"),
    ("QT_LGPL_COMPLIANCE.txt", "packaging/QT_LGPL_COMPLIANCE.txt"),
)

#: Qt binaries that have no LGPL option in the official 6.11.2 sources (GPL-3.0 or commercial only: checked in the qtvirtualkeyboard,
#: qtcharts, qtdatavis3d, qtgraphs, qthttpserver and qtnetworkauth source archives). ExileLens uses Qt under the LGPL, so none may
#: ship. Keep in sync with `_GPL_ONLY_QT_BINARY_TOKENS` in packaging/exilelens-gui.spec (a test compares the two).
GPL_ONLY_QT_BINARY_TOKENS = (
    "qt6virtualkeyboard",
    "qtvirtualkeyboardplugin",
    "qt6charts",
    "qt6datavisualization",
    "qt6graphs",
    "qt6httpserver",
    "qt6networkauth",
)

#: Qt binaries that are not licence-forbidden but that ExileLens does not use and that PyInstaller's PySide6 hooks collect anyway (Qt Quick/
#: Qml, Qt PDF and its image plugin, Qt6OpenGL, the software OpenGL renderer, the qtimageformats plugins). They are removed so the shipped
#: Qt surface stays inside the qtbase and qtsvg source modules that the LGPL source offer and the Qt attributions cover. Keep in sync with
#: `_UNUSED_QT_BINARY_TOKENS` in packaging/exilelens-gui.spec (a test compares the two).
UNUSED_QT_BINARY_TOKENS = (
    "qt6pdf",
    "imageformats/qpdf",
    "qt6qml",
    "qt6quick",
    "qt6opengl",
    "opengl32sw",
    "imageformats/qicns",
    "imageformats/qtga",
    "imageformats/qtiff",
    "imageformats/qwbmp",
    "imageformats/qwebp",
)

#: The approved shipped Qt surface, measured from the real 1.0-C build (docs/release-1.0/ARTIFACT_INVENTORY.md). Any other Qt library or
#: plugin in a built package blocks the release until it is reviewed against the Qt licensing metadata and the source offer.
EXPECTED_QT_LIBRARIES = ("Qt6Core", "Qt6Gui", "Qt6Network", "Qt6Svg", "Qt6Widgets")
EXPECTED_QT_PLUGINS = (
    "generic/qtuiotouchplugin",
    "iconengines/qsvgicon",
    "imageformats/qgif",
    "imageformats/qico",
    "imageformats/qjpeg",
    "imageformats/qsvg",
    "networkinformation/qnetworklistmanager",
    "platforms/qdirect2d",
    "platforms/qminimal",
    "platforms/qoffscreen",
    "platforms/qwindows",
    "styles/qmodernwindowsstyle",
    "tls/qcertonlybackend",
    "tls/qopensslbackend",
    "tls/qschannelbackend",
)

REQUIRED_PACKAGING = (
    "LICENSE",
    "packaging/THIRD_PARTY_NOTICES.txt",
    "packaging/QT_LGPL_COMPLIANCE.txt",
    "packaging/requirements-release.lock",
    ".python-version",
    *THIRD_PARTY_LICENSE_FILES,
    "packaging/CHANGELOG.txt",
    "packaging/RELEASE_NOTES.md",
    "packaging/README.txt",
    "packaging/version_info.txt",
    "packaging/version_info_updater.txt",
    "scripts/validate_release_binary_provenance.py",
    "src/exilelens/whats_new/whats_new.json",
    "packaging/exilelens-gui.spec",
    "packaging/exilelens-updater.spec",
    "scripts/build_exe.ps1",
    "scripts/build_updater.ps1",
    "scripts/create_desktop_shortcut.ps1",
    "scripts/generate_packaging_version_info.py",
)


@dataclass
class ReleaseGateReport:
    verdict: GateVerdict
    blockers: list[CheckResult] = field(default_factory=list)
    warnings: list[CheckResult] = field(default_factory=list)
    passed: list[CheckResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": f"RELEASE GATE: {self.verdict.value}",
            "verdict": self.verdict.value,
            "blockers": [item.to_dict() for item in self.blockers],
            "warnings": [item.to_dict() for item in self.warnings],
            "passed": [item.to_dict() for item in self.passed],
        }

    def format_text(self) -> str:
        lines = [f"RELEASE GATE: {self.verdict.value}"]
        if self.blockers:
            lines.append("BLOCKERS:")
            for item in self.blockers:
                sev = item.severity.value if item.severity else "P1"
                lines.append(f"  [{sev}] {item.name}: {item.detail}")
        if self.warnings:
            lines.append("WARNINGS:")
            for item in self.warnings:
                sev = item.severity.value if item.severity else "P2"
                lines.append(f"  [{sev}] {item.name}: {item.detail}")
        return "\n".join(lines)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def _version_files_coherent(root: Path) -> CheckResult:
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    version_info_path = root / "packaging" / "version_info.txt"
    version_info = version_info_path.read_text(encoding="utf-8")
    changelog = (root / "packaging" / "CHANGELOG.txt").read_text(encoding="utf-8")
    readme = (root / "packaging" / "README.txt").read_text(encoding="utf-8")
    missing = []
    if "exilelens._version.__version__" not in pyproject:
        missing.append("pyproject.toml dynamic version source")
    if version_info != render_version_info():
        missing.append("packaging/version_info.txt (regenerate with scripts/generate_packaging_version_info.py)")
    updater_info_path = root / "packaging" / "version_info_updater.txt"
    if not updater_info_path.is_file() or updater_info_path.read_text(encoding="utf-8") != render_version_info(identity=UPDATER):
        missing.append("packaging/version_info_updater.txt (regenerate with scripts/generate_packaging_version_info.py)")
    if __version__ not in changelog:
        missing.append("packaging/CHANGELOG.txt")
    if __version__ not in readme:
        missing.append("packaging/README.txt")
    manifest_path = root / "ops" / "compatibility.json"
    if manifest_path.is_file():
        import json

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("exilelens_version") != __version__:
            missing.append("ops/compatibility.json exilelens_version")
    if missing:
        return CheckResult(
            "version_coherence",
            GateVerdict.BLOCKED,
            Severity.P0,
            f"version {__version__} missing or stale in {', '.join(missing)}",
        )
    return CheckResult("version_coherence", GateVerdict.PASS, detail=f"version {__version__}")


def _whats_new(root: Path) -> CheckResult:
    """The candidate version must have a valid, player-facing entry in the packaged What's New content."""
    import json

    from exilelens.app.updates.version import ExileLensVersion
    from exilelens.whats_new import content

    path = root / "src" / "exilelens" / "whats_new" / content.CONTENT_FILE
    try:
        catalog = content.parse_document(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, UnicodeError) as exc:
        return CheckResult("whats_new", GateVerdict.BLOCKED, Severity.P1, f"whats_new.json unusable: {exc}")
    candidate = ExileLensVersion.parse(__version__)
    if candidate is None:
        return CheckResult("whats_new", GateVerdict.BLOCKED, Severity.P1, f"version {__version__!r} is not a release version")
    problems = content.lint_catalog(catalog, candidate)
    if problems:
        return CheckResult("whats_new", GateVerdict.BLOCKED, Severity.P1, "; ".join(problems[:8]))
    return CheckResult("whats_new", GateVerdict.PASS, detail=f"entry for {candidate} is valid")


def _release_tag_coherent(root: Path) -> CheckResult:
    tag = _git(root, "describe", "--tags", "--exact-match")
    if not tag:
        return CheckResult("release_tag", GateVerdict.PASS, detail="HEAD has no exact release tag")
    normalized = tag[1:] if tag.startswith("v") else tag
    if normalized != __version__:
        return CheckResult(
            "release_tag",
            GateVerdict.BLOCKED,
            Severity.P0,
            f"tag {tag!r} != canonical version {__version__!r}",
        )
    return CheckResult("release_tag", GateVerdict.PASS, detail=f"tag {tag}")


def _compatibility(root: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    try:
        manifest = load_manifest(root / "ops" / "compatibility.json")
    except Exception as exc:  # noqa: BLE001 — gate must stay runnable
        return [CheckResult("compatibility_manifest", GateVerdict.BLOCKED, Severity.P0, str(exc))]
    results.append(CheckResult("compatibility_manifest", GateVerdict.PASS, detail="manifest parsed"))
    if manifest.game_status in {CompatibilityStatus.BROKEN.value, CompatibilityStatus.UNVERIFIED.value}:
        severity = Severity.P0 if manifest.game_status == CompatibilityStatus.BROKEN.value else Severity.P1
        results.append(
            CheckResult(
                "game_compatibility",
                GateVerdict.BLOCKED if manifest.game_status == CompatibilityStatus.BROKEN.value else GateVerdict.WARN,
                severity,
                f"game.status={manifest.game_status} version={manifest.game_version!r}",
            )
        )
    else:
        results.append(CheckResult("game_compatibility", GateVerdict.PASS, detail=manifest.game_status))
    if manifest.pob_status == CompatibilityStatus.BROKEN.value:
        results.append(CheckResult("pob_compatibility", GateVerdict.BLOCKED, Severity.P0, "PoB marked BROKEN"))
    elif manifest.pob_verified_commit != SUPPORTED_POB_HEAD:
        results.append(
            CheckResult(
                "pob_compatibility",
                GateVerdict.BLOCKED,
                Severity.P0,
                "manifest PoB commit != SUPPORTED_POB_HEAD",
            )
        )
    else:
        results.append(CheckResult("pob_compatibility", GateVerdict.PASS, detail=manifest.pob_verified_commit[:12]))
    for warning in validate_against_code(manifest, root=root):
        results.append(CheckResult("compatibility_consistency", GateVerdict.WARN, Severity.P2, warning))
    return results


def _p0_registry(root: Path) -> CheckResult:
    try:
        entries = load_registry(root / "ops" / "regression_registry.json", root=root)
    except Exception as exc:  # noqa: BLE001 — gate must report invalid release inputs
        return CheckResult("known_p0", GateVerdict.BLOCKED, Severity.P0, f"regression registry unavailable: {exc}")
    uncovered_p0 = [entry for entry in entries if entry.severity == "P0" and entry.status != "covered"]
    if uncovered_p0:
        return CheckResult(
            "known_p0",
            GateVerdict.BLOCKED,
            Severity.P0,
            "P0 regressions lacking verified coverage: " + ", ".join(entry.id for entry in uncovered_p0),
        )
    return CheckResult(
        "known_p0",
        GateVerdict.PASS,
        detail="all required P0 entries declare verified source evidence; execution is required separately",
    )


def _dirty_tree(root: Path, *, allow_dirty: bool) -> CheckResult:
    porcelain = _git(root, "status", "--porcelain")
    if not porcelain:
        return CheckResult("git_tree", GateVerdict.PASS, detail="clean")
    if allow_dirty:
        return CheckResult("git_tree", GateVerdict.WARN, Severity.P2, "dirty tree allowed by flag")
    return CheckResult("git_tree", GateVerdict.BLOCKED, Severity.P1, "working tree is dirty")


def _packaging(root: Path) -> CheckResult:
    missing = [rel for rel in REQUIRED_PACKAGING if not (root / rel).is_file()]
    if missing:
        return CheckResult("packaging_files", GateVerdict.BLOCKED, Severity.P0, "missing " + ", ".join(missing))
    return CheckResult("packaging_files", GateVerdict.PASS, detail="required packaging files present")


def _locked_version(root: Path, name: str) -> str | None:
    """The exact pinned version of `name` in the hash-locked release requirements, or None."""
    import re

    lock = root / "packaging" / "requirements-release.lock"
    if not lock.is_file():
        return None
    match = re.search(rf"(?mi)^{re.escape(name)}==([0-9][^\s\\;]*)", lock.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _license_documentation_problems(root: Path) -> list[str]:
    """Source-level consistency of the licensing documentation with what the release actually pins. Proves the documents agree with
    the lock; it does NOT prove what a built package contains (that is the artifact check below and the 1.0-C inventory)."""
    import json

    problems: list[str] = []
    notices = root / "packaging" / "THIRD_PARTY_NOTICES.txt"
    qt_doc = root / "packaging" / "QT_LGPL_COMPLIANCE.txt"
    notices_text = notices.read_text(encoding="utf-8") if notices.is_file() else ""
    qt_text = qt_doc.read_text(encoding="utf-8") if qt_doc.is_file() else ""
    pin_file = root / ".python-version"
    python_version = pin_file.read_text(encoding="utf-8").strip() if pin_file.is_file() else ""
    expected = [("Python runtime " + python_version, "the pinned Python (.python-version)")] if python_version else []
    for package, phrase in (
        ("pyinstaller", "bootloader and bundling tools {v}"),
        ("PySide6", "PySide6 {v}"),
        ("shiboken6", "shiboken6 {v}"),
        ("cryptography", "cryptography {v}"),
        ("cffi", "cffi {v}"),
    ):
        version = _locked_version(root, package)
        if version is None:
            problems.append(f"{package} is not pinned in packaging/requirements-release.lock")
            continue
        expected.append((phrase.format(v=version), f"{package} {version} (release lock)"))
    for phrase, what in expected:
        if phrase not in notices_text:
            problems.append(f"THIRD_PARTY_NOTICES.txt does not name {what}")
    qt_version = _locked_version(root, "PySide6")
    if qt_version and (f"Qt                 {qt_version}" not in qt_text or f"PySide6            {qt_version}" not in qt_text):
        problems.append(f"QT_LGPL_COMPLIANCE.txt does not state Qt/PySide6 {qt_version} (release lock)")
    if "written offer" not in qt_text.lower() and "source code offer" not in qt_text.lower():
        problems.append("QT_LGPL_COMPLIANCE.txt has no source code offer")
    sbom = root / "packaging" / "third_party_licenses" / "cryptography" / "SBOM-openssl.json"
    if sbom.is_file():
        try:
            versions = {c.get("version") for c in json.loads(sbom.read_text(encoding="utf-8")).get("components", []) if c.get("name") == "openssl"}
        except (OSError, ValueError):
            versions = set()
        if not versions or not all(f"OpenSSL {v}" in notices_text for v in versions):
            problems.append("THIRD_PARTY_NOTICES.txt does not state the OpenSSL version recorded in the cryptography wheel SBOM")
    return problems


def _distribution_files(root: Path, *, required: bool = False) -> CheckResult:
    """The project LICENSE, the third-party notices, the Qt compliance notice and the verified license texts must ship in the package
    (not only live in the repo), byte-identical to the committed copies."""
    problems: list[str] = []
    build = root / "scripts" / "build_exe.ps1"
    build_text = build.read_text(encoding="utf-8") if build.is_file() else ""
    for token in ('"LICENSE"', "THIRD_PARTY_NOTICES.txt", "QT_LGPL_COMPLIANCE.txt", "third_party_licenses"):
        if token not in build_text:
            problems.append(f"scripts/build_exe.ps1 does not copy {token.strip(chr(34))} into dist")
    notices = root / "packaging" / "THIRD_PARTY_NOTICES.txt"
    notices_text = notices.read_text(encoding="utf-8") if notices.is_file() else ""
    for rel in THIRD_PARTY_LICENSE_FILES[1:]:
        folder_and_file = "third_party_licenses\\" + rel.split("third_party_licenses/", 1)[1].replace("/", "\\")
        if folder_and_file not in notices_text:
            problems.append(f"THIRD_PARTY_NOTICES.txt does not reference {folder_and_file}")
    if "QT_LGPL_COMPLIANCE.txt" not in notices_text:
        problems.append("THIRD_PARTY_NOTICES.txt does not point to QT_LGPL_COMPLIANCE.txt")
    problems.extend(_license_documentation_problems(root))
    if required:
        dist = root / "dist" / "ExileLens"
        for name, source_rel in DISTRIBUTION_FILES:
            shipped, source = dist / name, root / source_rel
            if not shipped.is_file():
                problems.append(f"dist/ExileLens/{name} missing from the package")
            elif source.is_file() and shipped.read_bytes() != source.read_bytes():
                problems.append(f"dist/ExileLens/{name} differs from {source_rel}")
        for rel in THIRD_PARTY_LICENSE_FILES:
            inner = rel.split("third_party_licenses/", 1)[1]
            shipped, source = dist / "third_party_licenses" / inner, root / rel
            if not shipped.is_file():
                problems.append(f"dist/ExileLens/third_party_licenses/{inner} missing from the package")
            elif source.is_file() and shipped.read_bytes() != source.read_bytes():
                problems.append(f"dist/ExileLens/third_party_licenses/{inner} differs from {rel}")
    if problems:
        return CheckResult("distribution_files", GateVerdict.BLOCKED, Severity.P0, "; ".join(problems))
    return CheckResult("distribution_files", GateVerdict.PASS, detail="license material is documented, consistent with the lock and packaged")


def _gpl_only_qt(root: Path, *, required: bool = False) -> CheckResult:
    """No Qt binary that lacks an LGPL option may be intentionally bundled. Source level: the spec filters them out. Built artifact
    (--require-artifact): no such file is present in dist. A passing result is NOT a claim about the full Qt module inventory, which
    is a separate, still-open release step."""
    import re

    problems: list[str] = []
    spec = root / "packaging" / "exilelens-gui.spec"
    spec_text = spec.read_text(encoding="utf-8") if spec.is_file() else ""
    match = re.search(r"_GPL_ONLY_QT_BINARY_TOKENS\s*=\s*\(([^)]*)\)", spec_text)
    if match is None:
        problems.append("packaging/exilelens-gui.spec does not filter the GPL-only Qt binaries")
    else:
        in_spec = tuple(re.findall(r'"([^"]+)"', match.group(1)))
        if in_spec != GPL_ONLY_QT_BINARY_TOKENS:
            problems.append("packaging/exilelens-gui.spec _GPL_ONLY_QT_BINARY_TOKENS differs from the release gate list")
        if "a.binaries = [" not in spec_text:
            problems.append("packaging/exilelens-gui.spec defines the GPL-only token list but never applies it to a.binaries")
    unused = re.search(r"_UNUSED_QT_BINARY_TOKENS\s*=\s*\(([^)]*)\)", spec_text)
    if unused is None or tuple(re.findall(r'"([^"]+)"', unused.group(1))) != UNUSED_QT_BINARY_TOKENS:
        problems.append("packaging/exilelens-gui.spec _UNUSED_QT_BINARY_TOKENS differs from the release gate list")
    for forbidden in ("PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtHttpServer", "PySide6.QtNetworkAuth"):
        quoted = f'"{forbidden}"'
        if spec_text.count(quoted) != 1:  # present exactly once: in `excludes`, never in `hiddenimports`
            problems.append(f"{forbidden} must be listed once, in the spec excludes")
    if required:
        dist = root / "dist" / "ExileLens"
        found = sorted(
            {str(path.relative_to(dist)) for path in dist.rglob("*") if path.is_file() and any(token in path.name.lower() for token in GPL_ONLY_QT_BINARY_TOKENS)}
        ) if dist.is_dir() else []
        if found:
            problems.append("GPL-only Qt binaries in the package: " + ", ".join(found[:6]))
    if problems:
        return CheckResult("gpl_only_qt", GateVerdict.BLOCKED, Severity.P0, "; ".join(problems))
    return CheckResult("gpl_only_qt", GateVerdict.PASS, detail="the spec filters the GPL-only Qt binaries" + ("; none in the built package" if required else ""))


#: Current shipped/public release surfaces. Historical docs (plans, changelog history, R-milestone records) are deliberately NOT scanned.
SHIPPING_COPY_FILES = ("packaging/README.txt", "README.md", "PRIVACY.md", "packaging/RELEASE_NOTES.md", "src/exilelens/whats_new/whats_new.json")
#: Product claims that are false for every build since R5-C / R2.
_STALE_ALWAYS = (
    (r"value for my build", "removed Build Value / price rating"),
    (r"power\s*/\s*cost", "removed Build Value / price rating"),
    (r"value\s*/\s*cost", "removed Build Value / price rating"),
    (r"best value", "removed Build Value / price rating"),
    (r"no analytics", "claims there is no analytics/telemetry (optional usage statistics and error reports exist)"),
    (r"telemetry system", "claims there is no analytics/telemetry (optional usage statistics and error reports exist)"),
)
#: "Early beta" copy: stale as soon as the version is a final release; always stale on the two files below.
_BETA_PATTERNS = (r"early beta", r"still in beta", r"current beta", r"beta page", r"in this beta")
_BETA_ALWAYS_FILES = ("packaging/README.txt", "README.md")
_LIVE_MARKET = r"live market pric"
_NEGATION = r"\b(not|no|never|isn't|without)\b"


def _shipping_copy(root: Path) -> CheckResult:
    """Reject known stale production claims on the current shipped/public surfaces (never the repository's history)."""
    import re

    final = "b" not in __version__.rsplit(".", 1)[-1]
    hits: list[str] = []
    for rel in SHIPPING_COPY_FILES:
        path = root / rel
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            lowered = line.lower()
            for pattern, why in _STALE_ALWAYS:
                if re.search(pattern, lowered):
                    hits.append(f"{rel}:{number} ({why})")
            if (final or rel in _BETA_ALWAYS_FILES) and any(re.search(pattern, lowered) for pattern in _BETA_PATTERNS):
                hits.append(f"{rel}:{number} (beta wording)")
            if re.search(_LIVE_MARKET, lowered) and not re.search(_NEGATION, lowered):
                hits.append(f"{rel}:{number} (implies live market pricing is available)")
    if hits:
        return CheckResult("shipping_copy", GateVerdict.BLOCKED, Severity.P0, "stale shipping copy: " + "; ".join(hits[:8]))
    return CheckResult("shipping_copy", GateVerdict.PASS, detail="no known stale claims on the shipped/public copy")


def _debug_deps(root: Path) -> CheckResult:
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    # Runtime deps must not include pytest/pyinstaller.
    runtime = pyproject.split("[project.optional-dependencies]", 1)[0]
    accidental = [name for name in ("pytest", "pyinstaller") if name in runtime]
    if accidental:
        return CheckResult(
            "debug_dependencies",
            GateVerdict.BLOCKED,
            Severity.P1,
            "dev-only packages listed as runtime: " + ", ".join(accidental),
        )
    return CheckResult("debug_dependencies", GateVerdict.PASS, detail="runtime deps do not include pytest/pyinstaller")


def _expected_artifact(root: Path, *, required: bool = False) -> CheckResult:
    exe = root / "dist" / "ExileLens" / "ExileLens.exe"
    updater = root / "dist" / "ExileLens" / "_internal" / "ExileLensUpdater.exe"
    stamp = root / "dist" / "ExileLens" / "build_stamp.json"
    if not exe.is_file():
        return CheckResult(
            "release_artifact",
            GateVerdict.BLOCKED if required else GateVerdict.WARN,
            Severity.P0 if required else Severity.P2,
            "dist/ExileLens/ExileLens.exe not built (run scripts/build_exe.ps1 for a packaged release)",
        )
    if required and not updater.is_file():
        return CheckResult(
            "release_updater",
            GateVerdict.BLOCKED,
            Severity.P0,
            "dist/ExileLens/_internal/ExileLensUpdater.exe missing (build_exe.ps1 must stage the updater)",
        )
    if required and not stamp.is_file():
        return CheckResult(
            "release_build_stamp",
            GateVerdict.BLOCKED,
            Severity.P0,
            "dist/ExileLens/build_stamp.json missing from packaged build",
        )
    detail = str(exe)
    if updater.is_file():
        detail += f"; updater={updater}"
    return CheckResult("release_artifact", GateVerdict.PASS, detail=detail)


def _artifact_provenance(root: Path, *, required: bool = False) -> CheckResult:
    if not required:
        return CheckResult("artifact_provenance", GateVerdict.PASS, detail="not required pre-build")
    stamp_path = root / "dist" / "ExileLens" / "build_stamp.json"
    if not stamp_path.is_file():
        return CheckResult(
            "artifact_provenance",
            GateVerdict.BLOCKED,
            Severity.P0,
            "build_stamp.json missing",
        )
    import json

    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, UnicodeError) as exc:
        return CheckResult("artifact_provenance", GateVerdict.BLOCKED, Severity.P0, f"invalid build_stamp.json: {exc}")
    if not isinstance(stamp, dict):
        return CheckResult("artifact_provenance", GateVerdict.BLOCKED, Severity.P0, "build_stamp.json must be an object")
    head = _git(root, "rev-parse", "HEAD")
    stamp_commit = str(stamp.get("git_commit") or "").strip().lower()
    if not head or stamp_commit != head:
        return CheckResult(
            "artifact_provenance",
            GateVerdict.BLOCKED,
            Severity.P0,
            f"build_stamp git_commit {stamp_commit!r} != HEAD {head!r}",
        )
    stamp_version = str(stamp.get("version") or "").strip()
    if stamp_version != __version__:
        return CheckResult(
            "artifact_provenance",
            GateVerdict.BLOCKED,
            Severity.P0,
            f"build_stamp version {stamp_version!r} != canonical {__version__!r}",
        )
    if stamp.get("product") != "ExileLens" or stamp.get("schema_version") != 1:
        return CheckResult(
            "artifact_provenance",
            GateVerdict.BLOCKED,
            Severity.P0,
            "build_stamp product/schema_version mismatch",
        )
    return CheckResult("artifact_provenance", GateVerdict.PASS, detail=f"stamp matches HEAD and v{__version__}")


def _spec_audit(root: Path) -> CheckResult:
    """PRE-BUILD: both PyInstaller specs are configured as claimed (spec-aware, not whole-file text). Does not prove a built artifact."""
    from exilelens.ops.packaging_spec import audit_specs

    problems = audit_specs(root)
    if problems:
        return CheckResult("spec_audit", GateVerdict.BLOCKED, Severity.P0, "; ".join(problems))
    return CheckResult("spec_audit", GateVerdict.PASS, detail="GUI (onedir) and updater (onefile) specs match the release configuration")


def _artifact_executables(root: Path, *, required: bool = False) -> CheckResult:
    """POST-BUILD: both executables carry the one canonical version, and binary_manifest.json covers both byte-for-byte."""
    if not required:
        return CheckResult("artifact_executables", GateVerdict.PASS, detail="not required pre-build (pre-build checks the configuration only)")
    import json
    import re

    from exilelens.ops.binary_provenance import GUI_EXE, UPDATER_REL, sha256_file
    from exilelens.ops.pe_version import read_version_strings

    dist = root / "dist" / "ExileLens"
    problems: list[str] = []
    paths = {"gui": dist / GUI_EXE, "updater": dist / UPDATER_REL}
    for identity in EXECUTABLES:
        path = paths[identity.role]
        if not path.is_file():
            problems.append(f"{identity.file_name} missing from the package")
            continue
        strings = read_version_strings(path)
        if strings is None:
            problems.append(f"{identity.file_name} has no readable Windows version resource")
            continue
        expected = {
            "FileVersion": __version__, "ProductVersion": __version__, "ProductName": "ExileLens", "CompanyName": "ExileLens",
            "FileDescription": identity.description, "OriginalFilename": identity.file_name, "InternalName": identity.internal_name,
        }
        for key, want in expected.items():
            if strings.get(key) != want:
                problems.append(f"{identity.file_name} {key}={strings.get(key)!r}, expected {want!r}")
    manifest_path = dist / "binary_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = None
    if not isinstance(manifest, dict):
        problems.append("binary_manifest.json missing or unreadable")
    else:
        if manifest.get("schema_version") != 2:
            problems.append("binary_manifest.json is not schema 2 (both executables recorded)")
        head = _git(root, "rev-parse", "HEAD")
        if manifest.get("git_commit") != head:
            problems.append("binary_manifest.json git_commit != HEAD")
        if manifest.get("application_version") != __version__:
            problems.append("binary_manifest.json application_version != canonical version")
        pin = root / ".python-version"
        if pin.is_file() and manifest.get("python_version") != pin.read_text(encoding="utf-8").strip():
            problems.append("binary_manifest.json python_version != .python-version")
        for key in ("pyinstaller_version", "architecture", "build_timestamp_utc", "release_lock_sha256"):
            if not manifest.get(key) or manifest.get(key) in ("unknown", "missing"):
                problems.append(f"binary_manifest.json {key} not recorded")
        recorded = {row.get("role"): row for row in manifest.get("executables", []) if isinstance(row, dict)}
        for identity in EXECUTABLES:
            row, path = recorded.get(identity.role), paths[identity.role]
            if row is None:
                problems.append(f"binary_manifest.json has no entry for {identity.file_name}")
            elif path.is_file() and (row.get("sha256") != sha256_file(path) or row.get("size") != path.stat().st_size):
                problems.append(f"binary_manifest.json hash/size for {identity.file_name} does not match the packaged file")
        listed = {row.get("relative_path"): row.get("sha256") for row in manifest.get("binaries", []) if isinstance(row, dict)}
        native = [p for p in dist.rglob("*") if p.is_file() and p.suffix.lower() in (".exe", ".dll", ".pyd")]
        unlisted = [p.relative_to(dist).as_posix() for p in native if listed.get(p.relative_to(dist).as_posix()) != sha256_file(p)]
        if unlisted:
            problems.append(f"{len(unlisted)} native file(s) missing from / different in binary_manifest.json, e.g. {unlisted[0]}")
        if re.search(r"[A-Za-z]:[\\/]", manifest_path.read_text(encoding="utf-8")):
            problems.append("binary_manifest.json contains an absolute drive path")
    if problems:
        return CheckResult("artifact_executables", GateVerdict.BLOCKED, Severity.P0, "; ".join(problems))
    return CheckResult("artifact_executables", GateVerdict.PASS, detail=f"both executables report version {__version__} and are covered by binary_manifest.json")


def _artifact_leak_scan(root: Path, *, required: bool = False) -> CheckResult:
    """POST-BUILD: no developer path, key material, token-like string or development host in the package. Categories and counts only."""
    if not required:
        return CheckResult("artifact_leak_scan", GateVerdict.PASS, detail="not required pre-build")
    from exilelens.ops.leak_scan import scan_package

    dist = root / "dist" / "ExileLens"
    if not dist.is_dir():
        return CheckResult("artifact_leak_scan", GateVerdict.BLOCKED, Severity.P0, "dist/ExileLens missing")
    literals = tuple({str(root), str(Path.home())})
    findings = scan_package(dist, literals=literals)
    if findings:
        shown = "; ".join(item.line() for item in findings[:8])
        return CheckResult("artifact_leak_scan", GateVerdict.BLOCKED, Severity.P0, f"{len(findings)} finding(s): {shown}")
    return CheckResult("artifact_leak_scan", GateVerdict.PASS, detail="no developer path, key material or secret-like string in the package")


def _artifact_qt_and_dependencies(root: Path, *, required: bool = False) -> CheckResult:
    """POST-BUILD: the shipped Qt surface is exactly the approved set (qtbase + qtsvg only), laid out as QT_LGPL_COMPLIANCE.txt says
    (separate files in _internal\\PySide6, none inside ExileLens.exe), and the other bundled runtime components are the ones the
    notices describe (OpenSSL versions, cffi/pycparser, Python runtime, MSVC runtime, font, Lua support files)."""
    if not required:
        return CheckResult("artifact_qt_and_dependencies", GateVerdict.PASS, detail="not required pre-build")
    import re

    from exilelens.ops.pe_version import read_version_strings

    dist = root / "dist" / "ExileLens"
    internal = dist / "_internal"
    if not internal.is_dir():
        return CheckResult("artifact_qt_and_dependencies", GateVerdict.BLOCKED, Severity.P0, "dist/ExileLens/_internal missing")
    problems: list[str] = []
    pyside = internal / "PySide6"
    libs = {path.stem for path in pyside.glob("Qt6*.dll")}
    if libs != set(EXPECTED_QT_LIBRARIES):
        extra, missing = sorted(libs - set(EXPECTED_QT_LIBRARIES)), sorted(set(EXPECTED_QT_LIBRARIES) - libs)
        problems.append(f"Qt libraries differ from the approved set (unexpected: {extra or 'none'}; missing: {missing or 'none'})")
    plugins = {
        path.relative_to(pyside / "plugins").with_suffix("").as_posix() for path in (pyside / "plugins").rglob("*.dll")
    } if (pyside / "plugins").is_dir() else set()
    if plugins != set(EXPECTED_QT_PLUGINS):
        problems.append(
            f"Qt plugins differ from the approved set (unexpected: {sorted(plugins - set(EXPECTED_QT_PLUGINS)) or 'none'}; "
            f"missing: {sorted(set(EXPECTED_QT_PLUGINS) - plugins) or 'none'})"
        )
    for other in internal.rglob("*"):
        if other.is_file() and other.suffix.lower() in (".dll", ".pyd") and other.name.lower().startswith("qt6") and pyside not in other.parents:
            problems.append(f"Qt file outside _internal\\PySide6: {other.relative_to(dist)}")
    forbidden = sorted(
        {
            path.relative_to(dist).as_posix()
            for path in dist.rglob("*")
            if path.is_file() and any(token in path.relative_to(dist).as_posix().lower() for token in (*GPL_ONLY_QT_BINARY_TOKENS, *UNUSED_QT_BINARY_TOKENS))
        }
    )
    if forbidden:
        problems.append("GPL-only or removed Qt binaries in the package: " + ", ".join(forbidden[:6]))
    exe = dist / "ExileLens.exe"
    if exe.is_file() and exe.stat().st_size > 8 * 1024 * 1024:
        problems.append("ExileLens.exe is large enough to embed Qt: the Qt libraries must stay separate files")
    # Python runtime and OpenSSL, compared with what the shipped notices say.
    notices = (dist / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8") if (dist / "THIRD_PARTY_NOTICES.txt").is_file() else ""
    pin = (root / ".python-version").read_text(encoding="utf-8").strip() if (root / ".python-version").is_file() else ""
    runtime_dll = internal / f"python{pin.split('.')[0]}{pin.split('.')[1]}.dll" if pin.count(".") == 2 else None
    if runtime_dll is None or not runtime_dll.is_file():
        problems.append("the pinned Python runtime DLL is missing from _internal")
    else:
        strings = read_version_strings(runtime_dll) or {}
        if not str(strings.get("ProductVersion", "")).startswith(pin):
            problems.append(f"the bundled Python runtime reports {strings.get('ProductVersion')!r}, expected {pin}")
    runtime_ssl = internal / "libcrypto-3.dll"
    if not runtime_ssl.is_file():
        problems.append("libcrypto-3.dll (Python runtime OpenSSL) is not in the package; the notices describe it")
    else:
        found = set(re.findall(rb"OpenSSL (\d+\.\d+\.\d+)", runtime_ssl.read_bytes()))
        if not found or any(f"OpenSSL {v.decode()}" not in notices for v in found):
            problems.append(f"the notices do not state the Python runtime's OpenSSL {sorted(v.decode() for v in found)}")
    rust = internal / "cryptography" / "hazmat" / "bindings" / "_rust.pyd"
    if not rust.is_file():
        problems.append("cryptography's native module is missing")
    else:
        found = set(re.findall(rb"OpenSSL (\d+\.\d+\.\d+)", rust.read_bytes()))
        if not found or any(f"OpenSSL {v.decode()}" not in notices for v in found):
            problems.append(f"the notices do not state cryptography's statically linked OpenSSL {sorted(v.decode() for v in found)}")
    if not list(internal.glob("_cffi_backend*.pyd")):
        problems.append("cffi's backend is not bundled, but the notices say it is")
    if (internal / "pycparser").exists() or list(internal.glob("pycparser*")):
        problems.append("pycparser is bundled, but the notices say it is not")
    for rel in ("assets/fonts/Spectral-SemiBold.ttf", "assets/fonts/OFL.txt", "runtime/lua/bridge.lua", "exilelens/whats_new/whats_new.json"):
        if not (internal / rel).is_file():
            problems.append(f"bundled resource missing: {rel}")
    if not list(internal.glob("VCRUNTIME140*.dll")) or not list(pyside.glob("MSVCP140*.dll")):
        problems.append("the Microsoft Visual C++ runtime DLLs described in the notices are missing")
    if problems:
        return CheckResult("artifact_qt_and_dependencies", GateVerdict.BLOCKED, Severity.P0, "; ".join(problems))
    return CheckResult(
        "artifact_qt_and_dependencies", GateVerdict.PASS,
        detail=f"Qt = {len(libs)} libraries + {len(plugins)} plugins, all approved; no GPL-only or removed module; runtime/OpenSSL/cffi coherent with the notices",
    )


EXPECTED_SHIPPING_UPDATE_KEYS = ["exilelens-prod-1"]


def _update_trust_set(root: Path) -> CheckResult:
    """Shipping builds must trust only production update keys; the test key's private half is public."""
    from exilelens.app.updates import trust

    shipping = trust.trust_report(frozen=True)
    if shipping.get("key_ids") != EXPECTED_SHIPPING_UPDATE_KEYS or shipping.get("profile") != trust.PRODUCTION_PROFILE:
        return CheckResult(
            "update_trust_set",
            GateVerdict.BLOCKED,
            Severity.P0,
            f"frozen builds would trust {shipping.get('key_ids')!r}; expected {EXPECTED_SHIPPING_UPDATE_KEYS!r}",
        )
    production_material = set(trust.PRODUCTION_VERIFY_KEYS.values())
    if set(trust.PRODUCTION_VERIFY_KEYS) & set(trust.TEST_VERIFY_KEYS) or production_material & set(
        trust.TEST_VERIFY_KEYS.values()
    ):
        return CheckResult("update_trust_set", GateVerdict.BLOCKED, Severity.P0, "test key present in production trust set")
    return CheckResult("update_trust_set", GateVerdict.PASS, detail="frozen builds trust only exilelens-prod-1")


def _cloud_config(root: Path) -> CheckResult:
    """The optional cloud service must be explicitly configured for a release, never by accident.

    * ``release_config.json`` may be empty (cloud features stay off) or hold a strict https URL that is not a
      ``*.workers.dev`` development host.
    * The packaged contract must be byte-identical to the canonical ``cloud/schema/events.v1.json``.
    """
    import json

    from exilelens.cloud.endpoint import normalize_base_url

    package = root / "src" / "exilelens" / "cloud"
    config_path = package / "release_config.json"
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            return CheckResult("cloud_config", GateVerdict.BLOCKED, Severity.P0, f"release_config.json unreadable: {exc}")
    else:
        config = {"schema": 1, "api_base_url": ""}  # generated per release; absent = cloud features off
    url = config.get("api_base_url") if isinstance(config, dict) else None
    if not isinstance(config, dict) or config.get("schema") != 1 or not isinstance(url, str):
        return CheckResult("cloud_config", GateVerdict.BLOCKED, Severity.P0, "release_config.json has an unexpected shape")
    if url.strip() and normalize_base_url(url) is None:
        return CheckResult(
            "cloud_config",
            GateVerdict.BLOCKED,
            Severity.P0,
            "api_base_url must be an https origin and not a *.workers.dev development host",
        )
    canonical = root / "cloud" / "schema" / "events.v1.json"
    packaged = package / "events.v1.json"
    if canonical.is_file() and (not packaged.is_file() or canonical.read_bytes() != packaged.read_bytes()):
        return CheckResult("cloud_config", GateVerdict.BLOCKED, Severity.P0, "packaged events.v1.json differs from cloud/schema/events.v1.json")
    state = "configured" if url.strip() else "not configured (cloud features stay off)"
    return CheckResult("cloud_config", GateVerdict.PASS, detail=f"cloud endpoint {state}; contract in sync")


def _packaged_update_trust(root: Path, *, required: bool = False) -> CheckResult:
    """Ask the packaged binary itself which update keys it trusts (proves no test-key fallback shipped)."""
    if not required:
        return CheckResult("packaged_update_trust", GateVerdict.PASS, detail="not required pre-build")
    import json
    import tempfile

    exe = root / "dist" / "ExileLens" / "ExileLens.exe"
    if not exe.is_file():
        return CheckResult("packaged_update_trust", GateVerdict.BLOCKED, Severity.P0, "packaged ExileLens.exe missing")
    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "trust.json"
        try:
            completed = subprocess.run(
                [str(exe), "--exilelens-update-trust-report", str(report_path)],
                timeout=120,
                check=False,
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return CheckResult("packaged_update_trust", GateVerdict.BLOCKED, Severity.P0, f"trust report failed: {exc}")
    if completed.returncode != 0 or not report.get("frozen") or report.get("key_ids") != EXPECTED_SHIPPING_UPDATE_KEYS:
        return CheckResult(
            "packaged_update_trust",
            GateVerdict.BLOCKED,
            Severity.P0,
            f"packaged binary trusts {report.get('key_ids')!r} (frozen={report.get('frozen')!r})",
        )
    return CheckResult("packaged_update_trust", GateVerdict.PASS, detail="packaged binary trusts only exilelens-prod-1")


def _packaged_whats_new(root: Path, *, required: bool = False) -> CheckResult:
    """Ask the packaged binary itself to load its release notes (proves the data file was bundled and is readable)."""
    if not required:
        return CheckResult("packaged_whats_new", GateVerdict.PASS, detail="not required pre-build")
    import json
    import tempfile

    exe = root / "dist" / "ExileLens" / "ExileLens.exe"
    if not exe.is_file():
        return CheckResult("packaged_whats_new", GateVerdict.BLOCKED, Severity.P1, "packaged ExileLens.exe missing")
    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "whats_new.json"
        try:
            completed = subprocess.run([str(exe), "--exilelens-whats-new-report", str(report_path)], timeout=120, check=False)
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return CheckResult("packaged_whats_new", GateVerdict.BLOCKED, Severity.P1, f"whats-new report failed: {exc}")
    if completed.returncode != 0 or not (report.get("frozen") and report.get("loaded") and report.get("has_entry")) or report.get("problems"):
        return CheckResult("packaged_whats_new", GateVerdict.BLOCKED, Severity.P1, f"packaged release notes unusable: {report!r}")
    return CheckResult("packaged_whats_new", GateVerdict.PASS, detail=f"packaged binary loads its notes for {report.get('version')}")


def evaluate_release_gate(
    *,
    root: Path | None = None,
    allow_dirty: bool = False,
    require_artifact: bool = False,
    smoke_result: CheckResult | None = None,
) -> ReleaseGateReport:
    base = root or repo_root()
    checks = [
        _version_files_coherent(base),
        _release_tag_coherent(base),
        _whats_new(base),
        *_compatibility(base),
        _p0_registry(base),
        _dirty_tree(base, allow_dirty=allow_dirty),
        _packaging(base),
        _spec_audit(base),
        _distribution_files(base, required=require_artifact),
        _gpl_only_qt(base, required=require_artifact),
        _shipping_copy(base),
        _debug_deps(base),
        _update_trust_set(base),
        _cloud_config(base),
        _expected_artifact(base, required=require_artifact),
        _artifact_provenance(base, required=require_artifact),
        _artifact_executables(base, required=require_artifact),
        _artifact_leak_scan(base, required=require_artifact),
        _artifact_qt_and_dependencies(base, required=require_artifact),
        _packaged_update_trust(base, required=require_artifact),
        _packaged_whats_new(base, required=require_artifact),
    ]
    if smoke_result is not None:
        checks.append(smoke_result)
    blockers = [item for item in checks if item.status == GateVerdict.BLOCKED]
    warnings = [item for item in checks if item.status == GateVerdict.WARN]
    passed = [item for item in checks if item.status == GateVerdict.PASS]
    verdict = GateVerdict.BLOCKED if blockers else GateVerdict.PASS
    return ReleaseGateReport(verdict=verdict, blockers=blockers, warnings=warnings, passed=passed)
