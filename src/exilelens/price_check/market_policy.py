from __future__ import annotations

import os
from typing import Literal

LiveMarketMode = Literal["auto", "disabled"]

_LIVE_CHAIN_PROVIDER_IDS = frozenset({"live_trade2", "cached_live_trade2"})


def _env_flag(name: str) -> str:
    return os.environ.get(name, "").strip().lower()


def _is_pytest_runtime() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def resolve_live_market_mode(settings_mode: str | None = None) -> LiveMarketMode:
    """Live market is enabled by default; disable via settings or POE2VALUE_LIVE_TRADE2=0."""
    from exilelens.security_audit import network_disabled

    if network_disabled():
        return "disabled"
    env = _env_flag("POE2VALUE_LIVE_TRADE2")
    if env in {"0", "false", "no", "disabled", "off"}:
        return "disabled"
    env_mode = _env_flag("POE2VALUE_LIVE_MARKET_MODE")
    if env_mode in {"disabled", "off", "0"}:
        return "disabled"
    mode = str(settings_mode or env_mode or "auto").strip().lower()
    if mode in {"disabled", "off", "0"}:
        return "disabled"
    return "auto"


def is_live_market_enabled(settings_mode: str | None = None) -> bool:
    return resolve_live_market_mode(settings_mode) == "auto"


def resolve_strict_live(settings_strict: bool | None = None) -> bool:
    """Strict live is ON by default for owner/dev/frozen builds; tests opt out via pytest or env."""
    env = _env_flag("POE2VALUE_LIVE_TRADE2_STRICT")
    if env in {"0", "false", "no", "off"}:
        return False
    if env in {"1", "true", "yes"}:
        return True
    if settings_strict is not None:
        return bool(settings_strict)
    if _is_pytest_runtime():
        return False
    return True


def is_live_chain_provider(provider_id: str) -> bool:
    return provider_id in _LIVE_CHAIN_PROVIDER_IDS
