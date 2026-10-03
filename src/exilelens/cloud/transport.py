"""Small JSON-over-HTTPS client and retry policy for the optional ExileLens cloud service.

Nothing here runs on the UI thread or the Item Check path: it is called only from the background
flusher. A failing, slow or quota-exhausted service must cost the app nothing, so every outcome is
mapped to one of a few actions and retries back off exponentially (honouring ``Retry-After``).
"""

from __future__ import annotations

import json
import logging
import random
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from exilelens._version import __version__

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 64 * 1024
BACKOFF_BASE_SECONDS = 60.0
BACKOFF_CAP_SECONDS = 6 * 3600.0
RETRY_AFTER_CAP_SECONDS = 24 * 3600.0


class Action(str, Enum):
    DONE = "done"  # accepted (or a harmless duplicate)
    DROP = "drop"  # permanent rejection: never retry this batch
    DISABLE = "disable"  # service says this client version is unsupported: stop until the app is updated
    RETRY = "retry"  # transient: keep the queue and back off


@dataclass(frozen=True)
class PostResult:
    status: int  # 0 = network failure
    code: str = ""
    retry_after: float | None = None
    body: dict[str, Any] = field(default_factory=dict)

    @property
    def action(self) -> Action:
        if 200 <= self.status < 300:
            return Action.DONE
        if self.status == 410:
            return Action.DISABLE
        if self.status in (400, 413, 415, 422):
            return Action.DROP
        return Action.RETRY


class CloudHttp:
    def __init__(self, base_url: str, opener: Callable = urllib.request.urlopen, timeout: float = REQUEST_TIMEOUT_SECONDS) -> None:
        self.base_url = base_url.rstrip("/")
        self._opener = opener
        self._timeout = timeout

    def post_json(self, path: str, body: dict[str, Any], *, headers: dict[str, str] | None = None) -> PostResult:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"ExileLens/{__version__}",
            "X-ExileLens-Client": __version__,
            **(headers or {}),
        }
        request = urllib.request.Request(self.base_url + path, data=data, headers=request_headers, method="POST")
        try:
            with self._opener(request, timeout=self._timeout) as response:
                return self._result(int(getattr(response, "status", 200) or 200), response)
        except urllib.error.HTTPError as exc:
            try:
                return self._result(int(exc.code), exc)
            finally:
                exc.close()
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return PostResult(status=0, code="network")

    def get_json(self, path: str, *, headers: dict[str, str] | None = None) -> PostResult:
        request_headers = {
            "Accept": "application/json",
            "User-Agent": f"ExileLens/{__version__}",
            "X-ExileLens-Client": __version__,
            **(headers or {}),
        }
        request = urllib.request.Request(self.base_url + path, headers=request_headers, method="GET")
        try:
            with self._opener(request, timeout=self._timeout) as response:
                return self._result(int(getattr(response, "status", 200) or 200), response)
        except urllib.error.HTTPError as exc:
            try:
                return self._result(int(exc.code), exc)
            finally:
                exc.close()
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return PostResult(status=0, code="network")

    @staticmethod
    def _result(status: int, response: Any) -> PostResult:
        body: dict[str, Any] = {}
        try:
            raw = response.read(MAX_RESPONSE_BYTES)
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
            if isinstance(parsed, dict):
                body = parsed
        except (ValueError, UnicodeError, OSError):
            body = {}
        headers = getattr(response, "headers", None)
        retry_after: float | None = None
        if headers is not None:
            try:
                value = headers.get("Retry-After")
                if value is not None:
                    retry_after = min(max(float(value), 0.0), RETRY_AFTER_CAP_SECONDS)
            except (TypeError, ValueError):
                retry_after = None
        code = body.get("code") if isinstance(body.get("code"), str) else ""
        return PostResult(status=status, code=code[:64], retry_after=retry_after, body=body)


class Backoff:
    """Exponential backoff with jitter; ``Retry-After`` raises the floor and is always honoured."""

    def __init__(self, rng: Callable[[], float] = random.random) -> None:
        self.failures = 0
        self.not_before = 0.0
        self._rng = rng

    def ready(self, now: float) -> bool:
        return now >= self.not_before

    def success(self) -> None:
        self.failures = 0
        self.not_before = 0.0

    def failure(self, now: float, retry_after: float | None = None) -> float:
        self.failures += 1
        delay = min(BACKOFF_BASE_SECONDS * (2 ** (self.failures - 1)), BACKOFF_CAP_SECONDS)
        delay *= 0.8 + 0.4 * self._rng()
        if retry_after is not None:
            delay = max(delay, retry_after)
        self.not_before = now + delay
        return delay
