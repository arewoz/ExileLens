from __future__ import annotations

import json
import logging
import os
import statistics
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable

from exilelens.price_check.cache import TimedResponseCache
from exilelens.price_check.rate_limit import RateLimitState, shared_rate_limit_state
from exilelens.price_check.trade2_query_validation import ensure_valid_trade2_search_body
from exilelens.price_check.rate_policy import (
    EXCHANGE,
    FETCH,
    LEAGUES,
    SEARCH,
    TradePolicyRegistry,
    shared_policy_registry,
)

TRADE2_BASE_URL = "https://www.pathofexile.com"
USER_AGENT = "poe2-value-overlay/0.5 (price-check)"
FETCH_BATCH_SIZE = 10

logger = logging.getLogger(__name__)

_QUERY_CACHE = TimedResponseCache(ttl_seconds=90.0)
_LISTING_CACHE = TimedResponseCache(ttl_seconds=120.0)


class Trade2Error(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "trade2_error",
        http_status: int | None = None,
        retry_after: float | None = None,
        response_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.retry_after = retry_after
        self.response_headers = response_headers or {}


@dataclass
class Trade2SearchResult:
    query_id: str
    total: int
    result_ids: list[str]
    http_status: int = 200
    response_headers: dict[str, str] = field(default_factory=dict)


def parse_exchange_rate(
    payload: dict[str, Any],
    *,
    have: str,
    want: str,
) -> float | None:
    """How many `want` one `have` buys, from a trade2 bulk-exchange payload.

    MARKET-01B9A fix. Each offer carries both sides of the trade::

        "exchange": {"currency": "exalted", "amount": 35}   # what you pay
        "item":     {"currency": "chaos",   "amount": 5}    # what you receive

    so the rate is ``item.amount / exchange.amount``. The previous implementation read
    only ``exchange.amount`` and took its minimum, which is not a rate at all: it
    returned 1.0 for both `exalted -> chaos` and `chaos -> exalted`, so every mixed
    currency comparable was normalized 1:1 and expensive listings were inflated to the
    point where the outlier filter discarded them.

    The median of the observed ratios is used rather than the best or worst offer, so a
    single junk 1:1 listing cannot move the rate.
    """
    result = payload.get("result")
    if not isinstance(result, dict):
        return None

    have_key = str(have or "").lower()
    want_key = str(want or "").lower()
    ratios: list[float] = []
    for row in result.values():
        if not isinstance(row, dict):
            continue
        listing = row.get("listing") or {}
        offers = listing.get("offers") or []
        if isinstance(offers, dict):
            offers = [offers]
        if not isinstance(offers, list):
            continue
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            exchange = offer.get("exchange") or {}
            item = offer.get("item") or {}
            if not isinstance(exchange, dict) or not isinstance(item, dict):
                continue
            paid = exchange.get("amount")
            received = item.get("amount")
            if paid is None or received is None:
                continue
            exchange_currency = str(exchange.get("currency") or "").lower()
            item_currency = str(item.get("currency") or "").lower()
            if exchange_currency and have_key and exchange_currency != have_key:
                continue
            if item_currency and want_key and item_currency != want_key:
                continue
            try:
                paid_value = float(paid)
                received_value = float(received)
            except (TypeError, ValueError):
                continue
            if paid_value <= 0 or received_value <= 0:
                continue
            ratios.append(received_value / paid_value)

    if not ratios:
        return None
    return statistics.median(ratios)


@dataclass
class Trade2Client:
    """Anonymous-first trade2 HTTP client. Session only from runtime env."""

    base_url: str = TRADE2_BASE_URL
    timeout_seconds: float = 30.0
    fetch_batch_size: int = FETCH_BATCH_SIZE
    rate_limit_state: RateLimitState | None = None
    query_cache: TimedResponseCache | None = None
    listing_cache: TimedResponseCache | None = None
    _stats_cache: dict[str, Any] | None = field(default=None, init=False)
    _leagues_cache: list[str] | None = field(default=None, init=False)
    _cache_lock: Lock = field(default_factory=Lock, init=False)
    policy_registry: TradePolicyRegistry | None = None
    _last_response_headers: dict[str, str] = field(default_factory=dict, init=False)
    _last_http_status: int = 200
    search_requests: int = field(default=0, init=False)
    fetch_requests: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.rate_limit_state is None:
            self.rate_limit_state = shared_rate_limit_state()
        if self.policy_registry is None:
            self.policy_registry = shared_policy_registry()
        if self.query_cache is None:
            self.query_cache = _QUERY_CACHE
        if self.listing_cache is None:
            self.listing_cache = _LISTING_CACHE

    @property
    def session_id(self) -> str | None:
        raw = os.environ.get("POE2VALUE_TRADE2_SESSION", "").strip()
        return raw or None

    @property
    def authentication_mode(self) -> str:
        return "SESSION" if self.session_id else "ANONYMOUS"

    @property
    def total_http_requests(self) -> int:
        return self.search_requests + self.fetch_requests

    def reset_request_counters(self) -> None:
        self.search_requests = 0
        self.fetch_requests = 0

    def search_url(self, league: str) -> str:
        encoded_league = urllib.parse.quote(league, safe="")
        return f"{self.base_url}/api/trade2/search/poe2/{encoded_league}"

    def search(self, league: str, body: dict[str, Any]) -> Trade2SearchResult:
        cache_key = TimedResponseCache.make_key("search", league, body)
        cached = self.query_cache.get(cache_key) if self.query_cache is not None else None
        if isinstance(cached, Trade2SearchResult):
            return cached

        url = self.search_url(league)
        self._ensure_not_rate_limited()
        self._gate(SEARCH)
        # MARKET-01B12: a malformed query fails here, locally, rather than spending a
        # scarce search request to be told HTTP 400. Checked after the rate gate so a
        # paced caller still gets the pacing signal it can queue on, but before the
        # request is accounted for, so an invalid query costs no budget.
        body = ensure_valid_trade2_search_body(body)
        self._account(SEARCH)
        self.search_requests += 1
        try:
            payload = self._post_json(url, body)
        finally:
            self._absorb_policy(SEARCH)
        if isinstance(payload.get("error"), dict):
            error = payload["error"]
            raise Trade2Error(
                str(error.get("message") or "trade2 search failed"),
                code="bad_request",
                http_status=400,
            )
        result_ids = [str(row) for row in payload.get("result") or []]
        query_id = str(payload.get("id") or "")
        if not query_id:
            raise Trade2Error("trade2 search missing query id", code="parse_error", http_status=200)
        result = Trade2SearchResult(
            query_id=query_id,
            total=int(payload.get("total") or len(result_ids)),
            result_ids=result_ids,
            http_status=self._last_http_status,
            response_headers=dict(self._last_response_headers),
        )
        if self.query_cache is not None:
            self.query_cache.put(cache_key, result)
        return result

    def fetch(self, result_ids: list[str], query_id: str) -> list[dict[str, Any]]:
        return self.fetch_progressive(result_ids, query_id)

    def fetch_progressive(
        self,
        result_ids: list[str],
        query_id: str,
        *,
        stop_when: Callable[[list[dict[str, Any]]], bool] | None = None,
        max_fetch_requests: int | None = None,
    ) -> list[dict[str, Any]]:
        if not result_ids:
            return []
        if not query_id:
            raise Trade2Error("trade2 fetch missing query id", code="fetch_error")
        rows: list[dict[str, Any]] = []
        batch_size = max(1, int(self.fetch_batch_size))
        fetch_batches = 0
        for offset in range(0, len(result_ids), batch_size):
            if max_fetch_requests is not None and fetch_batches >= max_fetch_requests:
                break
            batch = result_ids[offset : offset + batch_size]
            batch_rows = self._fetch_batch(batch, query_id)
            rows.extend(batch_rows)
            fetch_batches += 1
            if stop_when is not None and stop_when(rows):
                break
        return rows

    def _fetch_batch(self, result_ids: list[str], query_id: str) -> list[dict[str, Any]]:
        cache_key = TimedResponseCache.make_key("fetch", query_id, tuple(result_ids))
        cached = self.listing_cache.get(cache_key) if self.listing_cache is not None else None
        if isinstance(cached, list):
            return cached

        joined = ",".join(result_ids)
        query = urllib.parse.quote(query_id, safe="")
        url = f"{self.base_url}/api/trade2/fetch/{joined}?query={query}"
        self._ensure_not_rate_limited()
        self._gate(FETCH)
        self._account(FETCH)
        self.fetch_requests += 1
        try:
            payload = self._get_json(url)
        except Trade2Error:
            raise
        except Exception as exc:
            raise Trade2Error(str(exc), code="fetch_error") from exc
        finally:
            self._absorb_policy(FETCH)
        rows = payload.get("result") or []
        if not isinstance(rows, list):
            raise Trade2Error("invalid trade2 fetch response", code="parse_error")
        parsed = [row for row in rows if isinstance(row, dict)]
        if self.listing_cache is not None:
            self.listing_cache.put(cache_key, parsed)
        return parsed

    def list_leagues(self) -> list[str]:
        with self._cache_lock:
            if self._leagues_cache is not None:
                return list(self._leagues_cache)
        self._gate(LEAGUES)
        self._account(LEAGUES)
        try:
            payload = self._get_json(f"{self.base_url}/api/trade2/data/leagues")
        finally:
            self._absorb_policy(LEAGUES)
        leagues = [str(row.get("id") or "") for row in payload.get("result") or [] if isinstance(row, dict)]
        leagues = [row for row in leagues if row]
        with self._cache_lock:
            self._leagues_cache = leagues
        return list(leagues)

    def resolve_active_league(self) -> str | None:
        for league_id in self.list_leagues():
            lowered = league_id.lower()
            if lowered in {"standard", "hardcore"}:
                continue
            if lowered.startswith("hc "):
                continue
            return league_id
        return None

    def canonicalize_league(self, league: str) -> str | None:
        cleaned = str(league or "").strip()
        if not cleaned:
            return None
        with self._cache_lock:
            cached_leagues = self._leagues_cache
        if cached_leagues is not None:
            if cleaned in cached_leagues:
                return cleaned
            lowered = cleaned.lower()
            for candidate in cached_leagues:
                if candidate.lower() == lowered:
                    return candidate
        return cleaned

    def stats_data(self) -> list[dict[str, Any]]:
        with self._cache_lock:
            if self._stats_cache is not None:
                return list(self._stats_cache.get("result") or [])
        payload = self._get_json(f"{self.base_url}/api/trade2/data/stats")
        with self._cache_lock:
            self._stats_cache = payload
        return list(payload.get("result") or [])

    def exchange_rate(self, league: str, have: str, want: str) -> float | None:
        encoded_league = urllib.parse.quote(league, safe="")
        url = f"{self.base_url}/api/trade2/exchange/poe2/{encoded_league}"
        body = {
            "query": {
                "status": {"option": "online"},
                "have": [have],
                "want": [want],
            },
            "sort": {"have": "asc"},
            "engine": "new",
        }
        self._gate(EXCHANGE)
        self._account(EXCHANGE)
        try:
            payload = self._post_json(url, body)
        finally:
            self._absorb_policy(EXCHANGE)
        return parse_exchange_rate(payload, have=have, want=want)

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if self.session_id:
            headers["Cookie"] = f"POESESSID={self.session_id}"
        return headers

    def seconds_until_safe(self, endpoint: str) -> float:
        """How long before a request to this endpoint is allowed by server policy."""
        registry = self.policy_registry
        return 0.0 if registry is None else registry.seconds_until_safe(endpoint)

    def allows_now(self, endpoint: str) -> bool:
        return self.seconds_until_safe(endpoint) <= 0.0

    def _gate(self, endpoint: str) -> None:
        """Refuse to send a request the current server policy says will be penalised.

        MARKET-01B11: this is the difference between handling a 429 and not causing
        one. The error carries the exact wait so the caller can queue instead of
        failing.
        """
        registry = self.policy_registry
        if registry is not None:
            prediction = registry.predict_before_dispatch(endpoint)
            if prediction.get("seconds_until_safe", 0) > 0:
                logger.debug(
                    "trade2 dispatch withheld endpoint=%s policy=%s prediction=%s",
                    endpoint,
                    prediction.get("server_policy"),
                    prediction,
                )
        wait = self.seconds_until_safe(endpoint)
        if wait <= 0:
            return
        raise Trade2Error(
            f"trade2 {endpoint} paced by server policy",
            code="rate_limit_pacing",
            http_status=None,
            retry_after=wait,
        )

    def _account(self, endpoint: str) -> None:
        if self.policy_registry is not None:
            self.policy_registry.record_request(endpoint)

    def _absorb_policy(self, endpoint: str, retry_after: float | None = None) -> None:
        """Feed the response back into this endpoint's policy, penalty included.

        The Retry-After on an error response must reach the scheduler, otherwise a
        fresh process would rediscover an existing penalty with another 429 on every
        run instead of learning it once.
        """
        if self.policy_registry is None:
            return
        if retry_after is None:
            retry_after = self._parse_retry_after(self._last_response_headers)
        if retry_after is None and self._last_http_status == 429:
            # A 429 with no Retry-After still means "stop"; fall back to the tightest
            # penalty this endpoint's own rules declare.
            policy = self.policy_registry.policy(endpoint)
            penalties = [rule.penalty_seconds for rule in policy.rules if rule.penalty_seconds > 0]
            retry_after = float(min(penalties)) if penalties else 60.0
        self.policy_registry.update_from_headers(
            endpoint,
            self._last_response_headers,
            http_status=self._last_http_status,
            retry_after=retry_after,
        )

    def _ensure_not_rate_limited(self) -> None:
        state = self.rate_limit_state
        if state is None:
            return
        remaining = state.peek_cooldown(event="local_precheck")
        if remaining <= 0:
            return
        raise Trade2Error(
            "trade2 rate limited",
            code="rate_limited",
            http_status=429,
            retry_after=remaining,
            response_headers=dict(state.last_headers),
        )

    def _post_json(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        if self.rate_limit_state is not None:
            self.rate_limit_state.wait_if_needed()
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={**self._headers(), "Content-Type": "application/json"},
            method="POST",
        )
        return self._request_json(request)

    def _get_json(self, url: str) -> dict[str, Any]:
        if self.rate_limit_state is not None:
            self.rate_limit_state.wait_if_needed()
        request = urllib.request.Request(url, headers=self._headers(), method="GET")
        return self._request_json(request)

    def _request_json(self, request: urllib.request.Request) -> dict[str, Any]:
        import time

        self._last_http_status = 200
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                self._last_http_status = int(response.status or 200)
                self._last_response_headers = self._headers_to_dict(response.headers)
                if self.rate_limit_state is not None:
                    self.rate_limit_state.update_from_headers(
                        self._last_response_headers,
                        http_status=self._last_http_status,
                    )
                    self.rate_limit_state.wait_if_needed()
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            self._last_http_status = exc.code
            self._last_response_headers = self._headers_to_dict(exc.headers)
            retry_after = self._parse_retry_after(exc.headers)
            if self.rate_limit_state is not None:
                self.rate_limit_state.update_from_headers(
                    self._last_response_headers,
                    retry_after=retry_after,
                    http_status=exc.code,
                )
            if exc.code == 429:
                remaining = retry_after
                if self.rate_limit_state is not None:
                    remaining = self.rate_limit_state.seconds_until_allowed() or retry_after
                raise Trade2Error(
                    "trade2 rate limited",
                    code="rate_limited",
                    http_status=exc.code,
                    retry_after=remaining,
                    response_headers=self._last_response_headers,
                ) from exc
            if exc.code == 401:
                raise Trade2Error(
                    "trade2 authentication required",
                    code="auth_required",
                    http_status=exc.code,
                    response_headers=self._last_response_headers,
                ) from exc
            if exc.code == 403:
                raise Trade2Error(
                    "trade2 forbidden",
                    code="forbidden",
                    http_status=exc.code,
                    response_headers=self._last_response_headers,
                ) from exc
            if exc.code == 400:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    detail = ""
                raise Trade2Error(
                    f"trade2 HTTP {exc.code}" + (f": {detail}" if detail else ""),
                    code="bad_request",
                    http_status=exc.code,
                    retry_after=retry_after,
                    response_headers=self._last_response_headers,
                ) from exc
            raise Trade2Error(
                f"trade2 HTTP {exc.code}",
                code="http_error",
                http_status=exc.code,
                retry_after=retry_after,
                response_headers=self._last_response_headers,
            ) from exc
        except urllib.error.URLError as exc:
            raise Trade2Error(str(exc), code="network_error") from exc
        except json.JSONDecodeError as exc:
            raise Trade2Error("invalid trade2 response", code="parse_error") from exc
        if not isinstance(payload, dict):
            raise Trade2Error("invalid trade2 response", code="parse_error")
        return payload

    @staticmethod
    def _headers_to_dict(headers: Any) -> dict[str, str]:
        if headers is None:
            return {}
        result: dict[str, str] = {}
        for key in (
            "Retry-After",
            "retry-after",
            "X-Rate-Limit-Policy",
            "X-Rate-Limit-Rules",
            "X-Rate-Limit-Account",
            "X-Rate-Limit-Account-State",
            "X-Rate-Limit-Ip",
            "X-Rate-Limit-Ip-State",
            "X-Rate-Limit-Client",
            "X-Rate-Limit-Client-State",
        ):
            value = headers.get(key)
            if value is not None:
                result[key] = str(value)
        return result

    @staticmethod
    def _parse_retry_after(headers: Any) -> float | None:
        if headers is None:
            return None
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
