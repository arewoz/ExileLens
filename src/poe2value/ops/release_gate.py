"""Release gate: PASS or BLOCKED from executable checks. No invented numeric score."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from poe2value import SUPPORTED_POB_HEAD, __version__
from poe2value._version import windows_version_tuple
from poe2value.ops.compatibility import load_manifest, validate_against_code
from poe2value.ops.models import CheckResult, CompatibilityStatus, GateVerdict, Severity
from poe2value.ops.paths import repo_root
from poe2value.ops.regression import load_registry

REQUIRED_PACKAGING = (
    "packaging/CHANGELOG.txt",
    "packaging/README.txt",
    "packaging/version_info.txt",
    "packaging/poe2value-gui.spec",
    "scripts/build_exe.ps1",
    "scripts/package_closed_public_rc.ps1",
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
    version_info = (root / "packaging" / "version_info.txt").read_text(encoding="utf-8")
    changelog = (root / "packaging" / "CHANGELOG.txt").read_text(encoding="utf-8")
    readme = (root / "packaging" / "README.txt").read_text(encoding="utf-8")
    numeric = ", ".join(str(part) for part in windows_version_tuple())
    missing = []
    if f'version = "{__version__}"' not in pyproject:
        missing.append("pyproject.toml")
    if f"FileVersion', '{__version__}'" not in version_info:
        missing.append("packaging/version_info.txt")
    if f"ProductVersion', '{__version__}'" not in version_info:
        missing.append("packaging/version_info.txt product version")
    if f"filevers=({numeric})" not in version_info or f"prodvers=({numeric})" not in version_info:
        missing.append("packaging/version_info.txt numeric version")
    if __version__ not in changelog:
        missing.append("packaging/CHANGELOG.txt")
    if __version__ not in readme:
        missing.append("packaging/README.txt")
    if missing:
        return CheckResult(
            "version_coherence",
            GateVerdict.BLOCKED,
            Severity.P0,
            f"version {__version__} missing from {', '.join(missing)}",
        )
    return CheckResult("version_coherence", GateVerdict.PASS, detail=f"version {__version__}")


def _compatibility(root: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    try:
        manifest = load_manifest()
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


def _p0_registry() -> CheckResult:
    open_p0 = [entry for entry in load_registry() if entry.severity == "P0" and entry.status in {"open", "broken"}]
    if open_p0:
        return CheckResult(
            "known_p0",
            GateVerdict.BLOCKED,
            Severity.P0,
            "open P0 regressions: " + ", ".join(entry.id for entry in open_p0),
        )
    return CheckResult("known_p0", GateVerdict.PASS, detail="no open P0 registry entries")


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


def _expected_artifact(root: Path) -> CheckResult:
    exe = root / "dist" / "ExileLens" / "ExileLens.exe"
    if exe.is_file():
        return CheckResult("release_artifact", GateVerdict.PASS, detail=str(exe))
    return CheckResult(
        "release_artifact",
        GateVerdict.WARN,
        Severity.P2,
        "dist/ExileLens/ExileLens.exe not built (run scripts/build_exe.ps1 for a packaged release)",
    )


def evaluate_release_gate(
    *,
    root: Path | None = None,
    allow_dirty: bool = False,
    smoke_result: CheckResult | None = None,
) -> ReleaseGateReport:
    base = root or repo_root()
    checks = [
        _version_files_coherent(base),
        *_compatibility(base),
        _p0_registry(),
        _dirty_tree(base, allow_dirty=allow_dirty),
        _packaging(base),
        _debug_deps(base),
        _expected_artifact(base),
    ]
    if smoke_result is not None:
        checks.append(smoke_result)
    blockers = [item for item in checks if item.status == GateVerdict.BLOCKED]
    warnings = [item for item in checks if item.status == GateVerdict.WARN]
    passed = [item for item in checks if item.status == GateVerdict.PASS]
    verdict = GateVerdict.BLOCKED if blockers else GateVerdict.PASS
    return ReleaseGateReport(verdict=verdict, blockers=blockers, warnings=warnings, passed=passed)
