from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any, Callable

logger = logging.getLogger(__name__)

_monotonic_clock: Callable[[], float] = time.monotonic
_GLOBAL_RATE_LIMIT_STATE: RateLimitState | None = None


def monotonic_now() -> float:
    return _monotonic_clock()


def set_monotonic_clock(clock: Callable[[], float]) -> None:
    global _monotonic_clock
    _monotonic_clock = clock


def reset_monotonic_clock() -> None:
    global _monotonic_clock
    _monotonic_clock = time.monotonic


class CooldownSource(str, Enum):
    SERVER_RETRY_AFTER = "SERVER_RETRY_AFTER"
    SERVER_RATE_STATE = "SERVER_RATE_STATE"
    LOCAL_PROACTIVE_PACING = "LOCAL_PROACTIVE_PACING"
    LOCAL_DEFAULT = "LOCAL_DEFAULT"
    LOCAL_FALLBACK_COOLDOWN = "LOCAL_FALLBACK_COOLDOWN"


def shared_rate_limit_state() -> RateLimitState:
    global _GLOBAL_RATE_LIMIT_STATE
    if _GLOBAL_RATE_LIMIT_STATE is None:
        _GLOBAL_RATE_LIMIT_STATE = RateLimitState()
    return _GLOBAL_RATE_LIMIT_STATE


def reset_shared_rate_limit_state() -> None:
    state = shared_rate_limit_state()
    state.limited_until = 0.0
    state.proactive_wait_until = 0.0
    state.last_retry_after = None
    state.last_headers.clear()
    state.policy = ""
    state.rules = ()
    state.cooldown_source = ""
    state.cooldown_set_at_monotonic = 0.0


def log_cooldown_state(state: RateLimitState, *, event: str, **extra: Any) -> None:
    snapshot = state.snapshot(include_diagnostics=True)
    payload = {
        "event": event,
        "cooldown_source": snapshot.get("cooldown_source") or CooldownSource.LOCAL_DEFAULT.value,
        "now_monotonic": snapshot.get("now_monotonic"),
        "limited_until_monotonic": snapshot.get("limited_until"),
        "proactive_wait_until_monotonic": snapshot.get("proactive_wait_until"),
        "remaining_seconds": snapshot.get("seconds_until_allowed"),
        **extra,
    }
    logger.info("price_check_cooldown %s", payload)


@dataclass
class ParsedRateLimitRule:
    max_hits: int
    period_seconds: int
    penalty_seconds: int


@dataclass
class ParsedRateLimitState:
    current_hits: int
    period_seconds: int
    active_penalty_seconds: int


@dataclass
class RateLimitState:
    """Provider-level trade2 rate-limit state derived from response headers."""

    limited_until: float = 0.0
    policy: str = ""
    rules: tuple[str, ...] = ()
    last_retry_after: float | None = None
    last_headers: dict[str, str] = field(default_factory=dict)
    proactive_wait_until: float = 0.0
    cooldown_source: str = ""
    cooldown_set_at_monotonic: float = 0.0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def is_limited(self) -> bool:
        with self._lock:
            return self._seconds_until_allowed_locked() > 0

    def seconds_until_allowed(self) -> float:
        with self._lock:
            return self._seconds_until_allowed_locked()

    def _seconds_until_allowed_locked(self) -> float:
        now = monotonic_now()
        remaining = max(0.0, self.limited_until - now)
        proactive = max(0.0, self.proactive_wait_until - now)
        return max(remaining, proactive)

    def peek_cooldown(self, *, event: str = "local_check") -> float:
        """Read-only cooldown inspection — never extends the deadline."""
        remaining = self.seconds_until_allowed()
        log_cooldown_state(self, event=event)
        return remaining

    def update_from_headers(
        self,
        headers: dict[str, str] | None,
        *,
        retry_after: float | None = None,
        http_status: int | None = None,
    ) -> None:
        normalized = _normalize_headers(headers or {})
        header_retry = parse_retry_after(normalized)
        if retry_after is not None:
            parsed_retry = retry_after
        elif http_status == 429:
            parsed_retry = header_retry
        else:
            parsed_retry = None

        policy, rules, limited_until, proactive_wait, cooldown_source = parse_rate_limit_headers(
            normalized,
            parsed_retry,
            now=monotonic_now(),
        )
        with self._lock:
            if policy:
                self.policy = policy
            if rules:
                self.rules = rules
            if parsed_retry is not None:
                self.last_retry_after = parsed_retry
            if normalized:
                self.last_headers = dict(normalized)
            extended = False
            if limited_until > self.limited_until:
                self.limited_until = limited_until
                self.cooldown_source = cooldown_source.value
                self.cooldown_set_at_monotonic = monotonic_now()
                extended = True
            if proactive_wait > self.proactive_wait_until:
                self.proactive_wait_until = proactive_wait
                if not self.cooldown_source:
                    self.cooldown_source = CooldownSource.LOCAL_PROACTIVE_PACING.value
                    self.cooldown_set_at_monotonic = monotonic_now()
                extended = True
        if extended:
            log_cooldown_state(self, event="cooldown_extended", http_status=http_status)

    def wait_if_needed(self) -> float:
        seconds = self.seconds_until_allowed()
        if seconds <= 0:
            return 0.0
        time.sleep(min(seconds, 5.0))
        return seconds

    def snapshot(self, *, include_diagnostics: bool = False) -> dict[str, Any]:
        with self._lock:
            payload = {
                "limited_until": self.limited_until,
                "proactive_wait_until": self.proactive_wait_until,
                "policy": self.policy,
                "rules": list(self.rules),
                "last_retry_after": self.last_retry_after,
                "seconds_until_allowed": self._seconds_until_allowed_locked(),
                "cooldown_source": self.cooldown_source,
                "cooldown_set_at_monotonic": self.cooldown_set_at_monotonic,
            }
            if include_diagnostics:
                payload["now_monotonic"] = monotonic_now()
            return payload


def parse_retry_after(headers: dict[str, str]) -> float | None:
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def parse_rate_limit_rule(raw: str) -> ParsedRateLimitRule | None:
    parts = str(raw or "").split(":")
    if len(parts) != 3:
        return None
    try:
        return ParsedRateLimitRule(
            max_hits=int(parts[0]),
            period_seconds=int(parts[1]),
            penalty_seconds=int(parts[2]),
        )
    except ValueError:
        return None


def parse_rate_limit_state(raw: str) -> ParsedRateLimitState | None:
    parts = str(raw or "").split(":")
    if len(parts) != 3:
        return None
    try:
        return ParsedRateLimitState(
            current_hits=int(parts[0]),
            period_seconds=int(parts[1]),
            active_penalty_seconds=int(parts[2]),
        )
    except ValueError:
        return None


def parse_rate_limit_headers(
    headers: dict[str, str],
    retry_after: float | None = None,
    *,
    now: float | None = None,
) -> tuple[str, tuple[str, ...], float, float, CooldownSource]:
    """Return policy, rules, limited_until monotonic timestamp, proactive wait timestamp, source."""
    current = now if now is not None else monotonic_now()
    policy = headers.get("X-Rate-Limit-Policy") or headers.get("x-rate-limit-policy") or ""
    rules_raw = headers.get("X-Rate-Limit-Rules") or headers.get("x-rate-limit-rules") or ""
    rules = tuple(rule.strip() for rule in rules_raw.split(",") if rule.strip())

    limited_until = current
    proactive_wait = 0.0
    cooldown_source = CooldownSource.LOCAL_DEFAULT

    if retry_after is not None and retry_after > 0:
        limited_until = current + retry_after
        cooldown_source = CooldownSource.SERVER_RETRY_AFTER

    state_penalty_applied = False
    for rule_name in rules:
        limit_key = f"X-Rate-Limit-{rule_name}"
        state_key = f"X-Rate-Limit-{rule_name}-State"
        limit_raw = headers.get(limit_key) or headers.get(limit_key.lower()) or ""
        state_raw = headers.get(state_key) or headers.get(state_key.lower()) or ""
        limit_rules = [parse_rate_limit_rule(row) for row in limit_raw.split(",") if row.strip()]
        state_rules = [parse_rate_limit_state(row) for row in state_raw.split(",") if row.strip()]
        for index, state in enumerate(state_rules):
            if state is None:
                continue
            if state.active_penalty_seconds > 0:
                candidate = current + float(state.active_penalty_seconds)
                if candidate > limited_until:
                    limited_until = candidate
                    if retry_after is None or retry_after <= 0:
                        cooldown_source = CooldownSource.SERVER_RATE_STATE
                    state_penalty_applied = True
            rule = limit_rules[index] if index < len(limit_rules) else None
            if rule is None or rule.max_hits <= 0:
                continue
            if state.active_penalty_seconds <= 0 and state.current_hits >= rule.max_hits:
                # MARKET-01B11: this used to wait `headroom * period`, so the *fuller*
                # the bucket the *shorter* the wait — 0.25s once a bucket was completely
                # full, which is what earned the penalty on the very next request. A
                # full bucket must wait for the window to roll.
                # Fine-grained pacing lives in `price_check.rate_policy`, which tracks
                # our own request timestamps per endpoint; this stays as a coarse floor.
                proactive_wait = max(proactive_wait, current + float(rule.period_seconds))

    if proactive_wait > current and not state_penalty_applied and cooldown_source == CooldownSource.LOCAL_DEFAULT:
        cooldown_source = CooldownSource.LOCAL_PROACTIVE_PACING

    return policy, rules, limited_until, proactive_wait, cooldown_source


def _normalize_headers(headers: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in headers.items():
        if value is None:
            continue
        canonical = key if key.startswith("X-Rate-Limit") or key.lower() == "retry-after" else key
        if key.lower() == "retry-after":
            canonical = "Retry-After"
        result[canonical] = str(value)
    return result


@dataclass
class RateLimiter:
    """Simple token-bucket rate limiter for comparable lookups."""

    max_calls: int = 6
    window_seconds: float = 12.0
    _timestamps: list[float] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    def acquire(self) -> bool:
        with self._lock:
            now = monotonic_now()
            cutoff = now - self.window_seconds
            self._timestamps = [stamp for stamp in self._timestamps if stamp >= cutoff]
            if len(self._timestamps) >= self.max_calls:
                return False
            self._timestamps.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._timestamps.clear()
