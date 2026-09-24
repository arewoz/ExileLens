"""Canonical compatibility manifest load/validate."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from exilelens import SUPPORTED_POB_HEAD, __version__
from exilelens.ops.models import CompatibilityStatus, MarketCompatStatus
from exilelens.ops.paths import compatibility_path, repo_root

GAME_STATUSES = {item.value for item in CompatibilityStatus}
POB_STATUSES = GAME_STATUSES
MARKET_STATUSES = {item.value for item in MarketCompatStatus}


class CompatibilityError(ValueError):
    """Manifest is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class CompatibilityManifest:
    exilelens_version: str
    game_version: str | None
    game_status: str
    pob_verified_commit: str
    pob_status: str
    market_status: str
    market_mode: str
    last_full_verification: str | None
    raw: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.raw


def load_manifest(path: Path | None = None) -> CompatibilityManifest:
    manifest_path = path or compatibility_path()
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CompatibilityError(f"compatibility manifest missing: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise CompatibilityError(f"compatibility manifest is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise CompatibilityError("compatibility manifest root must be an object")
    return parse_manifest(raw)


def parse_manifest(raw: dict[str, Any]) -> CompatibilityManifest:
    errors = validate_manifest_dict(raw)
    if errors:
        raise CompatibilityError("; ".join(errors))
    game = raw.get("game") if isinstance(raw.get("game"), dict) else {}
    pob = raw.get("pob") if isinstance(raw.get("pob"), dict) else {}
    market = raw.get("market") if isinstance(raw.get("market"), dict) else {}
    game_version = game.get("version")
    return CompatibilityManifest(
        exilelens_version=str(raw.get("exilelens_version") or ""),
        game_version=None if game_version in (None, "") else str(game_version),
        game_status=str(game.get("status") or ""),
        pob_verified_commit=str(pob.get("verified_commit") or ""),
        pob_status=str(pob.get("status") or ""),
        market_status=str(market.get("status") or ""),
        market_mode=str(market.get("mode") or ""),
        last_full_verification=(
            None
            if raw.get("last_full_verification") in (None, "")
            else str(raw.get("last_full_verification"))
        ),
        raw=raw,
    )


def validate_manifest_dict(raw: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not str(raw.get("exilelens_version") or "").strip():
        errors.append("exilelens_version is required")
    game = raw.get("game")
    pob = raw.get("pob")
    market = raw.get("market")
    if not isinstance(game, dict):
        errors.append("game object is required")
    else:
        status = str(game.get("status") or "")
        if status not in GAME_STATUSES:
            errors.append(f"game.status must be one of {sorted(GAME_STATUSES)}")
        version = game.get("version")
        if status == CompatibilityStatus.SUPPORTED.value and not version:
            errors.append("game.status SUPPORTED requires game.version")
    if not isinstance(pob, dict):
        errors.append("pob object is required")
    else:
        status = str(pob.get("status") or "")
        if status not in POB_STATUSES:
            errors.append(f"pob.status must be one of {sorted(POB_STATUSES)}")
        commit = str(pob.get("verified_commit") or "").strip()
        if status in {CompatibilityStatus.SUPPORTED.value, CompatibilityStatus.PARTIALLY_SUPPORTED.value} and len(commit) < 7:
            errors.append("pob.status SUPPORTED/PARTIALLY_SUPPORTED requires verified_commit")
    if not isinstance(market, dict):
        errors.append("market object is required")
    else:
        status = str(market.get("status") or "")
        if status not in MARKET_STATUSES:
            errors.append(f"market.status must be one of {sorted(MARKET_STATUSES)}")
    return errors


def validate_against_code(manifest: CompatibilityManifest, *, root: Path | None = None) -> list[str]:
    """Consistency vs product constants. Does not invent game versions."""
    del root
    warnings: list[str] = []
    if manifest.exilelens_version != __version__:
        warnings.append(
            f"manifest exilelens_version {manifest.exilelens_version!r} != code {__version__!r}"
        )
    if manifest.pob_verified_commit and manifest.pob_verified_commit != SUPPORTED_POB_HEAD:
        warnings.append(
            "manifest pob.verified_commit differs from SUPPORTED_POB_HEAD; "
            "do not assume latest upstream is supported"
        )
    if manifest.pob_status == CompatibilityStatus.SUPPORTED.value and not manifest.pob_verified_commit:
        warnings.append("PoB marked SUPPORTED without a verified commit")
    return warnings


def mark_needs_verification(
    manifest: CompatibilityManifest,
    *,
    reason: str,
    game_version: str | None = None,
) -> dict[str, Any]:
    """Return an updated document. Does not write product code or assume support."""
    raw = json.loads(json.dumps(manifest.raw))
    game = dict(raw.get("game") or {})
    if game_version:
        game["detected_version"] = game_version
    game["status"] = CompatibilityStatus.UNVERIFIED.value
    game["needs_verification"] = True
    game["verification_reason"] = reason
    raw["game"] = game
    return raw


def write_manifest(data: dict[str, Any], path: Path | None = None) -> Path:
    errors = validate_manifest_dict(data)
    if errors:
        raise CompatibilityError("; ".join(errors))
    target = path or compatibility_path(repo_root())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return target
