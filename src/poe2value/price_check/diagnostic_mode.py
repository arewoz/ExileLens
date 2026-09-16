from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MARKET_FIXTURE = REPO_ROOT / "fixtures" / "market" / "diagnostic" / "sapphire_caster_ring.txt"


class PriceCheckDiagnosticMode(str, Enum):
    NONE = ""
    CAPTURE_ONLY = "capture_only"
    MARKET_ONLY = "market_only"


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_price_check_diagnostic_mode(settings_mode: str | None = None) -> PriceCheckDiagnosticMode:
    """Resolve B6 diagnostic mode from env or settings."""
    if _env_truthy("POE2VALUE_PRICE_CHECK_CAPTURE_ONLY"):
        return PriceCheckDiagnosticMode.CAPTURE_ONLY
    if _env_truthy("POE2VALUE_PRICE_CHECK_MARKET_ONLY"):
        return PriceCheckDiagnosticMode.MARKET_ONLY
    env_mode = os.environ.get("POE2VALUE_PRICE_CHECK_DIAGNOSTIC_MODE", "").strip().lower()
    mode = str(settings_mode or env_mode or "").strip().lower()
    if mode == PriceCheckDiagnosticMode.CAPTURE_ONLY.value:
        return PriceCheckDiagnosticMode.CAPTURE_ONLY
    if mode == PriceCheckDiagnosticMode.MARKET_ONLY.value:
        return PriceCheckDiagnosticMode.MARKET_ONLY
    return PriceCheckDiagnosticMode.NONE


def is_capture_only_mode(settings_mode: str | None = None) -> bool:
    return resolve_price_check_diagnostic_mode(settings_mode) == PriceCheckDiagnosticMode.CAPTURE_ONLY


def is_market_only_mode(settings_mode: str | None = None) -> bool:
    return resolve_price_check_diagnostic_mode(settings_mode) == PriceCheckDiagnosticMode.MARKET_ONLY


def is_diagnostic_mode_active(settings_mode: str | None = None) -> bool:
    return resolve_price_check_diagnostic_mode(settings_mode) != PriceCheckDiagnosticMode.NONE


def is_theoretical_disabled(settings_mode: str | None = None) -> bool:
    if _env_truthy("POE2VALUE_DISABLE_THEORETICAL"):
        return True
    return is_diagnostic_mode_active(settings_mode)


def default_market_fixture_path() -> Path:
    override = os.environ.get("POE2VALUE_MARKET_ONLY_FIXTURE", "").strip()
    if override:
        return Path(override)
    return DEFAULT_MARKET_FIXTURE


def load_market_fixture_text(path: Path | None = None) -> str:
    fixture_path = path or default_market_fixture_path()
    return fixture_path.read_text(encoding="utf-8")
