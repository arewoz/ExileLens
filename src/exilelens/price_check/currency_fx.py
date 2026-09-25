from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable

from exilelens.price_check.trade2_client import Trade2Client

_CURRENCY_ALIASES = {
    "divine": "divine",
    "div": "divine",
    "d": "divine",
    "exalted": "exalted",
    "ex": "exalted",
    "exa": "exalted",
    "chaos": "chaos",
    "c": "chaos",
    "regal": "regal",
}


_KNOWN_CURRENCIES = frozenset(
    {
        "divine",
        "exalted",
        "chaos",
        "regal",
        "orb of alchemy",
        "orb of fusing",
        "orb of alteration",
        "chromatic orb",
        "jeweller's orb",
        "orb of chance",
        "vaal orb",
    }
)

_GLOBAL_FX_RATES: dict[tuple[str, str, str], float] = {}
_GLOBAL_FX_FETCHED_AT: dict[tuple[str, str, str], float] = {}
_GLOBAL_FX_LOCK = Lock()
_GLOBAL_FX_TTL_SECONDS = 900.0


@dataclass
class CurrencyFxTable:
    """Auto-normalize comparable currencies using trade2 exchange when possible."""

    league: str
    client: Trade2Client | None = None
    ttl_seconds: float = 900.0
    _rates: dict[tuple[str, str], float] = field(default_factory=dict)
    _fetched_at: dict[tuple[str, str], float] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)
    _fetch_fn: Callable[[str, str, str], float | None] | None = None

    def normalize_currency(self, currency: str) -> str:
        return _CURRENCY_ALIASES.get(str(currency or "").lower(), str(currency or "").lower())

    def is_known_currency(self, currency: str) -> bool:
        normalized = self.normalize_currency(currency)
        return normalized in _KNOWN_CURRENCIES or normalized in _CURRENCY_ALIASES.values()

    def convert(self, amount: float, from_currency: str, to_currency: str) -> float | None:
        source = self.normalize_currency(from_currency)
        target = self.normalize_currency(to_currency)
        if source == target:
            return amount
        rate = self.rate(source, target)
        if rate is None:
            return None
        return amount * rate

    def rate(self, have: str, want: str) -> float | None:
        local_key = (have, want)
        global_key = (self.league, have, want)
        now = time.monotonic()
        with _GLOBAL_FX_LOCK:
            fetched = _GLOBAL_FX_FETCHED_AT.get(global_key)
            if fetched is not None and (now - fetched) <= _GLOBAL_FX_TTL_SECONDS:
                cached = _GLOBAL_FX_RATES.get(global_key)
                if cached is not None:
                    return cached
        with self._lock:
            fetched = self._fetched_at.get(local_key)
            if fetched is not None and (now - fetched) <= self.ttl_seconds:
                cached = self._rates.get(local_key)
                if cached is not None:
                    return cached
        resolved = self._fetch_rate(have, want)
        if resolved is None:
            return None
        with _GLOBAL_FX_LOCK:
            _GLOBAL_FX_RATES[global_key] = resolved
            _GLOBAL_FX_FETCHED_AT[global_key] = now
        with self._lock:
            self._rates[local_key] = resolved
            self._fetched_at[local_key] = now
        return resolved

    def _fetch_rate(self, have: str, want: str) -> float | None:
        if self._fetch_fn is not None:
            return self._fetch_fn(self.league, have, want)
        client = self.client or Trade2Client()
        return client.exchange_rate(self.league, have, want)
