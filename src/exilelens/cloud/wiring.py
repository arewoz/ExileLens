"""Qt glue: translate existing app signals into the contract's categorical observations.

Every slot is connected with ``QueuedConnection``, so it runs from the event loop *after* the emitting
code has returned — never inside the Item Check pipeline. Each slot only reads small enum-like fields,
increments an in-memory counter or appends a validated event; it does no disk or network work and
swallows its own failures.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from PySide6.QtCore import QObject, Qt, Slot

from exilelens.cloud.service import CloudServices
from exilelens.cloud.telemetry import analysis_categories, item_check_categories, latency_bucket

logger = logging.getLogger(__name__)
_QUEUED = Qt.ConnectionType.QueuedConnection

_DOWNLOAD_OUTCOMES = {
    "hash_mismatch": "hash_mismatch",
    "size_mismatch": "size_mismatch",
    "request_failed": "network",
    "stall_timeout": "network",
    "disk_error": "disk",
    "cancelled": "cancelled",
}


class CloudWiring(QObject):
    def __init__(self, cloud: CloudServices, controller: Any, update_service: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cloud = cloud
        self._controller = controller
        self._update = update_service
        self._boot_started = time.monotonic()
        self._pob_reported = False
        self._eval_started: dict[int, float] = {}
        self._analysis_started: float | None = None
        self._download_started: float | None = None
        self._detected: set[str] = set()
        controller.evaluation_started.connect(self._on_eval_started, _QUEUED)
        controller.evaluation_finished.connect(self._on_eval_finished, _QUEUED)
        controller.evaluation_error.connect(self._on_eval_error, _QUEUED)
        controller.build_analysis_started.connect(self._on_analysis_started, _QUEUED)
        controller.analysis_finished.connect(self._on_analysis_finished, _QUEUED)
        controller.analysis_error.connect(self._on_analysis_error, _QUEUED)
        controller.engine_ready.connect(self._on_engine_ready, _QUEUED)
        controller.engine_failed.connect(self._on_engine_failed, _QUEUED)
        update_service.state_changed.connect(self._on_update_state, _QUEUED)
        update_service.download_state_changed.connect(self._on_download_state, _QUEUED)

    # -- Item Check -----------------------------------------------------------------------------
    @Slot(int)
    def _on_eval_started(self, request_id: int) -> None:
        self._eval_started[request_id] = time.perf_counter()
        if len(self._eval_started) > 32:
            self._eval_started.pop(next(iter(self._eval_started)))

    @Slot(int, object)
    def _on_eval_finished(self, request_id: int, result: object) -> None:
        self._eval_started.pop(request_id, None)
        try:
            if not self._cloud.usage.active or not isinstance(result, dict):
                return
            categories = item_check_categories(result, self._controller.last_timing, request_id)
            if categories is not None:
                self._cloud.usage.item_check(*categories, outcome="ok")
        except Exception:  # noqa: BLE001
            logger.debug("cloud_item_check_slot_failed")

    @Slot(int, str)
    def _on_eval_error(self, request_id: int, _message: str) -> None:
        started = self._eval_started.pop(request_id, None)
        try:
            if not self._cloud.usage.active or started is None:
                return
            elapsed_ms = (time.perf_counter() - started) * 1000
            self._cloud.usage.item_check("not_evaluated", "none", "failed", latency_bucket(elapsed_ms), outcome="error")
        except Exception:  # noqa: BLE001
            logger.debug("cloud_item_error_slot_failed")

    # -- Analyze Build --------------------------------------------------------------------------
    @Slot(int)
    def _on_analysis_started(self, _request_id: int) -> None:
        self._analysis_started = time.perf_counter()

    @Slot(object)
    def _on_analysis_finished(self, payload: object) -> None:
        started, self._analysis_started = self._analysis_started, None
        if started is None or not isinstance(payload, dict):
            return  # a tree/rescore emission, not an Analyze Build run we saw start
        try:
            fields = analysis_categories(payload, time.perf_counter() - started)
            self._cloud.usage.analyze_build(fields)
        except Exception:  # noqa: BLE001
            logger.debug("cloud_analysis_slot_failed")

    @Slot(str)
    def _on_analysis_error(self, _message: str) -> None:
        started, self._analysis_started = self._analysis_started, None
        if started is None:
            return
        try:
            fields = analysis_categories({}, time.perf_counter() - started)
            if fields is not None:
                fields["outcome"] = "error"
            self._cloud.usage.analyze_build(fields)
        except Exception:  # noqa: BLE001
            logger.debug("cloud_analysis_error_slot_failed")

    # -- PoB engine -----------------------------------------------------------------------------
    @Slot()
    def _on_engine_ready(self) -> None:
        self._report_pob("ready")

    @Slot(str)
    def _on_engine_failed(self, _message: str) -> None:
        self._report_pob("failed", error_code="EL-POB-002")

    def _report_pob(self, outcome: str, error_code: str | None = None) -> None:
        if self._pob_reported:
            return
        self._pob_reported = True
        try:
            self._cloud.usage.pob_connected(outcome=outcome, boot_seconds=time.monotonic() - self._boot_started, error_code=error_code)
        except Exception:  # noqa: BLE001
            logger.debug("cloud_pob_slot_failed")

    # -- updates --------------------------------------------------------------------------------
    @Slot(str, str)
    def _on_update_state(self, state: str, version: str) -> None:
        if state in ("available", "verification_failed") and version and version not in self._detected:
            self._detected.add(version)
            try:
                self._cloud.usage.update_detected(to_version=version, verified=state == "available")
            except Exception:  # noqa: BLE001
                logger.debug("cloud_update_slot_failed")

    @Slot(str)
    def _on_download_state(self, state: str) -> None:
        try:
            version = str(getattr(self._update.settings, "update_latest_version", "") or "")
            if state == "downloading":
                self._download_started = time.monotonic()
                return
            started, self._download_started = self._download_started, None
            if started is None or not version:
                return
            elapsed = time.monotonic() - started
            if state == "ready":
                outcome = "ok"
            elif state == "error":
                outcome = _DOWNLOAD_OUTCOMES.get(str(getattr(self._update.settings, "update_last_error", "") or ""), "other")
            else:
                return
            mode = "auto" if getattr(self._update, "last_download_mode", "manual") == "auto" else "manual"
            self._cloud.usage.update_download_completed(to_version=version, mode=mode, outcome=outcome, duration_seconds=elapsed)
        except Exception:  # noqa: BLE001
            logger.debug("cloud_download_slot_failed")


def attach(cloud: CloudServices, controller: Any, update_service: Any) -> CloudWiring:
    return CloudWiring(cloud, controller, update_service)


__all__ = ["CloudWiring", "attach"]
