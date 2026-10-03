"""Privacy-friendly usage statistics: the small, fixed set of observations in the contract.

Every method here is O(1) and does no I/O (no disk, no network). Item Check results are *counted* in a
tiny in-memory table keyed by category and uploaded later as one ``item_checks_summary`` event, so there
is never an event per check and no per-check timestamp that could reveal play rhythm.

Producers pass categories only. Nothing that identifies an item, build, character, price or path is
accepted by the contract, so there is nothing to leak even if a caller tried.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping

from exilelens.cloud.sink import NullSink, Sink, hour_string

_VERDICTS = {
    "MEANINGFUL_UPGRADE": "meaningful_upgrade",
    "MINOR_UPGRADE": "minor_upgrade",
    "SIDEGRADE": "sidegrade",
    "MINOR_DOWNGRADE": "minor_downgrade",
    "MEANINGFUL_DOWNGRADE": "meaningful_downgrade",
    "NOT_VIABLE": "not_viable",
    "UNCERTAIN": "uncertain",
    "UNSUPPORTED": "unsupported",
    "NOT_EVALUATED": "not_evaluated",
    # Legacy persisted verdicts are folded into the neutral "uncertain" bucket.
    "POTENTIAL_UPGRADE": "uncertain",
    "POTENTIAL_DOWNGRADE": "uncertain",
}
_CONFIDENCE = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
_QUALITY = {"FULL": "full", "PARTIAL": "partial", "UNSUPPORTED": "unsupported", "FAILED": "failed"}
_COVERAGE = {"HIGH": "high", "PARTIAL": "partial", "LIMITED": "limited"}
_HEALTH_ORDER = ("NEEDS_ATTENTION", "NEARLY_CAPPED", "OPPORTUNITY", "NO_URGENT_ISSUE", "LIMITED")
MAX_SUMMARY_BUCKETS = 60


def latency_bucket(milliseconds: float) -> str:
    for limit, name in ((250, "lt_250ms"), (500, "lt_500ms"), (1000, "lt_1s"), (2000, "lt_2s"), (5000, "lt_5s")):
        if milliseconds < limit:
            return name
    return "ge_5s"


def duration_bucket(seconds: float) -> str:
    for limit, name in ((1, "lt_1s"), (5, "lt_5s"), (15, "lt_15s"), (60, "lt_60s")):
        if seconds < limit:
            return name
    return "ge_60s"


def boot_bucket(seconds: float) -> str:
    for limit, name in ((2, "lt_2s"), (5, "lt_5s"), (15, "lt_15s"), (60, "lt_60s")):
        if seconds < limit:
            return name
    return "ge_60s"


def _enum_name(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().upper()


def item_check_categories(result: Mapping[str, Any], timing: Any | None, request_id: int | None = None) -> tuple[str, str, str, str] | None:
    """(verdict, confidence, quality, latency) categories from an evaluation result; ``None`` if unusable."""
    try:
        outcome = ((result.get("recommendation") or {}).get("evaluation_outcome")) or {}
        verdict = _VERDICTS.get(_enum_name(outcome.get("verdict")), "not_evaluated")
        quality = _QUALITY.get(_enum_name(outcome.get("evaluation_quality")), "none")
        confidence = _CONFIDENCE.get(_enum_name((result.get("decision") or {}).get("confidence")), "none")
        if timing is None or (request_id is not None and getattr(timing, "request_id", request_id) != request_id):
            return None
        started = float(getattr(timing, "clipboard_received_ms", 0.0) or getattr(timing, "evaluation_started_ms", 0.0))
        ended = float(getattr(timing, "ui_updated_ms", 0.0) or getattr(timing, "evaluation_finished_ms", 0.0))
        if started <= 0 or ended < started:
            return None
        return verdict, confidence, quality, latency_bucket(ended - started)
    except Exception:  # noqa: BLE001 - telemetry must never raise into the app
        return None


def analysis_categories(payload: Mapping[str, Any], duration_seconds: float) -> dict[str, Any] | None:
    """Analyze Build system-health fields only (never a measured value)."""
    try:
        actionable = payload.get("actionable") or {}
        if not actionable:
            return {
                "outcome": "no_signal",
                "coverage": "none",
                "curve_count": 0,
                "hard_issue_present": False,
                "health": "none",
                "duration": duration_bucket(duration_seconds),
            }
        coverage = _COVERAGE.get(_enum_name((actionable.get("coverage") or {}).get("level")), "none")
        states = {_enum_name(row.get("state")) for row in actionable.get("build_health") or [] if isinstance(row, Mapping)}
        health = next((name.lower() for name in _HEALTH_ORDER if name in states), "none")
        curves = actionable.get("response_curves") or []
        focus = _enum_name((actionable.get("current_focus") or {}).get("kind"))
        return {
            "outcome": "ok",
            "coverage": coverage,
            "curve_count": min(len(curves), 3),
            "hard_issue_present": focus == "ISSUE",
            "health": health,
            "duration": duration_bucket(duration_seconds),
        }
    except Exception:  # noqa: BLE001
        return None


class UsageTelemetry:
    def __init__(self, sink: Sink | NullSink | None = None, clock: Callable[[], float] = time.time) -> None:
        self.sink: Sink | NullSink = sink or NullSink()
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str, str, str, str], int] = {}

    # -- helpers --------------------------------------------------------------------------------
    @property
    def active(self) -> bool:
        return bool(self.sink.active)

    def _emit(self, name: str, props: dict[str, Any]) -> bool:
        if not self.sink.active:
            return False
        return self.sink.add({"name": name, "t": hour_string(self._clock()), "props": props})

    # -- events ---------------------------------------------------------------------------------
    def app_started(self, *, launch: str, previous_session: str, pob_configured: bool) -> bool:
        return self._emit("app_started", {"launch": launch, "previous_session": previous_session, "pob_configured": bool(pob_configured)})

    def onboarding_completed(self, *, outcome: str, pob_autodetected: bool) -> bool:
        return self._emit("onboarding_completed", {"outcome": outcome, "pob_autodetected": bool(pob_autodetected)})

    def pob_connected(self, *, outcome: str, boot_seconds: float, error_code: str | None = None) -> bool:
        props: dict[str, Any] = {"outcome": outcome, "boot": boot_bucket(boot_seconds)}
        if error_code:
            props["error_code"] = error_code
        return self._emit("pob_connected", props)

    def item_check(self, verdict: str, confidence: str, quality: str, latency: str, outcome: str = "ok") -> None:
        """Count one result. In-memory only; uploaded later inside ``item_checks_summary``."""
        if not self.sink.active:
            return
        key = (verdict, confidence, quality, latency, outcome)
        with self._lock:
            self._buckets[key] = min(self._buckets.get(key, 0) + 1, 10000)

    def analyze_build(self, fields: dict[str, Any] | None, *, error_code: str | None = None) -> bool:
        if fields is None:
            return False
        props = dict(fields)
        if error_code:
            props["error_code"] = error_code
        return self._emit("analyze_build_completed", props)

    def update_detected(self, *, to_version: str, verified: bool) -> bool:
        return self._emit("update_detected", {"to_version": to_version, "verified": bool(verified)})

    def update_download_completed(self, *, to_version: str, mode: str, outcome: str, duration_seconds: float) -> bool:
        return self._emit(
            "update_download_completed",
            {"to_version": to_version, "mode": mode, "outcome": outcome, "duration": duration_bucket(duration_seconds)},
        )

    def update_install_completed(self, *, from_version: str, to_version: str, mode: str, outcome: str) -> bool:
        return self._emit(
            "update_install_completed",
            {"from_version": from_version, "to_version": to_version, "mode": mode, "outcome": outcome},
        )

    # -- roll-up / lifecycle --------------------------------------------------------------------
    def roll_up(self) -> int:
        """Convert pending Item Check counters into ``item_checks_summary`` events; returns events added."""
        with self._lock:
            if not self._buckets or not self.sink.active:
                return 0
            rows = list(self._buckets.items())
            self._buckets.clear()
        added = 0
        for start in range(0, len(rows), MAX_SUMMARY_BUCKETS):
            chunk = rows[start : start + MAX_SUMMARY_BUCKETS]
            buckets = [
                {"verdict": v, "confidence": c, "quality": q, "latency": l, "outcome": o, "n": n}
                for (v, c, q, l, o), n in chunk
            ]
            if self._emit("item_checks_summary", {"buckets": buckets}):
                added += 1
        return added

    def discard_counters(self) -> None:
        with self._lock:
            self._buckets.clear()

    def pending_counters(self) -> int:
        with self._lock:
            return sum(self._buckets.values())
