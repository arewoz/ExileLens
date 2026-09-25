"""Lightweight hooks from production UI paths into the diagnostic event buffer."""

from __future__ import annotations

from typing import Any

from exilelens.diagnostics.events import record_event


def record_application_initialized() -> None:
    record_event("app", "initialized")


def record_application_shutdown() -> None:
    record_event("app", "shutdown")


def attach_controller_diagnostics(controller: Any) -> None:
    def _started(request_id: int) -> None:
        record_event("item_check", "evaluation_started", detail={"request_id": int(request_id)})

    def _finished(request_id: int, _result: object) -> None:
        record_event("item_check", "evaluation_finished", detail={"request_id": int(request_id)})

    def _error(request_id: int, message: str) -> None:
        store = getattr(controller, "error_context", None)
        code = ""
        if store is not None and store.last_error is not None:
            code = store.last_error.code
        record_event(
            "item_check",
            "evaluation_error",
            detail={
                "request_id": int(request_id),
                "message": str(message or "")[:200],
                "error_code": code or None,
            },
        )

    def _build_changed(_info: object) -> None:
        record_event("build", "changed")

    controller.evaluation_started.connect(_started)
    controller.evaluation_finished.connect(_finished)
    controller.evaluation_error.connect(_error)
    controller.build_changed.connect(_build_changed)


def attach_update_diagnostics(update_service: Any, error_store: Any | None = None) -> None:
    from exilelens.error_catalog.integration import record_update_state

    def _state(state: str, version: str) -> None:
        record_event("update", "state", detail={"state": state, "version": version})
        if error_store is not None:
            record_update_state(error_store, state, version)

    def _download(state: str) -> None:
        record_event("update", "download_state", detail={"state": state})
        if error_store is not None and state == "error":
            from exilelens.error_catalog.integration import record_generic_failure

            record_generic_failure(
                error_store,
                "Update download failed verification.",
                el_code="EL-UPD-002",
                subsystem="update",
                stage="download",
            )

    update_service.state_changed.connect(_state)
    update_service.download_state_changed.connect(_download)
