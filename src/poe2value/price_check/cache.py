from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from concurrent.futures import Future
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable, TypeVar

from poe2value.price_check.models import PriceCheckResult

T = TypeVar("T")


@dataclass
class _CacheEntry:
    result: PriceCheckResult
    stored_at: float


@dataclass
class _TimedEntry:
    value: Any
    stored_at: float


@dataclass
class PriceCheckCache:
    """Isolated namespace for price-check results (not gameplay evaluation cache)."""

    ttl_seconds: float = 300.0
    live_ttl_seconds: float = 90.0
    stale_ttl_seconds: float = 3600.0
    _entries: dict[str, _CacheEntry] = field(default_factory=dict)

    def make_key(
        self,
        *,
        item_fingerprint: str,
        league: str | None,
        provider_id: str,
        provider_generation: str,
        hypothesis_fingerprint: str = "",
    ) -> str:
        league_key = league or "UNKNOWN"
        hypo = str(hypothesis_fingerprint or "").strip()
        if hypo:
            return f"price_check|{item_fingerprint}|{league_key}|{provider_id}|{provider_generation}|{hypo}"
        return f"price_check|{item_fingerprint}|{league_key}|{provider_id}|{provider_generation}"

    def get(self, key: str) -> PriceCheckResult | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if self.ttl_seconds > 0 and (time.monotonic() - entry.stored_at) > self.ttl_seconds:
            return None
        return self._with_cache_hit(entry.result)

    def get_live(self, key: str) -> PriceCheckResult | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if self.live_ttl_seconds > 0 and (time.monotonic() - entry.stored_at) > self.live_ttl_seconds:
            return None
        return self._with_cache_hit(entry.result, age_seconds=self._age_seconds(entry))

    def get_stale(self, key: str) -> PriceCheckResult | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if self.stale_ttl_seconds > 0 and (time.monotonic() - entry.stored_at) > self.stale_ttl_seconds:
            self._entries.pop(key, None)
            return None
        return self._with_cache_hit(entry.result, age_seconds=self._age_seconds(entry))

    def cache_age_seconds(self, key: str) -> float | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        return self._age_seconds(entry)

    def put(self, key: str, result: PriceCheckResult) -> None:
        self._entries[key] = _CacheEntry(result=result, stored_at=time.monotonic())

    def invalidate(self) -> None:
        self._entries.clear()

    def stats(self) -> dict[str, Any]:
        return {
            "entries": len(self._entries),
            "ttl_seconds": self.ttl_seconds,
            "live_ttl_seconds": self.live_ttl_seconds,
            "stale_ttl_seconds": self.stale_ttl_seconds,
        }

    @staticmethod
    def _age_seconds(entry: _CacheEntry) -> float:
        return max(0.0, time.monotonic() - entry.stored_at)

    @staticmethod
    def _with_cache_hit(cached: PriceCheckResult, *, age_seconds: float | None = None) -> PriceCheckResult:
        # MARKET-01B13: same stale-field-list bug as the service had — `replace` keeps
        # every field a cached result carries, including the ones added after this code.
        return replace(cached, cache_hit=True, cache_age_seconds=age_seconds)


@dataclass
class TimedResponseCache:
    """Short-lived cache for trade2 query/listing payloads."""

    ttl_seconds: float = 90.0
    _entries: dict[str, _TimedEntry] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    @staticmethod
    def make_key(*parts: Any) -> str:
        payload = json.dumps(parts, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if self.ttl_seconds > 0 and (time.monotonic() - entry.stored_at) > self.ttl_seconds:
                self._entries.pop(key, None)
                return None
            return entry.value

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._entries[key] = _TimedEntry(value=value, stored_at=time.monotonic())

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


@dataclass
class InFlightCoalescer:
    """Coalesce concurrent lookups for the same cache key into one pipeline."""

    _pending: dict[str, Future[Any]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def run(self, key: str, fn: Callable[[], T]) -> T:
        with self._lock:
            pending = self._pending.get(key)
            if pending is not None:
                waiter = pending
                future = None
            else:
                future: Future[T] = Future()
                self._pending[key] = future
                waiter = None
        if waiter is not None:
            return waiter.result()
        assert future is not None
        try:
            result = fn()
        except Exception as exc:
            with self._lock:
                self._pending.pop(key, None)
                future.set_exception(exc)
            raise
        with self._lock:
            self._pending.pop(key, None)
            future.set_result(result)
        return result
