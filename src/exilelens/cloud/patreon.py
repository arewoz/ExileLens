"""Optional Patreon linking: a device credential plus a signed capability lease. Nothing else.

ExileLens has no accounts. Linking Patreon only lets the ExileLens service say "this device may automate
updates" (capability ``seamless_updates``). The desktop never receives Patreon tokens, names, emails or any
profile data: the service completes the OAuth flow server-side and returns an opaque random *device
credential* and a signed *lease*.

* The device credential is protected with per-user Windows DPAPI (``device.bin``); the lease and the
  small non-secret status file sit beside it under ``%LOCALAPPDATA%\\ExileLens\\cloud\\patreon\\``.
* The lease is verified locally on every use (``exilelens.cloud.entitlement``). Tampered, expired,
  foreign-device or unknown-key leases yield no capabilities — the install behaves exactly like a free one.
* An outage of Cloudflare, D1 or Patreon never removes a still-valid lease ("offline grace"); an expired
  or missing lease just means manual updates, which always keep working.
* Disconnecting deletes the credential and lease locally first, then makes one best-effort server request.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit

from exilelens._version import __version__
from exilelens.cloud import entitlement
from exilelens.cloud.entitlement import CAP_SEAMLESS_UPDATES, LeaseStatus
from exilelens.cloud.transport import Backoff, CloudHttp, PostResult
from exilelens.platform.windows import dpapi

logger = logging.getLogger(__name__)

LINK_TTL_SECONDS = 600
POLL_INTERVAL_SECONDS = 2.0
AUTHORIZE_HOST = "www.patreon.com"
AUTHORIZE_PATH = "/oauth2/authorize"
_HEX32 = re.compile(r"[0-9a-f]{32}")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{20,128}")


class PatreonState(str, Enum):
    NOT_CONNECTED = "not_connected"
    LINKING = "linking"
    ACTIVE = "active"
    NOT_ELIGIBLE = "not_eligible"
    OFFLINE_GRACE = "offline_grace"
    EXPIRED = "expired"
    RECONNECT_REQUIRED = "reconnect_required"
    SERVICE_UNAVAILABLE = "service_unavailable"


@dataclass(frozen=True)
class PatreonView:
    state: PatreonState
    capabilities: frozenset[str] = frozenset()
    expires_at: int | None = None
    detail: str = ""  # machine-readable reason (never user text, never provider data)

    @property
    def seamless_updates(self) -> bool:
        return CAP_SEAMLESS_UPDATES in self.capabilities


@dataclass(frozen=True)
class Credential:
    device_id: str
    device_token: str


class PatreonStore:
    """Files for one linked device. Only ``device.bin`` is secret, and it is DPAPI-protected."""

    def __init__(
        self,
        root: Path,
        protect: Callable[[bytes], bytes] = dpapi.protect,
        unprotect: Callable[[bytes], bytes] = dpapi.unprotect,
    ) -> None:
        self.root = root
        self.credential_path = root / "device.bin"
        self.lease_path = root / "lease.json"
        self.state_path = root / "state.json"
        self._protect = protect
        self._unprotect = unprotect

    def save_credential(self, credential: Credential) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        blob = self._protect(json.dumps({"id": credential.device_id, "token": credential.device_token}).encode("utf-8"))
        tmp = self.credential_path.with_name("device.bin.tmp")
        tmp.write_bytes(blob)
        os.replace(tmp, self.credential_path)

    def has_credential_file(self) -> bool:
        return self.credential_path.is_file()

    def load_credential(self) -> Credential | None:
        """``None`` when there is no *usable* credential (missing, corrupt, other user/machine)."""
        try:
            blob = self.credential_path.read_bytes()
            payload = json.loads(self._unprotect(blob).decode("utf-8"))
        except (OSError, ValueError, UnicodeError, dpapi.DpapiUnavailable):
            return None
        if not isinstance(payload, dict) or set(payload) != {"id", "token"}:
            return None
        device_id, token = payload["id"], payload["token"]
        if isinstance(device_id, str) and _HEX32.fullmatch(device_id) and isinstance(token, str) and _TOKEN.fullmatch(token):
            return Credential(device_id, token)
        return None

    def save_lease(self, envelope: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.lease_path.with_name("lease.json.tmp")
        tmp.write_text(json.dumps(envelope, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, self.lease_path)

    def load_lease(self) -> dict[str, Any] | None:
        try:
            if self.lease_path.stat().st_size > entitlement.MAX_LEASE_BYTES:
                return None
            data = json.loads(self.lease_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return None
        return data if isinstance(data, dict) else None

    def delete_lease(self) -> None:
        self.lease_path.unlink(missing_ok=True)

    def read_status(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def write_status(self, **changes: Any) -> None:
        status = {**self.read_status(), **changes}
        allowed = {"reconnect_needed", "last_ok", "last_fail", "fail_reason"}
        status = {k: v for k, v in status.items() if k in allowed}
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_name("state.json.tmp")
        tmp.write_text(json.dumps(status), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def clear(self) -> None:
        try:
            shutil.rmtree(self.root)
        except FileNotFoundError:
            pass
        except OSError:
            for path in (self.credential_path, self.lease_path, self.state_path):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


def valid_authorize_url(url: object) -> bool:
    if not isinstance(url, str) or len(url) > 2048:
        return False
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and parts.hostname == AUTHORIZE_HOST
        and not parts.username
        and not parts.password
        and parts.port in (None, 443)
        and parts.path == AUTHORIZE_PATH
    )


class PatreonLink:
    def __init__(
        self,
        store: PatreonStore,
        *,
        base_url: Callable[[], str | None],
        http_factory: Callable[[str], CloudHttp] = CloudHttp,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        open_url: Callable[[str], bool] | None = None,
    ) -> None:
        self.store = store
        self._base_url = base_url
        self._http_factory = http_factory
        self._clock = clock
        self._sleep = sleep
        self._open_url = open_url or _default_open_url
        self._lock = threading.RLock()
        self._backoff = Backoff()
        self._linking = False
        self._cancel = threading.Event()
        self._link_thread: threading.Thread | None = None
        self._link_message = ""
        self._service_unavailable = False
        self._refreshing = False
        self._listeners: list[Callable[[PatreonView], None]] = []
        self._credential_cache: Credential | None = None
        self._credential_checked = False

    # -- availability / listeners ---------------------------------------------------------------
    def available(self) -> bool:
        return bool(self._base_url())

    def add_listener(self, listener: Callable[[PatreonView], None]) -> None:
        self._listeners.append(listener)

    def _notify(self) -> None:
        view = self.view()
        for listener in list(self._listeners):
            try:
                listener(view)
            except Exception:  # noqa: BLE001
                logger.debug("patreon_listener_failed")

    # -- state ----------------------------------------------------------------------------------
    def _credential(self) -> Credential | None:
        with self._lock:
            if not self._credential_checked:
                self._credential_cache = self.store.load_credential()
                self._credential_checked = True
            return self._credential_cache

    def _lease_result(self, now: float) -> entitlement.LeaseResult:
        credential = self._credential()
        envelope = self.store.load_lease()
        if credential is None or envelope is None:
            return entitlement.LeaseResult(LeaseStatus.MALFORMED)
        return entitlement.verify_lease(envelope, device_id=credential.device_id, now=now)

    def capabilities(self, now: float | None = None) -> frozenset[str]:
        """Known capabilities of a currently valid, locally verified lease (else empty)."""
        return self._lease_result(self._clock() if now is None else now).capabilities

    def seamless_updates_allowed(self, now: float | None = None) -> bool:
        return CAP_SEAMLESS_UPDATES in self.capabilities(now)

    def view(self, now: float | None = None) -> PatreonView:
        now = self._clock() if now is None else now
        with self._lock:
            if self._linking:
                return PatreonView(PatreonState.LINKING, detail=self._link_message)
        status = self.store.read_status()
        credential = self._credential()
        if credential is None:
            if self.store.has_credential_file() or status.get("reconnect_needed"):
                return PatreonView(PatreonState.RECONNECT_REQUIRED, detail="credential_unreadable")
            if self._service_unavailable:
                return PatreonView(PatreonState.SERVICE_UNAVAILABLE, detail=self._link_message)
            return PatreonView(PatreonState.NOT_CONNECTED, detail=self._link_message)
        if status.get("reconnect_needed"):
            return PatreonView(PatreonState.RECONNECT_REQUIRED, detail=str(status.get("fail_reason") or "reauthorize"))
        result = self._lease_result(now)
        if not result.valid or result.lease is None:
            return PatreonView(PatreonState.EXPIRED, detail=result.status.value)
        caps = result.capabilities
        expires = result.lease.expires_at
        failing = float(status.get("last_fail") or 0) > float(status.get("last_ok") or 0)
        if CAP_SEAMLESS_UPDATES not in caps:
            return PatreonView(PatreonState.NOT_ELIGIBLE, caps, expires)
        if failing and now >= result.lease.refresh_after:
            return PatreonView(PatreonState.OFFLINE_GRACE, caps, expires, str(status.get("fail_reason") or ""))
        return PatreonView(PatreonState.ACTIVE, caps, expires)

    # -- linking --------------------------------------------------------------------------------
    def start_link(self) -> bool:
        """Begin browser linking. Returns False when unavailable or already linking."""
        base = self._base_url()
        if not base:
            return False
        with self._lock:
            if self._linking:
                return False
            self._linking = True
            self._cancel.clear()
            self._link_message = ""
            self._service_unavailable = False
        self._link_thread = threading.Thread(target=self._link_worker, args=(base,), name="exilelens-patreon-link", daemon=True)
        self._link_thread.start()
        self._notify()
        return True

    def cancel_link(self) -> None:
        self._cancel.set()

    def _finish_link(self, message: str = "", *, unavailable: bool = False) -> None:
        with self._lock:
            self._linking = False
            self._link_message = message
            self._service_unavailable = unavailable
        self._notify()

    def _link_worker(self, base: str) -> None:
        http = self._http_factory(base)
        try:
            started = http.post_json("/v1/patreon/link/start", {"schema": 1})
            body = started.body
            if started.status != 201 or not body.get("ok"):
                self._finish_link("start_failed" if started.status else "network", unavailable=True)
                return
            session_id, poll_token, url = body.get("session_id"), body.get("poll_token"), body.get("authorize_url")
            if not (
                isinstance(session_id, str) and _HEX32.fullmatch(session_id)
                and isinstance(poll_token, str) and _TOKEN.fullmatch(poll_token)
                and valid_authorize_url(url)
            ):
                self._finish_link("invalid_start_response", unavailable=True)
                return
            ttl = body.get("expires_at")
            deadline = self._clock() + LINK_TTL_SECONDS
            if isinstance(ttl, int) and 0 < ttl - int(self._clock()) <= LINK_TTL_SECONDS:
                deadline = float(ttl)
            try:
                opened = bool(self._open_url(url))
            except Exception:  # noqa: BLE001
                opened = False
            if not opened:
                self._finish_link("browser_unavailable")
                return
            self._poll(http, session_id, poll_token, deadline)
        except Exception:  # noqa: BLE001 - linking must never raise into the app
            logger.exception("patreon_link_worker_failed")
            self._finish_link("link_failed")

    def _poll(self, http: CloudHttp, session_id: str, poll_token: str, deadline: float) -> None:
        headers = {"Authorization": f"Bearer {poll_token}"}
        path = f"/v1/patreon/link/status?session_id={quote(session_id)}"
        failures = 0
        while True:
            if self._cancel.is_set():
                self._cancel_remote(http, session_id, headers)
                self._finish_link("cancelled")
                return
            if self._clock() >= deadline:
                self._finish_link("timeout")
                return
            result = http.get_json(path, headers=headers)
            status = str(result.body.get("status") or "") if result.status == 200 else ""
            if result.status == 404:
                self._finish_link("link_failed")
                return
            if result.status != 200:
                failures += 1
                self._sleep(min(POLL_INTERVAL_SECONDS * (2 ** min(failures, 3)), 15.0))
                continue
            failures = 0
            if status == "pending":
                self._sleep(POLL_INTERVAL_SECONDS)
                continue
            if status in ("linked", "not_entitled"):
                self._complete(result)
                return
            self._finish_link(status if status in ("denied", "expired", "failed", "cancelled", "consumed") else "link_failed")
            return

    def _cancel_remote(self, http: CloudHttp, session_id: str, headers: dict[str, str]) -> None:
        try:
            http.delete_json(f"/v1/patreon/link/session?session_id={quote(session_id)}", headers=headers)
        except Exception:  # noqa: BLE001
            pass

    def _complete(self, result: PostResult) -> None:
        body = result.body
        device_id, token, lease = body.get("device_id"), body.get("device_token"), body.get("lease")
        if not (isinstance(device_id, str) and _HEX32.fullmatch(device_id) and isinstance(token, str) and _TOKEN.fullmatch(token)):
            self._finish_link("invalid_credential")
            return
        verified = entitlement.verify_lease(lease, device_id=device_id, now=self._clock())
        if not verified.valid:
            self._finish_link("invalid_lease")
            return
        try:
            self.store.save_credential(Credential(device_id, token))
            self.store.save_lease(lease)
            self.store.write_status(reconnect_needed=False, last_ok=self._clock(), last_fail=0, fail_reason="")
        except (OSError, dpapi.DpapiUnavailable):
            self.store.clear()
            self._finish_link("credential_store_failed")
            return
        with self._lock:
            self._credential_cache = Credential(device_id, token)
            self._credential_checked = True
            self._backoff.success()
        self._finish_link("")

    # -- refresh --------------------------------------------------------------------------------
    def refresh_due(self, now: float) -> bool:
        if self._linking or self._refreshing or not self._base_url():
            return False
        if self._credential() is None or self.store.read_status().get("reconnect_needed"):
            return False
        if not self._backoff.ready(now):
            return False
        result = self._lease_result(now)
        if not result.valid or result.lease is None:
            return True
        return now >= result.lease.refresh_after

    def tick(self, now: float | None = None) -> None:
        now = self._clock() if now is None else now
        try:
            if self.refresh_due(now):
                self.refresh(now)
        except Exception:  # noqa: BLE001
            logger.debug("patreon_tick_failed")

    def refresh(self, now: float | None = None) -> PostResult | None:
        """One refresh attempt (blocking; call from the flusher thread). Never raises."""
        now = self._clock() if now is None else now
        base = self._base_url()
        credential = self._credential()
        if not base or credential is None:
            return None
        with self._lock:
            if self._refreshing:
                return None
            self._refreshing = True
        try:
            http = self._http_factory(base)
            result = http.post_json(
                "/v1/patreon/entitlement/refresh",
                {"schema": 1, "client_version": __version__},
                headers={"Authorization": f"Bearer {credential.device_token}"},
            )
            self._apply_refresh(result, credential, now)
            return result
        except Exception:  # noqa: BLE001
            logger.exception("patreon_refresh_failed")
            return None
        finally:
            with self._lock:
                self._refreshing = False
            self._notify()

    def _apply_refresh(self, result: PostResult, credential: Credential, now: float) -> None:
        if result.status == 200 and result.body.get("ok"):
            verified = entitlement.verify_lease(result.body.get("lease"), device_id=credential.device_id, now=now)
            if verified.valid:
                self.store.save_lease(result.body["lease"])
                self.store.write_status(last_ok=now, last_fail=0, fail_reason="")
                self._backoff.success()
                return
            self._fail(now, "invalid_lease", None)
            return
        if result.status == 401 and result.code in ("device_unknown", "reauthorize_required"):
            # The service no longer recognises this device (unlinked, evicted or Patreon re-authorisation needed).
            self.store.delete_lease()
            self.store.write_status(reconnect_needed=True, last_fail=now, fail_reason=result.code)
            return
        self._fail(now, result.code or ("network" if result.status == 0 else f"http_{result.status}"), result.retry_after)

    def _fail(self, now: float, reason: str, retry_after: float | None) -> None:
        self.store.write_status(last_fail=now, fail_reason=reason[:64])
        self._backoff.failure(now, retry_after)

    # -- unlink ---------------------------------------------------------------------------------
    def unlink(self) -> None:
        """Disconnect. Local credential + lease are removed first and unconditionally."""
        self._cancel.set()
        base = self._base_url()
        credential = self._credential()
        self.store.clear()
        with self._lock:
            self._credential_cache = None
            self._credential_checked = True
            self._linking = False
            self._service_unavailable = False
            self._link_message = ""
            self._backoff.success()
        self._notify()
        if base and credential is not None:
            threading.Thread(
                target=self._unlink_remote, args=(base, credential), name="exilelens-patreon-unlink", daemon=True
            ).start()

    def _unlink_remote(self, base: str, credential: Credential) -> None:
        try:
            self._http_factory(base).post_json(
                "/v1/patreon/unlink", {"schema": 1}, headers={"Authorization": f"Bearer {credential.device_token}"}
            )
        except Exception:  # noqa: BLE001
            logger.debug("patreon_unlink_remote_failed")


def _default_open_url(url: str) -> bool:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    return bool(QDesktopServices.openUrl(QUrl(url)))
