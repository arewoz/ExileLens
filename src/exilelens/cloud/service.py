"""Owner object for the optional cloud services (usage statistics and error reports).

* Both categories are OFF unless the user switched them on *and* the build has an explicit https endpoint.
  Otherwise the app holds ``NullSink`` objects: no ID, no files, no requests.
* All network I/O happens on one daemon thread (``exilelens-cloud-flush``); nothing here runs on the
  hotkey or Item Check path, and ``stop()`` never touches the network.
* ``apply_consent`` is idempotent. Switching a category off removes its queue and ID immediately
  (memory, disk and the in-flight batch), then makes one best-effort server-side ``forget`` request.
  A request that was already on the wire when the switch was flipped may still complete.
* Unexpected session end is observed with a local marker (``cloud/session.json``): ``running`` while
  the app is up, ``clean`` after an orderly shutdown. A leftover ``running`` at the next start can mean
  power loss, Task Manager, a forced Windows shutdown or a native crash. It is *not* proof of a crash.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import threading
import time
from pathlib import Path
from typing import Any, Callable

from exilelens._version import __version__, is_packaged
from exilelens.cloud import contract
from exilelens.cloud.endpoint import cloud_base_url
from exilelens.cloud.errors import ErrorReporter
from exilelens.cloud.patreon import PatreonLink, PatreonStore
from exilelens.cloud.sink import FIRST_FLUSH_DELAY_SECONDS, FLUSH_INTERVAL_SECONDS, NullSink, Sink
from exilelens.cloud.store import CategoryStore, cloud_dir
from exilelens.cloud.telemetry import UsageTelemetry
from exilelens.cloud.transport import CloudHttp

logger = logging.getLogger(__name__)

TICK_SECONDS = 30.0
STOP_JOIN_SECONDS = 0.25


def app_info() -> dict[str, Any]:
    """The envelope's ``app`` block: version/channel/packaged/OS family only."""
    os_family = "other"
    if os.name == "nt":
        try:
            build = int(platform.version().split(".")[2])
            os_family = "win11" if build >= 22000 else "win10"
        except (IndexError, ValueError):
            os_family = "other"
    return {
        "version": __version__,
        "channel": "beta" if "b" in __version__ else "stable",
        "packaged": bool(is_packaged()),
        "os": os_family,
    }


def effective_consent(settings: Any, category: str) -> bool:
    """A choice made under an older contract version counts as OFF until the user confirms again."""
    flag = bool(getattr(settings, "send_usage_stats" if category == "usage" else "send_error_reports", False))
    current = int(contract.schema()["consent_version"])
    return flag and int(getattr(settings, "privacy_consent_version", 0) or 0) >= current


class CloudServices:
    def __init__(
        self,
        settings: Any,
        *,
        clock: Callable[[], float] = time.time,
        base_url: Callable[[], str | None] = cloud_base_url,
        http_factory: Callable[[str], CloudHttp] = CloudHttp,
        root: Path | None = None,
        first_flush_delay: float = FIRST_FLUSH_DELAY_SECONDS,
        flush_interval: float = FLUSH_INTERVAL_SECONDS,
    ) -> None:
        self.settings = settings
        self._clock = clock
        self._base_url = base_url
        self._http_factory = http_factory
        self._root = root
        self._first_flush_delay = first_flush_delay
        self._flush_interval = flush_interval
        self._lock = threading.RLock()
        self.usage = UsageTelemetry(NullSink(), clock)
        self.errors = ErrorReporter(NullSink(), clock)
        # Optional Patreon link (independent of both consent switches and of telemetry data/IDs).
        self.patreon = PatreonLink(PatreonStore(self._dir() / "patreon"), base_url=base_url, http_factory=http_factory, clock=clock)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._started_reported = False
        self.previous_session = "unknown"
        self._pob_configured = False
        # Set by the app when PoB was found automatically (in-memory; only used for one onboarding observation).
        self.pob_autodetected = False

    # -- paths ----------------------------------------------------------------------------------
    def _dir(self) -> Path:
        return self._root if self._root is not None else cloud_dir()

    def _store(self, category: str) -> CategoryStore:
        return CategoryStore(self._dir() / ("telemetry" if category == "usage" else "errors"))

    # -- consent --------------------------------------------------------------------------------
    def apply_consent(self) -> None:
        """Make reality match the settings. Safe to call at any time and from any thread."""
        with self._lock:
            url = self._base_url()
            was_active = self.usage.active or self.errors.active
            for category in ("usage", "errors"):
                self._apply_category(category, wanted=effective_consent(self.settings, category) and bool(url), url=url)
            now_active = self.usage.active or self.errors.active
            if now_active:
                self._write_marker("running")
            else:
                self._delete_marker()
            if now_active and not was_active and self._started_reported:
                # Switched on mid-session: this is the first observation of this session.
                self.previous_session = "first_run"
                self.usage.app_started(launch="normal", previous_session="first_run", pob_configured=self._pob_configured)

    def _apply_category(self, category: str, *, wanted: bool, url: str | None) -> None:
        holder = self.usage if category == "usage" else self.errors
        store = self._store(category)
        if wanted and not holder.active and url:
            sink = Sink(
                category,
                store,
                self._http_factory(url),
                app_info(),
                clock=self._clock,
                first_flush_delay=self._first_flush_delay,
                flush_interval=self._flush_interval,
            )
            holder.sink = sink
            return
        if not wanted:
            old = holder.sink
            holder.sink = NullSink()
            known_id: str | None = None
            if isinstance(old, Sink):
                known_id = old.purge()
            elif store.exists():
                known_id = store.read_id()
                store.purge()
            if category == "usage":
                self.usage.discard_counters()
            else:
                self.errors.discard_open()
            if known_id and url and isinstance(old, Sink):
                threading.Thread(
                    target=old.forget_remote, args=(known_id,), name=f"exilelens-cloud-forget-{category}", daemon=True
                ).start()

    # -- session marker -------------------------------------------------------------------------
    def _marker_path(self) -> Path:
        return self._dir() / "session.json"

    def _read_marker(self) -> str | None:
        try:
            payload = json.loads(self._marker_path().read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return None
        state = payload.get("state") if isinstance(payload, dict) else None
        return state if state in ("running", "clean") else None

    def _write_marker(self, state: str) -> None:
        try:
            path = self._marker_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name("session.json.tmp")
            tmp.write_text(json.dumps({"state": state, "ts": int(self._clock())}), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            logger.debug("cloud_session_marker_write_failed")

    def _delete_marker(self) -> None:
        try:
            self._marker_path().unlink(missing_ok=True)
        except OSError:
            pass

    # -- lifecycle ------------------------------------------------------------------------------
    def start(self, *, pob_configured: bool = False) -> None:
        """Call once, after the single-instance check and UI composition. Cheap; starts one daemon thread."""
        with self._lock:
            if self._started:
                return
            self._started = True
            self._pob_configured = bool(pob_configured)
            if effective_consent(self.settings, "usage") or effective_consent(self.settings, "errors"):
                marker = self._read_marker()
                self.previous_session = {"clean": "clean", "running": "unexpected", None: "first_run"}[marker]
            self.apply_consent()
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="exilelens-cloud-flush", daemon=True)
            self._thread.start()

    def report_startup(self, update_service: Any | None = None) -> None:
        """Emit the once-per-launch observations (called a few seconds after startup)."""
        with self._lock:
            if self._started_reported:
                return
            self._started_reported = True
            result = getattr(update_service, "last_install_result", None) if update_service is not None else None
            launch = "normal"
            if result is not None:
                outcome = result.outcome.value
                if outcome in ("success", "relaunch_failed"):
                    launch = "after_update"
                elif outcome in ("restored", "restore_failed", "recovered", "prepare_failed"):
                    launch = "after_update_failed"
            self.usage.app_started(launch=launch, previous_session=self.previous_session, pob_configured=self._pob_configured)
            if result is not None and result.from_version and result.to_version:
                self.usage.update_install_completed(
                    from_version=result.from_version,
                    to_version=result.to_version,
                    mode=result.mode,
                    outcome=result.outcome.value,
                )
            if self.previous_session == "unexpected":
                self.errors.unexpected_session_end()

    def tick(self, now: float | None = None) -> None:
        """One flusher iteration (also called directly by tests). At most one request per category."""
        now = self._clock() if now is None else now
        self.patreon.tick(now)
        for holder in (self.usage, self.errors):
            sink = holder.sink
            if not sink.time_ready(now):
                continue
            holder.roll_up()
            if sink.pending_count():
                sink.flush(now)

    def _run(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the flusher must survive anything
                logger.exception("cloud_flush_tick_failed")

    def stop(self) -> None:
        """Orderly shutdown: bounded local writes only, never a network call."""
        self._stop.set()
        try:
            for holder in (self.usage, self.errors):
                holder.roll_up()
                holder.sink.persist()
            if self.usage.active or self.errors.active:
                self._write_marker("clean")
        except Exception:  # noqa: BLE001
            logger.debug("cloud_stop_persist_failed")
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(STOP_JOIN_SECONDS)

    # -- introspection --------------------------------------------------------------------------
    def configured(self) -> bool:
        return bool(self._base_url())

    def status(self) -> dict[str, Any]:
        return {
            "endpoint_configured": self.configured(),
            "usage": self.usage.sink.status(),
            "errors": self.errors.sink.status(),
            "previous_session": self.previous_session,
        }
