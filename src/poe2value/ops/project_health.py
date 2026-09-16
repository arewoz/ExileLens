"""Project-health rollup: blockers, warnings, next actions. No invented score."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from poe2value import SUPPORTED_POB_HEAD, __version__
from poe2value.ops.compatibility import load_manifest, validate_against_code
from poe2value.ops.fixture_audit import audit_fixture_corpus
from poe2value.ops.models import CompatibilityStatus, GateVerdict, Severity
from poe2value.ops.paths import repo_root
from poe2value.ops.regression import load_registry
from poe2value.ops.release_gate import evaluate_release_gate


@dataclass
class HealthItem:
    severity: str
    title: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "title": self.title, "detail": self.detail}


@dataclass
class ProjectHealthReport:
    verdict: GateVerdict
    app_version: str
    blockers: list[HealthItem] = field(default_factory=list)
    warnings: list[HealthItem] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": f"PROJECT HEALTH: {self.verdict.value}",
            "verdict": self.verdict.value,
            "facts": self.facts,
            "blockers": [item.to_dict() for item in self.blockers],
            "warnings": [item.to_dict() for item in self.warnings],
            "next_actions": self.next_actions,
        }

    def format_text(self) -> str:
        lines = [f"PROJECT HEALTH: {self.verdict.value}", f"app_version: {self.app_version}"]
        for label, items in (("BLOCKERS", self.blockers), ("WARNINGS", self.warnings)):
            if not items:
                continue
            lines.append(f"{label}:")
            for item in items:
                lines.append(f"  [{item.severity}] {item.title}: {item.detail}")
        if self.next_actions:
            lines.append("NEXT:")
            for action in self.next_actions:
                lines.append(f"  - {action}")
        return "\n".join(lines)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    return (result.stdout or result.stderr or "").strip()


def evaluate_project_health(
    *,
    root: Path | None = None,
    allow_dirty: bool = True,
    smoke_result: str | None = None,
) -> ProjectHealthReport:
    base = root or repo_root()
    blockers: list[HealthItem] = []
    warnings: list[HealthItem] = []
    next_actions: list[str] = []
    facts: dict[str, Any] = {
        "app_version": __version__,
        "supported_pob_head": SUPPORTED_POB_HEAD,
        "branch": _git(base, "rev-parse", "--abbrev-ref", "HEAD"),
        "head": _git(base, "rev-parse", "HEAD"),
        "dirty": bool(_git(base, "status", "--porcelain")),
        "smoke": smoke_result or "not_run",
        "live_market_canary": "not_run",
    }
    try:
        manifest = load_manifest()
        facts["game"] = {"version": manifest.game_version, "status": manifest.game_status}
        facts["pob"] = {"verified_commit": manifest.pob_verified_commit, "status": manifest.pob_status}
        facts["market"] = {"status": manifest.market_status, "mode": manifest.market_mode}
        facts["last_full_verification"] = manifest.last_full_verification
        for warning in validate_against_code(manifest, root=base):
            warnings.append(HealthItem(Severity.P2.value, "compatibility_consistency", warning))
        if manifest.game_status == CompatibilityStatus.BROKEN.value:
            blockers.append(HealthItem(Severity.P0.value, "game", "compatibility marked BROKEN"))
        elif manifest.game_status == CompatibilityStatus.UNVERIFIED.value:
            warnings.append(HealthItem(Severity.P1.value, "game", "PoE2 client version is UNVERIFIED"))
            next_actions.append("Run: python -m poe2value ops game-update --notes <patch-notes.txt>")
        if manifest.pob_status == CompatibilityStatus.BROKEN.value:
            blockers.append(HealthItem(Severity.P0.value, "pob", "PoB compatibility marked BROKEN"))
        if manifest.market_status in {"FAILED", "DEGRADED"}:
            warnings.append(HealthItem(Severity.P1.value, "market", f"market.status={manifest.market_status}"))
    except Exception as exc:  # noqa: BLE001
        blockers.append(HealthItem(Severity.P0.value, "compatibility_manifest", str(exc)))

    open_blockers = [entry for entry in load_registry() if entry.status in {"open", "broken"}]
    for entry in open_blockers:
        item = HealthItem(entry.severity, entry.id, entry.title)
        if entry.severity == "P0":
            blockers.append(item)
        else:
            warnings.append(item)

    fixture = audit_fixture_corpus(root=base)
    facts["fixtures"] = fixture.summary()
    if fixture.missing:
        warnings.append(HealthItem(Severity.P1.value, "fixtures", "missing: " + ", ".join(fixture.missing)))

    gate = evaluate_release_gate(root=base, allow_dirty=allow_dirty)
    facts["release_gate"] = gate.verdict.value
    if gate.verdict == GateVerdict.BLOCKED and not allow_dirty:
        for check in gate.blockers:
            blockers.append(
                HealthItem(check.severity.value if check.severity else "P1", check.name, check.detail)
            )

    dirty = facts["dirty"]
    if dirty:
        warnings.append(HealthItem(Severity.P2.value, "git", "working tree has uncommitted changes"))
        next_actions.append("Inspect git status; do not mix unrelated WIP into ops/release commits")

    if smoke_result is None:
        next_actions.append("Run: python -m poe2value ops smoke")

    verdict = GateVerdict.BLOCKED if blockers else GateVerdict.WARN if warnings else GateVerdict.PASS
    return ProjectHealthReport(
        verdict=verdict,
        app_version=__version__,
        blockers=blockers,
        warnings=warnings,
        next_actions=next_actions,
        facts=facts,
    )
