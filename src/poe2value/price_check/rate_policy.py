"""Per-endpoint trade2 rate-limit scheduling, derived from server headers.

MARKET-01B11. The product objective is that normal repeated price checking produces
**zero** HTTP 429: a request the current server policy predicts will be penalised is
simply not sent.

Two things were wrong before:

1. There was a single global cooldown shared by every endpoint, but trade2 publishes a
   *separate* policy per endpoint (observed live)::

       trade-search-request-limit     5/10s(60s)  15/60s(300s)  30/300s(1800s)  600/6h(3600s)
       trade-fetch-request-limit     12/4s(10s)   16/12s(300s)  50/300s(300s)  1000/6h(1800s)
       trade-exchange-request-limit   5/15s(60s)  10/90s(300s)  30/300s(1800s)

   Mixing them meant a fetch response could relax the search cooldown and vice versa.

2. Proactive pacing was inverted. It waited ``headroom * period`` seconds, so the
   *fuller* the bucket the *shorter* the wait — 45s at 85% utilisation, but only 0.25s
   when a bucket was completely full. The next request went out a quarter of a second
   after the bucket filled and earned the full penalty.

This module instead tracks our own request timestamps per policy and computes, for each
server rule, the exact moment the sliding window frees a slot.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, Iterable

logger = logging.getLogger(__name__)

# Endpoint identities. These are ours; the server's own policy name is recorded too.
SEARCH = "search"
FETCH = "fetch"
EXCHANGE = "exchange"
LEAGUES = "leagues"

# Never sit exactly on a window boundary — clocks and the server's view differ slightly.
WINDOW_SAFETY_MARGIN_SECONDS = 0.35

# MARKET-02F2A1: cap unexplained server drift reserve so one cliff does not wedge the app.
MAX_UNCERTAINTY_RESERVE = 12

# Observed live on 2026-09-08. Used as a cold-start floor until the first 200 teaches
# the current policy. Headers always replace these.
_DEFAULT_RULES: dict[str, tuple[tuple[int, int, int], ...]] = {
    SEARCH: ((5, 10, 60), (15, 60, 300), (30, 300, 1800), (600, 21600, 3600)),
    FETCH: ((12, 4, 10), (16, 12, 300), (50, 300, 300), (1000, 21600, 1800)),
    EXCHANGE: ((5, 15, 60), (10, 90, 300), (30, 300, 1800)),
    # /data/leagues publishes no headers, yet it does 429.
    LEAGUES: ((1, 10, 60),),
}


def safety_reserve(max_hits: int) -> int:
    """How many slots of this window the product must not spend.

    A 5/10s rule keeps one slot for shared-IP drift, another process, and window-edge
    clocks. A 1-hit rule cannot reserve or the app would never send.
    """
    hits = int(max_hits or 0)
    if hits <= 1:
        return 0
    return 1


def product_max_hits(max_hits: int) -> int:
    """Known-safe dispatch budget for this window (server max minus the reserve)."""
    hits = int(max_hits or 0)
    return max(0, hits - safety_reserve(hits))


@dataclass(frozen=True)
class PolicyRule:
    """One server rule: `max_hits` requests per `period_seconds`, else `penalty_seconds`."""

    max_hits: int
    period_seconds: int
    penalty_seconds: int

    @classmethod
    def parse(cls, raw: str) -> PolicyRule | None:
        parts = str(raw or "").split(":")
        if len(parts) != 3:
            return None
        try:
            return cls(int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            return None

    def to_dict(self) -> dict[str, int]:
        return {
            "max_hits": self.max_hits,
            "period_seconds": self.period_seconds,
            "penalty_seconds": self.penalty_seconds,
        }


@dataclass(frozen=True)
class PolicyState:
    """The server's view: `current_hits` used of a `period_seconds` window."""

    current_hits: int
    period_seconds: int
    active_penalty_seconds: int

    @classmethod
    def parse(cls, raw: str) -> PolicyState | None:
        parts = str(raw or "").split(":")
        if len(parts) != 3:
            return None
        try:
            return cls(int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            return None


@dataclass
class EndpointPolicy:
    """Sliding-window scheduler for one trade2 endpoint."""

    endpoint: str
    clock: Callable[[], float] = time.monotonic
    rules: tuple[PolicyRule, ...] = ()
    server_policy: str = ""
    penalty_until: float = 0.0
    last_state: tuple[PolicyState, ...] = ()
    _requests: deque[float] = field(default_factory=deque, repr=False)
    _server_hits: dict[int, int] = field(default_factory=dict, repr=False)
    _ghosts: dict[int, list[float]] = field(default_factory=dict, repr=False)
    # MARKET-02F2A1: server-authoritative ledger — last observed hits + observation time.
    _server_watermarks: dict[int, tuple[int, float]] = field(default_factory=dict, repr=False)
    _uncertainty_reserve: dict[int, int] = field(default_factory=dict, repr=False)
    _last_dispatch_prediction: dict[int, int] = field(default_factory=dict, repr=False)
    _last_divergence: dict[str, object] = field(default_factory=dict, repr=False)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def __post_init__(self) -> None:
        if not self.rules and self.endpoint in _DEFAULT_RULES:
            self.rules = tuple(PolicyRule(*row) for row in _DEFAULT_RULES[self.endpoint])

    # ------------------------------------------------------------------ bookkeeping

    def record_request(self, at: float | None = None) -> None:
        """Record that we sent a request. Call immediately before dispatching."""
        with self._lock:
            self._requests.append(self.clock() if at is None else at)
            self._trim_locked()

    def _trim_locked(self) -> None:
        if not self.rules:
            # Keep a short tail so a policy learned later still has history.
            horizon = 600.0
        else:
            horizon = float(max(rule.period_seconds for rule in self.rules))
        cutoff = self.clock() - horizon
        while self._requests and self._requests[0] < cutoff:
            self._requests.popleft()

    # ------------------------------------------------------------------- scheduling

    def seconds_until_safe(self) -> float:
        """How long until another request is allowed. 0.0 means send it now."""
        with self._lock:
            now = self.clock()
            wait = max(0.0, self.penalty_until - now)
            for rule in self.rules:
                wait = max(wait, self._rule_wait_locked(rule, now))
            return wait

    def _occupied_locked(self, rule: PolicyRule, now: float) -> list[float]:
        window_start = now - rule.period_seconds
        in_window = [stamp for stamp in self._requests if stamp > window_start]
        # The server's own count for this window wins when it is higher: the bucket is
        # per IP, so another client (or an earlier run of this app) may have used it.
        # Counts are matched by window length, never mixed across rules — a six-hour
        # bucket sitting at 370/600 must not make the ten-second bucket look full.
        ghosts = [
            stamp
            for stamp in self._ghosts.get(rule.period_seconds, ())
            if stamp > window_start
        ]
        return sorted(in_window + ghosts)

    def _safe_capacity_locked(self, rule: PolicyRule) -> int:
        """Dispatch budget after base reserve and any proven unexplained server drift."""
        reserve = self._uncertainty_reserve.get(rule.period_seconds, 0)
        return max(0, product_max_hits(rule.max_hits) - int(reserve or 0))

    def _effective_used_locked(self, rule: PolicyRule, now: float) -> tuple[int, list[float]]:
        """Effective occupancy = max(local stamps, server watermark + local since observation)."""
        window_start = now - rule.period_seconds
        occupied = self._occupied_locked(rule, now)
        local_used = len(occupied)
        period = rule.period_seconds
        watermark_hits, watermark_at = self._server_watermarks.get(period, (0, 0.0))
        server_effective = 0
        if watermark_hits > 0 and watermark_at > window_start:
            requests_since = sum(
                1 for stamp in self._requests if stamp > max(window_start, watermark_at)
            )
            server_effective = int(watermark_hits) + requests_since
        effective = max(local_used, server_effective)
        return effective, occupied

    def _rule_wait_locked(self, rule: PolicyRule, now: float) -> float:
        if rule.max_hits <= 0 or rule.period_seconds <= 0:
            return 0.0
        effective_used, occupied = self._effective_used_locked(rule, now)
        effective_max = self._safe_capacity_locked(rule)
        if effective_max <= 0:
            return 0.0
        if effective_used < effective_max:
            return 0.0

        waits: list[float] = []
        if occupied:
            index = max(0, len(occupied) - effective_max)
            release_at = occupied[index] + rule.period_seconds
            waits.append(max(0.0, release_at - now + WINDOW_SAFETY_MARGIN_SECONDS))

        period = rule.period_seconds
        watermark_hits, watermark_at = self._server_watermarks.get(period, (0, 0.0))
        window_start = now - period
        if watermark_at > window_start and int(watermark_hits) >= effective_max:
            waits.append(max(0.0, watermark_at + period - now + WINDOW_SAFETY_MARGIN_SECONDS))
        return max(waits) if waits else float(rule.period_seconds)

    def next_safe_at(self) -> float:
        return self.clock() + self.seconds_until_safe()

    def allows_now(self) -> bool:
        return self.seconds_until_safe() <= 0.0

    # ---------------------------------------------------------------- server updates

    def update_from_headers(
        self,
        headers: dict[str, str] | None,
        *,
        http_status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Learn the policy from a response, and record any penalty the server applied."""
        normalized = _normalize(headers or {})
        now = self.clock()

        policy = normalized.get("x-rate-limit-policy") or ""
        if policy:
            self.server_policy = policy

        rules_raw = normalized.get("x-rate-limit-rules") or ""
        rule_names = [name.strip() for name in rules_raw.split(",") if name.strip()]

        parsed_rules: list[PolicyRule] = []
        parsed_states: list[PolicyState] = []
        for name in rule_names:
            limits = normalized.get(f"x-rate-limit-{name.lower()}") or ""
            states = normalized.get(f"x-rate-limit-{name.lower()}-state") or ""
            for raw in limits.split(","):
                rule = PolicyRule.parse(raw)
                if rule is not None:
                    parsed_rules.append(rule)
            for raw in states.split(","):
                state = PolicyState.parse(raw)
                if state is not None:
                    parsed_states.append(state)

        if parsed_rules:
            self.rules = tuple(parsed_rules)
        if parsed_states:
            self.last_state = tuple(parsed_states)

        # An explicit server penalty always wins.
        penalty = 0.0
        if retry_after is not None and retry_after > 0:
            penalty = float(retry_after)
        for state in parsed_states:
            if state.active_penalty_seconds > 0:
                penalty = max(penalty, float(state.active_penalty_seconds))
        if penalty > 0:
            self.penalty_until = max(self.penalty_until, now + penalty)
            logger.warning(
                "trade2 rate penalty endpoint=%s policy=%s seconds=%.1f http_status=%s",
                self.endpoint,
                self.server_policy,
                penalty,
                http_status,
            )

        # Reconcile our own history with the server's count. If the server has seen more
        # requests in a window than we recorded (shared IP, another client, an earlier
        # process), adopt its count so pacing stays conservative. A lower server figure
        # never erases local occupancy — the server header can lag.
        self._record_server_counts(parsed_rules, parsed_states, http_status=http_status)

    def predict_before_dispatch(self) -> dict[str, object]:
        """Diagnostic snapshot immediately before an HTTP dispatch."""
        with self._lock:
            now = self.clock()
            per_rule: list[dict[str, object]] = []
            prediction: dict[int, int] = {}
            wait = max(0.0, self.penalty_until - now)
            for rule in self.rules:
                effective_used, _occupied = self._effective_used_locked(rule, now)
                safe_capacity = self._safe_capacity_locked(rule)
                prediction[rule.period_seconds] = effective_used
                per_rule.append(
                    {
                        **rule.to_dict(),
                        "effective_used": effective_used,
                        "safe_capacity": safe_capacity,
                        "uncertainty_reserve": self._uncertainty_reserve.get(rule.period_seconds, 0),
                        "watermark_hits": self._server_watermarks.get(rule.period_seconds, (0, 0.0))[0],
                    }
                )
                wait = max(wait, self._rule_wait_locked(rule, now))
            self._last_dispatch_prediction = prediction
        return {
            "endpoint": self.endpoint,
            "server_policy": self.server_policy,
            "seconds_until_safe": round(wait, 3),
            "rules": per_rule,
        }

    def _record_server_counts(
        self,
        rules: Iterable[PolicyRule],
        states: Iterable[PolicyState],
        *,
        http_status: int | None = None,
    ) -> None:
        """Reconcile the server's per-window count with what we know we sent.

        Only the *difference* is recorded, as ghost requests stamped now — the
        conservative reading — and only against the window it was reported for.
        """
        rules = list(rules)
        states = list(states)
        if not states:
            return
        with self._lock:
            now = self.clock()
            for index, state in enumerate(states):
                period = state.period_seconds
                if period <= 0 and index < len(rules):
                    period = rules[index].period_seconds
                if period <= 0:
                    continue
                window_start = now - period
                ours = sum(1 for stamp in self._requests if stamp > window_start)
                existing = [s for s in self._ghosts.get(period, []) if s > window_start]
                server_hits = int(state.current_hits)
                # Server count wins when it is higher. Local occupancy wins when the
                # header is stale and reports fewer hits than we know we sent.
                unseen = max(0, server_hits - ours)
                if unseen > len(existing):
                    existing.extend([now] * (unseen - len(existing)))
                self._ghosts[period] = existing
                self._server_hits[period] = max(int(self._server_hits.get(period, 0) or 0), server_hits)

                prior_hits, prior_at = self._server_watermarks.get(period, (0, 0.0))
                if prior_at > window_start:
                    watermark_hits = max(int(prior_hits), server_hits)
                else:
                    watermark_hits = server_hits
                self._server_watermarks[period] = (watermark_hits, now)

                if http_status == 429:
                    predicted = int(self._last_dispatch_prediction.get(period, ours))
                    unexplained = max(0, server_hits - predicted)
                    if unexplained > 0:
                        prior = int(self._uncertainty_reserve.get(period, 0) or 0)
                        updated = min(MAX_UNCERTAINTY_RESERVE, max(prior, unexplained))
                        self._uncertainty_reserve[period] = updated
                        self._last_divergence = {
                            "endpoint": self.endpoint,
                            "server_policy": self.server_policy,
                            "period_seconds": period,
                            "predicted_effective": predicted,
                            "server_hits": server_hits,
                            "unexplained_delta": unexplained,
                            "uncertainty_reserve": updated,
                        }
                        logger.warning(
                            "trade2 rate divergence endpoint=%s policy=%s period=%ss "
                            "predicted=%s server=%s unexplained=%s reserve=%s",
                            self.endpoint,
                            self.server_policy,
                            period,
                            predicted,
                            server_hits,
                            unexplained,
                            updated,
                        )

    def penalty_remaining(self) -> float:
        return max(0.0, self.penalty_until - self.clock())

    def restore_penalty(self, seconds_remaining: float) -> None:
        """Re-arm a penalty learned before this process started."""
        seconds = float(seconds_remaining or 0.0)
        if seconds <= 0 or seconds > MAX_PERSISTED_PENALTY_SECONDS:
            return
        self.penalty_until = max(self.penalty_until, self.clock() + seconds)
        logger.info(
            "trade2 restored penalty endpoint=%s seconds=%.0f", self.endpoint, seconds
        )

    def dump_persist_state(self, *, wall_now: float) -> dict[str, object]:
        """Wall-clock snapshot so another process can reload occupancy, not just penalties."""
        with self._lock:
            mono_now = self.clock()
            remaining = max(0.0, self.penalty_until - mono_now)
            request_epochs = [
                wall_now - max(0.0, mono_now - stamp) for stamp in self._requests
            ]
            ghost_epochs = {
                str(period): [wall_now - max(0.0, mono_now - stamp) for stamp in stamps]
                for period, stamps in self._ghosts.items()
            }
            watermark_epochs = {
                str(period): {
                    "hits": hits,
                    "observed_epoch": wall_now - max(0.0, mono_now - observed_at),
                }
                for period, (hits, observed_at) in self._server_watermarks.items()
            }
            return {
                "until_epoch": (wall_now + remaining) if remaining > 0 else 0.0,
                "server_policy": self.server_policy,
                "rules": [rule.to_dict() for rule in self.rules],
                "server_hits": {str(period): hits for period, hits in self._server_hits.items()},
                "request_epochs": request_epochs,
                "ghost_epochs": ghost_epochs,
                "watermark_epochs": watermark_epochs,
                "uncertainty_reserve": {
                    str(period): value for period, value in self._uncertainty_reserve.items()
                },
                "observed_epoch": wall_now,
            }

    def restore_persist_state(self, entry: dict, *, wall_now: float) -> None:
        """Adopt occupancy + penalty from a persisted snapshot. Never shrinks occupancy."""
        if not isinstance(entry, dict):
            return
        try:
            remaining = float(entry.get("until_epoch", 0.0) or 0.0) - wall_now
        except (TypeError, ValueError):
            remaining = 0.0
        if remaining > 0:
            self.restore_penalty(remaining)

        policy_name = str(entry.get("server_policy") or "").strip()
        if policy_name:
            self.server_policy = policy_name

        parsed_rules: list[PolicyRule] = []
        for row in entry.get("rules") or ():
            if not isinstance(row, dict):
                continue
            try:
                parsed_rules.append(
                    PolicyRule(
                        int(row["max_hits"]),
                        int(row["period_seconds"]),
                        int(row["penalty_seconds"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        if parsed_rules:
            self.rules = tuple(parsed_rules)

        mono_now = self.clock()

        def _to_mono(epoch: object) -> float | None:
            try:
                age = max(0.0, wall_now - float(epoch))
            except (TypeError, ValueError):
                return None
            return mono_now - age

        restored_requests = [_to_mono(epoch) for epoch in entry.get("request_epochs") or ()]
        with self._lock:
            for stamp in restored_requests:
                if stamp is None:
                    continue
                if stamp not in self._requests:
                    self._requests.append(stamp)
            self._requests = deque(sorted(self._requests))
            ghost_epochs = entry.get("ghost_epochs") or {}
            if isinstance(ghost_epochs, dict):
                for raw_period, stamps in ghost_epochs.items():
                    try:
                        period = int(raw_period)
                    except (TypeError, ValueError):
                        continue
                    converted = []
                    for epoch in stamps or ():
                        stamp = _to_mono(epoch)
                        if stamp is not None:
                            converted.append(stamp)
                    existing = list(self._ghosts.get(period, ()))
                    merged = sorted(set(existing + converted))
                    self._ghosts[period] = merged
            hits = entry.get("server_hits") or {}
            if isinstance(hits, dict):
                for raw_period, raw_hits in hits.items():
                    try:
                        period = int(raw_period)
                        value = int(raw_hits)
                    except (TypeError, ValueError):
                        continue
                    self._server_hits[period] = max(int(self._server_hits.get(period, 0) or 0), value)
            watermark_epochs = entry.get("watermark_epochs") or {}
            if isinstance(watermark_epochs, dict):
                for raw_period, payload in watermark_epochs.items():
                    try:
                        period = int(raw_period)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(payload, dict):
                        continue
                    try:
                        hits = int(payload.get("hits", 0) or 0)
                    except (TypeError, ValueError):
                        continue
                    observed_at = _to_mono(payload.get("observed_epoch"))
                    if observed_at is None:
                        continue
                    prior_hits, prior_at = self._server_watermarks.get(period, (0, 0.0))
                    self._server_watermarks[period] = (
                        max(int(prior_hits), hits),
                        max(float(prior_at), float(observed_at)),
                    )
            reserves = entry.get("uncertainty_reserve") or {}
            if isinstance(reserves, dict):
                for raw_period, raw_value in reserves.items():
                    try:
                        period = int(raw_period)
                        value = int(raw_value)
                    except (TypeError, ValueError):
                        continue
                    self._uncertainty_reserve[period] = max(
                        int(self._uncertainty_reserve.get(period, 0) or 0),
                        min(MAX_UNCERTAINTY_RESERVE, value),
                    )
            self._trim_locked()

    # ------------------------------------------------------------------ diagnostics

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            now = self.clock()
            per_rule = []
            for rule in self.rules:
                effective_used, _occupied = self._effective_used_locked(rule, now)
                reserved = safety_reserve(rule.max_hits)
                uncertainty = int(self._uncertainty_reserve.get(rule.period_seconds, 0) or 0)
                safe_capacity = self._safe_capacity_locked(rule)
                remaining = max(0, rule.max_hits - effective_used)
                per_rule.append(
                    {
                        **rule.to_dict(),
                        "used": effective_used,
                        "remaining": remaining,
                        "reserved": reserved,
                        "uncertainty_reserve": uncertainty,
                        "dispatchable": max(0, safe_capacity - effective_used),
                        "safe_capacity": safe_capacity,
                        "watermark_hits": self._server_watermarks.get(rule.period_seconds, (0, 0.0))[0],
                    }
                )
        return {
            "endpoint": self.endpoint,
            "server_policy": self.server_policy,
            "rules": per_rule,
            "penalty_remaining_seconds": round(max(0.0, self.penalty_until - self.clock()), 2),
            "seconds_until_safe": round(self.seconds_until_safe(), 2),
            "last_divergence": dict(self._last_divergence),
        }

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()
            self._server_hits.clear()
            self._ghosts.clear()
            self._server_watermarks.clear()
            self._uncertainty_reserve.clear()
            self._last_dispatch_prediction.clear()
            self._last_divergence.clear()
            self.penalty_until = 0.0
            self.last_state = ()


# A persisted penalty older than this is ignored: better a single rediscovery request
# than an app wedged by stale state.
MAX_PERSISTED_PENALTY_SECONDS = 2 * 60 * 60


class TradePolicyRegistry:
    """The per-endpoint policies for one process."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._policies: dict[str, EndpointPolicy] = {}
        self._lock = Lock()
        self._persist_path = None

    def policy(self, endpoint: str) -> EndpointPolicy:
        with self._lock:
            existing = self._policies.get(endpoint)
            if existing is None:
                existing = EndpointPolicy(endpoint=endpoint, clock=self._clock)
                self._policies[endpoint] = existing
            return existing

    def seconds_until_safe(self, endpoint: str) -> float:
        return self.policy(endpoint).seconds_until_safe()

    def allows_now(self, endpoint: str) -> bool:
        return self.policy(endpoint).allows_now()

    def record_request(self, endpoint: str) -> None:
        self.policy(endpoint).record_request()
        self._maybe_persist()

    def predict_before_dispatch(self, endpoint: str) -> dict[str, object]:
        return self.policy(endpoint).predict_before_dispatch()

    def update_from_headers(
        self,
        endpoint: str,
        headers: dict[str, str] | None,
        *,
        http_status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        self.policy(endpoint).update_from_headers(
            headers, http_status=http_status, retry_after=retry_after
        )
        self._maybe_persist()

    def enable_persist(self, path) -> None:
        """Write occupancy + penalties after every change so another process can load it."""
        self._persist_path = path
        self._maybe_persist()

    def _maybe_persist(self) -> None:
        path = self._persist_path
        if path is None:
            return
        self.save_penalties(path)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            endpoints = list(self._policies)
        return {name: self.policy(name).snapshot() for name in endpoints}

    def reset(self) -> None:
        with self._lock:
            policies = list(self._policies.values())
        for policy in policies:
            policy.reset()


    def save_penalties(self, path) -> None:
        """Persist occupancy and active penalties as wall-clock state.

        MARKET-02B1: a restart, a diagnostic script, or another process sharing the IP
        must see the last known search occupancy — not only an explicit 429 penalty.
        Empty endpoints are omitted. Atomic replace so a crash cannot leave a partial file.
        """
        import json
        import os
        import pathlib
        import time as _time

        payload: dict[str, object] = {}
        wall_now = _time.time()
        with self._lock:
            endpoints = list(self._policies)
        for name in endpoints:
            payload[name] = self.policy(name).dump_persist_state(wall_now=wall_now)
        try:
            target = pathlib.Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            encoded = json.dumps(payload, indent=2)
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(encoded, encoding="utf-8")
            os.replace(tmp, target)
        except OSError:
            logger.warning("could not persist trade2 policy to %s", path)

    def load_penalties(self, path) -> None:
        import json
        import pathlib
        import time as _time

        try:
            raw = pathlib.Path(path).read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        wall_now = _time.time()
        for name, entry in data.items():
            if not isinstance(entry, dict):
                continue
            self.policy(str(name)).restore_persist_state(entry, wall_now=wall_now)


_REGISTRY: TradePolicyRegistry | None = None
_REGISTRY_LOCK = Lock()


def shared_policy_registry() -> TradePolicyRegistry:
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = TradePolicyRegistry()
        return _REGISTRY


def reset_shared_policy_registry() -> None:
    shared_policy_registry().reset()


def _normalize(headers: dict[str, str]) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in headers.items() if value is not None}
