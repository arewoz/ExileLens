"""PoB upstream compatibility inspection. Never assumes latest HEAD is supported."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from exilelens import SUPPORTED_POB_HEAD
from exilelens.ops.compatibility import load_manifest
from exilelens.ops.models import CompatibilityStatus

POB_GITHUB_REPO = "PathOfBuildingCommunity/PathOfBuilding-PoE2"
RELEVANT_PATHS = (
    "src/Classes/Item.lua",
    "src/Classes/ItemsTab.lua",
    "src/Classes/ImportTab.lua",
    "src/Classes/PassiveTree.lua",
    "src/Classes/CalcPerform.lua",
    "src/Classes/CalcOffence.lua",
    "src/Classes/CalcDefence.lua",
    "src/Modules/Build.lua",
    "src/Data/",
)

DEFAULT_LOCAL_POB = Path("PathOfBuilding-PoE2")


@dataclass
class PobCompatibilityReport:
    verified_commit: str
    observed_commit: str | None
    source: str
    relevant_changes: list[str] = field(default_factory=list)
    status: str = CompatibilityStatus.UNVERIFIED.value
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified_commit": self.verified_commit,
            "observed_commit": self.observed_commit,
            "source": self.source,
            "relevant_changes": self.relevant_changes,
            "status": self.status,
            "notes": self.notes,
            "assumption_forbidden": "Never automatically assume latest upstream is supported.",
        }


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip()


def fetch_github_head(*, token: str | None = None) -> str | None:
    url = f"https://api.github.com/repos/{POB_GITHUB_REPO}/commits/master"
    headers = {"User-Agent": "ExileLens-ops", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    sha = payload.get("sha")
    return str(sha) if sha else None


def inspect_pob_compatibility(
    *,
    pob_path: Path | None = None,
    fetch_remote: bool = False,
) -> PobCompatibilityReport:
    manifest = load_manifest()
    verified = manifest.pob_verified_commit or SUPPORTED_POB_HEAD
    notes = [
        "Latest upstream is not supported until pob-compatibility checks pass.",
        "This command does not rewrite SUPPORTED_POB_HEAD or product parsers.",
    ]
    local = pob_path or Path(os.environ.get("POB2_PATH") or DEFAULT_LOCAL_POB)
    observed = None
    source = "none"
    relevant: list[str] = []

    if fetch_remote:
        observed = fetch_github_head(token=os.environ.get("GITHUB_TOKEN"))
        source = "github_api" if observed else "github_api_failed"
        if not observed:
            notes.append("GitHub fetch failed; remaining local inspection only")

    if observed is None and local.is_dir() and (local / ".git").exists():
        observed = _git(local, "rev-parse", "HEAD") or None
        source = "local_git"
        if observed and observed != verified:
            diff = _git(local, "diff", "--name-only", verified, observed)
            relevant = [line for line in diff.splitlines() if any(line.replace("\\", "/").startswith(prefix) or prefix in line.replace("\\", "/") for prefix in RELEVANT_PATHS)]

    if observed is None:
        notes.append(f"No PoB checkout at {local}; pass --pob-path or set POB2_PATH")
        status = CompatibilityStatus.UNVERIFIED.value
    elif observed == verified:
        status = CompatibilityStatus.SUPPORTED.value
        notes.append("Observed revision matches verified commit")
    else:
        status = CompatibilityStatus.UNVERIFIED.value
        notes.append(f"Observed {observed[:12]} != verified {verified[:12]}")
        if not relevant:
            notes.append("Could not list relevant path changes (missing local range). Treat parser/tree/calcs as unverified.")

    return PobCompatibilityReport(
        verified_commit=verified,
        observed_commit=observed,
        source=source,
        relevant_changes=relevant,
        status=status,
        notes=notes,
    )
