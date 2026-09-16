"""PoE2 patch and PoB upstream watchers. Detection only — no product rewrites."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from poe2value.ops.compatibility import load_manifest, mark_needs_verification
from poe2value.ops.models import CompatibilityStatus
from poe2value.ops.patch_impact import parse_notes_text
from poe2value.ops.pob_compat import inspect_pob_compatibility

# Official patch-note retrieval is not a stable public API. Local notes files are
# the supported input. Optional URL fetch is explicit and fail-soft.
DEFAULT_PATCH_URL = os.environ.get("EXILELENS_PATCH_NOTES_URL", "").strip()


@dataclass
class PatchWatchReport:
    detected_version: str | None
    manifest_version: str | None
    status: str
    notes_entries: int
    proposed_manifest: dict[str, Any] | None = None
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected_version": self.detected_version,
            "manifest_game_version": self.manifest_version,
            "status": self.status,
            "notes_entries": self.notes_entries,
            "details": self.details,
            "proposed_manifest": self.proposed_manifest,
            "auto_product_rewrite": False,
        }


def fetch_url_text(url: str) -> str | None:
    request = urllib.request.Request(url, headers={"User-Agent": "ExileLens-ops"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def watch_patch(
    *,
    version: str | None = None,
    notes_text: str | None = None,
    notes_path: Path | None = None,
    fetch_url: str | None = None,
) -> PatchWatchReport:
    manifest = load_manifest()
    details = ["Watcher does not modify product parsers, scoring, or overlay code."]
    text = notes_text or ""
    if notes_path:
        text = Path(notes_path).read_text(encoding="utf-8")
        details.append(f"notes_path={notes_path}")
    url = (fetch_url if fetch_url is not None else DEFAULT_PATCH_URL) or ""
    if url and not text:
        fetched = fetch_url_text(url)
        if fetched:
            text = fetched
            details.append(f"fetched={url}")
        else:
            details.append(f"fetch failed for {url}; use --notes")
    entries = parse_notes_text(text) if text else []
    detected = version
    if detected is None:
        for line in (text or "").splitlines()[:20]:
            if line.lower().startswith("version:") or line.lower().startswith("patch:"):
                detected = line.split(":", 1)[1].strip() or None
                break
    current = manifest.game_version
    if detected and current and detected == current and manifest.game_status == CompatibilityStatus.SUPPORTED.value:
        status = "unchanged"
        proposed = None
        details.append("Detected version already recorded as SUPPORTED")
    elif detected and detected != current:
        status = "needs_verification"
        proposed = mark_needs_verification(manifest, reason=f"detected game version {detected}", game_version=detected)
        details.append("Compatibility must be re-verified via game-update; do not auto-SUPPORT")
    elif not detected:
        status = "no_version_detected"
        proposed = None
        details.append("Provide --version and/or --notes; GGG has no supported auto-scrape in this repo")
    else:
        status = "needs_verification"
        proposed = mark_needs_verification(manifest, reason="patch notes supplied without a supported version match")
    return PatchWatchReport(
        detected_version=detected,
        manifest_version=current,
        status=status,
        notes_entries=len(entries),
        proposed_manifest=proposed,
        details=details,
    )


def watch_pob(*, pob_path: Path | None = None, fetch_remote: bool = False) -> dict[str, Any]:
    report = inspect_pob_compatibility(pob_path=pob_path, fetch_remote=fetch_remote)
    payload = report.to_dict()
    payload["entry_point"] = "python -m poe2value ops pob-compatibility"
    if report.observed_commit and report.observed_commit != report.verified_commit:
        payload["compatibility"] = CompatibilityStatus.UNVERIFIED.value
    return payload
