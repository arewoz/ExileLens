"""HTTP transport seam for the trade2 client (R5-A).

The client never opens a connection itself: it hands a `TransportRequest` to a `Trade2Transport` and reads a `TransportResponse`.
Tests inject a fake transport, so no test can reach the network. Production uses `AuthorizedTransport(UrllibTransport())`, which
refuses every request unless central market access (`market_policy.resolve_market_access`) permits network use. While the live
trade2 provider is not authorized (see `market_policy.LIVE_TRADE2_AUTHORIZATION`) that is never, so the production transport
makes zero requests.

Deliberately small: a dataclass pair and a callable Protocol, no HTTP framework.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol


@dataclass(frozen=True)
class TransportRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None
    timeout: float = 30.0


@dataclass(frozen=True)
class TransportResponse:
    """Any HTTP status is a response, not an exception: status handling lives in one place (the client)."""

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""


class TransportError(Exception):
    """The request did not produce an HTTP response. `kind` is "timeout" or "network"."""

    def __init__(self, kind: str, message: str = "") -> None:
        super().__init__(message or kind)
        self.kind = kind


class TransportNotPermitted(TransportError):
    """Raised before anything is sent when market networking is not permitted (disabled, no_network, not authorized)."""

    def __init__(self, state: str) -> None:
        super().__init__("not_permitted", f"market network access not permitted: {state}")
        self.state = state


class Trade2Transport(Protocol):
    def __call__(self, request: TransportRequest) -> TransportResponse: ...


class UrllibTransport:
    """The only code in the market stack that opens a connection. Always wrapped by `AuthorizedTransport` in production."""

    def __call__(self, request: TransportRequest) -> TransportResponse:
        import socket

        outgoing = urllib.request.Request(request.url, data=request.body, headers=dict(request.headers), method=request.method)
        try:
            with urllib.request.urlopen(outgoing, timeout=request.timeout) as response:  # noqa: S310 - guarded by AuthorizedTransport
                return TransportResponse(int(response.status or 200), _headers(response.headers), response.read())
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read()
            except Exception:  # noqa: BLE001
                body = b""
            return TransportResponse(int(exc.code), _headers(exc.headers), body)
        except (socket.timeout, TimeoutError) as exc:
            raise TransportError("timeout", str(exc)) from exc
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), (socket.timeout, TimeoutError)):
                raise TransportError("timeout", str(exc)) from exc
            raise TransportError("network", str(exc)) from exc


def _headers(raw) -> dict[str, str]:
    if raw is None:
        return {}
    return {str(key): str(value) for key, value in raw.items()}


class AuthorizedTransport:
    """Checks central market access on EVERY request, before the inner transport can send anything."""

    def __init__(self, inner: Trade2Transport, access: Callable[[], object]) -> None:
        self._inner = inner
        self._access = access

    def refusal(self) -> str | None:
        """The reason a request would be refused right now, or None when permitted. Lets callers skip pacing/accounting for a request
        that would never be sent."""
        decision = self._access()
        if getattr(decision, "network_permitted", False):
            return None
        return str(getattr(getattr(decision, "state", None), "value", decision))

    def __call__(self, request: TransportRequest) -> TransportResponse:
        reason = self.refusal()
        if reason is not None:
            raise TransportNotPermitted(reason)
        return self._inner(request)
