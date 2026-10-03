"""A consent-gated outbound queue for one category (usage statistics or error reports).

``Sink`` is the real implementation (it exists only while its category is switched on); ``NullSink`` is
what the app holds otherwise: every method is a no-op, no ID is created and no file is touched.

Design points that matter for privacy and reliability:

* ``add`` validates against the canonical contract before anything is stored. Invalid items are
  dropped (never repaired), so a bug in a producer cannot widen what is collected.
* Memory and disk are bounded (event count, bytes, TTL). When full, the oldest items go first.
* ``purge`` (opt-out) clears memory, disk and the in-flight batch, bumps a generation counter so a
  request that is already in flight can never re-queue or persist anything afterwards, and removes the
  ID. A request that is already on the wire may still complete; that is documented, not hidden.
* ``flush`` is only ever called from the background flusher. It makes at most one request.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from exilelens.cloud import contract
from exilelens.cloud.store import CategoryStore
from exilelens.cloud.transport import Action, Backoff, CloudHttp, PostResult

logger = logging.getLogger(__name__)

FIRST_FLUSH_DELAY_SECONDS = 60.0
FLUSH_INTERVAL_SECONDS = 30 * 60.0
MEMORY_CAP_EVENTS = 500


@dataclass(frozen=True)
class FlushOutcome:
    attempted: bool = False
    sent: int = 0
    action: Action | None = None
    status: int = 0
    code: str = ""


def hour_string(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:00Z", time.gmtime(epoch))


class NullSink:
    """The sink for a category that is switched off (or has no configured endpoint)."""

    kind = "none"
    active = False

    def add(self, item: dict[str, Any]) -> bool:
        return False

    def pending_count(self) -> int:
        return 0

    def due(self, now: float) -> bool:
        return False

    def time_ready(self, now: float) -> bool:
        return False

    def flush(self, now: float | None = None) -> FlushOutcome:
        return FlushOutcome()

    def persist(self) -> None:
        return None

    def purge(self) -> str | None:
        return None

    def status(self) -> dict[str, Any]:
        return {"active": False, "queued": 0}

    def next_batch_preview(self) -> dict[str, Any] | None:
        return None


class Sink:
    active = True

    def __init__(
        self,
        kind: str,
        store: CategoryStore,
        http: CloudHttp,
        app_info: dict[str, Any],
        *,
        clock: Callable[[], float] = time.time,
        backoff: Backoff | None = None,
        first_flush_delay: float = FIRST_FLUSH_DELAY_SECONDS,
        flush_interval: float = FLUSH_INTERVAL_SECONDS,
    ) -> None:
        assert kind in ("usage", "errors")
        self.kind = kind
        self._cfg = contract.schema()["usage" if kind == "usage" else "errors"]
        self._id_field = self._cfg["id_field"]
        self._list_field = "events" if kind == "usage" else "reports"
        self._path = "/v1/telemetry/batch" if kind == "usage" else "/v1/errors/batch"
        self._forget_path = "/v1/telemetry/forget" if kind == "usage" else "/v1/errors/forget"
        self._store = store
        self._http = http
        self._app = dict(app_info)
        self._clock = clock
        self._backoff = backoff or Backoff()
        self._lock = threading.Lock()
        self._pending: list[dict[str, Any]] = []
        self._inflight: tuple[str, list[dict[str, Any]]] | None = None
        self._generation = 0
        self._active = True
        self._dropped = 0
        self._invalid = 0
        self._disabled_reason = ""
        self._flush_interval = flush_interval
        now = clock()
        self._next_flush_at = now + first_flush_delay
        self.last_status: dict[str, Any] = {"last_attempt": None, "last_result": ""}
        for row in store.load_queue(now):
            self._pending.append(row)

    # -- producers ------------------------------------------------------------------------------
    def add(self, item: dict[str, Any]) -> bool:
        now = self._clock()
        try:
            self._validate(item, now)
        except contract.Invalid as exc:
            self._invalid += 1
            logger.debug("cloud_item_rejected kind=%s code=%s", self.kind, exc.code)
            return False
        except Exception:  # noqa: BLE001 - producers must never raise into the app
            self._invalid += 1
            return False
        with self._lock:
            if not self._active or self._disabled_reason:
                return False
            self._pending.append({"q": now, "item": item})
            overflow = len(self._pending) - MEMORY_CAP_EVENTS
            if overflow > 0:
                del self._pending[:overflow]
                self._dropped += overflow
        return True

    def _validate(self, item: dict[str, Any], now: float) -> None:
        if self.kind == "usage":
            contract.validate_event(item["name"], item["t"], item["props"], now)
        else:
            contract.validate_report(item, now)

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending) + (len(self._inflight[1]) if self._inflight else 0)

    # -- flushing -------------------------------------------------------------------------------
    def time_ready(self, now: float) -> bool:
        """The flush interval elapsed and no backoff is pending (says nothing about queue contents)."""
        with self._lock:
            return self._active and not self._disabled_reason and now >= self._next_flush_at and self._backoff.ready(now)

    def due(self, now: float) -> bool:
        with self._lock:
            if not self._active or self._disabled_reason or not (self._pending or self._inflight):
                return False
            return now >= self._next_flush_at and self._backoff.ready(now)

    def _build_batch(self, now: float) -> tuple[str, list[dict[str, Any]]] | None:
        limits = contract.limits()
        cap = limits["usage_batch_max_events" if self.kind == "usage" else "error_batch_max_reports"]
        chosen: list[dict[str, Any]] = []
        while self._pending and len(chosen) < cap:
            chosen.append(self._pending.pop(0))
            body = self._body(self._PLACEHOLDER_ID, chosen, now, identifier=self._PLACEHOLDER_ID)
            if len(json.dumps(body, separators=(",", ":"))) > limits["batch_max_bytes"] - 512:
                if len(chosen) == 1:
                    self._dropped += 1  # a single item that cannot fit a batch is never sendable
                    chosen.clear()
                    continue
                self._pending.insert(0, chosen.pop())
                break
        if not chosen:
            return None
        return str(uuid.uuid4()), chosen

    _PLACEHOLDER_ID = "00000000-0000-4000-8000-000000000000"

    def _body(self, batch_id: str, rows: list[dict[str, Any]], now: float, *, identifier: str | None = None) -> dict[str, Any]:
        if identifier is None:
            identifier = self._store.get_or_create_id()
        body: dict[str, Any] = {
            "schema": contract.schema()["schema_version"],
            "batch_id": batch_id,
            self._id_field: identifier,
            "app": self._app,
            self._list_field: [row["item"] for row in rows],
        }
        if self.kind == "usage" and self._dropped:
            body["queue_dropped"] = min(self._dropped, 100000)
        return body

    def flush(self, now: float | None = None) -> FlushOutcome:
        now = self._clock() if now is None else now
        with self._lock:
            if not self._active or self._disabled_reason:
                return FlushOutcome()
            if not self._backoff.ready(now):
                return FlushOutcome()
            generation = self._generation
            if self._inflight is None:
                self._inflight = self._build_batch(now)
            if self._inflight is None:
                return FlushOutcome()
            batch_id, rows = self._inflight
            body = self._body(batch_id, rows, now)
        result = self._http.post_json(self._path, body)
        return self._finish(generation, result, rows, now)

    def _finish(self, generation: int, result: PostResult, rows: list[dict[str, Any]], now: float) -> FlushOutcome:
        action = result.action
        with self._lock:
            if generation != self._generation or not self._active:
                # Opted out while the request was in flight: remember nothing, store nothing.
                return FlushOutcome(attempted=True, sent=0, action=action, status=result.status, code=result.code)
            self.last_status = {"last_attempt": now, "last_result": f"{result.status}:{result.code}"}
            if action in (Action.DONE, Action.DROP):
                self._inflight = None
                if action == Action.DONE:
                    self._backoff.success()
                    self._dropped = 0
                else:
                    # A poison batch is never retried; the service said it can never accept it.
                    logger.warning("cloud_batch_dropped kind=%s status=%s code=%s", self.kind, result.status, result.code)
                self._next_flush_at = now + self._flush_interval
            elif action == Action.DISABLE:
                self._inflight = None
                self._pending.clear()
                self._disabled_reason = "client_unsupported"
            else:
                delay = self._backoff.failure(now, result.retry_after)
                self._next_flush_at = now + delay
            self._persist_locked()
            sent = len(rows) if action == Action.DONE else 0
        return FlushOutcome(attempted=True, sent=sent, action=action, status=result.status, code=result.code)

    # -- persistence / lifecycle ----------------------------------------------------------------
    def _persist_locked(self) -> None:
        if not self._active:
            return
        rows = list(self._inflight[1]) if self._inflight else []
        rows.extend(self._pending)
        try:
            self._store.save_queue(rows)
        except OSError:
            logger.warning("cloud_queue_persist_failed kind=%s", self.kind)

    def persist(self) -> None:
        """Small bounded write; used at shutdown. Never touches the network."""
        with self._lock:
            self._persist_locked()

    def purge(self) -> str | None:
        """Opt-out: drop everything locally and return the ID (for a best-effort server forget)."""
        with self._lock:
            self._active = False
            self._generation += 1
            self._pending.clear()
            self._inflight = None
        known_id = self._store.read_id()
        self._store.purge()
        return known_id

    def forget_remote(self, known_id: str | None) -> None:
        """Best effort, single attempt, no persistence (the ID is already gone locally)."""
        if not known_id:
            return
        body = {"schema": contract.schema()["schema_version"], self._id_field: known_id}
        try:
            self._http.post_json(self._forget_path, body)
        except Exception:  # noqa: BLE001
            logger.debug("cloud_forget_failed kind=%s", self.kind)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": self._active,
                "queued": len(self._pending) + (len(self._inflight[1]) if self._inflight else 0),
                "dropped": self._dropped,
                "rejected_locally": self._invalid,
                "disabled": self._disabled_reason or None,
                "backoff_failures": self._backoff.failures,
                **self.last_status,
            }

    def next_batch_preview(self) -> dict[str, Any] | None:
        """The payload that would be sent next (with the ID masked), for the transparency dialog."""
        with self._lock:
            rows = list(self._inflight[1]) if self._inflight else list(self._pending)
        rows = rows[: contract.limits()["usage_batch_max_events" if self.kind == "usage" else "error_batch_max_reports"]]
        if not rows:
            return None
        existing = self._store.read_id()
        body = {
            "schema": contract.schema()["schema_version"],
            "batch_id": "(assigned when sent)",
            self._id_field: (existing[:8] + "…") if existing else "(created on first send)",
            "app": self._app,
            self._list_field: [row["item"] for row in rows],
        }
        return body
