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
from exilelens.ops.packaging_version import render_version_info
from exilelens.ops.regression import load_registry

#: Verified third-party license texts that ship in the package (copied unmodified from the upstream distributions). The Qt/PySide6
#: LGPL text and source offer are deliberately NOT here: they could not be established from local package metadata and are an open
#: compliance item (docs/1.0-HARDENING-PLAN.md, 1.0-A).
THIRD_PARTY_LICENSE_FILES = (
    "packaging/third_party_licenses/README.txt",
    "packaging/third_party_licenses/cryptography/LICENSE",
    "packaging/third_party_licenses/cryptography/LICENSE.APACHE",
    "packaging/third_party_licenses/cryptography/LICENSE.BSD",
    "packaging/third_party_licenses/cffi/LICENSE",
    "packaging/third_party_licenses/pycparser/LICENSE",
    "packaging/third_party_licenses/pyinstaller/COPYING.txt",
)

#: What must sit next to ExileLens.exe in the release package (names relative to dist/ExileLens).
DISTRIBUTION_FILES = ("README.txt", "LICENSE", "THIRD_PARTY_NOTICES.txt")

REQUIRED_PACKAGING = (
    "LICENSE",
    "packaging/THIRD_PARTY_NOTICES.txt",
    *THIRD_PARTY_LICENSE_FILES,
    "packaging/CHANGELOG.txt",
    "packaging/RELEASE_NOTES.md",
    "packaging/README.txt",
    "packaging/version_info.txt",
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
    expected_info = render_version_info()
    if version_info != expected_info:
        missing.append("packaging/version_info.txt (regenerate with scripts/generate_packaging_version_info.py)")
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


def _distribution_files(root: Path, *, required: bool = False) -> CheckResult:
    """The project LICENSE, the third-party notices and the verified license texts must ship in the package (not only live in the repo)."""
    problems: list[str] = []
    build = root / "scripts" / "build_exe.ps1"
    build_text = build.read_text(encoding="utf-8") if build.is_file() else ""
    for token in ('"LICENSE"', "THIRD_PARTY_NOTICES.txt", "third_party_licenses"):
        if token not in build_text:
            problems.append(f"scripts/build_exe.ps1 does not copy {token.strip(chr(34))} into dist")
    notices = root / "packaging" / "THIRD_PARTY_NOTICES.txt"
    notices_text = notices.read_text(encoding="utf-8") if notices.is_file() else ""
    for rel in THIRD_PARTY_LICENSE_FILES[1:]:
        folder_and_file = "third_party_licenses\\" + rel.split("third_party_licenses/", 1)[1].replace("/", "\\")
        if folder_and_file not in notices_text:
            problems.append(f"THIRD_PARTY_NOTICES.txt does not reference {folder_and_file}")
    if required:
        dist = root / "dist" / "ExileLens"
        for name in DISTRIBUTION_FILES:
            if not (dist / name).is_file():
                problems.append(f"dist/ExileLens/{name} missing from the package")
        for rel in THIRD_PARTY_LICENSE_FILES:
            if not (dist / "third_party_licenses" / rel.split("third_party_licenses/", 1)[1]).is_file():
                problems.append(f"dist/ExileLens/third_party_licenses/{rel.split('third_party_licenses/', 1)[1]} missing from the package")
        shipped, source = dist / "LICENSE", root / "LICENSE"
        if shipped.is_file() and source.is_file() and shipped.read_bytes() != source.read_bytes():
            problems.append("dist/ExileLens/LICENSE differs from the repository LICENSE")
    if problems:
        return CheckResult("distribution_files", GateVerdict.BLOCKED, Severity.P0, "; ".join(problems))
    return CheckResult("distribution_files", GateVerdict.PASS, detail="LICENSE, notices and verified license texts are packaged")


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
        _distribution_files(base, required=require_artifact),
        _shipping_copy(base),
        _debug_deps(base),
        _update_trust_set(base),
        _cloud_config(base),
        _expected_artifact(base, required=require_artifact),
        _artifact_provenance(base, required=require_artifact),
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
